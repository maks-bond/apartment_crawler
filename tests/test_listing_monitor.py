import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from unittest.mock import patch
from pathlib import Path

from listing_monitor.collector import collect
from listing_monitor.craigslist import parse_detail, parse_search, source_id
from listing_monitor.db import connect, save
from listing_monitor.reporting import build_report
from listing_monitor.pacing import CollectionPaused, RequestPolicy


def search(price=2100, title='Furnished studio', coordinates=True):
    item = {'name':title,'numberOfBedrooms':0,'address':{'addressLocality':'Mountain View'}}
    if coordinates:
        item.update(latitude=37.4,longitude=-122.1)
    payload = {'itemListElement':[{'position':'0','item':item}]}
    return '<script id="ld_searchpage_results" type="application/ld+json">'+json.dumps(payload)+'''</script>
      <ol><li class="cl-static-search-result"><a href="https://www.craigslist.org/view/d/studio/abc_DEF">
      <div class="title">'''+title+'''</div><div class="price">$'''+str(price)+'''</div>
      <div class="location">Mountain View</div></a></li></ol>'''


def detail(post_id='1234567890'):
    return '''<script id="ld_posting_data" type="application/ld+json">{"numberOfBedrooms":0}</script>
     <span id="titletextonly">Furnished studio</span><span class="housing"> / 500ft2 - </span>
     <div class="attrgroup">apartment furnished</div>
     <p class="postinginfo">post id: '''+post_id+'''</p>
     <p class="postinginfo">posted: <time datetime="2026-10-01T12:00:00-0700"></time></p>'''


class ListingTests(unittest.TestCase):
    def test_request_pause_is_bounded_and_first_request_is_immediate(self):
        with tempfile.TemporaryDirectory() as temp:
            policy = RequestPolicy(Path(temp),{'request_delay_min_seconds':8,'request_delay_max_seconds':15})
            with patch('listing_monitor.pacing.time.sleep') as sleep, patch('listing_monitor.pacing.random.uniform',return_value=12) as draw:
                policy.before_request()
                sleep.assert_not_called()
                policy.before_request()
                draw.assert_called_once_with(8,15)
                sleep.assert_called_once_with(12)

    def test_cooldown_survives_restart_and_honors_long_retry_after(self):
        with tempfile.TemporaryDirectory() as temp:
            policy = RequestPolicy(Path(temp),{})
            policy.pause('HTTP 429',str(5*24*3600))
            restarted = RequestPolicy(Path(temp),{})
            until = datetime.fromisoformat(restarted.paused_until())
            self.assertGreater(until,datetime.now(timezone.utc)+timedelta(days=4))
            with self.assertRaises(CollectionPaused):
                restarted.before_request()

    def test_rate_limit_stops_remaining_requests_and_next_run(self):
        config = {'regions':{'pen':'Peninsula','sby':'South Bay'},'categories':{'apa':'rentals'},
                  'request_delay_seconds':0,'detail_limit':1,'detail_refresh_days':7}
        with tempfile.TemporaryDirectory() as temp:
            db = connect(Path(temp)/'test.sqlite3')
            calls = []
            def limited(url):
                calls.append(url)
                raise urllib.error.HTTPError(url,429,'Rate limited',{'Retry-After':'86400'},None)
            with self.assertLogs('listing_monitor.collector'):
                first = collect(db,config,temp,fetcher=limited)
                second = collect(db,config,temp,fetcher=limited)
            self.assertEqual(len(calls),1)
            self.assertEqual(first['searches_failed'],1)
            self.assertEqual(first['searches_skipped'],1)
            self.assertEqual(second['searches_skipped'],2)
            self.assertEqual(db.execute('SELECT count(*) FROM observations').fetchone()[0],0)
            db.close()

    def test_scheduler_runs_job_and_propagates_failure_without_delay(self):
        script = Path(__file__).resolve().parent.parent/'scripts'/'scheduled-run.py'
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root/'scripts').mkdir()
            (root/'scripts'/'daily-run.sh').write_text('#!/bin/sh\necho ran > ran.txt\nexit 3\n')
            result = subprocess.run([sys.executable,str(script),'--project-dir',temp,'--max-delay-seconds','0'])
            self.assertEqual(result.returncode,3)
            self.assertTrue((root/'ran.txt').exists())
            log = (root/'data/logs/schedule.log').read_text()
            self.assertIn('delay_seconds=0',log)
            self.assertIn('finished status=3',log)

    def test_url_formats_and_untrusted_hosts(self):
        self.assertEqual(source_id('https://sfbay.craigslist.org/pen/apa/d/studio/12345.html'),'12345')
        self.assertEqual(source_id('https://www.craigslist.org/view/d/studio/abc_DEF'),'abc_DEF')
        with self.assertRaises(ValueError):
            source_id('https://craigslist.org.evil.example/view/d/foo/123')

    def test_period_geography_and_missing_coordinates(self):
        row = parse_search(search(104,'From $104/nt or $567/wk'), 'sublets')[0]
        self.assertEqual(row['price_period'],'night')
        self.assertTrue(row['short_term'])
        self.assertEqual(row['county'],'Santa Clara')
        self.assertIsNone(parse_search(search(coordinates=False),'rooms')[0]['latitude'])
        self.assertEqual(parse_search(search(567,'From $104/nt or $567/wk'),'sublets')[0]['price_period'],'week')

    def test_challenge_and_mismatched_structured_data_fail(self):
        with self.assertRaises(ValueError):
            parse_search('<h1>Verify you are human</h1>','rentals')
        with self.assertRaises(ValueError):
            parse_search(search().replace('"name": "Furnished studio"','"name": "Wrong"'),'rentals')

    def test_room_sqft_does_not_become_dwelling_sqft(self):
        parsed = parse_detail(detail().replace('apartment furnished','apartment private room'))
        self.assertEqual(parsed['sqft'],500)
        self.assertEqual(parsed['sqft_scope'],'unknown')

    def test_daily_identity_history_and_price_changes(self):
        with tempfile.TemporaryDirectory() as temp:
            db = connect(Path(temp)/'test.sqlite3')
            row = parse_search(search(),'rentals')[0]
            def run(day,key='pen:apa'):
                return db.execute('INSERT INTO runs(started_at,search_key,url,status) VALUES(?,?,?,?)',
                      (day,key,'https://sfbay.craigslist.org/search/pen/apa','partial')).lastrowid
            day1,day2 = '2026-10-01T12:00:00+00:00','2026-10-02T12:00:00+00:00'
            first = run(day1)
            save(db,first,row,day1)
            # Enrichment promotes opaque ID and updates a single observation.
            save(db,first,row,day1,parse_detail(detail()))
            self.assertEqual(db.execute('SELECT count(*) FROM observations').fetchone()[0],1)
            row2 = dict(row,price=2000)
            save(db,run(day2),row2,day2)
            save(db,run(day2,'sby:apa'),row2,day2)
            report = build_report(db,['Santa Clara'])
            self.assertEqual(report['history_listings'],1)
            self.assertEqual(report['latest_unique_listings'],1)
            self.assertEqual(report['price_changes'],1)
            self.assertEqual(db.execute('SELECT observed_days FROM listing_history').fetchone()[0],2)
            # A fresh repost URL resolves to the same canonical post, not a second home.
            save(db,run('2026-10-03T12:00:00+00:00'),dict(row,source_id='different_alias'),
                 '2026-10-03T12:00:00+00:00',parse_detail(detail()))
            self.assertEqual(db.execute('SELECT count(*) FROM listings').fetchone()[0],1)
            db.close()

    def test_collector_failure_preserves_sample_and_logs_attempt(self):
        config = {'regions':{'pen':'Peninsula'},'categories':{'apa':'rentals'},
                  'request_delay_seconds':0,'detail_limit':1,'detail_refresh_days':7}
        with tempfile.TemporaryDirectory() as temp:
            db = connect(Path(temp)/'test.sqlite3')
            def fetch(url):
                return (detail() if '/view/' in url else search()).encode(),200,'text/html'
            result = collect(db,config,temp,fetcher=fetch)
            self.assertEqual(result['details_ok'],1)
            self.assertEqual(db.execute('SELECT complete FROM runs').fetchone()[0],0)
            self.assertEqual(db.execute('SELECT observed_listings FROM daily_geo_summary').fetchone()[0],1)
            self.assertEqual(db.execute('SELECT sqft FROM observations').fetchone()[0],500)
            self.assertTrue(list((Path(temp)/'raw/craigslist').glob('*.html')))
            def fail(url):
                raise urllib.error.HTTPError(url,403,'Forbidden',{},None)
            with self.assertLogs('listing_monitor.collector',level='ERROR'):
                result = collect(db,config,temp,fetcher=fail)
            self.assertEqual(result['searches_failed'],1)
            last = db.execute('SELECT * FROM runs ORDER BY id DESC LIMIT 1').fetchone()
            self.assertIsNone(last['observed_count'])
            self.assertEqual(last['http_status'],403)
            self.assertEqual(build_report(db,['Santa Clara'])['latest_unique_listings'],1)
            health = db.execute('SELECT * FROM daily_collection_health').fetchone()
            self.assertEqual(health['failed_searches'],1)
            self.assertEqual(health['failed_search_attempts'],1)
            db.close()

    def test_failed_detail_preserves_search_and_does_not_invent_sqft(self):
        config = {'regions':{'sfc':'SF'},'categories':{'roo':'rooms'},
                  'request_delay_seconds':0,'detail_limit':1,'detail_refresh_days':7}
        with tempfile.TemporaryDirectory() as temp:
            db = connect(Path(temp)/'test.sqlite3')
            def fetch(url):
                if '/view/' in url:
                    return b'<h1>Posting removed</h1>',200,'text/html'
                return search(coordinates=False).encode(),200,'text/html'
            with self.assertLogs('listing_monitor.collector',level='ERROR'):
                result = collect(db,config,temp,fetcher=fetch)
            self.assertEqual(result['searches_ok'],1)
            self.assertEqual(result['details_failed'],1)
            self.assertIsNone(db.execute('SELECT sqft FROM observations').fetchone()[0])
            self.assertEqual(db.execute('SELECT status FROM detail_attempts').fetchone()[0],'failed')
            report = build_report(db,['Santa Clara'])
            self.assertEqual(report['coordinate_listings'],0)
            self.assertEqual(report['latest_unique_listings'],1)
            db.close()


if __name__ == '__main__':
    unittest.main()
