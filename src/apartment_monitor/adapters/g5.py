import json
import re

from apartment_monitor.models import Offer, ParseResult

PARSER_VERSION = "g5-public-graphql/1"


def _number(value):
    if value in (None, ""):
        return None
    match = re.search(r"[\d,]+(?:\.\d+)?", str(value))
    return float(match.group().replace(",", "")) if match else None


def parse_g5(raw: str, *, max_bedrooms: float = 1.0) -> ParseResult:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("malformed G5 inventory JSON") from exc
    floorplans = payload.get("floorplans")
    units_by_floorplan = payload.get("units_by_floorplan")
    if not isinstance(floorplans, list) or not isinstance(units_by_floorplan, dict):
        raise ValueError("G5 inventory response is incomplete")
    offers = []
    relevant = [fp for fp in floorplans if _number(fp.get("beds")) is not None and _number(fp.get("beds")) <= max_bedrooms]
    for fp in relevant:
        fp_id = str(fp.get("id"))
        units = units_by_floorplan.get(fp_id)
        if not isinstance(units, list):
            raise ValueError(f"G5 units response missing for floorplan {fp_id}")
        for unit in units:
            source_id = str(unit.get("id") or unit.get("externalId") or "")
            if not source_id:
                raise ValueError("G5 unit is missing an id")
            prices = unit.get("prices") or []
            numeric_prices = [(p, _number(p.get("value") or p.get("formattedPrice"))) for p in prices]
            numeric_prices = [(p, v) for p, v in numeric_prices if v is not None]
            best = min(numeric_prices, key=lambda item: item[1]) if numeric_prices else ({}, None)
            sqft = int(_number(unit.get("sqftDisplay")) or fp.get("sqft")) if (_number(unit.get("sqftDisplay")) or _number(fp.get("sqft"))) else None
            specials = unit.get("specials") or []
            offers.append(Offer(
                source_listing_id=source_id, floorplan_id=fp_id, floorplan_name=fp.get("name"),
                unit_label=unit.get("displayName") or unit.get("name"), bedrooms=_number(fp.get("beds")),
                bathrooms=_number(fp.get("baths")), square_feet_min=sqft, square_feet_max=sqft,
                base_rent_min=best[1], base_rent_max=best[1],
                advertised_monthly_total_min=None, advertised_monthly_total_max=None,
                currency="USD", lease_months=int(_number(best[0].get("leaseTermBasisMin"))) if best[0].get("leaseTermBasisMin") else None,
                requested_move_in_date=unit.get("availabilityDate"), available_from=unit.get("availabilityDate"),
                availability="available", granularity="exact_unit",
                original_price_text=best[0].get("formattedPrice"),
                extraction_path=f"public G5 GraphQL units(floorplanId={fp_id})[id={source_id}]",
                concessions=json.dumps(specials, sort_keys=True) if specials else None,
            ))
    return ParseResult(status="success_complete" if offers else "explicit_no_availability",
                       completeness="complete", offers=tuple(offers), parser_version=PARSER_VERSION,
                       evidence=f"public G5 GraphQL; available floorplans={len(floorplans)}; relevant floorplans={len(relevant)}")
