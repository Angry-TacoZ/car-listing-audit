from car_listing_audit.models import VehicleListing
from car_listing_audit.scraper import collect_listings
from car_listing_audit.parsing import (
    detect_acc_keywords,
    merge_detail_page,
    parse_inventory_page,
)


def test_detect_acc_keywords_matches_requested_phrases() -> None:
    has_keyword, matches = detect_acc_keywords(
        "Heated seats, Intelligent Cruise Control, and Radar Cruise assist"
    )

    assert has_keyword is True
    assert matches == ["intelligent cruise control", "radar cruise"]


def test_parse_inventory_page_extracts_listing_card() -> None:
    html = """
    <html><head><link rel="next" href="/used-inventory/page/2"></head>
    <body><div data-vin="5N1BT3BB8PC860720" class="srp-cardcontainer">
      <div data-cy="vehicle-card">
        <a data-cy="inventory-link" title="2023 Nissan Rogue SV"
           href="/vehicle-details/used-2023-nissan-rogue-sv-vin">View</a>
        <img src="https://static.overfuel.com/photos/437/1/photo-thumb.webp?w=1920&amp;q=80">
        Stock # PV22623Z 36,520 miles Sale price $23,990
      </div>
    </div></body></html>
    """

    listings, next_url = parse_inventory_page(html, "https://bobruthford.com/used-inventory")

    assert next_url == "https://bobruthford.com/used-inventory/page/2"
    assert len(listings) == 1
    assert listings[0].vin == "5N1BT3BB8PC860720"
    assert listings[0].stock_number == "PV22623Z"
    assert listings[0].year == "2023"
    assert listings[0].make == "Nissan"
    assert listings[0].model == "Rogue"
    assert listings[0].trim == "SV"
    assert listings[0].mileage == "36,520"
    assert listings[0].price == "$23,990"
    assert listings[0].listing_url == "https://bobruthford.com/vehicle-details/used-2023-nissan-rogue-sv-vin"
    assert listings[0].photo_urls == ["https://static.overfuel.com/photos/437/1/photo.webp"]


def test_merge_detail_page_prefers_structured_data_and_features() -> None:
    html = """
    <html><body>
    <script type="application/ld+json">
    {
      "@context": "https://schema.org",
      "@type": ["Product", "Car"],
      "name": "2023 Nissan Rogue SV",
      "vehicleIdentificationNumber": "5N1BT3BB8PC860720",
      "brand": {"@type": "Brand", "name": "Nissan"},
      "model": "Rogue",
      "vehicleModelDate": 2023,
      "mileageFromOdometer": {"@type": "QuantitativeValue", "value": 36520},
      "offers": {
        "@type": "Offer",
        "price": 23990,
        "seller": {"@type": "AutoDealer", "name": "Example Dealer"}
      },
      "image": ["https://static.overfuel.com/photos/437/1/photo.webp"]
    }
    </script>
    <table class="vehicledetails">
      <tr><td><b>Trim</b></td><td>SV</td></tr>
      <tr><td><b>Stock #</b></td><td>PV22623Z</td></tr>
      <tr><td><b>VIN</b></td><td><span data-vin="5N1BT3BB8PC860720">5N1BT3BB8PC860720</span></td></tr>
    </table>
    <h2>2023 Nissan Rogue SV Key Features</h2>
    <div><img src="https://static.overfuel.com/images/features/adaptive-cruise-control.png"
      alt="Adaptive cruise control">Adaptive cruise control</div>
    </body></html>
    """
    listing = VehicleListing(listing_url="https://example.test/detail")

    merge_detail_page(listing, html, listing.listing_url)

    assert listing.dealer_name == "Example Dealer"
    assert listing.stock_number == "PV22623Z"
    assert listing.year == "2023"
    assert listing.make == "Nissan"
    assert listing.model == "Rogue"
    assert listing.trim == "SV"
    assert listing.mileage == "36520"
    assert listing.price == "23990"
    assert listing.vin == "5N1BT3BB8PC860720"
    assert listing.photo_urls == ["https://static.overfuel.com/photos/437/1/photo.webp"]
    assert listing.has_acc_keyword == "true"
    assert listing.acc_keyword_matches == "adaptive cruise control"


def test_collect_listings_reports_progress_when_dependencies_are_mocked(monkeypatch) -> None:
    class FakeRobotsPolicy:
        @classmethod
        def load(cls, base_url, session):
            return cls()

    class FakeResponse:
        text = "<html></html>"

        def raise_for_status(self):
            return None

    class FakeSession:
        def __init__(self, delay_seconds):
            self.delay_seconds = delay_seconds

        def get(self, url, robots):
            return FakeResponse()

    def fake_parse_inventory_page(html, page_url):
        listing = VehicleListing(
            listing_url="https://example.test/detail",
            feature_text="Adaptive cruise control",
        )
        return [listing], None

    def fake_merge_detail_page(listing, html, detail_url):
        listing.vin = "TESTVIN1234567890"
        return listing

    monkeypatch.setattr("car_listing_audit.scraper.RobotsPolicy", FakeRobotsPolicy)
    monkeypatch.setattr("car_listing_audit.scraper.PoliteSession", FakeSession)
    monkeypatch.setattr("car_listing_audit.scraper.parse_inventory_page", fake_parse_inventory_page)
    monkeypatch.setattr("car_listing_audit.scraper.merge_detail_page", fake_merge_detail_page)

    messages = []
    listings = collect_listings(
        start_url="https://example.test/used",
        max_listings=1,
        progress_callback=messages.append,
    )

    assert len(listings) == 1
    assert listings[0].vin == "TESTVIN1234567890"
    assert any("Fetching inventory page" in message for message in messages)
    assert any("Fetching detail page 1/1" in message for message in messages)
    assert messages[-1] == "Collected 1 listings"
