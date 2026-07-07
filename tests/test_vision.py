from pathlib import Path

from car_listing_audit.batch import PartnerListing
from car_listing_audit.vision import (
    ManualReviewVisionClient,
    StaticVisionClient,
    extract_output_text,
    parse_model_json,
    to_image_content,
)


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

