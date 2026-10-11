import json
from collections import defaultdict
from statistics import median


def stats(rows):
    priced = [r['price'] for r in rows if r['price'] is not None and r['price'] > 0]
    sqft = [r['price']/r['sqft'] for r in rows if r['price'] and r['sqft'] and
            r['sqft_scope'] == 'dwelling' and r['category'] != 'rooms']
    return {'observed_listings':len(rows), 'priced_listings':len(priced),
            'median_price':median(priced) if priced else None,
            'sqft_priced_listings':len(sqft), 'median_price_per_sqft':median(sqft) if sqft else None}


def build_report(db, target_counties):
    rows = [dict(r) for r in db.execute('SELECT * FROM daily_sample ORDER BY observed_at,id')]
    # Deduplicate overlapping searches for the same date, listing and category.
    unique = {}
    for row in rows:
        row.update(json.loads(row['data_json']))
        unique[(row['observed_at'][:10],row['listing_id'],row['category'])] = row
    groups = defaultdict(list)
    cells = defaultdict(list)
    for (day,_,_),row in unique.items():
        size = int(row['sqft']//100)*100 if row['sqft'] and row['sqft_scope']=='dwelling' else None
        kind = 'room' if row.get('room') or row['category']=='rooms' else row.get('housing_type','unknown')
        if row['county'] in target_counties:
            groups[(day,row['county'],row['city'],row['category'],kind,row['bedrooms'],size,row['price_period'])].append(row)
        if row.get('geo_cell'):
            cells[(day,row['geo_cell'],row['category'],kind,row['bedrooms'],row['price_period'])].append(row)
    daily = [dict(zip(['day','county','city','category','housing_type','bedrooms','sqft_bucket','price_period'],key),**stats(value))
             for key,value in groups.items()]
    geo_daily = [dict(zip(['day','geo_cell','category','housing_type','bedrooms','price_period'],key),**stats(value))
                 for key,value in cells.items()]
    searches = [dict(r) for r in db.execute('SELECT * FROM runs WHERE id IN '
        '(SELECT max(id) FROM runs GROUP BY search_key) ORDER BY search_key')]
    latest_day = db.execute("SELECT max(substr(started_at,1,10)) FROM runs WHERE status='partial'").fetchone()[0]
    latest = {}
    for (day,key,_),row in unique.items():
        if day == latest_day:
            latest[key] = row
    return {'coverage':'partial search samples; no market-wide inventory or disappearance claims',
            'latest_day_utc':latest_day,'searches':searches,
            'latest_unique_listings':len(latest),
            'coordinate_listings':sum(r['latitude'] is not None and r['longitude'] is not None for r in latest.values()),
            'target_county_listings':sum(r['county'] in target_counties for r in latest.values()),
            'unknown_or_other_county_listings':sum(r['county'] not in target_counties for r in latest.values()),
            'with_sqft':sum(bool(r['sqft']) for r in latest.values()),
            'daily_stats':daily,'daily_geo_stats':geo_daily,
            'daily_health':[dict(r) for r in db.execute('SELECT * FROM daily_collection_health ORDER BY day_utc')],
            'price_changes':db.execute('SELECT count(*) FROM price_changes').fetchone()[0],
            'history_listings':db.execute('SELECT count(*) FROM listings').fetchone()[0]}


def write_report(db, config, output):
    result = build_report(db,config['target_counties'])
    result['expected_daily_searches'] = len(config['regions'])*len(config['categories'])
    output.mkdir(parents=True,exist_ok=True)
    (output/'craigslist-stats.json').write_text(json.dumps(result,indent=2)+'\n')
    good = sum(s['status']=='partial' for s in result['searches'])
    text = f'''# Craigslist daily sample — {result['latest_day_utc']}

Searches returning usable samples: {good}/{len(result['searches'])}.
Unique observed listing IDs: {result['latest_unique_listings']}.
Coordinates: {result['coordinate_listings']}/{result['latest_unique_listings']}.
Advertised locality mapped to target counties: {result['target_county_listings']}.
Unknown/other county: {result['unknown_or_other_county_listings']}.
Square footage available (including unknown room scope): {result['with_sqft']}.
Same-listing price changes recorded: {result['price_changes']}.

These are partial search samples, not total available homes. Duplicate post IDs are
merged across searches and dates; each day's observation is retained. Different
post IDs may advertise the same rental. A disappeared ad does not prove a lease.
Observed span is a lower bound, not continuous time on market.
Rent periods remain separate. Bare housing prices are assumed monthly and their
evidence is stored. Room square footage with unknown scope is excluded from
price-per-square-foot statistics. Cached detail fields have their own timestamp.
Map coordinates are approximate advertised locations, not verified addresses.
City/county assignment uses advertised locality; cross-posts and errors can occur.
Failed searches never produce zero inventory. A retained daily sample may be older
than a failed latest attempt; inspect search timestamps in the JSON report.

Full daily city/type/size and geographic-cell summaries: `craigslist-stats.json`.
'''
    text += '\n## Recent collection health\n\n'
    text += f"Expected searches per daily run: {result['expected_daily_searches']}. Dates are UTC.\n\n"
    text += '| Date | Usable searches | Failed searches | Skipped | Unfinished | Detail failures |\n'
    text += '|---|---:|---:|---:|---:|---:|\n'
    for health in result['daily_health'][-7:]:
        text += (f"| {health['day_utc']} | {health['usable_searches']} | {health['failed_searches']} | "
                 f"{health['skipped_searches']} | {health['unfinished_searches']} | {health['failed_detail_attempts']} |\n")
    text += '\nA missing date means no search attempt was recorded, not a successful empty collection.\n'
    (output/'craigslist-latest.md').write_text(text)
    return {k:v for k,v in result.items() if k not in ('daily_stats','daily_geo_stats','daily_health','searches')}
