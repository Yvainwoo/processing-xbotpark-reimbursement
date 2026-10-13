#!/usr/bin/env python3
"""Read-only audit of reimbursement delivery and temporary-directory layout."""

from __future__ import annotations

import argparse
import re
from pathlib import Path


ARCHIVE = re.compile(r"(?P<date>\d{8})_(?P<category>.+)证明材料_(?P<amount>\d+(?:\.\d+)?)元")
GROUP = re.compile(r"(?P<date>\d{8})_(?P<category>.+)_(?P<amount>\d+(?:\.\d+)?)")
ATTACHMENT = re.compile(r"\d+_.+_(?:发票|订单凭证|付款凭证)(?:_\d+)?\.[^.]+")
FORMAL_FILE = re.compile(r"(?:\d{8}_.+证明材料_.+元|信息概要页_.+_.+元|\d{8}_采购申请单)\.(?:pdf|xlsx)", re.I)
SHARED_FILE = re.compile(r"\d{8}_.+费用报销附录表\.pdf", re.I)
PROCUREMENT_FILE = re.compile(r"(?P<date>\d{8})_采购申请单\.(?:xlsx|pdf)", re.I)
TEMP_NAMES = {"tmp", "downloads", "qa", "evidence-images", "__pycache__"}


def audit(root: Path) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    report: list[str] = []
    output = root / "output"
    temp = root / "tmp"
    if not output.is_dir():
        errors.append(f"缺少正式交付目录：{output}")
    if not temp.exists():
        report.append("根目录 tmp/ 已清理")
    elif not temp.is_dir():
        errors.append(f"根目录临时路径不是文件夹：{temp}")
    for item in root.iterdir():
        if item.is_file() and (FORMAL_FILE.fullmatch(item.name) or SHARED_FILE.fullmatch(item.name)):
            errors.append(f"正式文件仍在根目录：{item}")
        if item.is_dir() and (ARCHIVE.fullmatch(item.name) or GROUP.fullmatch(item.name)):
            errors.append(f"交付文件夹仍在根目录：{item}")
    if not output.is_dir():
        return errors, report

    group_count = 0
    attachment_count = 0
    formal_count = 0
    shared_count = 0
    procurement_dates: set[str] = set()
    for item in sorted(output.iterdir()):
        if item.is_file():
            procurement_match = PROCUREMENT_FILE.fullmatch(item.name)
            if procurement_match:
                procurement_dates.add(procurement_match['date'])
                shared_count += 1
            elif SHARED_FILE.fullmatch(item.name):
                shared_count += 1
            else:
                errors.append(f"output/ 顶层含未分类文件：{item}")
            continue
        if not item.is_dir():
            continue
        match = GROUP.fullmatch(item.name)
        if match is None:
            errors.append(f"output/ 顶层含未知目录：{item}")
            continue
        group_count += 1
        parts = match.groupdict()
        archive_name = f"{parts['date']}_{parts['category']}证明材料_{parts['amount']}元"
        archive = item / archive_name
        proof = item / f"{archive_name}.pdf"
        summary = item / f"信息概要页_{parts['category']}_{parts['amount']}元.pdf"
        if not archive.is_dir():
            errors.append(f"类型文件夹缺少原始附件目录：{archive}")
        if not proof.is_file():
            errors.append(f"原始附件缺少同名证明材料 PDF：{proof}")
        if not summary.is_file():
            errors.append(f"原始附件缺少对应信息概要页 PDF：{summary}")
        allowed_files = {proof.name, summary.name}
        count = 0
        for child in sorted(archive.iterdir()) if archive.is_dir() else []:
            if child.is_dir():
                errors.append(f"原始附件文件夹含子目录：{child}")
            elif not ATTACHMENT.fullmatch(child.name):
                errors.append(f"原始附件文件夹含非标准文件：{child}")
            else:
                count += 1
        attachment_count += count
        for child in item.iterdir():
            if child.is_dir() and child != archive:
                errors.append(f"类型文件夹含未知目录：{child}")
            elif child.is_file() and child.name not in allowed_files:
                if PROCUREMENT_FILE.fullmatch(child.name):
                    errors.append(f"采购申请单应作为本批共用文件放在 output/ 顶层：{child}")
                else:
                    errors.append(f"类型文件夹含未分类文件：{child}")
            elif child.is_file():
                formal_count += 1
        report.append(f"{item.name}：{count} 个原始附件")

    for date in sorted(procurement_dates):
        procurement = output / f"{date}_采购申请单"
        if not procurement.with_suffix('.xlsx').is_file() or not procurement.with_suffix('.pdf').is_file():
            errors.append(f"共用采购申请单 XLSX/PDF 未成对交付：{procurement}")

    for item in output.rglob("*"):
        if item.is_dir() and item.name.lower() in TEMP_NAMES:
            errors.append(f"临时目录混入 output/：{item}")
    report.append(f"合计：{group_count} 个类型文件夹，{attachment_count} 个附件，{formal_count} 个类型文件，{shared_count} 个共用文件")
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
