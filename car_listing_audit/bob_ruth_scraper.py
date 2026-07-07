from __future__ import annotations

import argparse
import csv
from pathlib import Path
from collections.abc import Callable

from .models import CSV_COLUMNS, VehicleListing
from .parsing import apply_acc_detection, merge_detail_page, parse_inventory_page
from .polite_http import PoliteSession, RobotsPolicy, same_site_base


START_URL = "https://bobruthford.com/used-inventory"
DEFAULT_OUTPUT = "bob_ruth_acc_audit_seed.csv"


def collect_listings(
    start_url: str = START_URL,
    max_listings: int = 50,
    delay_seconds: float = 2.0,
    visit_detail_pages: bool = True,
    use_playwright_fallback: bool = True,
    progress_callback: Callable[[str], None] | None = None,
) -> list[VehicleListing]:
    def report(message: str) -> None:
        if progress_callback:
            progress_callback(message)

    session = PoliteSession(delay_seconds=delay_seconds)
    report("Loading robots.txt")
    robots = RobotsPolicy.load(same_site_base(start_url), session)

    listings: list[VehicleListing] = []
    seen_urls: set[str] = set()
    next_url: str | None = start_url

    while next_url and len(listings) < max_listings:
        report(f"Fetching inventory page: {next_url}")
        response = session.get(next_url, robots)
        response.raise_for_status()
        page_listings, discovered_next_url = parse_inventory_page(response.text, next_url)

        if not page_listings and use_playwright_fallback:
            report("Static HTML had no listings; trying Playwright fallback")
            rendered_html = render_with_playwright(next_url, robots)
            page_listings, discovered_next_url = parse_inventory_page(rendered_html, next_url)

        for listing in page_listings:
            if not listing.listing_url or listing.listing_url in seen_urls:
                continue
            seen_urls.add(listing.listing_url)
            listings.append(listing)
            if len(listings) >= max_listings:
                break

        next_url = discovered_next_url

    if visit_detail_pages:
        for index, listing in enumerate(listings, start=1):
            if not listing.listing_url:
                apply_acc_detection(listing)
                continue
            report(f"Fetching detail page {index}/{len(listings)}: {listing.listing_url}")
            detail_response = session.get(listing.listing_url, robots)
            detail_response.raise_for_status()
            merge_detail_page(listing, detail_response.text, listing.listing_url)
    else:
        for listing in listings:
            apply_acc_detection(listing)

    report(f"Collected {len(listings)} listings")
    return listings


def render_with_playwright(url: str, robots: RobotsPolicy) -> str:
    robots.ensure_allowed(url)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError(
            "Static HTML did not contain inventory data and Playwright is not installed. "
            "Install requirements-playwright.txt and Chromium to enable the fallback."
        ) from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="networkidle", timeout=30_000)
        html = page.content()
        browser.close()
        return html


def write_csv(listings: list[VehicleListing], output_path: Path) -> None:
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for listing in listings:
            writer.writerow(listing.to_csv_row())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build a Bob Ruth Ford ACC audit seed CSV.")
    parser.add_argument("--start-url", default=START_URL)
    parser.add_argument("--max-listings", type=int, default=50)
    parser.add_argument("--delay-seconds", type=float, default=2.0)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--skip-detail-pages", action="store_true")
    parser.add_argument("--no-playwright-fallback", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    listings = collect_listings(
        start_url=args.start_url,
        max_listings=args.max_listings,
        delay_seconds=args.delay_seconds,
        visit_detail_pages=not args.skip_detail_pages,
        use_playwright_fallback=not args.no_playwright_fallback,
    )
    output_path = Path(args.output)
    write_csv(listings, output_path)
    print(f"Wrote {len(listings)} listings to {output_path}")


if __name__ == "__main__":
    main()
