# Apartment Monitor

A local daily monitor for official apartment-community websites. It supports **10 of 32 candidate communities**, stores exact-unit observations in SQLite, preserves raw evidence, distinguishes collection failures from no availability, and produces Markdown/CSV/JSON reports.

See [project status](docs/project-status.md) for the supported-community list, today's validation results, schema semantics, installed schedule, and expansion backlog. The imported research is discovery input only: its prices, availability, addresses, and commute claims are not treated as verified observations.

## Run

Python 3.11+ is sufficient and the runtime has no third-party dependencies.

```bash
PYTHONPATH=src python3 -m apartment_monitor init-db
PYTHONPATH=src python3 -m apartment_monitor collect --all
PYTHONPATH=src python3 -m apartment_monitor report
PYTHONPATH=src python3 -m apartment_monitor export
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Runtime data lives under `data/`, `reports/`, and `exports/` and is excluded from Git.
The installed crontab invokes `scripts/scheduled-run.py` at 09:07 local time daily;
it waits a random 0–20 minutes before running `scripts/daily-run.sh`, giving an
actual start between 09:07 and 09:27. The chosen delay is logged.

## Craigslist individual listings

The daily runner also collects nine Craigslist search samples: rentals, rooms, and
sublets in San Francisco, Peninsula, and South Bay. This has its own package,
configuration and SQLite database; community inventory remains separate.

```bash
PYTHONPATH=src python3 -m listing_monitor collect
PYTHONPATH=src python3 -m listing_monitor report
```

See [Craigslist operations and limitations](docs/craigslist-monitor-plan.md).
The database is `data/craigslist.sqlite3`; reports are
`reports/craigslist-latest.md` and `reports/craigslist-stats.json`.
These are sampled ads with approximate advertised coordinates, not complete
market inventory. Repeated post IDs are deduplicated; daily observations remain.

## Local dashboard

Run `./scripts/dashboard.sh` when you want to view the data, then open
http://127.0.0.1:8765. Ctrl+C stops it. The read-only dashboard includes current
inventory, city/geographic-cell filters, rent and inventory trends, individual
price histories and collection health for both datasets. It has no runtime
dependencies beyond Python and makes no external requests.

See [dashboard and SSH setup](docs/dashboard.md) for the laptop configuration
script and the `ssh apartment-dashboard` command, which starts the server and
tunnel together. The website is not an always-running service.

## Status meanings

- `success_complete`: the expected payload parsed completely and contains matching units.
- `explicit_no_availability`: a complete payload explicitly contains no matching studio/one-bedroom inventory.
- `blocked`: the source returned HTTP 401, 403, or 429.
- `parse_error`: content arrived but failed the adapter's completeness contract.
- `network_error`: transport failed.

Two consecutive complete runs must omit a previously observed unit before the monitor records `no_longer_listed`. This means the public source stopped listing it; it does not prove the unit was rented.
