#!/usr/bin/env python3
"""Create a one-record-per-page A4 reimbursement evidence PDF from a manifest."""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path
from typing import Any


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc


def find_material(materials: Path, record_id: str, role: str) -> Path | None:
    matches = sorted(materials.glob(f"{record_id}_{role}_0.*"))
    return matches[0] if matches else None


def supported_chinese_font() -> Path:
    for candidate in (Path("C:/Windows/Fonts/simhei.ttf"), Path("C:/Windows/Fonts/simsun.ttc")):
        if candidate.exists():
            return candidate
    raise ValueError("No supported Chinese font found. Install SimHei or provide a compatible font before generating the PDF.")


def convert_pdf_to_jpeg(source: Path, output: Path, dpi: int = 160) -> Path:
    import fitz
    from PIL import Image

    document = fitz.open(source)
    try:
        pixmap = document[0].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), alpha=False)
        Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples).save(output, "JPEG", quality=90)
    finally:
        document.close()
    return output


def image_for(path: Path | None, image_dir: Path, record_id: str, role: str) -> Path | None:
    if path is None:
        return None
    if path.suffix.lower() == ".pdf":
        return convert_pdf_to_jpeg(path, image_dir / f"{record_id}_{role}.jpg")
    return path


def draw_panel(canvas: Any, image_path: Path | None, box: tuple[float, float, float, float], label: str, missing_note: str) -> None:
    from PIL import Image
    from reportlab.lib import colors
    from reportlab.lib.units import mm

    x, y, width, height = box
    padding = 4 * mm
    canvas.setStrokeColor(colors.HexColor("#e8e8e8"))
    canvas.setLineWidth(0.5)
    canvas.rect(x, y, width, height)
    canvas.setFillColor(colors.HexColor("#8a8a8a"))
    canvas.setFont("ReimbursementChinese", 7.5)
    canvas.drawString(x + 2 * mm, y + height - 5 * mm, label)
    if image_path is None:
        canvas.setFont("ReimbursementChinese", 9)
        canvas.setFillColor(colors.HexColor("#aaaaaa"))
        canvas.drawCentredString(x + width / 2, y + height / 2, missing_note)
        return
    with Image.open(image_path) as image:
        inner_width, inner_height = width - 2 * padding, height - 2 * padding
        scale = min(inner_width / image.width, inner_height / image.height)
        draw_width, draw_height = image.width * scale, image.height * scale
    canvas.drawImage(
        str(image_path),
        x + padding + (inner_width - draw_width) / 2,
        y + padding + (inner_height - draw_height) / 2,
        draw_width,
        draw_height,
        preserveAspectRatio=True,
        mask="auto",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--materials", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--temp-dir", type=Path, help="临时图片目录；标准布局建议使用工作区 tmp/<类型>/evidence-images")
    parser.add_argument("--missing-notes", type=Path, help="JSON mapping of record_id to role-to-approved explanation")
    args = parser.parse_args()

    manifest = load_json(args.manifest)
    records = manifest.get("records") if isinstance(manifest, dict) else None
    if not isinstance(records, list) or not records:
        raise ValueError("Manifest has no records to render")
    missing_notes = load_json(args.missing_notes) if args.missing_notes else {}
    if not isinstance(missing_notes, dict):
        raise ValueError("missing-notes must be a JSON object")

    try:
        import fitz  # noqa: F401
        from pypdf import PdfReader, PdfWriter
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
        from reportlab.pdfgen import canvas
    except ImportError as exc:
        raise ValueError("Missing dependency. Install reportlab, pypdf, pymupdf, and Pillow.") from exc

    pdfmetrics.registerFont(TTFont("ReimbursementChinese", str(supported_chinese_font())))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    if args.temp_dir:
        image_dir = args.temp_dir
    elif args.out.parent.name.lower() == "output":
        image_dir = args.out.parent.parent / "tmp" / args.out.stem / "evidence-images"
    else:
        image_dir = args.out.parent / "tmp" / "evidence-images"
    image_dir.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    page_width, page_height = A4
    margin, header_height, gap = 10 * mm, 18 * mm, 4 * mm
    content_width = page_width - 2 * margin
    panel_height = (page_height - 2 * margin - header_height - gap) / 2
    lower_width = (content_width - gap) / 2

    for page_number, record in enumerate(records, start=1):
        if not isinstance(record, dict):
            raise ValueError("Manifest includes an invalid record")
        record_id = str(record.get("record_id", "")).strip()
        if not record_id:
            raise ValueError("Manifest record has no record_id")
        sequence_value = str(record.get("sequence", "")).strip() or str(page_number)
        buffer = io.BytesIO()
        page = canvas.Canvas(buffer, pagesize=A4)
        header_baseline = page_height - margin - header_height
        page.setStrokeColor(colors.HexColor("#e0e0e0"))
        page.line(margin, header_baseline, page_width - margin, header_baseline)
        page.setFillColor(colors.HexColor("#222222"))
        page.setFont("ReimbursementChinese", 13)
        page.drawString(margin, header_baseline + 7 * mm, str(record.get("title", "")))
        page.setFillColor(colors.HexColor("#555555"))
        page.setFont("ReimbursementChinese", 11)
        page.drawRightString(page_width - margin, header_baseline + 7 * mm, f"金额：{record.get('amount', '')} 元")
        page.setFillColor(colors.HexColor("#8a8a8a"))
        page.setFont("ReimbursementChinese", 8)
        page.drawString(
            margin,
            header_baseline + 2.5 * mm,
            f"{sequence_value}    {str(record.get('category', '')).strip()}",
        )

        invoice_box = (margin, margin + panel_height + gap, content_width, panel_height)
        order_box = (margin, margin, lower_width, panel_height)
        payment_box = (margin + lower_width + gap, margin, lower_width, panel_height)
        notes_for_record = missing_notes.get(record_id, {})
        if not isinstance(notes_for_record, dict):
            raise ValueError(f"missing-notes for {record_id} must be an object")
        for role, label, box in (
            ("invoice", "发票", invoice_box),
            ("order", "订单凭证", order_box),
            ("payment", "付款凭证", payment_box),
        ):
            local = image_for(find_material(args.materials, record_id, role), image_dir, record_id, role)
            note = str(notes_for_record.get(role, "")).strip()
            if local is None and not note:
                raise ValueError(f"{record_id}: {role} is missing. Get user approval and supply --missing-notes, or exclude the record.")
            draw_panel(page, local, box, label, note)
        page.save()
        buffer.seek(0)
        writer.add_page(PdfReader(buffer).pages[0])

    with args.out.open("wb") as output:
        writer.write(output)
    print(f"Created {args.out} with {len(records)} page(s).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
