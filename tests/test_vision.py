from pathlib import Path
from unittest.mock import patch
import json
import pytest

from car_listing_audit.audit import audit_partner_listings
from car_listing_audit.batch import PartnerListing
from car_listing_audit.vision import (
    ManualReviewVisionClient,
    OpenAIVisionClient,
    StaticVisionClient,
    extract_output_text,
    parse_model_json,
    to_image_content,
)


class FakeModelResponse:
    def __init__(self, output_text: str) -> None:
        self.output_text = output_text

    def raise_for_status(self) -> None:
        pass

    def json(self) -> dict[str, str]:
        return {"output_text": self.output_text}


def audit_with_mock_model(listing: PartnerListing, model_result: object):
    response = FakeModelResponse(json.dumps(model_result))
    with patch("car_listing_audit.vision.requests.post", return_value=response):
        return audit_partner_listings([listing], OpenAIVisionClient(api_key="test-key"))


def test_manual_review_provider_returns_safe_default() -> None:
    listing = PartnerListing(
        listing_id="cg-1",
        claimed_features="Adaptive cruise control",
        photo_urls=["https://img.test/1.jpg", "https://img.test/2.jpg"],
    )

    result = ManualReviewVisionClient().audit_acc(listing)

    assert result.verdict == "manual_review"
    assert result.evidence_photo_urls == ["https://img.test/1.jpg", "https://img.test/2.jpg"]
    assert "No vision model configured" in result.evidence_summary


def test_static_provider_can_mock_all_verdicts() -> None:
    listing = PartnerListing(
        listing_id="cg-1",
        claimed_features="Adaptive cruise control",
        photo_urls=["https://img.test/1.jpg"],
    )

    for verdict in ["pass", "fail", "uncertain", "manual_review"]:
        result = StaticVisionClient(verdict=verdict).audit_acc(listing)
        assert result.verdict == verdict


def test_to_image_content_accepts_urls_and_local_images(tmp_path) -> None:
    assert to_image_content("https://img.test/1.jpg") == {
        "type": "input_image",
        "image_url": "https://img.test/1.jpg",
    }

    image_path = tmp_path / "wheel.jpg"
    image_path.write_bytes(b"fake-image")
    content = to_image_content(str(image_path))

    assert content["type"] == "input_image"
    assert content["image_url"].startswith("data:image/jpeg;base64,")


def test_parse_model_json_handles_fenced_json() -> None:
    data = parse_model_json(
        '```json\n{"verdict":"fail","confidence":"0.82","evidence_summary":"No distance buttons","evidence_photo_urls":[]}\n```'
    )

    assert data["verdict"] == "fail"


def test_extract_output_text_handles_responses_payload_shape() -> None:
    payload = {
        "output": [
            {
                "content": [
                    {
                        "type": "output_text",
                        "text": '{"verdict":"uncertain"}',
                    }
                ]
            }
        ]
    }

    assert extract_output_text(payload) == '{"verdict":"uncertain"}'


def test_incomplete_openai_result_becomes_manual_review() -> None:
    listing = PartnerListing(
        listing_id="cg-1",
        claimed_features="Adaptive cruise control",
        photo_urls=["https://img.test/1.jpg"],
    )

    rows, summary = audit_with_mock_model(listing, {"verdict": "pass"})

    assert rows[0].verdict == "manual_review"
    assert rows[0].evidence_photo_urls == []
    assert "missing required fields" in rows[0].review_notes
    assert summary.pass_count == 0
    assert summary.manual_review_count == 1


@pytest.mark.parametrize(
    "model_result",
    [
        {"verdict": "pass", "confidence": "high", "evidence_summary": "Observed ACC controls.", "evidence_photo_urls": ["https://img.test/1.jpg"]},
        {"verdict": "pass", "confidence": "0.9", "evidence_summary": "Observed ACC controls.", "evidence_photo_urls": []},
        {"verdict": "pass", "confidence": "0.9", "evidence_summary": "Observed ACC controls.", "evidence_photo_urls": ["https://other.test/photo.jpg"]},
    ],
)
def test_invalid_openai_result_becomes_manual_review(model_result) -> None:
    listing = PartnerListing(
        listing_id="cg-1",
        claimed_features="Adaptive cruise control",
        photo_urls=["https://img.test/1.jpg"],
    )

    rows, summary = audit_with_mock_model(listing, model_result)

    assert rows[0].verdict == "manual_review"
    assert summary.pass_count == 0
    assert summary.manual_review_count == 1


def test_complete_openai_result_accepts_only_supplied_evidence() -> None:
    image_url = "https://img.test/1.jpg"
    listing = PartnerListing(
        listing_id="cg-1",
        claimed_features="Adaptive cruise control",
        photo_urls=[image_url],
    )

    rows, summary = audit_with_mock_model(
        listing,
        {
            "verdict": "pass",
            "confidence": 0.91,
            "evidence_summary": "Distance control buttons are visible.",
            "evidence_photo_urls": [image_url],
            "review_notes": "",
        },
    )

    assert rows[0].verdict == "pass"
    assert rows[0].evidence_photo_urls == [image_url]
    assert summary.pass_count == 1

