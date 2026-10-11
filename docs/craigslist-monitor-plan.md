# Craigslist monitor: implementation and operations

Last updated: 2026-10-11 (America/Los_Angeles). First live collection succeeded.

## Scope and verified first run

User selected San Francisco, San Mateo, and Santa Clara counties, with rentals,
rooms/shares, and short-term sublets; short-term housing is preferred. Community
advertiser ads are included. All bedroom counts are retained for later filtering.
Cities are normalized when supported by an exact advertised locality. Neighborhood
normalization and commercial-ad classification remain unimplemented; advertiser
identity is unknown rather than inferred from marketing language.

Nine searches run daily: `sfc`, `pen`, `sby` crossed with `apa`, `roo`, `sub`.
These search areas cross county boundaries. Source search area and advertised
location remain separate. Unknown/other locations stay in the database and map
history, but are excluded from the three-county city statistics.

Live collection on October 11:

| Search area | Rentals | Rooms | Sublets |
|---|---:|---:|---:|
| San Francisco | 355 | 202 | 86 |
| Peninsula | 359 | 144 | 25 |
| South Bay | 354 | 324 | 18 |

- All 9 searches returned usable samples; no search failures.
- 1,867 unique observed listing IDs; 1,867/1,867 supplied map coordinates.
- 1,757 mapped to target counties by advertised city; 110 unknown/other county.
- 425 geographic cells were represented.
- 90/90 requested detail pages parsed; no detail failures. Remaining 1,777
  listings have search-level data; missing detail fields are unknown.
- Square footage was exposed for 48 ads; 22 have uncertain room/dwelling scope.
  Only 24 have usable monthly dwelling rent per square foot in this first sample.
- 1,858 asking amounts assumed or identified monthly, 3 nightly, 2 weekly, 4
  ambiguous. Bare housing prices default to monthly with explicit assumption
  provenance. They are not verified monthly quotes.
- Zero price changes so far: one collection establishes a baseline, not a trend.

## Source validation and completeness

Ordinary public HTML exposes a static listing list and position-matched JSON-LD
(`ld_searchpage_results`). The parser validates counts and titles before pairing
URLs, prices, locations, bedrooms, bathrooms, and coordinates. Changed markup,
challenges, and transport failures are logged as failures, never zero inventory.
Detail pages expose `ld_posting_data`, housing attributes, square footage when
present, numeric post IDs, posting/update timestamps, and map accuracy metadata.

Current search URLs redirect to the `www.craigslist.org` public search routes.
Listing URLs may have opaque IDs containing underscores, in addition to legacy
numeric `.html` IDs. Both formats are supported.

There is no verified total/pagination contract in the current static responses.
Every successful search therefore has status `partial` and `complete=0`, including
an empty parsed sample. Counts describe observed ads, not all available rentals.
No Craigslist disappearance/rented events are generated. Increasing sampled ad
counts do not alone establish increasing market availability.

Official source examples:
- https://sfbay.craigslist.org/search/sfc/apa
- https://sfbay.craigslist.org/search/pen/sub
- https://sfbay.craigslist.org/search/sby/roo

Craigslist terms prohibit automated collection unless separately licensed:
https://www.craigslist.org/about/terms (USE section). Public accessibility does not
establish an authorized API. This collector uses ordinary unauthenticated requests;
it does not bypass authentication or access challenges. No retries are made on a
failed request. The first validation used a two-second request interval. Scheduled
collection now waits a random 8–15 seconds after the previous request completes,
with one concurrent request and a cap of 9 searches plus 90 detail pages per day.
HTTP 401/403/429 or a recognized access challenge stops remaining requests and
persists a 48-hour cooldown in `data/craigslist-cooldown.json`. A longer
`Retry-After`, whether seconds or an HTTP date, extends that cooldown. Later runs
record searches as skipped without contacting Craigslist while paused. Slower
collection reduces pressure but cannot guarantee access or prevent a ban.

### Review of the suggested repository

Reviewed https://github.com/masterfung/scrapy-craigslist on October 11, including
its spider, settings, items and pipeline. Its older spider uses page selectors
that do not match the currently verified static/JSON-LD contract. Its pipeline
deduplicates by title within a process, which would merge distinct homes and does
not preserve cross-day identity. Its settings configure a browser user agent but
no explicit download delay. No source code was copied. We retain persistent post
IDs, an identifying monitor user agent and the bounded request policy above.

## Code, schedule and outputs

- `src/apartment_monitor/`: existing community inventory monitor and SQLite DB.
- `src/listing_monitor/`: independent Craigslist parser, collector, database,
  reporting and CLI; reuses the existing HTTP helper and process lock.
- `config/craigslist.json`: regions, categories, target counties, request-delay bounds,
  daily detail budget (90), detail refresh interval (7 days), cell size (0.01°).
- `data/craigslist.sqlite3`: local observations and source health, separate from
  `data/apartment_monitor.sqlite3`. Runtime data is ignored by Git.
- `data/raw/craigslist/`: SHA-256-addressed source bodies, including parse failures
  and HTTP error bodies when returned. These public pages may contain advertiser
  contact text; contact details are not extracted into structured records.
- `data/logs/craigslist.log`: timestamps, search/detail IDs and failure tracebacks.
- `reports/craigslist-latest.md`, `reports/craigslist-stats.json`: readable summary
  and full daily city/type/100-square-foot-bucket and cell statistics.

The user cron was updated and verified on October 11:

```cron
7 9 * * * /home/maksym/dev/apartment_crawler/scripts/scheduled-run.py
```

The scheduler waits an independently drawn random 0–1,200 seconds each day, so
both collectors start between 09:07 and 09:27 local machine time (09:17 ±10
minutes). `data/logs/schedule.log` records the selected delay, actual runner start
and final status. Collection is still once daily. Community failures do not
prevent Craigslist from running. The runner logs
individual exit statuses and returns failure if either collection fails. Separate
locks prevent overlapping collections. No additional cron entry is needed.

```bash
PYTHONPATH=src python3 -m listing_monitor collect
PYTHONPATH=src python3 -m listing_monitor report
PYTHONPATH=src python3 -m unittest discover -s tests -q
```

All 25 tests passed, including 11 Craigslist/scheduler tests covering both ID formats,
canonical-ID merging, multiple days of price history, overlapping searches,
room square-footage uncertainty, rate-period separation, missing coordinates,
failed details, failed searches, raw artifacts, geographic aggregation, randomized
pacing, persistent cooldowns, rate-limit request suppression across runs and
scheduler failure propagation. A runner smoke check also verified that community
failures do not prevent the listing collector or either report from running.

## Listing identity and daily history

`listings` contains one record per known post identity; `aliases` maps search URL
IDs onto it. A numeric post ID from a detail page promotes an opaque identity and
merges known aliases. Repeated daily discoveries update last seen and append
observations, not new listings. Overlapping searches are deduplicated in daily
statistics by date, post identity and category. Detail enrichment updates the
same run's observation rather than manufacturing another price sample.

`observations` retains asking amount, price period/evidence, advertised city and
county, bedrooms, square feet/scope, category, coordinates/cell, source URL, and
structured housing fields in `data_json`. Detail fields retain a separate
observation timestamp because cached square feet/attributes can be stale.
Room bedroom counts may describe the shared dwelling, not the rented room.

`price_changes` records comparable same-ID, same-category, same-period changes.
Nightly/weekly asking prices are not converted to monthly equivalents.
`listing_history` exposes first/last seen, number of distinct observed days, and
monthly low/high asking prices. `observed_span_days` is elapsed time between
observations; it does not prove continuous time advertised or time on market.

Different post IDs can advertise the same home or commercial inventory. They are
not merged heuristically. Unresolved opaque aliases can remain distinct until
both expose a common numeric post ID. Repost/unit matching is future work.

## Geography and database queries

Coordinates are advertised, potentially approximate map points, not verified
addresses. Every first-run ad had them, but the parser accepts missing points.
`geo_cell` uses a fixed latitude/longitude grid anchored at 0°, encoded as
`cell_size:floor(latitude/size):floor(longitude/size)`. At 0.01° the cells are
roughly 1.1 km north/south and 0.9 km east/west in the Bay Area; this is not an
equal-area grid. Keep its configured size fixed for comparable history.

`geo_history` exposes coordinates/cells as queryable SQLite columns.
`daily_geo_summary` and `daily_region_summary` deduplicate daily samples and expose
counts and mean rent/rent-per-square-foot with coverage counts. JSON reports add
median metrics. Dates are UTC; schedule time is local. Latest failed attempts are
reported separately from retained older samples.

`daily_collection_health` records the daily coverage summary from durable attempt
records. The Markdown report shows the most recent seven recorded dates, with
usable/failed/skipped/unfinished searches and detail failures. Nine usable searches
are expected for a normal run. A missing date means the cron/application did not
record an attempt and must be investigated; it is never interpreted as zero
inventory. Scheduler startup/exit logs distinguish job-level failure from source
failure. No notification delivery or presentation website is configured yet.

Example rectangular geofence history (replace coordinates with your bounds):

```sql
SELECT observed_at, listing_id, category, price, price_period, sqft, data_json
FROM geo_history
WHERE longitude BETWEEN -122.15 AND -122.05
  AND latitude BETWEEN 37.35 AND 37.45
ORDER BY observed_at, listing_id;

SELECT * FROM daily_geo_summary ORDER BY day_utc, geo_cell;
SELECT * FROM daily_region_summary ORDER BY day_utc, county, city;
SELECT * FROM listing_history ORDER BY observed_span_days DESC;
SELECT * FROM runs WHERE status='failed';
SELECT * FROM detail_attempts WHERE status='failed';
SELECT * FROM daily_collection_health ORDER BY day_utc DESC;
```

Polygon geofences can be evaluated from stored points later. County mapping is
based on advertised city, not a verified boundary polygon. Approximate points
near boundaries can change cells without a home moving.

## Next milestones

Validate total/pagination coverage before market-wide supply or disappearance
claims; increase useful square-footage coverage within an explicit request budget;
validate rent periods against detail text; improve uncertain city/neighborhood
assignment; classify commercial advertising with evidence; evaluate separate-ID
reposts; add trend notifications once enough comparable days exist. Daily history
collection is enabled now; completeness, deduplication and coverage limits must
remain visible in future analyses.
