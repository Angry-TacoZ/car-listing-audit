from __future__ import annotations

import csv
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

from .batch import PartnerListing, load_partner_batch
from .models import PARTNER_AUDIT_COLUMNS, PartnerAuditRow
from .vision import VisionClient


@dataclass
class AuditSummary:
    total_audited: int
    pass_count: int = 0
    fail_count: int = 0
    uncertain_count: int = 0
    manual_review_count: int = 0
    skipped_no_acc_claim_count: int = 0

    @classmethod
    def from_rows(cls, rows: list[PartnerAuditRow], skipped: int = 0) -> "AuditSummary":
        counts = Counter(row.verdict for row in rows)
        return cls(
            total_audited=len(rows),
            pass_count=counts.get("pass", 0),
            fail_count=counts.get("fail", 0),
            uncertain_count=counts.get("uncertain", 0),
            manual_review_count=counts.get("manual_review", 0),
            skipped_no_acc_claim_count=skipped,
        )

    def to_message(self) -> str:
        return (
            f"Audited {self.total_audited} ACC-claimed listings. "
            f"Pass: {self.pass_count}; fail: {self.fail_count}; uncertain: {self.uncertain_count}; "
            f"manual review: {self.manual_review_count}; skipped no ACC claim: {self.skipped_no_acc_claim_count}."
        )


def audit_partner_listings(listings: list[PartnerListing], vision_client: VisionClient) -> tuple[list[PartnerAuditRow], AuditSummary]:
    rows: list[PartnerAuditRow] = []
    skipped = 0
    for listing in listings:
        claimed_features = listing.claimed_acc_features
        if not claimed_features:
            skipped += 1
            continue
        try:
            result = vision_client.audit_acc(listing)
        except Exception as exc:
            rows.append(
                PartnerAuditRow(
                    listing_id=listing.listing_id,
                    listing_url=listing.listing_url,
                    vehicle=listing.vehicle_label,
                    claimed_feature=" | ".join(claimed_features),
                    verdict="manual_review",
                    confidence="0.00",
                    evidence_summary="Vision provider failed before returning a usable result.",
                    evidence_photo_urls=[],
                    review_notes=str(exc),
                )
            )
            continue
        rows.append(
            PartnerAuditRow(
                listing_id=listing.listing_id,
                listing_url=listing.listing_url,
                vehicle=listing.vehicle_label,
                claimed_feature=" | ".join(claimed_features),
                verdict=result.verdict,
                confidence=result.confidence,
                evidence_summary=result.evidence_summary,
                evidence_photo_urls=result.evidence_photo_urls,
                review_notes=result.review_notes,
            )
        )
    return rows, AuditSummary.from_rows(rows, skipped=skipped)


def run_partner_batch_audit(input_path: Path, output_path: Path, vision_client: VisionClient) -> AuditSummary:
    _ensure_distinct_input_and_output(input_path, output_path)
    listings = load_partner_batch(input_path)
    rows, summary = audit_partner_listings(listings, vision_client)
    write_partner_audit_csv(rows, output_path)
    return summary


def _ensure_distinct_input_and_output(input_path: Path, output_path: Path) -> None:
    if input_path.resolve() == output_path.resolve():
        raise ValueError("Input and output paths must refer to different files.")
    if input_path.exists() and output_path.exists():
        try:
            if input_path.samefile(output_path):
                raise ValueError("Input and output paths must refer to different files.")
        except OSError:
            # Resolved path equality above still protects ordinary path aliases.
            pass


def write_partner_audit_csv(rows: list[PartnerAuditRow], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=PARTNER_AUDIT_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row.to_csv_row())

