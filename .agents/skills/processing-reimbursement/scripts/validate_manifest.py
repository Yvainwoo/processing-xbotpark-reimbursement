#!/usr/bin/env python3
"""Validate a reimbursement manifest and optionally its downloaded materials."""

from __future__ import annotations

import argparse
import json
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


REQUIRED_ROLES = ("invoice", "order", "payment")


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"Manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid manifest JSON: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError("Manifest must be an object with a records array")
    return payload


def has_material(materials: Path, record_id: str, role: str, index: int) -> bool:
    return any(materials.glob(f"{record_id}_{role}_{index}.*"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--materials", type=Path, help="Archive directory containing downloaded attachments")
    parser.add_argument("--allow-missing-evidence", action="store_true", help="Report missing roles without failing validation")
    args = parser.parse_args()

    manifest = load_manifest(args.manifest)
    errors: list[str] = []
    missing: list[str] = []
    seen_ids: set[str] = set()
    calculated_total = Decimal("0.00")

    for item in manifest["records"]:
        if not isinstance(item, dict):
            errors.append("A record is not an object")
            continue
        record_id = str(item.get("record_id", "")).strip()
        if not record_id:
            errors.append("A record has no record_id")
            continue
        if record_id in seen_ids:
            errors.append(f"Duplicate record_id: {record_id}")
        seen_ids.add(record_id)
        if not str(item.get("title", "")).strip():
            errors.append(f"{record_id}: title is blank")
        try:
            amount = Decimal(str(item.get("amount", "")))
            if amount < 0:
                raise InvalidOperation
            calculated_total += amount
        except InvalidOperation:
            errors.append(f"{record_id}: amount is not a nonnegative decimal")

        attachments = item.get("attachments")
        if not isinstance(attachments, dict):
            errors.append(f"{record_id}: attachments is not an object")
            continue
        for role in REQUIRED_ROLES:
            files = attachments.get(role, [])
            if not isinstance(files, list) or not files:
                missing.append(f"{record_id}: missing {role}")
                continue
            tokens: set[str] = set()
            for index, file in enumerate(files):
                token = str(file.get("token", "")).strip() if isinstance(file, dict) else ""
                if not token:
                    errors.append(f"{record_id}: {role}[{index}] has no token")
                elif token in tokens:
                    errors.append(f"{record_id}: duplicate token in {role}: {token}")
                tokens.add(token)
                if args.materials and not has_material(args.materials, record_id, role, index):
                    errors.append(f"{record_id}: downloaded material missing for {role}[{index}]")

    summary = manifest.get("summary", {})
    try:
        declared_total = Decimal(str(summary.get("amount_total", "")))
        if declared_total != calculated_total:
            errors.append(f"Summary total {declared_total} differs from records total {calculated_total}")
    except InvalidOperation:
        errors.append("Summary amount_total is not a decimal")
    if summary.get("record_count") != len(manifest["records"]):
        errors.append("Summary record_count differs from records length")

    for item in missing:
        print(f"MISSING: {item}")
    for item in errors:
        print(f"ERROR: {item}", file=sys.stderr)
    if errors or (missing and not args.allow_missing_evidence):
        return 2
    print(f"Manifest valid: {len(manifest['records'])} record(s), {calculated_total:.2f} yuan.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
