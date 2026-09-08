import json
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path

from apartment_monitor.adapters.sevens import parse_sevens
from apartment_monitor.adapters.avalon import parse_avalon
from apartment_monitor.adapters.martin import parse_martin
from apartment_monitor.adapters.sightmap import parse_sightmap
from apartment_monitor.adapters.g5 import parse_g5
from apartment_monitor.collector import collect
from apartment_monitor.db import connect
from apartment_monitor.reporting import build_report, export_bundle

FIXTURES = Path(__file__).parent / "fixtures"
PROPERTY = {
    "id": "sevens", "name": "Sevens", "official_url": "https://sevensmv.com/",
    "availability_url": "https://sevensmv.com/floorplans/", "adapter": "sevens", "enabled": True,
}


class ParserTests(unittest.TestCase):
    def test_g5_exact_inventory_and_empty_target_segment(self):
        payload = {"floorplans":[{"id":1,"name":"A1","beds":1,"baths":"1.0","sqft":700}],
          "units_by_floorplan":{"1":[{"id":9,"displayName":"209","sqftDisplay":"700 sq ft",
          "availabilityDate":"2026-10-01","prices":[{"value":4100,"formattedPrice":"$4,100","leaseTermBasisMin":12}]}]}}
        offer = parse_g5(json.dumps(payload)).offers[0]
        self.assertEqual((offer.source_listing_id, offer.square_feet_min, offer.base_rent_min), ("9", 700, 4100))
        empty = parse_g5(json.dumps({"floorplans":[{"id":2,"beds":2}],"units_by_floorplan":{}}))
        self.assertEqual(empty.status, "explicit_no_availability")

    def test_sightmap_exact_inventory_and_affordable_flag(self):
        payload = {"data":{"floor_plans":[{"id":7,"name":"S1","bedroom_count":0,"bathroom_count":1}],
          "units":[{"id":44,"floor_plan_id":7,"unit_number":"101","area":562,"price":3867,
          "total_price":[3897.12,3910],"available_on":"2026-09-27","display_lease_term":"9 Months",
          "affordable_housing_info":{"is_affordable":True}}]}}
        offer = parse_sightmap(json.dumps(payload)).offers[0]
        self.assertEqual(offer.source_listing_id, "44")
        self.assertEqual(offer.bedrooms, 0)
        self.assertEqual(offer.base_rent_min, 3867)
        self.assertEqual(offer.advertised_monthly_total_min, 3897.12)
        self.assertEqual(offer.lease_months, 9)
        self.assertIn("is_affordable", offer.concessions)

    def test_avalon_fusion_inventory(self):
        unit = {"unitId":"AVB-X-101","unitName":"101","floorPlan":{"name":"A1"},
                "bedroomNumber":1,"bathroomNumber":1,"squareFeet":700,
                "availableDateUnfurnished":"2026-10-01T04:00:00+00:00",
                "startingAtPricesUnfurnished":{"moveInDate":"2026-10-01T04:00:00+00:00","leaseTerm":12,
                "prices":{"price":3200,"totalPrice":3310,"netEffectivePrice":3150}},
                "promotions":[{"promotionTitle":"one month free","promotionDescription":"select leases"}]}
        script = 'Fusion.globalContent=' + json.dumps({"communityId":"AVB-X","units":[unit]}) + ';'
        html = f'<script id="fusion-metadata">{script}</script>'
        offer = parse_avalon(html).offers[0]
        self.assertEqual(offer.base_rent_min, 3200)
        self.assertEqual(offer.advertised_monthly_total_min, 3310)
        self.assertIsNone(offer.effective_monthly_cost)
        self.assertIn("one month free", offer.concessions)

    def test_martin_public_inventory(self):
        payload = {"floorplans":{"floorplans":[{"floorplanId":12,"floorplanName":"J1"}]},
          "units":{"apartmentAvailabilities":[{"apartmentId":99,"apartmentName":"1201","floorplanId":12,
          "floorplanName":"J1","beds":1,"baths":1,"sqft":524,"minimumRent":4244,"maximumRent":6788,
          "minimumRentLeaseTerm":10,"availableDate":"09/20/2026","deposit":0}]}}
        offer = parse_martin(json.dumps(payload)).offers[0]
        self.assertEqual(offer.source_listing_id, "99")
        self.assertEqual(offer.base_rent_min, 4244)
        self.assertEqual(offer.lease_months, 10)
        self.assertEqual(offer.available_from, "2026-09-20")
    def test_exact_units_price_kinds_concession_and_duplicate(self):
        result = parse_sevens((FIXTURES / "sevens_inventory.html").read_text())
        self.assertEqual(result.status, "success_complete")
        self.assertEqual(len(result.offers), 2)
        studio, one_bed = result.offers
        self.assertEqual(studio.bedrooms, 0)
        self.assertEqual(studio.base_rent_min, 3180)
        self.assertEqual(studio.advertised_monthly_total_min, 3210.12)
        self.assertEqual(studio.lease_months, 15)
        self.assertIsNone(one_bed.advertised_monthly_total_min)
        self.assertIn("2 weeks free", one_bed.concessions)

    def test_explicit_empty_is_distinct(self):
        result = parse_sevens((FIXTURES / "sevens_empty.html").read_text())
        self.assertEqual(result.status, "explicit_no_availability")
        self.assertEqual(result.completeness, "complete")

    def test_shell_and_malformed_fail_visibly(self):
        with self.assertRaisesRegex(ValueError, "missing embedded"):
            parse_sevens((FIXTURES / "shell_only.html").read_text())
        with self.assertRaisesRegex(ValueError, "malformed"):
            parse_sevens('<script id="jd-fp-data-script-app">{bad</script>')

    def test_contact_for_price_stays_unknown(self):
        html = '<script id="jd-fp-data-script-app">' + json.dumps({"units": [{
            "id_value": "x", "bedrooms": "1", "rent_min": "Contact for price", "price_entity": {}
        }]}) + '</script>'
        offer = parse_sevens(html).offers[0]
        self.assertIsNone(offer.base_rent_min)
        self.assertIsNone(offer.advertised_monthly_total_min)

    def test_incomplete_pagination_fails(self):
        html = '<script id="jd-fp-data-script-app">' + json.dumps({"units": [], "pagination": {"next": "/page/2"}}) + '</script>'
        with self.assertRaisesRegex(ValueError, "incomplete paginated"):
            parse_sevens(html)


class DatabaseAndReportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = connect(self.root / "monitor.sqlite3")
        self.fixture = (FIXTURES / "sevens_inventory.html").read_bytes()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_migration_and_idempotent_run(self):
        self.assertEqual(self.db.execute("PRAGMA user_version").fetchone()[0], 6)
        collect(self.db, PROPERTY, self.root, run_id="same", raw_override=self.fixture)
        collect(self.db, PROPERTY, self.root, run_id="same", raw_override=self.fixture)
        self.assertEqual(self.db.execute("SELECT count(*) FROM observations").fetchone()[0], 2)

    def test_change_detection_and_failure_no_false_disappearance(self):
        collect(self.db, PROPERTY, self.root, run_id="one", raw_override=self.fixture)
        changed = self.fixture.replace(b'"3180"', b'"3100"').replace(b'"3210.12"', b'"3130.12"')
        collect(self.db, PROPERTY, self.root, run_id="two", raw_override=changed)
        events = [r[0] for r in self.db.execute("SELECT event_type FROM events WHERE run_id='two'")]
        self.assertIn("base_rent_changed", events)
        collect(self.db, PROPERTY, self.root, run_id="failed", raw_override=(FIXTURES / "shell_only.html").read_bytes())
        self.assertEqual(self.db.execute("SELECT status FROM collection_runs WHERE id='failed'").fetchone()[0], "parse_error")
        self.assertEqual(self.db.execute("SELECT count(*) FROM events WHERE run_id='failed'").fetchone()[0], 0)

    def test_report_and_exports(self):
        collect(self.db, PROPERTY, self.root, run_id="baseline", raw_override=self.fixture)
        report = build_report(self.db, self.root / "summary.md")
        self.assertIn("History is insufficient", report.read_text())
        paths = export_bundle(self.db, self.root / "export")
        self.assertEqual(len(paths), 7)
        self.assertTrue(all(p.exists() for p in paths))
        trend = self.db.execute("SELECT available_units,average_rent_per_sqft FROM daily_market_summary").fetchone()
        self.assertEqual(trend[0], 1)
        self.assertIsNotNone(trend[1])

    def test_blocked_and_network_statuses(self):
        def blocked(_url):
            raise urllib.error.HTTPError(_url, 429, "rate limited", {}, None)
        def offline(_url):
            raise urllib.error.URLError("offline")
        collect(self.db, PROPERTY, self.root, run_id="blocked", fetcher=blocked)
        collect(self.db, PROPERTY, self.root, run_id="offline", fetcher=offline)
        statuses = dict(self.db.execute("SELECT id,status FROM collection_runs"))
        self.assertEqual(statuses["blocked"], "blocked")
        self.assertEqual(statuses["offline"], "network_error")

    def test_disappearance_requires_two_complete_missing_runs(self):
        collect(self.db, PROPERTY, self.root, run_id="seen", raw_override=self.fixture)
        empty = (FIXTURES / "sevens_empty.html").read_bytes()
        collect(self.db, PROPERTY, self.root, run_id="missing-once", raw_override=empty)
        self.assertEqual(self.db.execute("SELECT count(*) FROM events WHERE event_type='no_longer_listed'").fetchone()[0], 0)
        collect(self.db, PROPERTY, self.root, run_id="missing-twice", raw_override=empty)
        self.assertEqual(self.db.execute("SELECT count(*) FROM events WHERE event_type='no_longer_listed'").fetchone()[0], 2)


if __name__ == "__main__":
    unittest.main()
