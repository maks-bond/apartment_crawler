from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class Offer:
    source_listing_id: str
    floorplan_id: str | None
    floorplan_name: str | None
    unit_label: str | None
    bedrooms: float | None
    bathrooms: float | None
    square_feet_min: int | None
    square_feet_max: int | None
    base_rent_min: float | None
    base_rent_max: float | None
    advertised_monthly_total_min: float | None
    advertised_monthly_total_max: float | None
    currency: str
    lease_months: int | None
    requested_move_in_date: str | None
    available_from: str | None
    availability: str
    granularity: str
    original_price_text: str | None
    extraction_path: str
    effective_monthly_cost: float | None = None
    mandatory_recurring_fees: float | None = None
    parking: str | None = None
    one_time_fees: str | None = None
    deposit: str | None = None
    concessions: str | None = None

    def asdict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ParseResult:
    status: str
    completeness: str
    offers: tuple[Offer, ...]
    parser_version: str
    evidence: str
