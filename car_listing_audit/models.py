from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class VehicleListing:
    dealer_name: str = ""
    stock_number: str = ""
    year: str = ""
    make: str = ""
    model: str = ""
    trim: str = ""
    mileage: str = ""
    price: str = ""
    listing_url: str = ""
    vin: str = ""
    feature_text: str = ""
    photo_urls: list[str] = field(default_factory=list)
    has_acc_keyword: str = "false"
    acc_keyword_matches: str = ""
    steering_wheel_photo_url: str = ""
    visual_acc_evidence: str = ""
    verdict: str = ""
    notes: str = ""

    def to_csv_row(self) -> dict[str, str]:
        row = asdict(self)
        row["photo_urls"] = " | ".join(self.photo_urls)
        return row


CSV_COLUMNS = [
    "dealer_name",
    "stock_number",
    "year",
    "make",
    "model",
    "trim",
    "mileage",
    "price",
    "listing_url",
    "vin",
    "feature_text",
    "photo_urls",
    "has_acc_keyword",
    "acc_keyword_matches",
    "steering_wheel_photo_url",
    "visual_acc_evidence",
    "verdict",
    "notes",
]
