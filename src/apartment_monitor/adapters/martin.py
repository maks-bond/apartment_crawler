import json
from datetime import datetime

from apartment_monitor.models import Offer, ParseResult

PARSER_VERSION = "martin-public-wordpress-inventory/1"


def _date(value):
    return datetime.strptime(value, "%m/%d/%Y").date().isoformat() if value else None


def parse_martin(raw: str, *, max_bedrooms: float = 1.0) -> ParseResult:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("malformed Martin inventory JSON") from exc
    units = (payload.get("units") or {}).get("apartmentAvailabilities")
    floorplans = (payload.get("floorplans") or {}).get("floorplans")
    if not isinstance(units, list) or not isinstance(floorplans, list):
        raise ValueError("Martin inventory response is incomplete")
    floorplan_by_id = {str(x.get("floorplanId")): x for x in floorplans}
    offers = []
    for unit in units:
        bedrooms = unit.get("beds")
        if bedrooms is None or float(bedrooms) > max_bedrooms:
            continue
        source_id = str(unit.get("apartmentId") or "")
        if not source_id:
            raise ValueError("Martin unit missing apartmentId")
        fp_id = str(unit.get("floorplanId"))
        fp = floorplan_by_id.get(fp_id, {})
        rent = unit.get("minimumRent")
        available = _date(unit.get("availableDate"))
        specials = unit.get("specials") or ("floor-plan special" if fp.get("floorplanHasSpecials") else None)
        offers.append(Offer(
            source_listing_id=source_id, floorplan_id=fp_id,
            floorplan_name=unit.get("floorplanName") or fp.get("floorplanName"),
            unit_label=unit.get("apartmentName"), bedrooms=float(bedrooms),
            bathrooms=float(unit["baths"]) if unit.get("baths") is not None else None,
            square_feet_min=unit.get("sqft"), square_feet_max=unit.get("sqft"),
            base_rent_min=float(rent) if rent is not None else None,
            base_rent_max=float(rent) if rent is not None else None,
            advertised_monthly_total_min=None, advertised_monthly_total_max=None,
            currency="USD", lease_months=unit.get("minimumRentLeaseTerm"),
            requested_move_in_date=available, available_from=available,
            availability="available", granularity="exact_unit",
            original_price_text=(f"${unit.get('minimumRent')}–${unit.get('maximumRent')}; minimum price term {unit.get('minimumRentLeaseTerm')} months" if rent is not None else None),
            extraction_path=f"public WordPress actions get_api_floorplans + get_api_apartments_availability; apartmentAvailabilities[apartmentId={source_id}]",
            deposit=str(unit.get("deposit")) if unit.get("deposit") not in (None, "") else None,
            concessions=str(specials) if specials else None,
        ))
    return ParseResult(status="success_complete" if offers else "explicit_no_availability",
                       completeness="complete", offers=tuple(offers), parser_version=PARSER_VERSION,
                       evidence=f"public WordPress inventory actions; floorplans={len(floorplans)}; units={len(units)}")

