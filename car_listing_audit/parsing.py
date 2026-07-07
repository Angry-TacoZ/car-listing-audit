from __future__ import annotations

import json
import re
from collections.abc import Iterable
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .models import VehicleListing


ACC_KEYWORDS = [
    "adaptive cruise control",
    "intelligent cruise control",
    "smart cruise control",
    "dynamic cruise control",
    "radar cruise",
    "active cruise control",
]

COMMON_MAKES = {
    "Acura",
    "Audi",
    "BMW",
    "Buick",
    "Cadillac",
    "Chevrolet",
    "Chrysler",
    "Dodge",
    "Ford",
    "GMC",
    "Honda",
    "Hyundai",
    "Jeep",
    "Kia",
    "Lexus",
    "Lincoln",
    "Mazda",
    "Mercedes-Benz",
    "Nissan",
    "Ram",
    "Subaru",
    "Toyota",
    "Volkswagen",
    "Volvo",
}


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def unique_preserve_order(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = normalize_text(value)
        if cleaned and cleaned not in seen:
            result.append(cleaned)
            seen.add(cleaned)
    return result


def detect_acc_keywords(feature_text: str) -> tuple[bool, list[str]]:
    lowered = feature_text.lower()
    matches = [keyword for keyword in ACC_KEYWORDS if keyword in lowered]
    return bool(matches), matches


def apply_acc_detection(listing: VehicleListing) -> None:
    has_keyword, matches = detect_acc_keywords(listing.feature_text)
    listing.has_acc_keyword = "true" if has_keyword else "false"
    listing.acc_keyword_matches = " | ".join(matches)


def parse_title_parts(title: str) -> dict[str, str]:
    title = normalize_text(title)
    match = re.match(r"^(?P<year>19\d{2}|20\d{2})\s+(?P<rest>.+)$", title)
    if not match:
        return {}
    rest = match.group("rest")
    make = ""
    for candidate in sorted(COMMON_MAKES, key=len, reverse=True):
        if rest == candidate or rest.startswith(candidate + " "):
            make = candidate
            rest = rest[len(candidate) :].strip()
            break
    if not make:
        pieces = rest.split(maxsplit=1)
        make = pieces[0]
        rest = pieces[1] if len(pieces) > 1 else ""

    model = rest
    trim = ""
    if " " in rest:
        model, trim = rest.split(" ", 1)

    return {
        "year": match.group("year"),
        "make": make,
        "model": model,
        "trim": trim,
    }


def parse_inventory_page(html: str, page_url: str) -> tuple[list[VehicleListing], str | None]:
    soup = BeautifulSoup(html, "html.parser")
    listings = parse_inventory_cards(soup, page_url)
    if not listings:
        listings = parse_inventory_json_ld(soup)
    next_link = soup.select_one('link[rel="next"]')
    next_url = urljoin(page_url, next_link["href"]) if next_link and next_link.get("href") else None
    return listings, next_url


def parse_inventory_cards(soup: BeautifulSoup, page_url: str) -> list[VehicleListing]:
    listings: list[VehicleListing] = []
    for card in soup.select('[data-cy="vehicle-card"]'):
        container = _listing_container(card)
        if container is None:
            continue
        link = container.select_one('a[data-cy="inventory-link"][href]')
        if not link:
            continue
        title = link.get("title") or link.get_text(" ", strip=True)
        text = normalize_text(container.get_text(" ", strip=True))
        listing = VehicleListing(
            vin=container.get("data-vin", ""),
            stock_number=_regex_first(r"Stock\s*#\s*([A-Za-z0-9-]+)", text),
            mileage=_regex_first(r"([\d,]+)\s*miles", text),
            price=_extract_price(text),
            listing_url=urljoin(page_url, link["href"]),
            photo_urls=_extract_photo_urls(container),
        )
        for field_name, value in parse_title_parts(title).items():
            setattr(listing, field_name, value)
        listings.append(listing)
    return listings


def parse_inventory_json_ld(soup: BeautifulSoup) -> list[VehicleListing]:
    listings: list[VehicleListing] = []
    for data in iter_json_ld(soup):
        if data.get("@type") != "ItemList":
            continue
        for element in data.get("itemListElement", []):
            item = element.get("item", {})
            if not isinstance(item, dict):
                continue
            listing = VehicleListing(
                listing_url=item.get("url", ""),
                price=str(item.get("offers", {}).get("price", "") or ""),
                photo_urls=_as_list(item.get("image")),
            )
            for field_name, value in parse_title_parts(item.get("name", "")).items():
                setattr(listing, field_name, value)
            listings.append(listing)
    return listings


def merge_detail_page(listing: VehicleListing, html: str, detail_url: str) -> VehicleListing:
    soup = BeautifulSoup(html, "html.parser")
    product = find_vehicle_product_json_ld(soup)
    if product:
        _merge_product_json_ld(listing, product)

    table_values = extract_vehicle_table(soup)
    listing.stock_number = table_values.get("Stock #", listing.stock_number)
    listing.trim = table_values.get("Trim", listing.trim)
    listing.vin = table_values.get("VIN", listing.vin)

    if not listing.listing_url:
        listing.listing_url = detail_url

    feature_text = extract_feature_text(soup)
    if feature_text:
        listing.feature_text = feature_text
    if not listing.photo_urls:
        listing.photo_urls = extract_detail_photo_urls(soup)
    apply_acc_detection(listing)
    return listing


def iter_json_ld(soup: BeautifulSoup) -> Iterable[dict]:
    for script in soup.select('script[type="application/ld+json"]'):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict):
            yield data
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    yield item


def find_vehicle_product_json_ld(soup: BeautifulSoup) -> dict | None:
    for data in iter_json_ld(soup):
        schema_type = data.get("@type")
        types = schema_type if isinstance(schema_type, list) else [schema_type]
        if "Car" in types or "Product" in types and data.get("vehicleIdentificationNumber"):
            return data
    return None


def extract_vehicle_table(soup: BeautifulSoup) -> dict[str, str]:
    values: dict[str, str] = {}
    for row in soup.select("table.vehicledetails tr"):
        cells = row.select("td")
        if len(cells) < 2:
            continue
        label = normalize_text(cells[0].get_text(" ", strip=True)).rstrip(":")
        value = normalize_text(cells[1].get_text(" ", strip=True))
        if label:
            values[label] = value
    return values


def extract_feature_text(soup: BeautifulSoup) -> str:
    labels: list[str] = []
    for image in soup.select('img[src*="/features/"], img[srcset*="/features/"]'):
        if image.get("alt"):
            labels.append(image["alt"])
        parent_text = image.parent.get_text(" ", strip=True) if image.parent else ""
        if parent_text:
            labels.append(parent_text)

    for heading in soup.find_all(["h2", "h3"]):
        text = normalize_text(heading.get_text(" ", strip=True))
        if text and ("feature" in text.lower() or text in {"Safety", "Interior", "Exterior"}):
            labels.append(text)

    return " | ".join(unique_preserve_order(labels))


def extract_detail_photo_urls(soup: BeautifulSoup) -> list[str]:
    product = find_vehicle_product_json_ld(soup)
    if product:
        images = _as_list(product.get("image"))
        if images:
            return images
    return _extract_photo_urls(soup)


def _merge_product_json_ld(listing: VehicleListing, product: dict) -> None:
    listing.vin = str(product.get("vehicleIdentificationNumber") or listing.vin)
    listing.year = str(product.get("vehicleModelDate") or listing.year)
    listing.model = str(product.get("model") or listing.model)

    brand = product.get("brand")
    if isinstance(brand, dict):
        listing.make = str(brand.get("name") or listing.make)
    elif brand:
        listing.make = str(brand)

    offers = product.get("offers")
    if isinstance(offers, dict):
        listing.price = str(offers.get("price") or listing.price)
        listing.dealer_name = str(offers.get("seller", {}).get("name") or listing.dealer_name)

    odometer = product.get("mileageFromOdometer")
    if isinstance(odometer, dict):
        listing.mileage = str(odometer.get("value") or listing.mileage)

    images = _as_list(product.get("image"))
    if images:
        listing.photo_urls = images

    name = product.get("name", "")
    if name and not listing.trim:
        parts = parse_title_parts(name)
        if parts:
            listing.trim = parts.get("trim", listing.trim)


def _listing_container(card: Tag) -> Tag | None:
    parent = card
    while parent:
        if isinstance(parent, Tag) and (parent.get("data-vin") or "srp-cardcontainer" in parent.get("class", [])):
            return parent
        parent = parent.parent
    return None


def _extract_price(text: str) -> str:
    sale_price = _regex_first(r"Sale\s+price\s+(\$[\d,]+)", text, flags=re.IGNORECASE)
    if sale_price:
        return sale_price
    prices = re.findall(r"\$[\d,]+", text)
    return prices[-1] if prices else ""


def _extract_photo_urls(container: Tag | BeautifulSoup) -> list[str]:
    urls: list[str] = []
    for image in container.select("img[src]"):
        src = image.get("src", "")
        if "static.overfuel.com/photos/" in src:
            urls.append(src.replace("-thumb.webp", ".webp").split("?")[0])
    return unique_preserve_order(urls)


def _regex_first(pattern: str, text: str, flags: int = 0) -> str:
    match = re.search(pattern, text, flags)
    return match.group(1).strip() if match else ""


def _as_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    if value:
        return [str(value)]
    return []

