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

Runtime data lives under `data/`, `reports/`, and `exports/` and is excluded from Git. The installed crontab invokes `scripts/daily-run.sh` at 09:17 local time every day.

## Status meanings

- `success_complete`: the expected payload parsed completely and contains matching units.
- `explicit_no_availability`: a complete payload explicitly contains no matching studio/one-bedroom inventory.
- `blocked`: the source returned HTTP 401, 403, or 429.
- `parse_error`: content arrived but failed the adapter's completeness contract.
- `network_error`: transport failed.

Two consecutive complete runs must omit a previously observed unit before the monitor records `no_longer_listed`. This means the public source stopped listing it; it does not prove the unit was rented.
