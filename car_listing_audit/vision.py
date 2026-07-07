from __future__ import annotations

import base64
import json
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
        data = parse_model_json(output_text)
        return VisionAuditResult(
            verdict=str(data.get("verdict", "uncertain")),
            confidence=str(data.get("confidence", "")),
            evidence_summary=str(data.get("evidence_summary", "")),
            evidence_photo_urls=[str(item) for item in data.get("evidence_photo_urls", [])],
            review_notes=str(data.get("review_notes", "")),
        )


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


def create_vision_client(provider: str) -> VisionClient:
    if provider == "manual":
        return ManualReviewVisionClient()
    if provider == "mock":
        return StaticVisionClient()
    if provider == "openai":
        return OpenAIVisionClient()
    raise ValueError("Vision provider must be one of: manual, mock, openai.")

