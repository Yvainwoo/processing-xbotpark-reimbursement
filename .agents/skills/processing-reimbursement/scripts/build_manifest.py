#!/usr/bin/env python3
"""Build a normalized reimbursement manifest from a Lark Base record-list response."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


ATTACHMENT_ROLES = ("invoice", "order", "payment")
DISPLAY_FIELDS = ("sequence", "title", "amount", "category", "date", "counterparty", "notes")


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise ValueError(f"File not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc


def find_items(payload: Any) -> list[dict[str, Any]]:
    """兼容对象式和 Base 快捷命令返回的列式记录。"""
    if isinstance(payload, dict):
        if isinstance(payload.get("items"), list):
            return payload["items"]
        for key in ("data", "result"):
            nested = payload.get(key)
            if isinstance(nested, dict) and isinstance(nested.get("items"), list):
                return nested["items"]
        if isinstance(payload.get("data"), dict):
            response = payload["data"]
            rows = response.get("data")
            field_names = response.get("fields")
            record_ids = response.get("record_id_list")
            if isinstance(rows, list) and isinstance(field_names, list) and isinstance(record_ids, list):
                if not (len(rows) == len(record_ids)):
                    raise ValueError("列式记录返回的 data 与 record_id_list 长度不一致")
                if any(not isinstance(row, list) or len(row) != len(field_names) for row in rows):
                    raise ValueError("列式记录返回的字段数与数据行不一致")
                return [
                    {"record_id": record_id, "fields": dict(zip(field_names, row, strict=True))}
                    for record_id, row in zip(record_ids, rows, strict=True)
                ]
    raise ValueError("未找到记录数组。请保存完整的 +record-list JSON 响应。")


def text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, Decimal)):
        return str(value)
    if isinstance(value, dict):
        for key in ("text", "name", "value", "display_value"):
            if key in value:
                return text_value(value[key])
        return ""
    if isinstance(value, list):
        return ", ".join(part for part in (text_value(part) for part in value) if part)
    return str(value).strip()


def attachment_items(value: Any) -> list[dict[str, str]]:
    """Extract attachment tokens from typical Base attachment cell representations."""
    values = value if isinstance(value, list) else [value]
    attachments: list[dict[str, str]] = []
    for item in values:
        if not isinstance(item, dict):
            continue
        token = next(
            (text_value(item.get(key)) for key in ("file_token", "fileToken", "token") if item.get(key)),
            "",
        )
        if not token:
            continue
        name = next(
            (text_value(item.get(key)) for key in ("name", "file_name", "fileName") if item.get(key)),
            token,
        )
        attachments.append({"token": token, "name": name})
    return attachments


def parse_amount(value: Any, record_id: str) -> str:
    raw = text_value(value).replace(",", "").replace("元", "").strip()
    if not raw:
        raise ValueError(f"Record {record_id}: mapped amount is blank")
    try:
        amount = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError(f"Record {record_id}: amount {raw!r} is not numeric") from exc
    if amount < 0:
        raise ValueError(f"Record {record_id}: amount cannot be negative")
    return format(amount.quantize(Decimal("0.01")), "f")


def is_eligible(fields: dict[str, Any], mapping: dict[str, str], args: argparse.Namespace) -> tuple[bool, str]:
    review_name = mapping.get("review_status")
    if not review_name:
        return False, "no_review_status_mapping"
    if text_value(fields.get(review_name)) != args.approved_value:
        return False, "review_status_not_approved"

    receipt_name = mapping.get("receipt_status")
    receipt_value = text_value(fields.get(receipt_name)) if receipt_name else ""
    if receipt_value and receipt_value not in args.include_receipt_status:
        return False, "receipt_status_not_eligible"

    category_name = mapping.get("category")
    category_value = text_value(fields.get(category_name))
    if args.category and category_value != args.category:
        return False, "category_not_selected"
    if category_value in args.exclude_category:
        return False, "category_excluded"
    return True, ""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--records",
        type=Path,
        required=True,
        action="append",
        help="保存的 +record-list JSON 响应；分页读取时可重复指定",
    )
    parser.add_argument("--field-map", type=Path, required=True, help="JSON mapping of semantic roles to exact Base fields")
    parser.add_argument("--out", type=Path, required=True, help="Output manifest JSON")
    parser.add_argument("--category", help="Exact selected category; omit for all categories")
    parser.add_argument(
        "--exclude-category",
        action="append",
        default=[],
        help="排除的精确费用类型；可重复指定。用于从“其余类型”范围中移除已处理类型",
    )
    parser.add_argument("--approved-value", required=True, help="Exact approved value from the discovered field options")
    parser.add_argument(
        "--include-receipt-status",
        action="append",
        default=[],
        help="可额外纳入的精确报销状态，可重复指定；空状态默认纳入",
    )
    args = parser.parse_args()

    mapping = load_json(args.field_map)
    if not isinstance(mapping, dict):
        raise ValueError("Field map must be a JSON object")
    for role in ("title", "amount", "review_status"):
        if not text_value(mapping.get(role)):
            raise ValueError(f"Field map requires a nonempty {role!r} entry")

    raw_records: list[dict[str, Any]] = []
    for source in args.records:
        raw_records.extend(find_items(load_json(source)))

    records: list[dict[str, Any]] = []
    excluded: list[dict[str, str]] = []
    for raw_record in raw_records:
        if not isinstance(raw_record, dict):
            continue
        record_id = text_value(raw_record.get("record_id") or raw_record.get("id"))
        fields = raw_record.get("fields")
        if not record_id or not isinstance(fields, dict):
            raise ValueError("Each Base record must include record_id/id and a fields object")
        eligible, reason = is_eligible(fields, mapping, args)
        if not eligible:
            excluded.append({"record_id": record_id, "reason": reason})
            continue

        record: dict[str, Any] = {"record_id": record_id}
        for role in DISPLAY_FIELDS:
            field_name = text_value(mapping.get(role))
            if role == "amount":
                record[role] = parse_amount(fields.get(field_name), record_id)
            else:
                record[role] = text_value(fields.get(field_name)) if field_name else ""
        record["attachments"] = {
            role: attachment_items(fields.get(text_value(mapping.get(role)))) if text_value(mapping.get(role)) else []
            for role in ATTACHMENT_ROLES
        }
        records.append(record)

    total = sum((Decimal(record["amount"]) for record in records), Decimal("0.00"))
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "filters": {
            "category": args.category or None,
            "excluded_categories": args.exclude_category,
            "approved_value": args.approved_value,
            "included_receipt_statuses": args.include_receipt_status,
        },
        "summary": {"record_count": len(records), "amount_total": format(total.quantize(Decimal("0.01")), "f")},
        "records": records,
        "excluded": excluded,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Planned {len(records)} record(s), total {manifest['summary']['amount_total']} yuan; excluded {len(excluded)}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
