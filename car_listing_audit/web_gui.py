from __future__ import annotations

import argparse
import html
import json
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from .bob_ruth_scraper import DEFAULT_OUTPUT, START_URL, collect_listings, write_csv
from .models import CSV_COLUMNS, VehicleListing


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
input[type="number"] {
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
    start_url: str = START_URL,
    output_path: str = DEFAULT_OUTPUT,
    max_listings: int = 50,
    delay_seconds: float = 2.0,
    visit_detail_pages: bool = True,
    use_playwright_fallback: bool = True,
    listings: list[VehicleListing] | None = None,
    message: str = "Ready.",
    error: str = "",
) -> str:
    rows = listings or []
    summary_class = "summary error" if error else "summary"
    safe_message = html.escape(error or message)
    table_html = render_table(rows) if rows else ""
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
  <div class="{summary_class}">{safe_message}</div>
  {table_html}
</main>
</body>
</html>"""


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


def parse_run_form(body: str) -> dict[str, object]:
    fields = parse_qs(body, keep_blank_values=True)
    max_listings = int(_first(fields, "max_listings", "50"))
    delay_seconds = float(_first(fields, "delay_seconds", "2.0"))
    if not 1 <= max_listings <= 50:
        raise ValueError("Max listings must be between 1 and 50.")
    if delay_seconds < 2.0:
        raise ValueError("Delay must be at least 2 seconds.")
    return {
        "start_url": _first(fields, "start_url", START_URL).strip(),
        "output_path": _first(fields, "output_path", DEFAULT_OUTPUT).strip(),
        "max_listings": max_listings,
        "delay_seconds": delay_seconds,
        "visit_detail_pages": "visit_detail_pages" in fields,
        "use_playwright_fallback": "use_playwright_fallback" in fields,
    }


class AuditGuiHandler(BaseHTTPRequestHandler):
    server_version = "CarListingAuditGui/0.1"

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self._send_json({"ok": True})
            return
        if self.path not in {"/", "/index.html"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self._send_html(render_page())

    def do_POST(self) -> None:
        if self.path != "/run":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
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
            message = f"Wrote {len(listings)} listings to {output_path}. ACC keyword hits: {acc_count}."
            self._send_html(render_page(listings=listings, message=message, **config))
        except Exception as exc:
            self._send_html(render_page(error=str(exc)), status=HTTPStatus.BAD_REQUEST)

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


def _first(fields: dict[str, list[str]], name: str, default: str) -> str:
    values = fields.get(name)
    return values[0] if values else default


if __name__ == "__main__":
    main()

