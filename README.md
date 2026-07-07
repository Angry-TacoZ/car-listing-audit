# Adaptive Cruise Listing Audit

Python MVP scraper for building a manual-review CSV from public used-car inventory pages.

The tool is designed to help audit whether a used-car listing appears to mention adaptive cruise control or related feature names, then produce a spreadsheet for manual verification. It does not make the final feature decision for you. It creates a review queue with listing metadata, feature text, photo URLs, and blank columns for human evidence notes.

The original example target used during development was:

https://bobruthford.com/used-inventory

The scraper is intentionally conservative:

- checks `robots.txt` before fetching inventory or detail pages
- uses `requests` and `BeautifulSoup` first
- only attempts Playwright if the static HTML has no usable inventory data
- waits at least 2 seconds between page requests
- caps collection at 50 listings by default
- does not use login-only pages, bot-protection bypasses, credentialed sessions, or hidden APIs

## Current Scope

This is an MVP, not a universal car-marketplace crawler.

It currently works best on dealership inventory pages that expose listing data in public HTML or JSON-LD. Sites with custom marketplace search APIs, bot protection, or very different JavaScript-rendered markup may need a dedicated parser adapter before useful rows can be generated.

Known limitation: CarGurus search URLs can be rendered with Playwright after optional setup, but the current parser does not yet extract CarGurus result cards into rows.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

Playwright is optional and only needed if a future page becomes JavaScript-only:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-playwright.txt
.\.venv\Scripts\python.exe -m playwright install chromium
```

## Run

Local browser GUI:

```powershell
.\.venv\Scripts\python.exe -m car_listing_audit.web_gui
```

This starts a local-only server at `http://127.0.0.1:8765/` and opens it in your browser.

Command line:

```powershell
.\.venv\Scripts\python.exe -m car_listing_audit.scraper
```

This writes:

```text
acc_audit_seed.csv
```

Useful smaller smoke run:

```powershell
.\.venv\Scripts\python.exe -m car_listing_audit.scraper --max-listings 3 --output smoke.csv
```

## CSV Fields

The output includes listing data:

- `dealer_name`
- `stock_number`
- `year`
- `make`
- `model`
- `trim`
- `mileage`
- `price`
- `listing_url`
- `vin`
- `feature_text`
- `photo_urls`
- `has_acc_keyword`
- `acc_keyword_matches`

It also includes blank manual-review fields:

- `steering_wheel_photo_url`
- `visual_acc_evidence`
- `verdict`
- `notes`

`has_acc_keyword` is based on whether the collected feature text mentions any of:

- adaptive cruise control
- intelligent cruise control
- smart cruise control
- dynamic cruise control
- radar cruise
- active cruise control

This is only a seed signal. The final verdict should still come from manual feature verification, especially steering-wheel photos and window sticker or equipment evidence.

## Engineering Notes

The code is split so it can grow without becoming a one-off script:

- `polite_http.py` owns robots checks and request pacing.
- `parsing.py` owns HTML and JSON-LD extraction.
- `scraper.py` owns the command-line workflow.
- `web_gui.py` owns the local browser interface and calls the same scraper workflow.

No secrets are required. Do not add API keys, cookies, dealership admin credentials, or authenticated scraping flows to this repo. Generated CSV files are ignored by default because inventory snapshots are time-sensitive and should be regenerated for each audit.

## Public Repo Safety

This project is intended to be safe to host publicly:

- no API keys or credentials are required
- generated CSV inventory snapshots are ignored by Git
- browser automation is optional and only used for normal rendering
- the scraper does not attempt to bypass bot protection
- public deployment is not required; the GUI runs locally on `127.0.0.1`

## Validation

Run unit tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

Run a live smoke scrape:

```powershell
.\.venv\Scripts\python.exe -m car_listing_audit.scraper --max-listings 3 --output smoke.csv
```

Before making a public GitHub repo, also run a basic secret scan:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Users\angry\.codex\sessions\scripts\predeploy-secret-scan.ps1 -Path C:\Users\angry\.codex\sessions\car-listing-audit
```

## PR Workflow

For meaningful changes, use a focused branch:

```powershell
git checkout -b codex/<short-change-name>
```

Open a draft PR when a GitHub remote exists. Keep generated CSV snapshots out of the PR unless there is a specific review reason to include one.
