#!/usr/bin/env python3
"""Download all required manifest attachments through the Lark media API.

Uses up to four workers while globally spacing download starts by at least a
quarter second. Each completed file is named with its record, role, and index
and verified by signature before it becomes part of the archive.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REQUIRED_ROLES = ("invoice", "order", "payment")


@dataclass(frozen=True)
class DownloadJob:
    record_id: str
    role: str
    index: int
    token: str

    @property
    def temporary_name(self) -> str:
        return f"{self.record_id}_{self.role}_{self.index}.download"


class StartRateLimiter:
    """Limit media-download starts without serializing the downloads."""

    def __init__(self, interval: float) -> None:
        self.interval = interval
        self._lock = threading.Lock()
        self._next_start = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delay = max(0.0, self._next_start - now)
            self._next_start = max(now, self._next_start) + self.interval
        if delay:
            time.sleep(delay)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        raise ValueError(f"Cannot read {path}: {exc}") from exc


def parse_field_ids(values: list[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for value in values:
        role, separator, field_id = value.partition("=")
        if not separator or role not in REQUIRED_ROLES or not field_id:
            raise ValueError("--field-id must be invoice=<field_id>, order=<field_id>, or payment=<field_id>")
        if role in result:
            raise ValueError(f"Duplicate field ID for {role}")
        result[role] = field_id
    missing = set(REQUIRED_ROLES) - set(result)
    if missing:
        raise ValueError(f"Missing --field-id values for: {', '.join(sorted(missing))}")
    return result


def jobs_from_manifest(manifest: dict[str, Any]) -> list[DownloadJob]:
    records = manifest.get("records")
    if not isinstance(records, list):
        raise ValueError("Manifest has no records array")
    jobs: list[DownloadJob] = []
    for record in records:
        if not isinstance(record, dict):
            raise ValueError("Manifest contains a non-object record")
        record_id = str(record.get("record_id", "")).strip()
        attachments = record.get("attachments")
        if not record_id or not isinstance(attachments, dict):
            raise ValueError("Manifest record has no record_id or attachments")
        for role in REQUIRED_ROLES:
            files = attachments.get(role)
            if not isinstance(files, list) or not files:
                raise ValueError(f"{record_id}: missing {role}")
            for index, file in enumerate(files):
                token = str(file.get("token", "")).strip() if isinstance(file, dict) else ""
                if not token:
                    raise ValueError(f"{record_id}: {role}[{index}] has no token")
                jobs.append(DownloadJob(record_id, role, index, token))
    return jobs


def extension_from_signature(path: Path) -> str:
    with path.open("rb") as stream:
        header = stream.read(32)
    if header.startswith(b"%PDF"):
        return ".pdf"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if header.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if header.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return ".tiff"
    if header.startswith(b"RIFF") and header[8:12] == b"WEBP":
        return ".webp"
    if header.startswith(b"PK\x03\x04"):
        return ".zip"
    if header[4:8] == b"ftyp" and header[8:12] in {b"heic", b"heix", b"hevc", b"hevx"}:
        return ".heic"
    raise ValueError(f"Cannot identify downloaded file type: {path.name}")


def download_one(
    job: DownloadJob,
    archive: Path,
    table_id: str,
    field_ids: dict[str, str],
    lark_cli: str,
    identity: str,
    limiter: StartRateLimiter,
) -> Path:
    temporary = archive / job.temporary_name
    if temporary.exists():
        raise ValueError(f"Temporary download already exists: {temporary}")

    attachment_map = {field_ids[job.role]: {job.record_id: [job.token]}}
    extra = json.dumps(
        {"bitablePerm": {"tableId": table_id, "attachments": attachment_map}},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    params = json.dumps({"extra": extra}, ensure_ascii=False, separators=(",", ":"))
    # lark-cli only accepts a relative output path inside its current directory.
    relative_output = f"./{archive.name}/{job.temporary_name}"
    command = [
        lark_cli,
        "api",
        "GET",
        f"/open-apis/drive/v1/medias/{job.token}/download",
        "--params",
        params,
        "--output",
        relative_output,
        "--as",
        identity,
    ]
    limiter.wait()
    result = subprocess.run(
        command,
        cwd=archive.parent,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode or not temporary.exists() or temporary.stat().st_size == 0:
        detail = (result.stdout + result.stderr).strip()
        raise ValueError(f"{job.record_id} {job.role}[{job.index}] download failed: {detail}")
    extension = extension_from_signature(temporary)
    target = archive / f"{job.record_id}_{job.role}_{job.index}{extension}"
    if target.exists():
        raise ValueError(f"Refusing to overwrite existing attachment: {target}")
    temporary.rename(target)
    return target


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--archive", type=Path, required=True, help="Existing attachment archive directory")
    parser.add_argument("--base-token", required=True)
    parser.add_argument("--table-id", required=True)
    parser.add_argument("--field-id", action="append", default=[], help="Repeat for invoice/order/payment, e.g. invoice=fldxxx")
    parser.add_argument("--as", dest="identity", choices=("user", "bot"), default="user")
    parser.add_argument("--workers", type=int, default=4, help="1-4 concurrent downloads (default: 4)")
    parser.add_argument("--min-interval", type=float, default=0.25, help="Minimum seconds between download starts (minimum: 0.25)")
    parser.add_argument("--lark-cli", default="lark-cli.cmd", help="lark-cli executable or command")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not 1 <= args.workers <= 4:
        raise ValueError("--workers must be between 1 and 4")
    if args.min_interval < 0.25:
        raise ValueError("--min-interval must be at least 0.25 seconds")
    archive = args.archive.resolve()
    if not archive.is_dir():
        raise ValueError(f"Archive directory does not exist: {archive}")
    field_ids = parse_field_ids(args.field_id)
    manifest = load_json(args.manifest)
    if not isinstance(manifest, dict):
        raise ValueError("Manifest must be a JSON object")
    jobs = jobs_from_manifest(manifest)
    if args.dry_run:
        print(f"Planned {len(jobs)} attachment download(s) with {args.workers} worker(s).")
        return 0

    limiter = StartRateLimiter(args.min_interval)
    completed: list[Path] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = [
            pool.submit(download_one, job, archive, args.table_id, field_ids, args.lark_cli, args.identity, limiter)
            for job in jobs
        ]
        for future in as_completed(futures):
            try:
                completed.append(future.result())
            except Exception:
                for pending in futures:
                    pending.cancel()
                raise
            if len(completed) % 10 == 0 or len(completed) == len(jobs):
                print(f"Downloaded {len(completed)}/{len(jobs)} attachment(s).")
    print(f"Downloaded and signature-verified {len(completed)} attachment(s).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
