#!/usr/bin/env python3
"""从已下载的稳定命名材料导出可交付的“原始附件”文件夹。"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROLE_NAMES = {
    "invoice": "发票",
    "order": "订单凭证",
    "payment": "付款凭证",
}
INVALID_WINDOWS_CHARS = str.maketrans({
    "<": "＜", ">": "＞", ":": "：", '"': "＂", "/": "／", "\\": "＼", "|": "｜", "?": "？", "*": "＊",
})


@dataclass(frozen=True)
class ExportJob:
    source: Path
    target_name: str


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取清单 {path}: {exc}") from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("records"), list):
        raise ValueError("清单必须包含 records 数组")
    return payload


def safe_component(value: Any, label: str) -> str:
    text = ("" if value is None else str(value)).strip().translate(INVALID_WINDOWS_CHARS)
    text = "".join(character for character in text if ord(character) >= 32).rstrip(". ")
    if not text:
        raise ValueError(f"记录缺少可用于文件名的{label}")
    return text


def source_for(materials: Path, record_id: str, role: str, index: int) -> Path:
    matches = sorted(materials.glob(f"{record_id}_{role}_{index}.*"))
    if not matches:
        raise ValueError(f"{record_id}: 未找到已下载的 {role}[{index}]")
    if len(matches) > 1:
        raise ValueError(f"{record_id}: {role}[{index}] 存在多个候选文件")
    return matches[0]


def jobs_from_manifest(manifest: dict[str, Any], materials: Path) -> list[ExportJob]:
    jobs: list[ExportJob] = []
    names: set[str] = set()
    for record in manifest["records"]:
        if not isinstance(record, dict):
            raise ValueError("清单中存在非对象记录")
        record_id = str(record.get("record_id", "")).strip()
        sequence = safe_component(record.get("sequence"), "序号")
        title = safe_component(record.get("title"), "费用名称")
        attachments = record.get("attachments")
        if not record_id or not isinstance(attachments, dict):
            raise ValueError("清单记录缺少 record_id 或 attachments")
        for role, material_name in ROLE_NAMES.items():
            files = attachments.get(role)
            if not isinstance(files, list) or not files:
                raise ValueError(f"{record_id}: 缺少 {role}")
            for index, _ in enumerate(files):
                source = source_for(materials, record_id, role, index)
                occurrence = "" if index == 0 else f"_{index + 1}"
                target_name = f"{sequence}_{title}_{material_name}{occurrence}{source.suffix.lower()}"
                if target_name.casefold() in names:
                    raise ValueError(f"导出文件名冲突：{target_name}")
                names.add(target_name.casefold())
                jobs.append(ExportJob(source=source, target_name=target_name))
    return jobs


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--materials", type=Path, required=True, help="稳定命名下载文件所在目录")
    parser.add_argument("--out", type=Path, required=True, help="原始附件归档目录；可已存在，但必须为空")
    parser.add_argument("--dry-run", action="store_true", help="只验证输入并列出计划，不创建文件")
    args = parser.parse_args()

    if not args.materials.is_dir():
        raise ValueError(f"材料目录不存在：{args.materials}")
    if args.out.exists():
        if not args.out.is_dir():
            raise ValueError(f"原始附件归档路径不是目录：{args.out}")
        unexpected = [entry.name for entry in args.out.iterdir()]
        if unexpected:
            raise ValueError(f"拒绝覆盖归档目录中的已有内容：{', '.join(sorted(unexpected))}")
    jobs = jobs_from_manifest(load_manifest(args.manifest), args.materials)
    if args.dry_run:
        print(f"Planned {len(jobs)} original attachment export(s) to {args.out}.")
        for job in jobs:
            print(job.target_name)
        return 0

    args.out.mkdir(parents=True, exist_ok=True)
    copied = 0
    for job in jobs:
        target = args.out / job.target_name
        shutil.copy2(job.source, target)
        if target.stat().st_size != job.source.stat().st_size:
            raise ValueError(f"复制后的文件大小不一致：{target.name}")
        copied += 1
    print(f"Exported {copied} original attachment(s) to {args.out}.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
