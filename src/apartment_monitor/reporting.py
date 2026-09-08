import csv
import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

LOCAL = ZoneInfo("America/Los_Angeles")


def _local(value: str | None) -> str:
    if not value:
        return "unknown"
    return datetime.fromisoformat(value).astimezone(LOCAL).strftime("%Y-%m-%d %H:%M %Z")


def build_report(db, output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    runs = db.execute("""
      SELECT r.*,p.name FROM collection_runs r JOIN properties p ON p.id=r.property_id
      WHERE r.finished_at >= datetime('now','-7 days') ORDER BY r.finished_at DESC
    """).fetchall()
    latest_ids = []
    successful = db.execute("""SELECT * FROM collection_runs WHERE status IN
      ('success_complete','explicit_no_availability') ORDER BY finished_at DESC""").fetchall()
    for row in successful:
        if row["property_id"] not in {x[0] for x in latest_ids}:
            latest_ids.append((row["property_id"], row["id"]))
    offers = []
    for _, run_id in latest_ids:
        offers.extend(db.execute("SELECT * FROM observations WHERE run_id=? ORDER BY bedrooms,base_rent_min", (run_id,)))
    events = db.execute("""SELECT e.*,p.name FROM events e JOIN properties p ON p.id=e.property_id
      JOIN collection_runs r ON r.id=e.run_id WHERE r.finished_at >= datetime('now','-7 days') ORDER BY e.id""").fetchall()

    lines = ["# Apartment watchlist weekly report", "",
             f"Generated: {_local(datetime.now().astimezone().isoformat())}", "",
             "This is a selected-watchlist asking-rent report. It is not a citywide market estimate.", "",
             "## Collection coverage", ""]
    if runs:
        lines += ["| Property | Collected (local) | Status | Completeness | Offers | HTTP |",
                  "|---|---:|---|---|---:|---:|"]
        for row in runs:
            lines.append(f"| {row['name']} | {_local(row['finished_at'])} | {row['status']} | {row['completeness'] or 'unknown'} | {row['observed_count']} | {row['http_status'] or ''} |")
    else:
        lines.append("No collection runs in this window.")
    lines += ["", "## Current studio and one-bedroom availability", ""]
    if offers:
        lines += ["| Property | Unit | Plan | Beds | Sq ft | Base rent | Monthly total | Effective cost | Lease | Available | Days observed listed |",
                  "|---|---|---|---:|---:|---:|---:|---:|---:|---|---:|"]
        names = {r["id"]: r["name"] for r in db.execute("SELECT id,name FROM properties")}
        for row in offers:
            base = f"${row['base_rent_min']:,.0f}" if row["base_rent_min"] is not None else "unknown"
            total = f"${row['advertised_monthly_total_min']:,.2f}" if row["advertised_monthly_total_min"] is not None else "unknown"
            effective = f"${row['effective_monthly_cost']:,.2f}" if row["effective_monthly_cost"] is not None else "unknown"
            beds = "Studio" if row["bedrooms"] == 0 else f"{row['bedrooms']:g}"
            first_seen = db.execute("SELECT min(observed_at) FROM observations WHERE property_id=? AND source_listing_id=?",
                                    (row["property_id"], row["source_listing_id"])).fetchone()[0]
            days = max(0, (datetime.now(first_seen and datetime.fromisoformat(first_seen).tzinfo).date() - datetime.fromisoformat(first_seen).date()).days) if first_seen else 0
            lines.append(f"| {names[row['property_id']]} | {row['unit_label'] or '—'} | {row['floorplan_name'] or '—'} | {beds} | {row['square_feet_min'] or 'unknown'} | {base} | {total} | {effective} | {row['lease_months'] or 'unknown'} mo | {row['available_from'] or 'unknown'} | {days} |")
    else:
        lines.append("No currently observed offers. Check source health before interpreting this as no availability.")
    lines += ["", "## Watchlist availability summary", ""]
    summary = db.execute("""SELECT p.name,o.bedrooms,count(DISTINCT o.source_listing_id) units,
      min(o.base_rent_min) min_base,max(o.base_rent_min) max_base,
      sum(CASE WHEN o.square_feet_min IS NULL THEN 1 ELSE 0 END) missing_sqft
      FROM observations o JOIN properties p ON p.id=o.property_id
      WHERE o.run_id IN (SELECT id FROM collection_runs r2 WHERE r2.property_id=o.property_id
        AND r2.status='success_complete' ORDER BY r2.rowid DESC LIMIT 1)
      GROUP BY p.name,o.bedrooms ORDER BY p.name,o.bedrooms""").fetchall()
    if summary:
        lines += ["| Property | Bedroom | Units | Base-rent range | Missing sq ft |",
                  "|---|---:|---:|---:|---:|"]
        for row in summary:
            bedroom = "No matching inventory" if row["bedrooms"] is None else ("Studio" if row["bedrooms"] == 0 else f"{row['bedrooms']:g} BR")
            price = "unknown" if row["min_base"] is None else f"${row['min_base']:,.0f}–${row['max_base']:,.0f}"
            lines.append(f"| {row['name']} | {bedroom} | {row['units']} | {price} | {row['missing_sqft']} |")
    lines += ["", "## Comparable changes", ""]
    if events:
        for event in events:
            detail = json.loads(event["detail_json"])
            lines.append(f"- {event['name']}: `{event['event_type']}` for {detail.get('unit') or event['source_listing_id']} ({detail})")
    else:
        lines.append("History is insufficient for trends; the first successful run is a baseline.")
    trends = db.execute("""SELECT d.*,p.name FROM daily_market_summary d
      JOIN properties p ON p.id=d.property_id
      WHERE d.observation_date >= date('now','-7 days')
      ORDER BY d.observation_date,p.name,d.bedrooms,d.sqft_bucket""").fetchall()
    lines += ["", "## Daily market trend series", ""]
    if trends:
        lines += ["| Date | Property | Bedroom | Sq-ft bucket | Available | Avg base rent | Avg rent/sq ft |",
                  "|---|---|---:|---:|---:|---:|---:|"]
        for row in trends:
            bedroom = "No matching inventory" if row["bedrooms"] is None else ("Studio" if row["bedrooms"] == 0 else f"{row['bedrooms']:g} BR")
            avg = f"${row['average_base_rent']:,.0f}" if row["average_base_rent"] is not None else "unknown"
            per_sqft = f"${row['average_rent_per_sqft']:,.2f}" if row["average_rent_per_sqft"] is not None else "unknown"
            bucket = f"{row['sqft_bucket']}–{row['sqft_bucket'] + 99}" if row["sqft_bucket"] is not None else "unknown"
            lines.append(f"| {row['observation_date']} | {row['name']} | {bedroom} | {bucket} | {row['available_units']} | {avg} | {per_sqft} |")
    else:
        lines.append("No complete daily observations yet.")
    failures = [r for r in runs if r["status"] not in ("success_complete", "explicit_no_availability")]
    lines += ["", "## Source failures", ""]
    lines.extend([f"- {r['name']}: {r['status']} — {r['error'] or 'no detail'}" for r in failures] or ["None in this window."])
    output.write_text("\n".join(lines) + "\n")
    return output


def export_bundle(db, output_dir: Path) -> list[Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    specs = {
        "properties.csv": "SELECT * FROM properties ORDER BY id",
        "units.csv": "SELECT * FROM observations ORDER BY observed_at,property_id,source_listing_id",
        "changes.csv": "SELECT * FROM events ORDER BY id",
        "source-health.csv": "SELECT * FROM collection_runs ORDER BY started_at",
        "daily-market-summary.csv": "SELECT * FROM daily_market_summary ORDER BY observation_date,property_id,bedrooms,sqft_bucket",
        "unit-history-summary.csv": "SELECT * FROM unit_history_summary ORDER BY property_id,source_listing_id",
    }
    paths = []
    for filename, query in specs.items():
        rows = db.execute(query).fetchall()
        path = output_dir / filename
        with path.open("w", newline="") as handle:
            writer = csv.writer(handle)
            if rows:
                writer.writerow(rows[0].keys())
                writer.writerows([tuple(r) for r in rows])
        paths.append(path)
    payload = {name: [dict(r) for r in db.execute(query)] for name, query in specs.items()}
    json_path = output_dir / "bundle.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    paths.append(json_path)
    return paths
