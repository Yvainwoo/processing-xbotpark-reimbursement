#!/usr/bin/env python3
"""Check all evidence/summary PDFs against manifests and render four-page review sheets."""

from __future__ import annotations

import argparse
import io
import json
from decimal import Decimal
from pathlib import Path

import fitz
from PIL import Image, ImageDraw

A4_POINTS = (595.28, 841.89)


def is_a4(page: fitz.Page) -> bool:
    width, height = sorted((page.rect.width, page.rect.height))
    return abs(width - A4_POINTS[0]) < 1 and abs(height - A4_POINTS[1]) < 1


def make_contact_sheets(document: fitz.Document, output_dir: Path, stem: str) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for start in range(0, len(document), 4):
        images = []
        for index in range(start, min(start + 4, len(document))):
            pixmap = document[index].get_pixmap(matrix=fitz.Matrix(1.25, 1.25), alpha=False)
            images.append((index + 1, Image.open(io.BytesIO(pixmap.tobytes("png"))).convert("RGB")))
        width = max(image.width for _, image in images)
        height = max(image.height for _, image in images)
        sheet = Image.new("RGB", (2 * width + 40, 2 * height + 70), "white")
        drawing = ImageDraw.Draw(sheet)
        for position, (page_number, image) in enumerate(images):
            x = 10 + position % 2 * (width + 20)
            y = 25 + position // 2 * (height + 35)
            sheet.paste(image, (x + (width - image.width) // 2, y))
            drawing.text((x, y - 18), f"page {page_number}", fill="black")
        sheet.save(output_dir / f"{stem}_{start + 1:02}-{start + len(images):02}.png")


def check_job(job: dict, render: bool) -> tuple[int, Decimal]:
    manifest = json.loads(Path(job["manifest"]).read_text(encoding="utf-8-sig"))
    records = manifest["records"]
    category = records[0]["category"]
    total = sum((Decimal(record["amount"]) for record in records), Decimal("0.00"))
    expected_total = Decimal(manifest["summary"]["amount_total"])
    if total != expected_total or any(record["category"] != category for record in records):
        raise ValueError(f"{category}: 清单金额或类型不一致")

    evidence = fitz.open(job["evidence_pdf"])
    summary = fitz.open(job["summary_pdf"])
    try:
        if len(evidence) != len(records) or len(summary) != 1:
            raise ValueError(f"{category}: PDF 页数与清单不一致")
        for index, record in enumerate(records):
            page = evidence[index]
            lines = page.get_text().splitlines()
            expected_header = [
                str(record["title"]),
                f"金额：{record['amount']} 元",
                f"{record['sequence']}    {category}",
            ]
            if (not is_a4(page) or lines[:3] != expected_header or
                    any(label not in lines[3:] for label in ("发票", "订单凭证", "付款凭证"))):
                raise ValueError(f"{category}: 证明材料第 {index + 1} 页尺寸或页眉/分区不符")
        summary_page = summary[0]
        summary_text = summary_page.get_text().replace("\n", "")
        expected_summary = (f"（{category}）", f"报销总金额：{total:.2f}", "报销人：", "报销人电话：")
        if not is_a4(summary_page) or any(value not in summary_text for value in expected_summary) or "XXX" in summary_text:
            raise ValueError(f"{category}: 信息概要页尺寸或内容不符")
        if render:
            output_dir = Path(job["qa_dir"])
            make_contact_sheets(evidence, output_dir, "证明材料")
            make_contact_sheets(summary, output_dir, "信息概要页")
    finally:
        evidence.close()
        summary.close()
    return len(records), total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--jobs-json", type=Path, required=True, help="数组：manifest/evidence_pdf/summary_pdf/qa_dir")
    parser.add_argument("--render", action="store_true", help="渲染每页，并按每四页生成视觉联系表")
    args = parser.parse_args()
    jobs = json.loads(args.jobs_json.read_text(encoding="utf-8-sig"))
    if not isinstance(jobs, list) or not jobs:
        raise ValueError("jobs-json 必须是非空数组")
    record_count = 0
    amount_total = Decimal("0.00")
    for job in jobs:
        count, total = check_job(job, args.render)
        record_count += count
        amount_total += total
        print(f"通过：{Path(job['evidence_pdf']).name}，{count} 页，{total:.2f} 元")
    print(f"合计：{record_count} 条，{amount_total:.2f} 元")


if __name__ == "__main__":
    main()
