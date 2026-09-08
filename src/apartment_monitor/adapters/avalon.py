import json
from datetime import datetime
from html.parser import HTMLParser

from apartment_monitor.models import Offer, ParseResult

PARSER_VERSION = "avalon-fusion-metadata/1"
SCRIPT_ID = "fusion-metadata"


class _FusionExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == SCRIPT_ID:
            self.capture = True

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self.capture:
            self.capture = False


def _date(value):
    return datetime.fromisoformat(value).date().isoformat() if value else None


def parse_avalon(html: str, *, max_bedrooms: float = 1.0) -> ParseResult:
    extractor = _FusionExtractor()
    extractor.feed(html)
    script = "".join(extractor.parts)
    marker = "Fusion.globalContent="
    position = script.find(marker)
    if position < 0:
        raise ValueError(f"missing {marker} in script#{SCRIPT_ID}")
    try:
        payload, _ = json.JSONDecoder().raw_decode(script, position + len(marker))
    except json.JSONDecodeError as exc:
        raise ValueError("malformed Fusion.globalContent inventory") from exc
    units = payload.get("units")
    if not isinstance(units, list):
        raise ValueError("Fusion.globalContent has no units array")
    offers = []
    seen = set()
    for unit in units:
        bedrooms = unit.get("bedroomNumber")
        if bedrooms is None or float(bedrooms) > max_bedrooms:
            continue
        source_id = str(unit.get("unitId") or "")
        if not source_id:
            raise ValueError("Avalon unit is missing unitId")
        if source_id in seen:
            continue
        seen.add(source_id)
        pricing = unit.get("startingAtPricesUnfurnished") or {}
        prices = pricing.get("prices") or {}
        base = prices.get("price")
        total = prices.get("totalPrice")
        promotions = (unit.get("promotions") or []) + (unit.get("concessions") or [])
        sqft = unit.get("squareFeet")
        offers.append(Offer(
            source_listing_id=source_id,
            floorplan_id=(unit.get("floorPlan") or {}).get("name"),
            floorplan_name=(unit.get("floorPlan") or {}).get("name"),
            unit_label=unit.get("unitName"), bedrooms=float(bedrooms),
            bathrooms=float(unit["bathroomNumber"]) if unit.get("bathroomNumber") is not None else None,
            square_feet_min=int(sqft) if sqft else None, square_feet_max=int(sqft) if sqft else None,
            base_rent_min=float(base) if base is not None else None,
            base_rent_max=float(base) if base is not None else None,
            advertised_monthly_total_min=float(total) if total is not None else None,
            advertised_monthly_total_max=float(total) if total is not None else None,
            currency="USD", lease_months=pricing.get("leaseTerm"),
            requested_move_in_date=_date(pricing.get("moveInDate")),
            available_from=_date(unit.get("availableDateUnfurnished")),
            availability="available", granularity="exact_unit",
            original_price_text=f"base={base}; total={total}" if base is not None else None,
            extraction_path=f"script#{SCRIPT_ID} Fusion.globalContent.units[unitId={source_id}].startingAtPricesUnfurnished",
            concessions=json.dumps(promotions, sort_keys=True) if promotions else None,
        ))
    return ParseResult(
        status="success_complete" if offers else "explicit_no_availability",
        completeness="complete", offers=tuple(offers), parser_version=PARSER_VERSION,
        evidence=f"script#{SCRIPT_ID} Fusion.globalContent; communityId={payload.get('communityId')}; units={len(units)}",
    )

