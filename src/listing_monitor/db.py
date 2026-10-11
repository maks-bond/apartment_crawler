import json
import sqlite3
from pathlib import Path


SCHEMA = '''
CREATE TABLE IF NOT EXISTS runs (
 id INTEGER PRIMARY KEY, started_at TEXT NOT NULL, finished_at TEXT,
 search_key TEXT NOT NULL, url TEXT NOT NULL, status TEXT NOT NULL,
 complete INTEGER NOT NULL DEFAULT 0, observed_count INTEGER, error TEXT,
 http_status INTEGER, artifact_path TEXT, sha256 TEXT, parser_version TEXT DEFAULT 'cl-static-v1');
CREATE INDEX IF NOT EXISTS run_daily_search ON runs(search_key,substr(started_at,1,10),started_at,id);
CREATE TABLE IF NOT EXISTS listings (
 id TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
 detail_json TEXT, detail_checked_at TEXT);
CREATE TABLE IF NOT EXISTS aliases (source_id TEXT PRIMARY KEY, listing_id TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observations (
 id INTEGER PRIMARY KEY, run_id INTEGER NOT NULL REFERENCES runs(id), listing_id TEXT NOT NULL,
 observed_at TEXT NOT NULL, category TEXT NOT NULL, city TEXT, county TEXT,
 price REAL, price_period TEXT, sqft REAL, sqft_scope TEXT, bedrooms REAL,
 data_json TEXT NOT NULL, UNIQUE(run_id, listing_id));
CREATE INDEX IF NOT EXISTS obs_history ON observations(listing_id, observed_at);
CREATE INDEX IF NOT EXISTS obs_geo ON observations(
 json_extract(data_json,'$.longitude'),json_extract(data_json,'$.latitude'));
CREATE TABLE IF NOT EXISTS price_changes (
 id INTEGER PRIMARY KEY, listing_id TEXT NOT NULL, observed_at TEXT NOT NULL,
 previous_observation_id INTEGER, observation_id INTEGER UNIQUE,
 old_price REAL, new_price REAL, price_period TEXT);
CREATE TABLE IF NOT EXISTS detail_attempts (
 id INTEGER PRIMARY KEY, listing_id TEXT, source_id TEXT, attempted_at TEXT NOT NULL,
 status TEXT NOT NULL, error TEXT, http_status INTEGER, artifact_path TEXT, sha256 TEXT);
CREATE VIEW IF NOT EXISTS daily_sample AS
 SELECT o.* FROM observations o JOIN runs r ON r.id=o.run_id
 WHERE r.id=(SELECT r2.id FROM runs r2 WHERE r2.search_key=r.search_key
 AND substr(r2.started_at,1,10)=substr(r.started_at,1,10) AND r2.status='partial'
 ORDER BY r2.started_at DESC,r2.id DESC LIMIT 1);
CREATE VIEW IF NOT EXISTS listing_history AS
 SELECT l.id,l.first_seen,l.last_seen,
 CAST(julianday(l.last_seen)-julianday(l.first_seen) AS INTEGER) AS observed_span_days,
 count(DISTINCT substr(o.observed_at,1,10)) AS observed_days,
 min(CASE WHEN price_period='month' AND price>0 THEN price END) AS lowest_monthly_price,
 max(CASE WHEN price_period='month' AND price>0 THEN price END) AS highest_monthly_price
 FROM listings l JOIN observations o ON o.listing_id=l.id GROUP BY l.id;
CREATE VIEW IF NOT EXISTS geo_history AS
 SELECT o.*,json_extract(data_json,'$.latitude') AS latitude,
 json_extract(data_json,'$.longitude') AS longitude,
 json_extract(data_json,'$.geo_cell') AS geo_cell FROM observations o;
CREATE VIEW IF NOT EXISTS daily_geo_summary AS
 WITH ranked AS (
 SELECT *,row_number() OVER (PARTITION BY substr(observed_at,1,10),listing_id,category
 ORDER BY observed_at DESC,id DESC) AS rank FROM daily_sample),
 sample AS (SELECT *,json_extract(data_json,'$.geo_cell') AS geo_cell FROM ranked WHERE rank=1)
 SELECT substr(observed_at,1,10) AS day_utc,geo_cell,category,bedrooms,price_period,
 count(*) AS observed_listings,count(CASE WHEN price>0 THEN price END) AS priced_listings,avg(CASE WHEN price>0 THEN price END) AS mean_price,
 sum(CASE WHEN sqft>0 AND sqft_scope='dwelling' AND category!='rooms' AND price>0 THEN 1 ELSE 0 END) AS sqft_priced_listings,
 avg(CASE WHEN sqft>0 AND sqft_scope='dwelling' AND category!='rooms' AND price>0 THEN price/sqft END) AS mean_price_per_sqft
 FROM sample WHERE geo_cell IS NOT NULL GROUP BY day_utc,geo_cell,category,bedrooms,price_period;
CREATE VIEW IF NOT EXISTS daily_region_summary AS
 WITH ranked AS (
 SELECT *,row_number() OVER (PARTITION BY substr(observed_at,1,10),listing_id,category
 ORDER BY observed_at DESC,id DESC) AS rank FROM daily_sample)
 SELECT substr(observed_at,1,10) AS day_utc,county,city,category,bedrooms,price_period,
 CASE WHEN sqft_scope='dwelling' THEN CAST(sqft/100 AS INTEGER)*100 END AS sqft_bucket,
 count(*) AS observed_listings,count(CASE WHEN price>0 THEN price END) AS priced_listings,
 min(CASE WHEN price>0 THEN price END) AS minimum_price,avg(CASE WHEN price>0 THEN price END) AS mean_price,max(CASE WHEN price>0 THEN price END) AS maximum_price,
 sum(CASE WHEN sqft>0 AND sqft_scope='dwelling' AND category!='rooms' AND price>0 THEN 1 ELSE 0 END) AS sqft_priced_listings,
 avg(CASE WHEN sqft>0 AND sqft_scope='dwelling' AND category!='rooms' AND price>0 THEN price/sqft END) AS mean_price_per_sqft
 FROM ranked WHERE rank=1 GROUP BY day_utc,county,city,category,bedrooms,price_period,sqft_bucket;
CREATE VIEW IF NOT EXISTS daily_collection_health AS
 WITH ranked AS (
 SELECT *,substr(started_at,1,10) AS day_utc,row_number() OVER (
 PARTITION BY substr(started_at,1,10),search_key ORDER BY started_at DESC,id DESC) AS rank
 FROM runs)
 SELECT day_utc,count(*) AS attempted_searches,
 sum(status='partial') AS usable_searches,sum(status='failed') AS failed_searches,
 sum(status='skipped') AS skipped_searches,sum(status='running') AS unfinished_searches,
 (SELECT count(*) FROM runs r WHERE substr(r.started_at,1,10)=ranked.day_utc AND r.status='failed') AS failed_search_attempts,
 (SELECT count(*) FROM detail_attempts d WHERE substr(d.attempted_at,1,10)=ranked.day_utc AND d.status='failed') AS failed_detail_attempts,
 min(started_at) AS first_started_at,max(finished_at) AS last_finished_at
 FROM ranked WHERE rank=1 GROUP BY day_utc;
'''


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA journal_mode=WAL')
    if db.execute('PRAGMA user_version').fetchone()[0] < 1:
        for view in ['listing_history','daily_geo_summary','daily_region_summary']:
            db.execute(f'DROP VIEW IF EXISTS {view}')
    db.executescript(SCHEMA)
    db.execute('PRAGMA user_version=1')
    db.commit()
    return db


def cached_detail(db, source):
    row = db.execute('SELECT l.* FROM listings l JOIN aliases a ON a.listing_id=l.id '
                     'WHERE a.source_id=?', (source,)).fetchone()
    return dict(row) if row else None


def identity(db, source, canonical, now):
    old = db.execute('SELECT listing_id FROM aliases WHERE source_id=?', (source,)).fetchone()
    key = canonical or (old[0] if old else 'url:' + source)
    db.execute('INSERT OR IGNORE INTO listings(id,first_seen,last_seen) VALUES(?,?,?)', (key, now, now))
    if old and old[0] != key:
        previous = old[0]
        # Promote an opaque search URL identity once a numeric post ID is exposed.
        db.execute('UPDATE listings SET first_seen=min(first_seen,(SELECT first_seen FROM listings WHERE id=?)) WHERE id=?', (previous, key))
        db.execute('UPDATE OR IGNORE observations SET listing_id=? WHERE listing_id=?', (key, previous))
        db.execute('DELETE FROM observations WHERE listing_id=?', (previous,))
        db.execute('UPDATE price_changes SET listing_id=? WHERE listing_id=?', (key, previous))
        db.execute('UPDATE detail_attempts SET listing_id=? WHERE listing_id=?', (key, previous))
        db.execute('UPDATE aliases SET listing_id=? WHERE listing_id=?', (key, previous))
        db.execute('DELETE FROM listings WHERE id=?', (previous,))
    db.execute('INSERT OR REPLACE INTO aliases VALUES(?,?)', (source, key))
    return key


def save(db, run_id, row, now, fresh_detail=None):
    cached = cached_detail(db, row['source_id'])
    detail = fresh_detail or (json.loads(cached['detail_json']) if cached and cached['detail_json'] else {})
    key = identity(db, row['source_id'], detail.get('canonical_post_id'), now)
    row = dict(row)
    # Preserve today's search title/price/location; older details have their own timestamp.
    for field in ['sqft', 'sqft_scope', 'housing_type', 'room', 'attributes', 'posted_at',
                  'updated_at', 'canonical_post_id', 'map_accuracy_source_value','postal_code']:
        if field in detail:
            row[field] = detail[field]
    if row['category'] == 'rooms':
        row['room'] = True
        row['sqft_scope'] = 'unknown'
    row['detail_observed_at'] = now if fresh_detail else (cached['detail_checked_at'] if cached else None)
    row['listing_id'] = key
    db.execute('UPDATE listings SET last_seen=max(last_seen,?) WHERE id=?', (now, key))
    if fresh_detail:
        db.execute('UPDATE listings SET detail_json=?,detail_checked_at=? WHERE id=?',
                   (json.dumps(fresh_detail, sort_keys=True), now, key))
    previous = db.execute('SELECT * FROM observations WHERE listing_id=? AND category=? '
                           'ORDER BY observed_at DESC,id DESC LIMIT 1', (key, row['category'])).fetchone()
    existing = db.execute('SELECT id FROM observations WHERE run_id=? AND listing_id=?', (run_id,key)).fetchone()
    if existing:
        cur = db.execute('UPDATE observations SET sqft=?,sqft_scope=?,data_json=? WHERE id=?',
            (row['sqft'],row['sqft_scope'],json.dumps(row, sort_keys=True),existing['id']))
    else:
        cur = db.execute('INSERT INTO observations(run_id,listing_id,observed_at,category,city,county,'
            'price,price_period,sqft,sqft_scope,bedrooms,data_json) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',
            (run_id,key,now,row['category'],row['city'],row['county'],row['price'],row['price_period'],
             row['sqft'],row['sqft_scope'],row['bedrooms'],json.dumps(row, sort_keys=True)))
    if (not existing and previous and previous['price'] is not None and row['price'] is not None
        and previous['price'] > 0 and row['price'] > 0
        and previous['price_period'] == row['price_period'] != 'unknown'
        and previous['price'] != row['price']):
        db.execute('INSERT INTO price_changes(listing_id,observed_at,previous_observation_id,'
            'observation_id,old_price,new_price,price_period) VALUES(?,?,?,?,?,?,?)',
            (key,now,previous['id'],cur.lastrowid,previous['price'],row['price'],row['price_period']))
    return key
