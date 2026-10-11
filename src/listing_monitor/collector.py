import hashlib
import json
import logging
import math
import re
import urllib.error
from datetime import datetime, timezone, timedelta
from pathlib import Path

from apartment_monitor.collector import fetch, run_lock
from listing_monitor.craigslist import parse_detail, parse_search
from listing_monitor.db import cached_detail, save
from listing_monitor.pacing import CollectionPaused, RequestPolicy

LOG = logging.getLogger(__name__)


def now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def collect(db, config, data_dir, fetcher=None):
    fetcher = fetcher or (lambda url: fetch(url, retries=0))
    data_dir = Path(data_dir)
    raw_dir = data_dir / 'raw' / 'craigslist'
    raw_dir.mkdir(parents=True, exist_ok=True)
    result = {'searches_ok': 0, 'searches_failed': 0, 'searches_skipped': 0, 'observations': 0,
              'details_ok': 0, 'details_failed': 0, 'complete_searches': 0}
    details_used = 0
    attempted = set()
    policy = RequestPolicy(data_dir,config)
    cutoff = (datetime.now(timezone.utc)-timedelta(days=config['detail_refresh_days'])).isoformat()

    def request(url):
        policy.before_request()
        try:
            raw, code, content_type = fetcher(url)
        except urllib.error.HTTPError as exc:
            if exc.code in (401,403,429):
                policy.pause(f'HTTP {exc.code}',exc.headers.get('Retry-After') if exc.headers else None)
            body = exc.read()
            if body:
                digest = hashlib.sha256(body).hexdigest()
                path = raw_dir / (digest+'.html')
                path.write_bytes(body)
                exc.artifact_path, exc.sha256 = str(path), digest
            exc.close()
            raise
        digest = hashlib.sha256(raw).hexdigest()
        artifact = raw_dir / (digest + '.html')
        artifact.write_bytes(raw)
        html = raw.decode('utf-8', errors='replace')
        if (not re.search(r'id=["\']ld_(?:searchpage_results|posting_data)["\']',html)
            and re.search(r'captcha|verify you are human|access denied|request blocked',html,re.I)):
            policy.pause('Public page returned an access challenge')
            exc = ValueError('Public page returned an access challenge; collection paused')
            exc.artifact_path,exc.sha256 = str(artifact),digest
            exc.code = code
            raise exc
        return html, code, str(artifact), digest

    with run_lock(data_dir / '.craigslist.lock'):
        searches = [(region, cat, category) for region in config['regions']
                    for cat, category in config['categories'].items()]
        # Retrieve all search snapshots first so detail requests cannot starve a region.
        batches = []
        for region, cat, category in searches:
            started = now()
            url = f'https://sfbay.craigslist.org/search/{region}/{cat}'
            run_id = db.execute('INSERT INTO runs(started_at,search_key,url,status) VALUES(?,?,?,?)',
                                (started, region+':'+cat, url, 'running')).lastrowid
            db.commit()
            code = artifact = digest = None
            try:
                html, code, artifact, digest = request(url)
                rows = parse_search(html, category)
                for row in rows:
                    lat,lon = row['latitude'],row['longitude']
                    size = config.get('geo_cell_degrees',0.01)
                    row['geo_cell'] = (f'{size:g}:{math.floor(lat/size)}:{math.floor(lon/size)}'
                                       if lat is not None and lon is not None else None)
                    row['coordinate_provenance'] = 'advertised_approximate_map_location' if row['geo_cell'] else None
                    save(db, run_id, row, started)
                db.execute('UPDATE runs SET finished_at=?,status=?,observed_count=?,http_status=?,artifact_path=?,sha256=? WHERE id=?',
                    (now(),'partial',len(rows),code,artifact,digest,run_id))
                db.commit()
                batches.append((run_id, started, rows))
                result['searches_ok'] += 1
                result['observations'] += len(rows)
                LOG.info('search=%s:%s status=partial observed=%s artifact=%s', region,cat,len(rows),artifact)
            except Exception as exc:
                db.rollback()
                skipped = isinstance(exc,CollectionPaused)
                db.execute('UPDATE runs SET finished_at=?,status=?,error=?,http_status=?,artifact_path=?,sha256=? WHERE id=?',
                    (now(),'skipped' if skipped else 'failed',str(exc),getattr(exc,'code',code),
                     getattr(exc,'artifact_path',artifact),getattr(exc,'sha256',digest),run_id))
                db.commit()
                result['searches_skipped' if skipped else 'searches_failed'] += 1
                if skipped:
                    LOG.warning('search=%s:%s skipped: %s',region,cat,exc)
                else:
                    LOG.exception('search=%s:%s failed url=%s',region,cat,url)

        # Round-robin queues give rooms/sublets access to the daily detail budget.
        queues = [iter(sorted(rows, key=lambda r: (cached_detail(db,r['source_id']) or {}).get('detail_checked_at') or ''))
                  for _,_,rows in batches]
        while queues and details_used < config['detail_limit']:
            if policy.paused_until():
                break
            any_left = False
            for queue in queues:
                row = next(queue, None)
                if row is None:
                    continue
                any_left = True
                source = row['source_id']
                cached = cached_detail(db,source)
                if source in attempted or (cached and cached['detail_checked_at'] and cached['detail_checked_at'] > cutoff):
                    continue
                if details_used >= config['detail_limit']:
                    break
                attempted.add(source)
                details_used += 1
                stamp = now()
                code = artifact = digest = None
                try:
                    html,code,artifact,digest = request(row['url'])
                    detail = parse_detail(html)
                    for run_id,started,rows in batches:
                        for observed in rows:
                            if observed['source_id'] == source:
                                # Enrich today's snapshot without creating another price observation.
                                save(db,run_id,observed,started,fresh_detail=detail)
                    db.execute('INSERT INTO detail_attempts(listing_id,source_id,attempted_at,status,http_status,artifact_path,sha256) VALUES(?,?,?,?,?,?,?)',
                        (detail.get('canonical_post_id') or cached['id'],source,stamp,'ok',code,artifact,digest))
                    db.commit()
                    result['details_ok'] += 1
                    LOG.info('detail=%s status=ok',source)
                except Exception as exc:
                    db.rollback()
                    db.execute('INSERT INTO detail_attempts(listing_id,source_id,attempted_at,status,error,http_status,artifact_path,sha256) VALUES(?,?,?,?,?,?,?,?)',
                        (cached['id'] if cached else None,source,stamp,'failed',str(exc),getattr(exc,'code',code),
                         getattr(exc,'artifact_path',artifact),getattr(exc,'sha256',digest)))
                    db.commit()
                    result['details_failed'] += 1
                    LOG.exception('detail=%s failed url=%s',source,row['url'])
            if not any_left:
                break
    result['paused_until'] = policy.paused_until()
    return result
