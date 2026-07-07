from __future__ import annotations

import argparse
from pathlib import Path

from .audit import run_partner_batch_audit
from .vision import create_vision_client


DEFAULT_PARTNER_OUTPUT = "partner_acc_audit_report.csv"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run an ACC audit from an approved partner batch file.")
    parser.add_argument("--input", required=True, help="CSV or JSON batch file with listing data and photo URLs.")
    parser.add_argument("--output", default=DEFAULT_PARTNER_OUTPUT)
    parser.add_argument(
        "--vision-provider",
        choices=["manual", "mock", "openai"],
        default="manual",
        help="Use 'openai' only when OPENAI_API_KEY is configured locally/server-side.",
    )
    return parser


def main() -> None:
    args = build_parser().parse_args()
    summary = run_partner_batch_audit(
        input_path=Path(args.input),
        output_path=Path(args.output),
        vision_client=create_vision_client(args.vision_provider),
    )
    print(summary.to_message())
    print(f"Wrote report to {args.output}")


if __name__ == "__main__":
    main()

