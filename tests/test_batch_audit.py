import csv
import json

from car_listing_audit.audit import audit_partner_listings, run_partner_batch_audit
from car_listing_audit.batch import load_partner_batch, parse_photo_urls
from car_listing_audit.vision import ManualReviewVisionClient, StaticVisionClient


def test_load_partner_batch_csv_valid_row(tmp_path) -> None:
    path = tmp_path / "partner.csv"
    path.write_text(
        "listing_id,listing_url,year,make,model,trim,vin,stock_number,claimed_features,photo_urls\n"
        "cg-1,https://example.test/1,2024,Mini,Cooper,S,,STK1,Adaptive cruise control,"
        "https://img.test/steering.jpg | https://img.test/window.jpg\n",
        encoding="utf-8",
    )

    listings = load_partner_batch(path)

    assert len(listings) == 1
    assert listings[0].listing_id == "cg-1"
    assert listings[0].vehicle_label == "2024 Mini Cooper S"
    assert listings[0].claimed_acc_features == ["adaptive cruise control"]
    assert listings[0].photo_urls == ["https://img.test/steering.jpg", "https://img.test/window.jpg"]


def test_load_partner_batch_json_valid_rows(tmp_path) -> None:
    path = tmp_path / "partner.json"
    path.write_text(
        json.dumps(
            {
                "listings": [
                    {
                        "listing_id": "cg-2",
                        "claimed_features": "Radar cruise",
                        "photo_urls": ["https://img.test/1.jpg"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    listings = load_partner_batch(path)

    assert len(listings) == 1
    assert listings[0].claimed_acc_features == ["radar cruise"]


def test_load_partner_batch_rejects_missing_required_columns(tmp_path) -> None:
    path = tmp_path / "partner.csv"
    path.write_text("listing_id,claimed_features\ncg-1,Adaptive cruise control\n", encoding="utf-8")

    try:
        load_partner_batch(path)
    except ValueError as exc:
        assert "missing required columns" in str(exc)
        assert "photo_urls" in str(exc)
    else:
        raise AssertionError("Expected missing column validation to fail")


def test_load_partner_batch_rejects_empty_file(tmp_path) -> None:
    path = tmp_path / "partner.csv"
    path.write_text("listing_id,claimed_features,photo_urls\n", encoding="utf-8")

    try:
        load_partner_batch(path)
    except ValueError as exc:
        assert "does not contain any listing rows" in str(exc)
    else:
        raise AssertionError("Expected empty batch validation to fail")


def test_parse_photo_urls_rejects_comma_delimited_values() -> None:
    try:
        parse_photo_urls("https://img.test/1.jpg,https://img.test/2.jpg")
    except ValueError as exc:
        assert "pipe-delimited" in str(exc)
    else:
        raise AssertionError("Expected comma-delimited photo URL validation to fail")


def test_audit_partner_listings_filters_to_acc_claims(tmp_path) -> None:
    path = tmp_path / "partner.csv"
    path.write_text(
        "listing_id,claimed_features,photo_urls\n"
        "cg-1,Adaptive cruise control,https://img.test/1.jpg\n"
        "cg-2,Heated seats,https://img.test/2.jpg\n",
        encoding="utf-8",
    )
    listings = load_partner_batch(path)

    rows, summary = audit_partner_listings(
        listings,
        StaticVisionClient(verdict="fail", confidence="0.91", evidence_summary="Distance buttons missing."),
    )

    assert len(rows) == 1
    assert rows[0].listing_id == "cg-1"
    assert rows[0].verdict == "fail"
    assert summary.total_audited == 1
    assert summary.fail_count == 1
    assert summary.skipped_no_acc_claim_count == 1


def test_run_partner_batch_audit_writes_stable_report_columns(tmp_path) -> None:
    input_path = tmp_path / "partner.csv"
    output_path = tmp_path / "report.csv"
    input_path.write_text(
        "listing_id,listing_url,year,make,model,trim,claimed_features,photo_urls\n"
        "cg-1,https://example.test/1,2024,Mini,Cooper,S,Smart cruise control,https://img.test/1.jpg\n",
        encoding="utf-8",
    )

    summary = run_partner_batch_audit(input_path, output_path, ManualReviewVisionClient())

    with output_path.open(newline="", encoding="utf-8") as csv_file:
        rows = list(csv.DictReader(csv_file))
    assert summary.manual_review_count == 1
    assert rows[0]["listing_id"] == "cg-1"
    assert rows[0]["vehicle"] == "2024 Mini Cooper S"
    assert rows[0]["verdict"] == "manual_review"
    assert list(rows[0].keys()) == [
        "listing_id",
        "listing_url",
        "vehicle",
        "claimed_feature",
        "verdict",
        "confidence",
        "evidence_summary",
        "evidence_photo_urls",
        "review_notes",
    ]

