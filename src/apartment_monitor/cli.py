import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from apartment_monitor.collector import collect, run_lock
from apartment_monitor.db import connect, upsert_property
from apartment_monitor.reporting import build_report, export_bundle

ROOT = Path.cwd()


def load_registry(path: Path) -> list[dict]:
    data = json.loads(path.read_text())
    if not isinstance(data, list) or not all(isinstance(x, dict) and "id" in x and "name" in x for x in data):
        raise ValueError("registry must be a JSON array of properties with id and name")
    return data


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="apartment-monitor")
    parser.add_argument("--db", type=Path, default=ROOT / "data" / "apartment_monitor.sqlite3")
    parser.add_argument("--registry", type=Path, default=ROOT / "config" / "properties.json")
    parser.add_argument("--seed-registry", type=Path, default=ROOT / "config" / "unverified-seeds.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init-db")
    audit = commands.add_parser("audit")
    audit.add_argument("--document", type=Path, default=ROOT / "docs" / "source-audit.md")
    collection = commands.add_parser("collect")
    collection.add_argument("--property")
    collection.add_argument("--all", action="store_true")
    collection.add_argument("--run-id")
    report = commands.add_parser("report")
    report.add_argument("--output", type=Path)
    export = commands.add_parser("export")
    export.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    db = connect(args.db)
    registry = load_registry(args.registry)
    for item in registry:
        upsert_property(db, item)
    for item in json.loads(args.seed_registry.read_text()):
        db.execute("""INSERT INTO candidate_seeds(name,research_claimed_address,url_hint,provenance,imported_at)
          VALUES(?,?,?,?,?) ON CONFLICT(name) DO UPDATE SET research_claimed_address=excluded.research_claimed_address,
          url_hint=excluded.url_hint,provenance=excluded.provenance""",
          (item["name"], item.get("research_claimed_address"), item.get("url_hint"), item["provenance"],
           datetime.now(timezone.utc).isoformat(timespec="seconds")))
    db.commit()
    if args.command == "init-db":
        print(args.db)
    elif args.command == "audit":
        print(args.document.read_text())
    elif args.command == "collect":
        if args.run_id and (args.all or not args.property):
            raise SystemExit("--run-id requires exactly one --property")
        if args.all:
            selected = [x for x in registry if x.get("enabled")]
        else:
            property_id = args.property or "sevens"
            selected = [x for x in registry if x["id"] == property_id and x.get("enabled")]
        if not selected:
            raise SystemExit(f"property is missing or disabled: {args.property}")
        results = []
        with run_lock(ROOT / ".apartment-monitor.lock"):
            for item in selected:
                run_id = collect(db, item, ROOT / "data", run_id=args.run_id)
                row = db.execute("SELECT status,observed_count,error FROM collection_runs WHERE id=?", (run_id,)).fetchone()
                result = {"property_id": item["id"], "run_id": run_id, **dict(row)}
                results.append(result)
                print(json.dumps(result, sort_keys=True))
        return 0 if all(x["status"] in ("success_complete", "explicit_no_availability") for x in results) else 2
    elif args.command == "report":
        output = args.output or ROOT / "reports" / f"weekly-{datetime.now():%Y-%m-%d}.md"
        print(build_report(db, output))
    elif args.command == "export":
        output = args.output_dir or ROOT / "exports" / datetime.now().strftime("%Y-%m-%d")
        print("\n".join(map(str, export_bundle(db, output))))
    return 0
