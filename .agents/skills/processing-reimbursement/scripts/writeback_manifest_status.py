#!/usr/bin/env python3
"""安全地把已确认清单中的记录写回到飞书多维表格状态字段。

先对状态字段配置和所有清单记录做全量只读校验；实际写入时每条记录
再次前置校验，写入后立即回读。脚本不替代用户对外部修改的明确确认。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any


@dataclass
class CheckFailure:
    record_id: str
    sequence: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "record_id": self.record_id,
            "sequence": self.sequence,
            "reason": self.reason,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="全量校验清单后，逐条写回飞书多维表格状态并立即回读验证。"
    )
    parser.add_argument("--manifest", type=Path, required=True, help="已核验的 manifest.json")
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--status-field-id", required=True, help="状态字段的字段 ID，用于核对选项")
    parser.add_argument("--status-field", required=True, help="状态字段的精确字段名")
    parser.add_argument("--category-field", required=True, help="费用类型的精确字段名")
    parser.add_argument("--review-field", required=True, help="审核结果的精确字段名")
    parser.add_argument("--amount-field", required=True, help="金额的精确字段名")
    parser.add_argument("--sequence-field", help="序号的精确字段名；提供时会逐条核对")
    parser.add_argument("--target-status", required=True, help="写入的下拉选项精确名称")
    parser.add_argument("--as", dest="identity", default="user", choices=("user", "bot"))
    parser.add_argument("--lark-cli", default="lark-cli.cmd", help="lark-cli 可执行文件")
    parser.add_argument("--delay", type=float, default=0.5, help="两次写入之间的最短间隔（秒）")
    parser.add_argument("--dry-run", action="store_true", help="只核验，不产生任何写入")
    parser.add_argument("--resume", action="store_true", help="允许已是目标状态的记录，跳过写入并继续处理其余记录")
    args = parser.parse_args()
    if args.delay < 0:
        parser.error("--delay 不能为负数")
    return args


def cli(args: argparse.Namespace, command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        [args.lark_cli, "base", *command, "--as", args.identity],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip() or "没有返回错误信息"
        raise RuntimeError(f"lark-cli 退出码 {completed.returncode}：{message}")
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"lark-cli 未返回 JSON：{completed.stdout.strip()}") from exc
    if payload.get("ok") is False:
        raise RuntimeError(f"lark-cli 返回失败：{json.dumps(payload, ensure_ascii=False)}")
    if payload.get("code") not in (None, 0):
        raise RuntimeError(f"飞书接口返回失败：{json.dumps(payload, ensure_ascii=False)}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise RuntimeError(f"lark-cli 返回中缺少 data：{json.dumps(payload, ensure_ascii=False)}")
    return data


def get_record(args: argparse.Namespace, record_id: str) -> dict[str, Any]:
    data = cli(
        args,
        [
            "+record-get",
            "--base-token",
            args.base_token,
            "--table-id",
            args.table_id,
            "--record-id",
            record_id,
        ],
    )
    record = data.get("record")
    if not isinstance(record, dict):
        raise RuntimeError(f"记录 {record_id} 的返回中缺少 record")
    return record


def write_status(args: argparse.Namespace, record_id: str) -> None:
    cli(
        args,
        [
            "+record-upsert",
            "--base-token",
            args.base_token,
            "--table-id",
            args.table_id,
            "--record-id",
            record_id,
            "--json",
            json.dumps({args.status_field: args.target_status}, ensure_ascii=False),
        ],
    )


def display_value(value: Any) -> str:
    """将常见的飞书字段值统一为可精确比较的显示文本。"""
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float, Decimal)):
        return str(value).strip()
    if isinstance(value, list):
        return ",".join(filter(None, (display_value(item) for item in value)))
    if isinstance(value, dict):
        for key in ("text", "name", "value"):
            if key in value:
                return display_value(value[key])
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def record_fields(record: dict[str, Any]) -> dict[str, Any]:
    fields = record.get("fields", record)
    if not isinstance(fields, dict):
        raise RuntimeError("记录的 fields 不是对象")
    return fields


def option_names(value: Any) -> set[str]:
    names: set[str] = set()
    if isinstance(value, dict):
        name = value.get("name")
        if isinstance(name, str):
            names.add(name)
        for nested in value.values():
            names.update(option_names(nested))
    elif isinstance(value, list):
        for nested in value:
            names.update(option_names(nested))
    return names


def check_status_field(args: argparse.Namespace) -> None:
    data = cli(
        args,
        [
            "+field-get",
            "--base-token",
            args.base_token,
            "--table-id",
            args.table_id,
            "--field-id",
            args.status_field_id,
        ],
    )
    field = data.get("field")
    if not isinstance(field, dict):
        raise RuntimeError("状态字段的返回中缺少 field")
    if field.get("field_name") not in (None, args.status_field) and field.get("name") != args.status_field:
        raise RuntimeError(f"状态字段 ID 不属于“{args.status_field}”")
    if field.get("type") not in {"select", "single_select"} or field.get("multiple") is True:
        raise RuntimeError("状态字段必须为单选下拉字段")
    if args.target_status not in option_names(field):
        raise RuntimeError(f"状态字段中不存在精确选项“{args.target_status}”")


def same_amount(actual: str, expected: str) -> bool:
    try:
        return Decimal(actual) == Decimal(expected)
    except (InvalidOperation, ValueError):
        return False


def check_record(args: argparse.Namespace, planned: dict[str, Any]) -> CheckFailure | str:
    record_id = str(planned.get("record_id", ""))
    sequence = str(planned.get("sequence", ""))
    if not record_id:
        return CheckFailure(record_id="", sequence=sequence, reason="manifest_record_id_missing")
    try:
        fields = record_fields(get_record(args, record_id))
    except RuntimeError as exc:
        return CheckFailure(record_id=record_id, sequence=sequence, reason=f"record_get_failed: {exc}")

    expected_category = str(planned.get("category", ""))
    expected_amount = str(planned.get("amount", ""))
    if display_value(fields.get(args.category_field)) != expected_category:
        return CheckFailure(record_id, sequence, "category_changed_or_not_selected")
    if display_value(fields.get(args.review_field)) != str(args.approved_value):
        return CheckFailure(record_id, sequence, "review_status_not_approved")
    if not same_amount(display_value(fields.get(args.amount_field)), expected_amount):
        return CheckFailure(record_id, sequence, "amount_changed")
    if args.sequence_field and display_value(fields.get(args.sequence_field)) != sequence:
        return CheckFailure(record_id, sequence, "sequence_changed")
    status = display_value(fields.get(args.status_field))
    if not status:
        return "blank"
    if args.resume and status == args.target_status:
        return "already_target"
    return CheckFailure(record_id, sequence, "status_is_not_blank")


def report(mode: str, manifest: Path, summary: dict[str, Any], failures: list[CheckFailure], successes: list[str], already: list[str]) -> None:
    print(
        json.dumps(
            {
                "mode": mode,
                "manifest": str(manifest),
                "planned_record_count": summary["record_count"],
                "planned_amount_total": summary["amount_total"],
                "success_record_ids": successes,
                "already_target_record_ids": already,
                "failure_count": len(failures),
                "failures": [failure.as_dict() for failure in failures],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main() -> int:
    args = parse_args()
    try:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"无法读取清单：{exc}", file=sys.stderr)
        return 2
    records = manifest.get("records")
    summary = manifest.get("summary")
    filters = manifest.get("filters")
    if not isinstance(records, list) or not isinstance(summary, dict) or not isinstance(filters, dict):
        print("清单缺少 records、summary 或 filters", file=sys.stderr)
        return 2
    if not records:
        print("清单没有可写回的记录", file=sys.stderr)
        return 2
    if not isinstance(summary.get("record_count"), int) or "amount_total" not in summary:
        print("清单 summary 格式不完整", file=sys.stderr)
        return 2
    if summary["record_count"] != len(records):
        print("清单 summary.record_count 与 records 数量不一致", file=sys.stderr)
        return 2
    args.approved_value = filters.get("approved_value")
    if not isinstance(args.approved_value, str) or not args.approved_value:
        print("清单 filters.approved_value 缺失", file=sys.stderr)
        return 2

    try:
        check_status_field(args)
    except RuntimeError as exc:
        print(f"状态字段校验失败：{exc}", file=sys.stderr)
        return 2

    # 全量预检先完成，确保发现任一漂移时不会产生部分写入。
    checks = [check_record(args, item) for item in records]
    failures = [result for result in checks if isinstance(result, CheckFailure)]
    already = [str(item["record_id"]) for item, result in zip(records, checks, strict=True) if result == "already_target"]
    if failures:
        report("dry-run" if args.dry_run else "preflight_failed", args.manifest, summary, failures, [], already)
        return 2
    if args.dry_run:
        report("dry-run", args.manifest, summary, [], [], already)
        return 0

    successes: list[str] = []
    failures = []
    already = []
    for planned in records:
        # 紧挨写入再检查，避免全量预检与写入之间的并发变更造成误写。
        state = check_record(args, planned)
        if isinstance(state, CheckFailure):
            failures.append(state)
            break
        record_id = str(planned["record_id"])
        if state == "already_target":
            already.append(record_id)
            continue
        try:
            write_status(args, record_id)
            verified = False
            for attempt in range(5):
                time.sleep(max(args.delay, 0.25) * (attempt + 1))
                fields = record_fields(get_record(args, record_id))
                if display_value(fields.get(args.status_field)) == args.target_status:
                    verified = True
                    break
            if not verified:
                raise RuntimeError("回读值与目标状态不一致")
        except RuntimeError as exc:
            failures.append(CheckFailure(record_id, str(planned.get("sequence", "")), f"write_or_verify_failed: {exc}"))
            break
        successes.append(record_id)

    report("writeback" if not failures else "partially_written", args.manifest, summary, failures, successes, already)
    return 0 if not failures else 3


if __name__ == "__main__":
    raise SystemExit(main())
