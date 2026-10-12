from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .parsing import detect_acc_keywords, normalize_text, unique_preserve_order


REQUIRED_BATCH_FIELDS = ["listing_id", "claimed_features", "photo_urls"]


@dataclass
class PartnerListing:
    listing_id: str
    listing_url: str = ""
    year: str = ""
    make: str = ""
    model: str = ""
    trim: str = ""
    vin: str = ""
    stock_number: str = ""
    claimed_features: str = ""
    photo_urls: list[str] = field(default_factory=list)

    @property
    def vehicle_label(self) -> str:
        return normalize_text(" ".join([self.year, self.make, self.model, self.trim]))

    @property
    def claimed_acc_features(self) -> list[str]:
        _, matches = detect_acc_keywords(self.claimed_features)
        return matches


def load_partner_batch(path: Path) -> list[PartnerListing]:
    if not path.exists():
        raise FileNotFoundError(f"Batch file not found: {path}")
    if path.suffix.lower() == ".csv":
        return load_partner_batch_csv(path)
    if path.suffix.lower() == ".json":
        return load_partner_batch_json(path)
    raise ValueError("Partner batch must be a .csv or .json file.")


def load_partner_batch_csv(path: Path) -> list[PartnerListing]:
    with path.open(newline="", encoding="utf-8-sig") as csv_file:
        reader = csv.DictReader(csv_file)
        if not reader.fieldnames:
            raise ValueError("Batch CSV is empty or missing a header row.")
        missing = [field for field in REQUIRED_BATCH_FIELDS if field not in reader.fieldnames]
        if missing:
            raise ValueError(f"Batch CSV is missing required columns: {', '.join(missing)}")
        rows = [parse_partner_row(row, row_number=index) for index, row in enumerate(reader, start=2)]
    if not rows:
        raise ValueError("Batch CSV does not contain any listing rows.")
    return rows


def load_partner_batch_json(path: Path) -> list[PartnerListing]:
    with path.open(encoding="utf-8") as json_file:
        payload = json.load(json_file)
    records = payload.get("listings") if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise ValueError("Batch JSON must be a list of listings or an object with a 'listings' list.")
    if not records:
        raise ValueError("Batch JSON does not contain any listing rows.")
    rows = []
    for index, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError(f"Batch JSON row {index} must be an object.")
        rows.append(parse_partner_row(record, row_number=index))
    return rows


def parse_partner_row(row: dict, row_number: int) -> PartnerListing:
    listing_id = normalize_text(str(row.get("listing_id", "") or ""))
    claimed_features = normalize_text(str(row.get("claimed_features", "") or ""))
    photo_urls = parse_photo_urls(row.get("photo_urls"))

    missing = []
    if not listing_id:
        missing.append("listing_id")
    if not claimed_features:
        missing.append("claimed_features")
    if not photo_urls:
        missing.append("photo_urls")
    if missing:
        raise ValueError(f"Batch row {row_number} is missing required values: {', '.join(missing)}")

    return PartnerListing(
        listing_id=listing_id,
        listing_url=normalize_text(str(row.get("listing_url", "") or "")),
        year=normalize_text(str(row.get("year", "") or "")),
        make=normalize_text(str(row.get("make", "") or "")),
        model=normalize_text(str(row.get("model", "") or "")),
        trim=normalize_text(str(row.get("trim", "") or "")),
        vin=normalize_text(str(row.get("vin", "") or "")),
        stock_number=normalize_text(str(row.get("stock_number", "") or "")),
        claimed_features=claimed_features,
        photo_urls=photo_urls,
    )


def parse_photo_urls(value: object) -> list[str]:
    if isinstance(value, list):
        raw_values = [str(item) for item in value]
    else:
        text = normalize_text(str(value or ""))
        if not text:
            return []
        if re.search(r",\s*https?://", text, flags=re.IGNORECASE):
            raise ValueError("photo_urls must be pipe-delimited in CSV, not comma-delimited.")
        raw_values = [part.strip() for part in text.replace("\n", "|").split("|")]

    return unique_preserve_order(raw_values)

