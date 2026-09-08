import json
import sqlite3
from pathlib import Path

from apartment_monitor.models import Offer

SCHEMA_VERSION = 6


def connect(path: Path | str) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    migrate(db)
    return db


def migrate(db: sqlite3.Connection) -> None:
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        raise RuntimeError(f"database schema {version} is newer than supported {SCHEMA_VERSION}")
    if version == 0:
        db.executescript("""
        CREATE TABLE properties (
          id TEXT PRIMARY KEY, name TEXT NOT NULL, official_url TEXT,
          availability_url TEXT, adapter TEXT, enabled INTEGER NOT NULL DEFAULT 0,
          verified_at TEXT, metadata_json TEXT NOT NULL DEFAULT '{}'
        );
        CREATE TABLE collection_runs (
          id TEXT PRIMARY KEY, property_id TEXT NOT NULL REFERENCES properties(id),
          started_at TEXT NOT NULL, finished_at TEXT, status TEXT NOT NULL,
          completeness TEXT, http_status INTEGER, error TEXT, parser_version TEXT,
          evidence TEXT, observed_count INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE artifacts (
          id INTEGER PRIMARY KEY, run_id TEXT NOT NULL UNIQUE REFERENCES collection_runs(id),
          path TEXT NOT NULL, sha256 TEXT NOT NULL, content_type TEXT, byte_count INTEGER NOT NULL
        );
        CREATE TABLE observations (
          id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES collection_runs(id),
          property_id TEXT NOT NULL REFERENCES properties(id), observed_at TEXT NOT NULL,
          source_listing_id TEXT NOT NULL, floorplan_id TEXT, floorplan_name TEXT,
          unit_label TEXT, bedrooms REAL, bathrooms REAL, square_feet_min INTEGER,
          square_feet_max INTEGER, base_rent_min REAL, base_rent_max REAL,
          advertised_monthly_total_min REAL, advertised_monthly_total_max REAL,
          currency TEXT, lease_months INTEGER, requested_move_in_date TEXT,
          available_from TEXT, availability TEXT NOT NULL, granularity TEXT NOT NULL,
          original_price_text TEXT, extraction_path TEXT NOT NULL, effective_monthly_cost REAL,
          mandatory_recurring_fees REAL, parking TEXT, one_time_fees TEXT,
          deposit TEXT, concessions TEXT,
          UNIQUE(run_id, source_listing_id, lease_months, requested_move_in_date)
        );
        CREATE TABLE events (
          id INTEGER PRIMARY KEY, run_id TEXT NOT NULL REFERENCES collection_runs(id),
          property_id TEXT NOT NULL REFERENCES properties(id), event_type TEXT NOT NULL,
          source_listing_id TEXT NOT NULL, detail_json TEXT NOT NULL,
          UNIQUE(run_id, event_type, source_listing_id)
        );
        CREATE INDEX observations_comparison ON observations
          (property_id, source_listing_id, lease_months, requested_move_in_date, observed_at);
        CREATE VIEW unit_history_summary AS
          SELECT property_id,source_listing_id,min(observed_at) AS first_seen_at,
            max(observed_at) AS last_seen_at,
            CAST(julianday(max(observed_at))-julianday(min(observed_at)) AS INTEGER) AS days_observed_listed,
            count(DISTINCT run_id) AS observations,
            min(base_rent_min) AS lowest_base_rent,
            max(base_rent_min) AS highest_base_rent
          FROM observations GROUP BY property_id,source_listing_id;
        CREATE TABLE candidate_seeds (
          name TEXT PRIMARY KEY, research_claimed_address TEXT, url_hint TEXT,
          provenance TEXT NOT NULL, imported_at TEXT NOT NULL
        );
        CREATE VIEW daily_market_summary AS
          WITH ranked_runs AS (
            SELECT id, property_id, status, date(finished_at) AS observation_date,
              row_number() OVER (PARTITION BY property_id,date(finished_at) ORDER BY rowid DESC) AS rank_in_day
            FROM collection_runs
            WHERE status IN ('success_complete','explicit_no_availability') AND completeness='complete'
          )
          SELECT r.observation_date,r.property_id,r.status,o.bedrooms,
            CAST(o.square_feet_min / 100 AS INTEGER) * 100 AS sqft_bucket,
            count(o.id) AS available_units,min(o.base_rent_min) AS minimum_base_rent,
            avg(o.base_rent_min) AS average_base_rent,max(o.base_rent_min) AS maximum_base_rent,
            avg(CASE WHEN o.square_feet_min > 0 THEN o.base_rent_min/o.square_feet_min END) AS average_rent_per_sqft
          FROM ranked_runs r LEFT JOIN observations o ON o.run_id=r.id
          WHERE r.rank_in_day=1
          GROUP BY r.observation_date,r.property_id,r.status,o.bedrooms,CAST(o.square_feet_min / 100 AS INTEGER);
        CREATE VIEW collection_failures AS
          SELECT id,property_id,started_at,finished_at,status,http_status,error
          FROM collection_runs WHERE status IN ('blocked','network_error','parse_error');
        PRAGMA user_version = 6;
        """)
        db.commit()
    elif version == 1:
        db.execute("ALTER TABLE observations ADD COLUMN effective_monthly_cost REAL")
        db.execute("PRAGMA user_version = 2")
        db.commit()
        version = 2
    if version == 2:
        db.execute("""CREATE VIEW IF NOT EXISTS unit_history_summary AS
          SELECT property_id,source_listing_id,min(observed_at) AS first_seen_at,
            max(observed_at) AS last_seen_at,
            CAST(julianday(max(observed_at))-julianday(min(observed_at)) AS INTEGER) AS days_observed_listed,
            count(DISTINCT run_id) AS observations,
            min(base_rent_min) AS lowest_base_rent,
            max(base_rent_min) AS highest_base_rent
          FROM observations GROUP BY property_id,source_listing_id""")
        db.execute("PRAGMA user_version = 3")
        db.commit()
        version = 3
    if version == 3:
        db.execute("""CREATE TABLE IF NOT EXISTS candidate_seeds (
          name TEXT PRIMARY KEY, research_claimed_address TEXT, url_hint TEXT,
          provenance TEXT NOT NULL, imported_at TEXT NOT NULL)""")
        db.execute("PRAGMA user_version = 4")
        db.commit()
        version = 4
    if version == 4:
        db.executescript("""
          CREATE VIEW IF NOT EXISTS daily_market_summary AS
            WITH ranked_runs AS (
              SELECT id, property_id, date(finished_at) AS observation_date,
                row_number() OVER (PARTITION BY property_id,date(finished_at) ORDER BY rowid DESC) AS rank_in_day
              FROM collection_runs
              WHERE status IN ('success_complete','explicit_no_availability') AND completeness='complete'
            )
            SELECT r.observation_date,o.property_id,o.bedrooms,
              CAST(o.square_feet_min / 100 AS INTEGER) * 100 AS sqft_bucket,
              count(*) AS available_units,min(o.base_rent_min) AS minimum_base_rent,
              avg(o.base_rent_min) AS average_base_rent,max(o.base_rent_min) AS maximum_base_rent,
              avg(CASE WHEN o.square_feet_min > 0 THEN o.base_rent_min/o.square_feet_min END) AS average_rent_per_sqft
            FROM ranked_runs r JOIN observations o ON o.run_id=r.id
            WHERE r.rank_in_day=1
            GROUP BY r.observation_date,o.property_id,o.bedrooms,CAST(o.square_feet_min / 100 AS INTEGER);
          CREATE VIEW IF NOT EXISTS collection_failures AS
            SELECT id,property_id,started_at,finished_at,status,http_status,error
            FROM collection_runs WHERE status IN ('blocked','network_error','parse_error');
          PRAGMA user_version = 5;
        """)
        db.commit()
        version = 5
    if version == 5:
        db.executescript("""
          DROP VIEW IF EXISTS daily_market_summary;
          CREATE VIEW daily_market_summary AS
            WITH ranked_runs AS (
              SELECT id, property_id, status, date(finished_at) AS observation_date,
                row_number() OVER (PARTITION BY property_id,date(finished_at) ORDER BY rowid DESC) AS rank_in_day
              FROM collection_runs
              WHERE status IN ('success_complete','explicit_no_availability') AND completeness='complete'
            )
            SELECT r.observation_date,r.property_id,r.status,o.bedrooms,
              CAST(o.square_feet_min / 100 AS INTEGER) * 100 AS sqft_bucket,
              count(o.id) AS available_units,min(o.base_rent_min) AS minimum_base_rent,
              avg(o.base_rent_min) AS average_base_rent,max(o.base_rent_min) AS maximum_base_rent,
              avg(CASE WHEN o.square_feet_min > 0 THEN o.base_rent_min/o.square_feet_min END) AS average_rent_per_sqft
            FROM ranked_runs r LEFT JOIN observations o ON o.run_id=r.id
            WHERE r.rank_in_day=1
            GROUP BY r.observation_date,r.property_id,r.status,o.bedrooms,CAST(o.square_feet_min / 100 AS INTEGER);
          PRAGMA user_version = 6;
        """)
        db.commit()


def upsert_property(db, item: dict) -> None:
    db.execute("""
      INSERT INTO properties(id,name,official_url,availability_url,adapter,enabled,verified_at,metadata_json)
      VALUES(?,?,?,?,?,?,?,?)
      ON CONFLICT(id) DO UPDATE SET name=excluded.name, official_url=excluded.official_url,
        availability_url=excluded.availability_url, adapter=excluded.adapter,
        enabled=excluded.enabled, verified_at=excluded.verified_at,
        metadata_json=excluded.metadata_json
    """, (item["id"], item["name"], item.get("official_url"), item.get("availability_url"),
          item.get("adapter"), int(item.get("enabled", False)), item.get("verified_at"),
          json.dumps(item.get("metadata", {}), sort_keys=True)))


def save_observations(db, run_id: str, property_id: str, observed_at: str, offers: tuple[Offer, ...]) -> None:
    columns = list(Offer.__dataclass_fields__)
    sql = f"INSERT OR IGNORE INTO observations(run_id,property_id,observed_at,{','.join(columns)}) VALUES ({','.join('?' for _ in range(3 + len(columns)))})"
    db.executemany(sql, [(run_id, property_id, observed_at, *(getattr(o, c) for c in columns)) for o in offers])


def derive_events(db, run_id: str, property_id: str) -> None:
    current = db.execute("SELECT * FROM observations WHERE run_id=?", (run_id,)).fetchall()
    # rowid breaks timestamp ties when two fixture/smoke runs finish in one second.
    prior_runs = db.execute("""
      SELECT id FROM collection_runs WHERE property_id=? AND id<>?
      AND status IN ('success_complete','explicit_no_availability')
      AND rowid < (SELECT rowid FROM collection_runs WHERE id=?)
      ORDER BY rowid DESC LIMIT 2
    """, (property_id, run_id, run_id)).fetchall()
    if not prior_runs:
        return
    previous = {r["source_listing_id"]: r for r in db.execute("SELECT * FROM observations WHERE run_id=?", (prior_runs[0][0],))}
    now = {r["source_listing_id"]: r for r in current}
    for source_id, row in now.items():
        old = previous.get(source_id)
        if old is None:
            _event(db, run_id, property_id, "newly_observed", source_id, {"unit": row["unit_label"]})
        elif _basis(row) == _basis(old) and row["base_rent_min"] != old["base_rent_min"]:
            _event(db, run_id, property_id, "base_rent_changed", source_id,
                   {"from": old["base_rent_min"], "to": row["base_rent_min"], "unit": row["unit_label"]})
    # Require two consecutive complete observations without the unit. The first
    # absence remains an unreported disappearance candidate.
    if len(prior_runs) == 2:
        older = {r["source_listing_id"]: r for r in db.execute(
            "SELECT * FROM observations WHERE run_id=?", (prior_runs[1][0],))}
        for source_id, row in older.items():
            if source_id not in previous and source_id not in now:
                _event(db, run_id, property_id, "no_longer_listed", source_id, {"unit": row["unit_label"]})


def _basis(row):
    return row["source_listing_id"], row["lease_months"], row["requested_move_in_date"]


def _event(db, run_id, property_id, kind, source_id, detail):
    db.execute("INSERT OR IGNORE INTO events(run_id,property_id,event_type,source_listing_id,detail_json) VALUES(?,?,?,?,?)",
               (run_id, property_id, kind, source_id, json.dumps(detail, sort_keys=True)))
