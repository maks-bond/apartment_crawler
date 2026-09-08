import json
import re

from apartment_monitor.models import Offer, ParseResult

PARSER_VERSION = "sightmap-public-api/1"


def _number(value):
    if value in (None, ""):
        return None
    if isinstance(value, (list, tuple)):
        return _number(value[0]) if value else None
    match = re.search(r"-?[\d,]+(?:\.\d+)?", str(value))
    return float(match.group().replace(",", "")) if match else None


def _integer(value):
    number = _number(value)
    return int(number) if number is not None else None


def parse_sightmap(raw: str, *, max_bedrooms: float = 1.0) -> ParseResult:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("malformed SightMap inventory JSON") from exc
    data = payload.get("data")
    if not isinstance(data, dict) or not isinstance(data.get("units"), list) or not isinstance(data.get("floor_plans"), list):
        raise ValueError("SightMap inventory response is incomplete")
    floorplans = {str(fp.get("id")): fp for fp in data["floor_plans"]}
    offers = []
    for unit in data["units"]:
        fp_id = str(unit.get("floor_plan_id") or "")
        fp = floorplans.get(fp_id, {})
        bedrooms = _number(fp.get("bedroom_count"))
        if bedrooms is None or bedrooms > max_bedrooms:
            continue
        source_id = str(unit.get("id") or "")
        if not source_id:
            raise ValueError("SightMap unit is missing an id")
        base = _number(unit.get("price"))
        totals = unit.get("total_price") or []
        total_low = _number(totals[0]) if isinstance(totals, list) and totals else None
        total_high = _number(totals[-1]) if isinstance(totals, list) and totals else total_low
        sqft = _integer(unit.get("area"))
        term = _integer(unit.get("display_lease_term"))
        affordable = unit.get("affordable_housing_info")
        restrictions = json.dumps(affordable, sort_keys=True) if affordable not in (None, False, {}, []) else None
        special = unit.get("specials_description")
        concessions = "; ".join(x for x in (str(special) if special else None,
                                             f"affordable_housing_info={restrictions}" if restrictions else None) if x)
        available = unit.get("available_on") or None
        offers.append(Offer(
            source_listing_id=source_id, floorplan_id=fp_id or None,
            floorplan_name=fp.get("name"), unit_label=str(unit.get("unit_number") or "") or None,
            bedrooms=bedrooms, bathrooms=_number(fp.get("bathroom_count")),
            square_feet_min=sqft, square_feet_max=sqft,
            base_rent_min=base, base_rent_max=base,
            advertised_monthly_total_min=total_low,
            advertised_monthly_total_max=total_high,
            currency="USD", lease_months=term, requested_move_in_date=available,
            available_from=available, availability="available", granularity="exact_unit",
            original_price_text=unit.get("total_display_price") or unit.get("display_price"),
            extraction_path=f"public SightMap API $.data.units[id={source_id}]",
            concessions=concessions or None,
        ))
    return ParseResult(
        status="success_complete" if offers else "explicit_no_availability",
        completeness="complete", offers=tuple(offers), parser_version=PARSER_VERSION,
        evidence=f"public SightMap API; floorplans={len(floorplans)}; units={len(data['units'])}",
    )
