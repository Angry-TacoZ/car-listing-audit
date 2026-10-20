from __future__ import annotations

import argparse
import csv
import html
import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from .audit import run_partner_batch_audit
from .models import CSV_COLUMNS, PARTNER_AUDIT_COLUMNS, PartnerAuditRow, VehicleListing
from .partner_audit import DEFAULT_PARTNER_OUTPUT
from .scraper import DEFAULT_OUTPUT, START_URL, collect_listings, write_csv
from .vision import create_vision_client


STYLE = """
body {
  margin: 0;
  font-family: Arial, sans-serif;
  color: #1f2933;
  background: #f5f7fa;
}
main {
  max-width: 1180px;
  margin: 0 auto;
  padding: 24px;
}
h1 {
  font-size: 24px;
  margin: 0 0 16px;
}
form {
  display: grid;
  grid-template-columns: 160px minmax(0, 1fr);
  gap: 12px;
  padding: 16px;
  background: #ffffff;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
}
label {
  font-weight: 700;
  align-self: center;
}
input[type="text"],
input[type="number"],
select {
  width: 100%;
  box-sizing: border-box;
  padding: 8px 10px;
  border: 1px solid #bcccdc;
  border-radius: 4px;
  font: inherit;
}
.options {
  display: flex;
  gap: 20px;
  flex-wrap: wrap;
}
.mode-tabs {
  display: flex;
  gap: 8px;
  margin: 16px 0 8px;
}
.mode-tabs a {
  padding: 8px 12px;
  border: 1px solid #bcccdc;
  border-radius: 4px;
  color: #075985;
  text-decoration: none;
  background: #ffffff;
}
.mode-tabs a.active {
  background: #075985;
  color: #ffffff;
  border-color: #075985;
}
.actions {
  grid-column: 2;
  display: flex;
  gap: 10px;
  align-items: center;
}
button {
  padding: 9px 14px;
  border: 0;
  border-radius: 4px;
  background: #075985;
  color: white;
  font-weight: 700;
  cursor: pointer;
}
button:hover {
  background: #0c4a6e;
}
.summary {
  margin: 16px 0;
  padding: 12px 14px;
  background: #ffffff;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
}
.error {
  border-color: #ef4444;
  color: #991b1b;
}
.table-wrap {
  overflow: auto;
  max-height: 58vh;
  background: #ffffff;
  border: 1px solid #d9e2ec;
  border-radius: 8px;
}
table {
  border-collapse: collapse;
  min-width: 1800px;
  width: 100%;
}
th,
td {
  padding: 8px 10px;
  border-bottom: 1px solid #edf2f7;
  text-align: left;
  vertical-align: top;
  font-size: 13px;
}
th {
  position: sticky;
  top: 0;
  background: #e6eef8;
  z-index: 1;
}
td.long {
  max-width: 360px;
}
"""


def render_page(
    mode: str = "public_url",
    start_url: str = "",
    output_path: str = DEFAULT_OUTPUT,
    max_listings: int = 50,
    delay_seconds: float = 2.0,
    visit_detail_pages: bool = True,
    use_playwright_fallback: bool = True,
    batch_path: str = "",
    partner_output_path: str = DEFAULT_PARTNER_OUTPUT,
    vision_provider: str = "manual",
    listings: list[VehicleListing] | None = None,
    partner_rows: list[PartnerAuditRow] | None = None,
    message: str = "Ready.",
    error: str = "",
) -> str:
    rows = listings or []
    report_rows = partner_rows or []
    summary_class = "summary error" if error else "summary"
    safe_message = html.escape(error or message)
    table_html = render_table(rows) if rows else ""
    partner_table_html = render_partner_table(report_rows) if report_rows else ""
    public_active = "active" if mode == "public_url" else ""
    partner_active = "active" if mode == "partner_batch" else ""
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Car Listing ACC Audit Scraper</title>
  <style>{STYLE}</style>
</head>
<body>
<main>
  <h1>Car Listing ACC Audit Scraper</h1>
  <div class="mode-tabs">
    <a class="{public_active}" href="/?mode=public_url">Public dealership URL</a>
    <a class="{partner_active}" href="/?mode=partner_batch">Partner batch upload</a>
  </div>
  {render_public_form(start_url, output_path, max_listings, delay_seconds, visit_detail_pages, use_playwright_fallback) if mode == "public_url" else render_partner_form(batch_path, partner_output_path, vision_provider)}
  <div class="{summary_class}">{safe_message}</div>
  {table_html}
  {partner_table_html}
</main>
</body>
</html>"""


def render_public_form(
    start_url: str,
    output_path: str,
    max_listings: int,
    delay_seconds: float,
    visit_detail_pages: bool,
    use_playwright_fallback: bool,
) -> str:
    return f"""
  <form method="post" action="/run">
    <label for="start_url">Inventory URL</label>
    <input id="start_url" name="start_url" type="text" value="{html.escape(start_url)}" required>

    <label for="output_path">Output CSV</label>
    <input id="output_path" name="output_path" type="text" value="{html.escape(output_path)}" required>

    <label for="max_listings">Max listings</label>
    <input id="max_listings" name="max_listings" type="number" min="1" max="50" value="{max_listings}" required>

    <label for="delay_seconds">Delay seconds</label>
    <input id="delay_seconds" name="delay_seconds" type="number" min="2" step="0.5" value="{delay_seconds}" required>

    <label>Options</label>
    <div class="options">
      <label><input name="visit_detail_pages" type="checkbox" value="1" {_checked(visit_detail_pages)}> Visit detail pages</label>
      <label><input name="use_playwright_fallback" type="checkbox" value="1" {_checked(use_playwright_fallback)}> Use Playwright fallback if needed</label>
    </div>

    <div class="actions">
      <button type="submit">Run Scrape</button>
      <span>Runs locally and respects robots.txt plus the configured delay.</span>
    </div>
  </form>
"""


def render_partner_form(batch_path: str, partner_output_path: str, vision_provider: str) -> str:
    return f"""
  <form method="post" action="/partner-run">
    <label for="batch_path">Partner batch file</label>
    <input id="batch_path" name="batch_path" type="text" value="{html.escape(batch_path)}" required>

    <label for="partner_output_path">Output report CSV</label>
    <input id="partner_output_path" name="partner_output_path" type="text" value="{html.escape(partner_output_path)}" required>

    <label for="vision_provider">Vision provider</label>
    <select id="vision_provider" name="vision_provider">
      <option value="manual" {_selected(vision_provider, "manual")}>Manual review fallback</option>
      <option value="mock" {_selected(vision_provider, "mock")}>Mock provider</option>
      <option value="openai" {_selected(vision_provider, "openai")}>OpenAI vision provider</option>
    </select>

    <div class="actions">
      <button type="submit">Run Partner Audit</button>
      <span>CarGurus public search pages are not scraped; use an approved export/feed.</span>
    </div>
  </form>
"""


def render_table(listings: list[VehicleListing]) -> str:
    headers = "".join(f"<th>{html.escape(column)}</th>" for column in CSV_COLUMNS)
    body_rows = []
    for listing in listings:
        row = listing.to_csv_row()
        cells = []
        for column in CSV_COLUMNS:
            class_name = ' class="long"' if column in {"feature_text", "photo_urls", "listing_url"} else ""
            cells.append(f"<td{class_name}>{html.escape(row[column])}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{headers}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'


def render_partner_table(rows: list[PartnerAuditRow]) -> str:
    headers = "".join(f"<th>{html.escape(column)}</th>" for column in PARTNER_AUDIT_COLUMNS)
    body_rows = []
    for report_row in rows:
        row = report_row.to_csv_row()
        cells = []
        for column in PARTNER_AUDIT_COLUMNS:
            class_name = ' class="long"' if column in {"evidence_summary", "evidence_photo_urls", "listing_url"} else ""
            cells.append(f"<td{class_name}>{html.escape(row[column])}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return f'<div class="table-wrap"><table><thead><tr>{headers}</tr></thead><tbody>{"".join(body_rows)}</tbody></table></div>'


def parse_run_form(body: str) -> dict[str, object]:
    fields = parse_qs(body, keep_blank_values=True)
    max_listings = int(_first(fields, "max_listings", "50"))
    delay_seconds = float(_first(fields, "delay_seconds", "2.0"))
    if not 1 <= max_listings <= 50:
        raise ValueError("Max listings must be between 1 and 50.")
    if delay_seconds < 2.0:
        raise ValueError("Delay must be at least 2 seconds.")
    start_url = _first(fields, "start_url", "").strip()
    if not start_url:
        raise ValueError("Inventory URL is required.")
    return {
        "start_url": start_url,
        "output_path": _first(fields, "output_path", DEFAULT_OUTPUT).strip(),
        "max_listings": max_listings,
        "delay_seconds": delay_seconds,
        "visit_detail_pages": "visit_detail_pages" in fields,
        "use_playwright_fallback": "use_playwright_fallback" in fields,
    }


def parse_partner_form(body: str) -> dict[str, str]:
    fields = parse_qs(body, keep_blank_values=True)
    batch_path = _first(fields, "batch_path", "").strip()
    output_path = _first(fields, "partner_output_path", DEFAULT_PARTNER_OUTPUT).strip()
    vision_provider = _first(fields, "vision_provider", "manual").strip()
    if not batch_path:
        raise ValueError("Partner batch file is required.")
    if not output_path:
        raise ValueError("Output report CSV is required.")
    if vision_provider not in {"manual", "mock", "openai"}:
        raise ValueError("Vision provider must be manual, mock, or openai.")
    return {
        "batch_path": batch_path,
        "partner_output_path": output_path,
        "vision_provider": vision_provider,
    }


class AuditGuiHandler(BaseHTTPRequestHandler):
    server_version = "CarListingAuditGui/0.1"

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json({"ok": True})
            return
        if not (self.path == "/" or self.path == "/index.html" or self.path.startswith("/?mode=")):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        mode = "partner_batch" if "mode=partner_batch" in self.path else "public_url"
        self._send_html(render_page(mode=mode))

    def do_POST_partner_run(self) -> None:
        config: dict[str, str] = {}
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 20_000:
                raise ValueError("Request body is too large.")
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            config = parse_partner_form(body)
            output_path = Path(config["partner_output_path"]).expanduser()
            summary = run_partner_batch_audit(
                input_path=Path(config["batch_path"]).expanduser(),
                output_path=output_path,
                vision_client=create_vision_client(config["vision_provider"]),
            )
            # Read the rows just written so the local UI can preview the same report.
            partner_rows = read_partner_report(output_path)
            self._send_html(
                render_page(
                    mode="partner_batch",
                    partner_rows=partner_rows,
                    message=f"{summary.to_message()} Wrote report to {output_path}.",
                    **config,
                )
            )
        except Exception as exc:
            if config:
                self._send_html(
                    render_page(mode="partner_batch", error=str(exc), **config),
                    status=HTTPStatus.BAD_REQUEST,
                )
            else:
                self._send_html(render_page(mode="partner_batch", error=str(exc)), status=HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:
        if self.path == "/partner-run":
            self.do_POST_partner_run()
            return
        if self.path != "/run":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.do_POST_public_run()

    def do_POST_public_run(self) -> None:
        config: dict[str, object] = {}
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 20_000:
                raise ValueError("Request body is too large.")
            body = self.rfile.read(length).decode("utf-8", errors="replace")
            config = parse_run_form(body)
            listings = collect_listings(
                start_url=str(config["start_url"]),
                max_listings=int(config["max_listings"]),
                delay_seconds=float(config["delay_seconds"]),
                visit_detail_pages=bool(config["visit_detail_pages"]),
                use_playwright_fallback=bool(config["use_playwright_fallback"]),
            )
            output_path = Path(str(config["output_path"])).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            write_csv(listings, output_path)
            acc_count = sum(1 for listing in listings if listing.has_acc_keyword == "true")
            if listings:
                message = f"Wrote {len(listings)} listings to {output_path}. ACC keyword hits: {acc_count}."
            else:
                message = (
                    f"Wrote 0 listings to {output_path}. The page loaded, but no supported inventory data was found. "
                    "This site may need a dedicated parser adapter."
                )
            self._send_html(render_page(mode="public_url", listings=listings, message=message, **config))
        except Exception as exc:
            if config:
                self._send_html(render_page(mode="public_url", error=str(exc), **config), status=HTTPStatus.BAD_REQUEST)
            else:
                self._send_html(render_page(mode="public_url", error=str(exc)), status=HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_html(self, content: str, status: HTTPStatus = HTTPStatus.OK) -> None:
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def _send_json(self, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def run_server(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), AuditGuiHandler)
    url = f"http://{host}:{server.server_port}/"
    print(f"Serving GUI at {url}")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping GUI server")
    finally:
        server.server_close()
    return server


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local browser GUI for the car listing audit scraper.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run_server(host=args.host, port=args.port, open_browser=not args.no_browser)


def _checked(value: bool) -> str:
    return "checked" if value else ""


def _selected(current: str, value: str) -> str:
    return "selected" if current == value else ""


def _first(fields: dict[str, list[str]], name: str, default: str) -> str:
    values = fields.get(name)
    return values[0] if values else default


def read_partner_report(path: Path) -> list[PartnerAuditRow]:
    with path.open(newline="", encoding="utf-8") as csv_file:
        rows = []
        for record in csv.DictReader(csv_file):
            rows.append(
                PartnerAuditRow(
                    listing_id=record.get("listing_id", ""),
                    listing_url=record.get("listing_url", ""),
                    vehicle=record.get("vehicle", ""),
                    claimed_feature=record.get("claimed_feature", ""),
                    verdict=record.get("verdict", ""),
                    confidence=record.get("confidence", ""),
                    evidence_summary=record.get("evidence_summary", ""),
                    evidence_photo_urls=[
                        value.strip()
                        for value in record.get("evidence_photo_urls", "").split("|")
                        if value.strip()
                    ],
                    review_notes=record.get("review_notes", ""),
                )
            )
        return rows


if __name__ == "__main__":
    main()
