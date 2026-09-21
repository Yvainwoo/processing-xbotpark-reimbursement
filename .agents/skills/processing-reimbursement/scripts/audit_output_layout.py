#!/usr/bin/env python3
"""Read-only audit of reimbursement delivery and temporary-directory layout."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ARCHIVE = re.compile(r"(?P<date>\d{8})_(?P<category>.+)证明材料_(?P<amount>\d+(?:\.\d+)?)元")
ATTACHMENT = re.compile(r"\d+_.+_(?:发票|订单凭证|付款凭证)(?:_\d+)?\.[^.]+")
FORMAL_FILE = re.compile(r"(?:\d{8}_.+证明材料_.+元|信息概要页_.+_.+元|\d{8}_采购申请单)\.(?:pdf|xlsx)", re.I)
TEMP_NAMES = {"tmp", "downloads", "qa", "evidence-images", "__pycache__"}


def audit(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    report: list[str] = []
    output = root / "output"
    temp = root / "tmp"
    if not output.is_dir():
        errors.append(f"缺少正式交付目录：{output}")
    if not temp.is_dir():
        errors.append(f"缺少根目录临时目录：{temp}")
    for item in root.iterdir():
        if item.is_file() and FORMAL_FILE.fullmatch(item.name):
            errors.append(f"正式文件仍在根目录：{item}")
        if item.is_dir() and ARCHIVE.fullmatch(item.name):
            errors.append(f"原始附件文件夹仍在根目录：{item}")
    if not output.is_dir():
        return errors, report

    archive_count = 0
    attachment_count = 0
    for item in sorted(output.iterdir()):
        if item.is_file():
            if item.suffix.lower() not in {".pdf", ".xlsx"}:
                errors.append(f"output/ 顶层含非交付文件：{item}")
            continue
        if not item.is_dir():
            continue
        match = ARCHIVE.fullmatch(item.name)
        if match is None:
            errors.append(f"output/ 顶层含未知目录：{item}")
            continue
        archive_count += 1
        parts = match.groupdict()
        proof = output / f"{item.name}.pdf"
        summary = output / f"信息概要页_{parts['category']}_{parts['amount']}元.pdf"
        if not proof.is_file():
            errors.append(f"原始附件缺少同名证明材料 PDF：{proof}")
        if not summary.is_file():
            errors.append(f"原始附件缺少对应信息概要页 PDF：{summary}")
        count = 0
        for child in sorted(item.iterdir()):
            if child.is_dir():
                errors.append(f"原始附件文件夹含子目录：{child}")
            elif not ATTACHMENT.fullmatch(child.name):
                errors.append(f"原始附件文件夹含非标准文件：{child}")
            else:
                count += 1
        attachment_count += count
        report.append(f"{item.name}：{count} 个原始附件")

    for item in output.rglob("*"):
        if item.is_dir() and item.name.lower() in TEMP_NAMES:
            errors.append(f"临时目录混入 output/：{item}")
    for item in output.glob("*_采购申请单.*"):
        if item.suffix.lower() in {".xlsx", ".pdf"}:
            counterpart = item.with_suffix(".pdf" if item.suffix.lower() == ".xlsx" else ".xlsx")
            if not counterpart.is_file():
                errors.append(f"采购申请单缺少配套文件：{counterpart}")

    formal_count = sum(1 for item in output.iterdir() if item.is_file())
    report.append(f"合计：{archive_count} 个原始附件文件夹，{attachment_count} 个附件，{formal_count} 个顶层交付文件")
    return errors, report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="工作区根目录")
    args = parser.parse_args()
    root = args.root.resolve()
    if not root.is_dir():
        parser.error(f"工作区根目录不存在：{root}")
    errors, report = audit(root)
    for line in report:
        print(line)
    for line in errors:
        print(f"错误：{line}")
    print("目录检查通过" if not errors else f"目录检查失败：{len(errors)} 项")
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
