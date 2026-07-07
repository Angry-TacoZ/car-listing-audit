from car_listing_audit.models import VehicleListing
from car_listing_audit.web_gui import parse_run_form, render_page


def test_parse_run_form_validates_bounds() -> None:
    config = parse_run_form(
        "start_url=https%3A%2F%2Fexample.test%2Fused&"
        "output_path=out.csv&max_listings=3&delay_seconds=2.5&visit_detail_pages=1"
    )

    assert config["start_url"] == "https://example.test/used"
    assert config["output_path"] == "out.csv"
    assert config["max_listings"] == 3
    assert config["delay_seconds"] == 2.5
    assert config["visit_detail_pages"] is True
    assert config["use_playwright_fallback"] is False


def test_parse_run_form_rejects_too_fast_delay() -> None:
    try:
        parse_run_form("max_listings=3&delay_seconds=1")
    except ValueError as exc:
        assert "Delay must be at least 2 seconds" in str(exc)
    else:
        raise AssertionError("Expected delay validation to fail")


def test_parse_run_form_requires_inventory_url() -> None:
    try:
        parse_run_form("max_listings=3&delay_seconds=2")
    except ValueError as exc:
        assert "Inventory URL is required" in str(exc)
    else:
        raise AssertionError("Expected inventory URL validation to fail")


def test_render_page_includes_listing_preview() -> None:
    listing = VehicleListing(
        dealer_name="Example Dealer",
        stock_number="ABC123",
        year="2024",
        make="Ford",
        model="Escape",
        trim="Active",
        has_acc_keyword="true",
        acc_keyword_matches="adaptive cruise control",
    )

    html = render_page(listings=[listing], message="Wrote 1 listing.")

    assert "Car Listing ACC Audit Scraper" in html
    assert "Example Dealer" in html
    assert "adaptive cruise control" in html
    assert "Wrote 1 listing." in html


def test_render_page_preserves_form_values_on_error() -> None:
    html = render_page(
        start_url="https://example.test/used",
        output_path="example.csv",
        max_listings=3,
        delay_seconds=2.5,
        visit_detail_pages=False,
        use_playwright_fallback=False,
        error="No listings found",
    )

    assert 'value="https://example.test/used"' in html
    assert 'value="example.csv"' in html
    assert 'value="3"' in html
    assert 'value="2.5"' in html
    assert "No listings found" in html
