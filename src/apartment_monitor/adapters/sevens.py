import json
import re
from datetime import datetime, timezone
from html.parser import HTMLParser

from apartment_monitor.models import Offer, ParseResult

PARSER_VERSION = "sevens-embedded-json/1"
SCRIPT_ID = "jd-fp-data-script-app"


class _ScriptExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.capture = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == SCRIPT_ID:
            self.capture = True

    def handle_data(self, data: str) -> None:
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.capture:
            self.capture = False


def _number(value):
    if value in (None, "", "Contact for price"):
        return None
    try:
        return float(str(value).replace("$", "").replace(",", ""))
    except ValueError:
        return None


def _int(value):
    number = _number(value)
    return int(number) if number is not None else None


def _bedrooms(value):
    if isinstance(value, str) and value.strip().lower() == "studio":
        return 0.0
    return _number(value)


def _iso_date(epoch_value, fallback=None):
    if epoch_value:
        try:
            return datetime.fromtimestamp(int(epoch_value), timezone.utc).date().isoformat()
        except (ValueError, TypeError, OSError):
            pass
    return fallback


def _base_rent(price_entity):
    adjusted = price_entity.get("adjusted") or {}
    low = _number(adjusted.get("low_no_fees"))
    high = _number(adjusted.get("high_no_fees"))
    if low is not None:
        return low, high if high is not None else low
    text = price_entity.get("priceDisplayNoFees") or ""
    match = re.search(r"\$([\d,]+(?:\.\d+)?)", text)
    value = _number(match.group(1)) if match else None
    return value, value


def parse_jonah(html: str, *, max_bedrooms: float = 1.0) -> ParseResult:
    extractor = _ScriptExtractor()
    extractor.feed(html)
    if not extractor.parts:
        raise ValueError(f"missing embedded inventory script #{SCRIPT_ID}")
    try:
        payload = json.loads("".join(extractor.parts))
    except json.JSONDecodeError as exc:
        raise ValueError("malformed embedded inventory JSON") from exc
    if "units" not in payload or not isinstance(payload["units"], list):
        raise ValueError("embedded inventory has no units array")
    pagination = payload.get("pagination") or {}
    if payload.get("has_more") or pagination.get("next") or pagination.get("has_more"):
        raise ValueError("incomplete paginated inventory payload")

    offers: list[Offer] = []
    seen: set[str] = set()
    for unit in payload["units"]:
        bedrooms = _bedrooms(unit.get("bedrooms"))
        if bedrooms is None or bedrooms > max_bedrooms:
            continue
        source_id = str(unit.get("id_value") or unit.get("id") or "")
        if not source_id:
            raise ValueError("exact unit is missing a source listing ID")
        if source_id in seen:
            continue
        seen.add(source_id)
        price_entity = unit.get("price_entity") or {}
        base_low, base_high = _base_rent(price_entity)
        total_low = _number(price_entity.get("priceLow") or unit.get("rent_min"))
        total_high = _number(price_entity.get("priceHigh") or unit.get("rent_max"))
        pricing_includes_fees = bool(price_entity.get("pricingReflectFees"))
        if not pricing_includes_fees:
            total_low = total_high = None
        sqft = _int(unit.get("square_feet"))
        term = _int(price_entity.get("term") or unit.get("price_term_origin"))
        requested_date = price_entity.get("date")
        offers.append(Offer(
            source_listing_id=source_id,
            floorplan_id=str(unit.get("floorplan_id")) if unit.get("floorplan_id") is not None else None,
            floorplan_name=unit.get("floorplan_title"),
            unit_label=unit.get("apartment_number") or unit.get("title"),
            bedrooms=bedrooms,
            bathrooms=_number(unit.get("bathrooms")),
            square_feet_min=sqft,
            square_feet_max=sqft,
            base_rent_min=base_low,
            base_rent_max=base_high,
            advertised_monthly_total_min=total_low,
            advertised_monthly_total_max=total_high,
            currency="USD",
            lease_months=term,
            requested_move_in_date=requested_date,
            available_from=_iso_date(unit.get("available_date"), requested_date),
            availability="available",
            granularity="exact_unit",
            original_price_text=unit.get("price_display") or unit.get("price"),
            extraction_path=f"script#{SCRIPT_ID} $.units[id_value={source_id}]",
            concessions=json.dumps(unit.get("specials"), sort_keys=True) if unit.get("specials") else None,
        ))

    status = "success_complete" if offers else "explicit_no_availability"
    return ParseResult(
        status=status,
        completeness="complete",
        offers=tuple(offers),
        parser_version=PARSER_VERSION,
        evidence=f"script#{SCRIPT_ID}; provider payload version={payload.get('version', 'unknown')}; units={len(payload['units'])}",
    )


parse_sevens = parse_jonah
