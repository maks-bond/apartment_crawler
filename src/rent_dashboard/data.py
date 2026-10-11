import json
import math
import sqlite3
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import median


def readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True,timeout=5)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    return db


def positive(value):
    return value is not None and value > 0


def metric(rows):
    prices = [r['price'] for r in rows if positive(r['price'])]
    ratios = [r['price']/r['sqft'] for r in rows if positive(r['price']) and
              positive(r['sqft']) and r['sqft_eligible']]
    return {'inventory':len(rows),'priced':len(prices),'sqft_priced':len(ratios),
            'median_price':median(prices) if prices else None,
            'median_psf':median(ratios) if ratios else None}


def normalize_cl(row):
    raw = json.loads(row['data_json'])
    return {'id':row['listing_id'],'property_id':None,'label':raw.get('title','Untitled listing'),
        'city':row['city'],'county':row['county'],'category':row['category'],
        'bedrooms':row['bedrooms'],'price':row['price'],'period':row['price_period'],
        'sqft':row['sqft'],'sqft_eligible':row['sqft_scope']=='dwelling' and row['category']!='rooms',
        'latitude':raw.get('latitude'),'longitude':raw.get('longitude'),'geo_cell':raw.get('geo_cell'),
        'short_term':bool(raw.get('short_term')),'url':raw.get('url'),
        'location_label':raw.get('location_label'),'observed_at':row['observed_at'],
        'day':row['observed_at'][:10],'first_seen':row['first_seen'],'last_seen':row['observed_at'],
        'basis':row['category']+':'+str(row['price_period']),
        'detail_observed_at':raw.get('detail_observed_at'),
        'period_evidence':raw.get('period_evidence'),'posted_at':raw.get('posted_at'),
        'available_from':None,'lease_months':None,'search_key':row['search_key']}


def normalize_community(row):
    metadata = json.loads(row['metadata_json'])
    exact = row['square_feet_min'] == row['square_feet_max']
    return {'id':row['source_listing_id'],'property_id':row['property_id'],
        'label':row['name']+' · '+str(row['unit_label'] or row['source_listing_id']),
        'city':metadata.get('city'),'county':None,'category':'rentals','bedrooms':row['bedrooms'],
        'price':row['base_rent_min'],'period':'month','sqft':row['square_feet_min'],
        'sqft_eligible':exact,'latitude':None,'longitude':None,'geo_cell':None,'short_term':False,
        'url':row['availability_url'],'location_label':metadata.get('address'),
        'observed_at':row['observed_at'],'day':row['observed_at'][:10],
        'first_seen':row['first_seen'],'last_seen':row['observed_at'],
        'basis':str(row['lease_months'])+':'+str(row['requested_move_in_date']),
        'detail_observed_at':row['observed_at'],'period_evidence':'official_base_rent',
        'posted_at':None,'available_from':row['available_from'],'lease_months':row['lease_months'],
        'search_key':row['property_id']}


class Store:
    def __init__(self, project):
        self.project = Path(project)

    def path(self, source):
        return self.project/'data'/('craigslist.sqlite3' if source=='craigslist' else 'apartment_monitor.sqlite3')

    def expected(self, source):
        if source=='craigslist':
            config = json.loads((self.project/'config/craigslist.json').read_text())
            return [region+':'+cat for region in config['regions'] for cat in config['categories']]
        return [p['id'] for p in json.loads((self.project/'config/properties.json').read_text()) if p.get('enabled')]

    def meta(self):
        result = {'today':datetime.now(timezone.utc).date().isoformat(),'sources':{},'cell_degrees':0.01}
        config = self.project/'config/craigslist.json'
        if config.exists():
            result['cell_degrees'] = json.loads(config.read_text()).get('geo_cell_degrees',0.01)
        for source in ('craigslist','communities'):
            if not self.path(source).exists():
                result['sources'][source] = {'available':False,'cities':[],'properties':[]}
                continue
            db = readonly(self.path(source))
            try:
                bounds = db.execute('SELECT min(observed_at),max(observed_at) FROM observations').fetchone()
                if source=='craigslist':
                    cities = [r[0] for r in db.execute('SELECT DISTINCT city FROM observations WHERE city IS NOT NULL ORDER BY city')]
                    props = []
                else:
                    props = [dict(r) for r in db.execute('SELECT id,name,metadata_json FROM properties WHERE enabled=1 ORDER BY name')]
                    for p in props:
                        p['city'] = json.loads(p.pop('metadata_json')).get('city')
                    cities = sorted({p['city'] for p in props if p['city']})
                result['sources'][source] = {'available':True,'first_day':bounds[0][:10] if bounds[0] else None,
                    'last_day':bounds[1][:10] if bounds[1] else None,'cities':cities,'properties':props}
            finally:
                db.close()
        return result

    def read(self, source, start, end):
        db = readonly(self.path(source))
        try:
            if source=='craigslist':
                rows = db.execute('''SELECT o.*,l.first_seen,l.last_seen,r.search_key
                    FROM daily_sample o JOIN listings l ON l.id=o.listing_id JOIN runs r ON r.id=o.run_id
                    WHERE substr(o.observed_at,1,10) BETWEEN ? AND ? ORDER BY o.observed_at,o.id''',(start,end))
                items = [normalize_cl(r) for r in rows]
                runs = [dict(r) for r in db.execute('''SELECT id,search_key,started_at,finished_at,status,
                     observed_count,http_status,error,substr(started_at,1,10) AS day
                     FROM runs WHERE substr(started_at,1,10)<=? ORDER BY started_at,id''',(end,))]
                failures = [dict(r) for r in db.execute('''SELECT source_id AS id,attempted_at AS started_at,
                    status,http_status,error FROM detail_attempts WHERE status='failed'
                    AND substr(attempted_at,1,10) BETWEEN ? AND ? ORDER BY attempted_at DESC LIMIT 30''',(start,end))]
            else:
                rows = db.execute('''WITH ranked AS (
                    SELECT id,property_id,date(finished_at) AS day,row_number() OVER (
                    PARTITION BY property_id,date(finished_at) ORDER BY rowid DESC) AS n
                    FROM collection_runs WHERE status IN ('success_complete','explicit_no_availability')
                    AND completeness='complete' AND date(finished_at) BETWEEN ? AND ?)
                    SELECT o.*,p.name,p.availability_url,p.metadata_json,h.first_seen_at AS first_seen,h.last_seen_at AS last_seen
                    FROM ranked r JOIN observations o ON o.run_id=r.id JOIN properties p ON p.id=o.property_id
                    JOIN unit_history_summary h ON h.property_id=o.property_id AND h.source_listing_id=o.source_listing_id
                    WHERE r.n=1 ORDER BY o.observed_at,o.id''',(start,end))
                items = [normalize_community(r) for r in rows]
                runs = [dict(r) for r in db.execute('''SELECT id,property_id AS search_key,started_at,finished_at,status,
                    observed_count,http_status,error,coalesce(date(finished_at),date(started_at)) AS day
                    FROM collection_runs WHERE coalesce(date(finished_at),date(started_at))<=? ORDER BY started_at,rowid''',(end,))]
                failures = []
            return items,runs,failures
        finally:
            db.close()

    def dashboard(self, query):
        source = query.get('source','craigslist')
        if source not in ('craigslist','communities'):
            raise ValueError('Unknown source')
        end = date.fromisoformat(query.get('to') or datetime.now(timezone.utc).date().isoformat())
        start = date.fromisoformat(query.get('from') or (end-timedelta(days=30)).isoformat())
        if start>end or (end-start).days>730:
            raise ValueError('Choose an ordered date range of at most 731 days')
        bbox = None
        if query.get('bbox'):
            bbox = list(map(float,query['bbox'].split(',')))
            if len(bbox)!=4 or not (-180<=bbox[0]<bbox[2]<=180 and -90<=bbox[1]<bbox[3]<=90):
                raise ValueError('Geofence must be west,south,east,north in decimal degrees')
        minimum = float(query['sqft_min']) if query.get('sqft_min') else None
        maximum = float(query['sqft_max']) if query.get('sqft_max') else None
        if any(v is not None and not math.isfinite(v) for v in (minimum,maximum)):
            raise ValueError('Square-footage bounds must be finite')
        if (minimum is not None and minimum<0) or (maximum is not None and (maximum<0 or minimum is not None and maximum<minimum)):
            raise ValueError('Invalid square-footage range')
        items,runs,details = self.read(source,start.isoformat(),end.isoformat()) if self.path(source).exists() else ([],[],[])
        expected = self.expected(source)
        if query.get('property'):
            expected = [k for k in expected if k==query['property']]
        good_status = ('partial',) if source=='craigslist' else ('success_complete','explicit_no_availability')
        latest,success = {},{}
        coverage = defaultdict(set)
        failures_by_day = defaultdict(int)
        for run in runs:
            if run['search_key'] not in expected:
                continue
            latest[run['search_key']] = run
            if run['status'] in good_status:
                coverage[run['day']].add(run['search_key'])
                success[run['search_key']] = run
            elif run['day']>=start.isoformat():
                failures_by_day[run['day']] += 1
        snapshot_day = max((d for d in coverage if start.isoformat()<=d<=end.isoformat()),default=None)
        def accepts(row):
            if row['search_key'] not in expected:
                return False
            for field in ('city','county','category','property_id'):
                target = query.get('property' if field=='property_id' else field)
                if target and row[field]!=target:
                    return False
            if query.get('bedrooms') and row['bedrooms']!=float(query['bedrooms']):
                return False
            if row['period']!=query.get('period','month'):
                return False
            if query.get('short_term')=='1' and not row['short_term']:
                return False
            if minimum is not None or maximum is not None:
                if not row['sqft_eligible'] or row['sqft'] is None:
                    return False
                if minimum is not None and row['sqft']<minimum or maximum is not None and row['sqft']>maximum:
                    return False
            if bbox:
                if row['longitude'] is None or row['latitude'] is None:
                    return False
                if not (bbox[0]<=row['longitude']<=bbox[2] and bbox[1]<=row['latitude']<=bbox[3]):
                    return False
            return True
        selected = {}
        for row in items:
            if accepts(row):
                # Database columns are authoritative after opaque-ID promotion.
                selected[(row['day'],row['property_id'],row['id'])] = row
        days = defaultdict(list)
        for row in selected.values():
            days[row['day']].append(row)
        series,previous = [],None
        for n in range((end-start).days+1):
            day = (start+timedelta(days=n)).isoformat()
            sample = days[day]
            usable = len(coverage[day])
            point = {'day':day,**metric(sample),'usable_sources':usable,'expected_sources':len(expected),
                     'coverage_key':','.join(sorted(coverage[day])),
                     'failed_attempts':failures_by_day[day],'matched_count':0,'matched_change_pct':None}
            if not usable:
                point.update(inventory=None,median_price=None,median_psf=None)
            else:
                current = {(r['property_id'],r['id'],r['basis']):r for r in sample if positive(r['price'])}
                # Compare adjacent days only when the set of usable sources is unchanged.
                if previous is not None and coverage[day]==coverage[previous[0]]:
                    changes = [100*(r['price']/previous[1][key]['price']-1) for key,r in current.items() if key in previous[1]]
                    point['matched_count'] = len(changes)
                    point['matched_change_pct'] = median(changes) if changes else None
                previous = (day,current)
            if not usable:
                previous = None
            series.append(point)
        current = days[snapshot_day] if snapshot_day else []
        cities,cells = defaultdict(list),defaultdict(list)
        for row in current:
            cities[row['city'] or 'Unknown city'].append(row)
            if row['geo_cell']:
                cells[row['geo_cell']].append(row)
        health = [dict(latest[k]) if k in latest else {'search_key':k,'status':'not_run','day':None,
                   'http_status':None,'error':None,'started_at':None,'finished_at':None} for k in expected]
        for item in health:
            item['last_success_day'] = success.get(item['search_key'],{}).get('day')
        overview = metric(current)
        if not snapshot_day:
            overview['inventory'] = None
        overview.update(coordinates=sum(r['latitude'] is not None and r['longitude'] is not None for r in current),
                        default_period_prices=sum(r['period_evidence']=='housing_default_assumption' and positive(r['price']) for r in current))
        return {'source':source,'period':query.get('period','month'),'snapshot_day':snapshot_day,
            'as_of':end.isoformat(),'stats':overview,'series':series,'expected_sources':len(expected),
            'snapshot_sources':len(coverage[snapshot_day]) if snapshot_day else 0,
            'latest_health':health,'detail_failures':details,
            'cities':[{'city':name,**metric(rows)} for name,rows in sorted(cities.items())],
            'cells':[{'cell':name,**metric(rows)} for name,rows in cells.items()],
            'listings':sorted(current,key=lambda r:(r['price'] is None or r['price']<=0,r['price'] or 0,r['label'])),
            'partial':source=='craigslist','bbox':bbox}

    def history(self, source, identity, property_id=None):
        if source not in ('craigslist','communities') or not identity:
            raise ValueError('Choose a source and listing ID')
        db = readonly(self.path(source))
        try:
            if source=='craigslist':
                rows = db.execute('''SELECT o.*,l.first_seen,l.last_seen,r.search_key FROM observations o
                    JOIN listings l ON l.id=o.listing_id JOIN runs r ON r.id=o.run_id
                    WHERE o.listing_id=? ORDER BY o.observed_at,o.id''',(identity,))
                result = [normalize_cl(r) for r in rows]
            else:
                rows = db.execute('''SELECT o.*,p.name,p.availability_url,p.metadata_json,
                    h.first_seen_at AS first_seen,h.last_seen_at AS last_seen FROM observations o
                    JOIN properties p ON p.id=o.property_id JOIN unit_history_summary h ON
                    h.property_id=o.property_id AND h.source_listing_id=o.source_listing_id
                    WHERE o.source_listing_id=? AND o.property_id=? ORDER BY o.observed_at,o.id''',(identity,property_id))
                result = [normalize_community(r) for r in rows]
            unique = {(r['day'],r['basis']):r for r in result}
            return {'observations':list(unique.values())}
        finally:
            db.close()
