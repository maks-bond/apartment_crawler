# Apartment Monitor Project Status

Last updated: 2026-10-29 (America/Los_Angeles)

## October 29 dashboard update

Trend plots and individual listing histories now show immediate hover cards with
values, dates and available sample/coverage counts. Hover anywhere across a plot,
tap, or focus a point with the keyboard; Escape dismisses the card. Missing values
remain explicitly unavailable.

Inventory cells now overlay a muted OpenStreetMap street background using matching
Web Mercator coordinates. Select a city or geofence for a closer view. The Street
map checkbox hides external tiles; failed tile loading leaves data and filters usable.
Tiles are requested directly by the browser only for the current viewport, with
normal browser caching and visible attribution. Daily collectors do not fetch tiles.
Restart the dashboard process to load the updated image security policy, then refresh.

Operations review: Craigslist collected all nine searches on each of October 11–29
(171/171). Ten detail pages returned 410; 1,700 succeeded. Seven communities remain
consistent, Martin/Avelle return 403, and Villa Del Sol has intermittent incomplete
responses. Daily scheduling remains enabled.

## October 11 update

Rent Observatory is now an on-demand local dashboard for both datasets. It reads
SQLite without changing it, separates current snapshots from daily trends, shows
square-footage/source coverage and failure history, and supports city/geofence
filters and individual listing histories. Run `scripts/dashboard.sh` locally or
use the SSH configuration helper on your browser computer. See
[dashboard launch and SSH instructions](dashboard.md). The dashboard is not
scheduled; daily crawlers continue independently.

The daily community monitor remains scheduled and has 35 observation dates since
September 7. Supported coverage remains 10 communities. Recent collection has
usable inventory from 7, explicit no matching inventory from Villa Del Sol, and
HTTP 403 failures for The Martin and Avelle. The initial validation table below
is historical and must not be used as today's availability.

A separate Craigslist monitor now collects nine daily rental/room/sublet search
samples across San Francisco, Peninsula and South Bay. First live run: 1,867 unique
listing IDs, coordinates for all 1,867, and 90 successful detail pages with no
request/parser failures. It stores a separate SQLite database with daily price
history, canonical-ID deduplication and geographic cells. The cron
runner now invokes both monitors, with a random daily start between 09:07 and
09:27 local time. Craigslist uses 8–15-second request pauses and a persistent
cooldown after access blocks/rate limits. The collector suite has 26 passing tests, including
exclusion of zero-price ads from market-price statistics. See
[Craigslist implementation and operations](craigslist-monitor-plan.md) for scope,
source limitations, database queries and reproducible commands.

Eight dashboard/SSH regression tests bring the full Python suite to 34 passing
tests. Real-data Chromium checks also pass for filters, geographic cells, listing
histories, both sources, trend/health views and mobile layout. No browser errors
or external web requests were observed. The preview server is stopped after QA;
the dashboard is launched on demand through a loopback-bound SSH tunnel.

## Objective

Collect daily studio and small one-bedroom availability from official apartment-community websites, retain append-only price and availability history in SQLite, and generate weekly artifacts for later market-condition analysis. The destination preference is 280 N Bernardo Ave, Mountain View. Route and bicycle evidence remains separate from rental observations and has not yet been validated.

## Coverage and initial verified result (September 7)

**10 of the 32 research-candidate apartment complexes have working collectors.** The remaining 22 do not yet have a validated collector. Counts below are the initial availability snapshot, not a measure of crawler coverage.

| Community | City | Adapter | Latest status | Matching exact units |
|---|---|---|---|---:|
| Sevens | Mountain View | Jonah embedded JSON | complete | 49 |
| Loft House | Sunnyvale | Jonah embedded JSON | complete | 6 |
| AIRE | San Jose | Jonah embedded JSON | complete | 15 |
| eaves Mountain View at Middlefield | Mountain View | Avalon Fusion | complete | 18 |
| Avalon Mountain View | Mountain View | Avalon Fusion | complete | 5 |
| The Martin | Sunnyvale | Yardi/RentCafe public WordPress actions | complete | 12 |
| Rowe at Pear Village | Mountain View | SightMap public API | complete | 4 |
| The Flats at CityLine | Sunnyvale | SightMap public API | complete | 1 |
| Avelle | Mountain View | Yardi public WordPress actions | complete | 2 |
| Villa Del Sol | Sunnyvale | G5 public GraphQL | explicit no matching availability | 0 |

All 10 sources returned a conclusive result in the final validation. Villa Del Sol currently exposes only a two-bedroom floorplan, so its zero means a complete response with no studio/one-bedroom inventory. Earlier diagnostic failures remain in `collection_runs` as source-health history.

Avelle's official site currently lists 1170 Spruce St, Mountain View, rather than the research report's 2530 W El Camino Real. The official address is stored and the discrepancy is retained in metadata.

## Durable market data

- `observations` is append-only and records every collected exact-unit offer with observation time, source unit and floorplan IDs, bedroom/bath count, square feet, base rent, advertised monthly total, lease term, availability date, concessions, fees when exposed, and extraction path.
- `unit_history_summary` provides first seen, last seen, calendar days observed listed, number of observations, and the low/high base rent for each unit.
- `events` records comparable price changes and new/disappeared listings. Price comparisons require the same unit, lease term, and requested move-in basis.
- `daily_market_summary` selects the final complete run per property per calendar day, then groups inventory and base-rent metrics by bedroom type and 100-square-foot bucket. It includes min/average/max rent and average rent per square foot.
- `properties.metadata_json` stores the city for future city-level aggregation. City-level claims should wait for broader, less geographically biased coverage.
- A disappearance requires two consecutive complete observations that omit the unit. Failed or partial runs cannot imply unavailability.
- `collection_runs` records every attempt, status, completeness, HTTP code, parser version, evidence, observed count, and error. `collection_failures` exposes failed attempts. Successfully fetched source bodies, including bodies that later fail parsing, are retained under `data/raw/` with SHA-256 hashes.
- Base rent, advertised fee-inclusive monthly total, and effective cost stay separate. Effective cost remains unknown until the lease term, required fees, and concession eligibility are known.
- Research prices and availability estimates are never inserted into observations. All 32 research names are stored only in `candidate_seeds` with unverified provenance.

## Operations

The installed user crontab launches a scheduler at 09:07 local time; it waits
0–20 random minutes before running both collectors once daily:

```cron
# Apartment Monitor: once daily, random start 09:07–09:27 local server time.
7 9 * * * /home/maksym/dev/apartment_crawler/scripts/scheduled-run.py
```

The runner collects all enabled communities sequentially, continues after individual failures, writes structured per-community results and errors to `data/logs/daily.log`, then regenerates the Markdown report and CSV/JSON exports. A lock prevents overlapping collection runs.

## Validation

The full live validation completed with 10 conclusive community results: 9 `success_complete` and 1 `explicit_no_availability`. The parser/database/report suite contains 14 tests and passes on Python 3.14. It covers all provider parser families, malformed and incomplete payloads, blocked/network/parse status distinctions, idempotence, price changes, two-run disappearance confirmation, daily trend aggregation, reports, and exports.

Commands:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
PYTHONPATH=src python3 -m apartment_monitor collect --all
PYTHONPATH=src python3 -m apartment_monitor report
PYTHONPATH=src python3 -m apartment_monitor export
sqlite3 data/apartment_monitor.sqlite3 'SELECT * FROM daily_market_summary;'
sqlite3 data/apartment_monitor.sqlite3 'SELECT * FROM collection_failures;'
```

## Next expansion targets

The other 22 candidates remain unsupported today. Useful next provider families are Prometheus, Essex, and Irvine Company, though several return security checkpoints from this machine. Catalyst exposes exact inventory through its official web rendering but its raw page currently challenges this collector. ILARA and Montrose advertise SightMap maps, making them possible additions once their public map identifiers can be validated. Commute/bicycle routing, thresholds for notifications, minimum square feet, budget, parking, pets, and desired lease/move-in windows remain unconfigured.

## October 30: clearer map and immediate city zoom

Selecting a city now applies immediately and clears the previous geofence. The
map fits that city's listings; +/− buttons adjust zoom without changing the data
filter. Street tiles render at a sharper resolution, the redundant coordinate grid
and duplicate city labels are hidden when streets are visible, and inventory fills
are lighter so roads remain readable. Tile images are clipped to the map panel.
Browser regression checks cover automatic city zoom and both zoom controls.

## October 30: searchable cities and minimal map

The city field accepts typed names with browser suggestions; selecting a suggestion
or leaving the field applies the city and zooms immediately. Clear it for all cities.
The map is always on. A compact Map settings menu controls inventory opacity.
CARTO Positron matches the Strava app's light basemap. With explicit user approval,
the public basemap key was copied to ignored `data/map-config.json` (`carto_key`).
This key is intentionally sent to the browser for tile requests, never committed.
Without that file the dashboard uses OpenStreetMap tiles. Both attributions are
shown when CARTO is configured. Restart the dashboard to pick up the server changes.

Live CARTO verification returned HTTP 403 from localhost. The Strava project notes
restrict the key to its hosted domains; localhost may need authorization in CARTO.
Failed CARTO tiles automatically fall back to OpenStreetMap. The key was not printed
or committed. Browser interactions passed with mocked tiles; live CARTO access is
not yet working from this origin.

## CARTO paused (October 30)

OpenStreetMap is the default and no CARTO requests are attempted. The locally saved
key is retained outside Git but is not exposed by the API while CARTO is disabled.
To explicitly enable CARTO later, set `"provider": "carto"` in
`data/map-config.json` after resolving key authorization. Leaving provider unset
uses OpenStreetMap even if a saved key exists.
