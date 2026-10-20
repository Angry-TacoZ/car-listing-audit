from __future__ import annotations

import base64
import json
import math
import mimetypes
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlparse

import requests

from .batch import PartnerListing


VALID_VERDICTS = {"pass", "fail", "uncertain", "manual_review"}


@dataclass
class VisionAuditResult:
    verdict: str
    confidence: str
    evidence_summary: str
    evidence_photo_urls: list[str]
    review_notes: str = ""

    def __post_init__(self) -> None:
        if self.verdict not in VALID_VERDICTS:
            raise ValueError(f"Unsupported audit verdict: {self.verdict}")


class VisionClient(Protocol):
    def audit_acc(self, listing: PartnerListing) -> VisionAuditResult:
        ...


class ManualReviewVisionClient:
    def audit_acc(self, listing: PartnerListing) -> VisionAuditResult:
        return VisionAuditResult(
            verdict="manual_review",
            confidence="0.00",
            evidence_summary="No vision model configured. Listing requires manual image review.",
            evidence_photo_urls=listing.photo_urls[:3],
            review_notes="Set OPENAI_API_KEY and use the openai provider for model-backed review.",
        )


class StaticVisionClient:
    def __init__(
        self,
        verdict: str = "uncertain",
        confidence: str = "0.50",
        evidence_summary: str = "Mocked model response.",
        review_notes: str = "",
    ) -> None:
        self.verdict = verdict
        self.confidence = confidence
        self.evidence_summary = evidence_summary
        self.review_notes = review_notes

    def audit_acc(self, listing: PartnerListing) -> VisionAuditResult:
        return VisionAuditResult(
            verdict=self.verdict,
            confidence=self.confidence,
            evidence_summary=self.evidence_summary,
            evidence_photo_urls=listing.photo_urls[:2],
            review_notes=self.review_notes,
        )


class OpenAIVisionClient:
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        endpoint: str = "https://api.openai.com/v1/responses",
    ) -> None:
        self.api_key = api_key or os.getenv("OPENAI_API_KEY", "")
        if not self.api_key:
            raise RuntimeError("OPENAI_API_KEY is required for the OpenAI vision provider.")
        self.model = model or os.getenv("OPENAI_VISION_MODEL", "gpt-5.5")
        self.endpoint = endpoint

    def audit_acc(self, listing: PartnerListing) -> VisionAuditResult:
        content = [
            {
                "type": "input_text",
                "text": build_acc_prompt(listing),
            }
        ]
        for image_ref in listing.photo_urls[:8]:
            content.append(to_image_content(image_ref))

        response = requests.post(
            self.endpoint,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": self.model,
                "input": [{"role": "user", "content": content}],
            },
            timeout=90,
        )
        response.raise_for_status()
        payload = response.json()
        output_text = extract_output_text(payload)
        return parse_model_result(output_text, listing)


def build_acc_prompt(listing: PartnerListing) -> str:
    return (
        "Audit this used-car listing for visual evidence of adaptive cruise control. "
        "Look for steering-wheel distance-control buttons, cruise/resume/set controls, "
        "dashboard ACC indicators, window-sticker text, or equipment labels. "
        "Return only JSON with keys: verdict, confidence, evidence_summary, "
        "evidence_photo_urls, review_notes. verdict must be one of pass, fail, uncertain, manual_review. "
        f"Listing ID: {listing.listing_id}. Vehicle: {listing.vehicle_label}. "
        f"Claimed features: {listing.claimed_features}. Photo URLs: {' | '.join(listing.photo_urls[:8])}."
    )


def to_image_content(image_ref: str) -> dict[str, str]:
    parsed = urlparse(image_ref)
    if parsed.scheme in {"http", "https"}:
        return {"type": "input_image", "image_url": image_ref}
    path = Path(image_ref).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"Local image not found: {image_ref}")
    mime_type = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {"type": "input_image", "image_url": f"data:{mime_type};base64,{encoded}"}


def extract_output_text(payload: dict) -> str:
    if isinstance(payload.get("output_text"), str):
        return payload["output_text"]
    parts: list[str] = []
    for item in payload.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") in {"output_text", "text"}:
                text = content.get("text")
                if isinstance(text, str):
                    parts.append(text)
    return "\n".join(parts).strip()


def parse_model_json(output_text: str) -> dict:
    cleaned = output_text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        cleaned = cleaned.removeprefix("json").strip()
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Vision model did not return parseable JSON: {output_text[:200]}") from exc
    if not isinstance(data, dict):
        raise RuntimeError("Vision model response must be a JSON object.")
    return data


def parse_model_result(output_text: str, listing: PartnerListing) -> VisionAuditResult:
    data = parse_model_json(output_text)
    required_fields = {"verdict", "confidence", "evidence_summary", "evidence_photo_urls"}
    missing_fields = sorted(required_fields - data.keys())
    if missing_fields:
        raise RuntimeError(f"Vision model response is missing required fields: {', '.join(missing_fields)}.")

    verdict = data["verdict"]
    if not isinstance(verdict, str) or verdict not in VALID_VERDICTS:
        raise RuntimeError("Vision model response contains an unsupported verdict.")

    confidence_value = data["confidence"]
    if isinstance(confidence_value, bool) or not isinstance(confidence_value, (str, int, float)):
        raise RuntimeError("Vision model confidence must be a number from 0 to 1.")
    confidence = str(confidence_value).strip()
    try:
        confidence_number = float(confidence)
    except ValueError as exc:
        raise RuntimeError("Vision model confidence must be a number from 0 to 1.") from exc
    if not math.isfinite(confidence_number) or not 0 <= confidence_number <= 1:
        raise RuntimeError("Vision model confidence must be a number from 0 to 1.")

    evidence_summary = data["evidence_summary"]
    if not isinstance(evidence_summary, str) or not evidence_summary.strip():
        raise RuntimeError("Vision model evidence_summary must be nonempty text.")

    evidence_photo_urls = data["evidence_photo_urls"]
    if not isinstance(evidence_photo_urls, list) or any(
        not isinstance(item, str) or not item.strip() for item in evidence_photo_urls
    ):
        raise RuntimeError("Vision model evidence_photo_urls must be a list of nonempty strings.")
    evidence_photo_urls = [item.strip() for item in evidence_photo_urls]
    allowed_photo_urls = set(listing.photo_urls[:8])
    if any(item not in allowed_photo_urls for item in evidence_photo_urls):
        raise RuntimeError("Vision model evidence_photo_urls must reference supplied listing photos.")
    if verdict in {"pass", "fail"} and not evidence_photo_urls:
        raise RuntimeError("Conclusive vision model verdicts must cite at least one supplied listing photo.")

    review_notes = data.get("review_notes", "")
    if not isinstance(review_notes, str):
        raise RuntimeError("Vision model review_notes must be text.")

    return VisionAuditResult(
        verdict=verdict,
        confidence=confidence,
        evidence_summary=evidence_summary.strip(),
        evidence_photo_urls=evidence_photo_urls,
        review_notes=review_notes.strip(),
    )


def create_vision_client(provider: str) -> VisionClient:
    if provider == "manual":
        return ManualReviewVisionClient()
    if provider == "mock":
        return StaticVisionClient()
    if provider == "openai":
        return OpenAIVisionClient()
    raise ValueError("Vision provider must be one of: manual, mock, openai.")

