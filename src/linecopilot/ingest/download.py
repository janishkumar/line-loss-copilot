"""Download the source datasets and write a checksum manifest.

A file whose md5 already matches the pinned value is not fetched again.
"""

import hashlib
import json
import os
import shutil
import sys
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from linecopilot.config import get_settings
from linecopilot.ingest.sources import SOURCES

USER_AGENT = "line-loss-copilot/0.1"


class ChecksumError(RuntimeError):
    pass


@dataclass
class Manifest:
    files: list[dict] = field(default_factory=list)


def request_headers() -> dict[str, str]:
    return {"User-Agent": USER_AGENT}


def http_fetch(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers=request_headers())
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as out:
        shutil.copyfileobj(resp, out, length=1 << 20)


def _digests(path: Path) -> tuple[str, str]:
    md5, sha = hashlib.md5(), hashlib.sha256()  # noqa: S324 (md5 matches Zenodo's published sums)
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            md5.update(chunk)
            sha.update(chunk)
    return md5.hexdigest(), sha.hexdigest()


def download_all(
    data_dir: Path,
    fetch: Callable[[str, Path], None] = http_fetch,
    log: Callable[[str], None] = lambda _msg: None,
) -> Manifest:
    manifest = Manifest()
    for src in SOURCES:
        dest = data_dir / "raw" / src.dataset / src.filename
        dest.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(UTC).isoformat(timespec="seconds")
        cached = False
        if dest.exists():
            md5, sha = _digests(dest)
            cached = md5 == src.md5
        if cached:
            stamp = datetime.fromtimestamp(dest.stat().st_mtime, UTC).isoformat(timespec="seconds")
            log(f"{src.dataset}/{src.filename}: ok (cached)")
        else:
            tmp = dest.with_name(dest.name + ".part")
            try:
                fetch(src.url, tmp)
                md5, sha = _digests(tmp)
                if md5 != src.md5:
                    raise ChecksumError(
                        f"{src.dataset}/{src.filename}: md5 {md5} != expected {src.md5}"
                    )
                os.replace(tmp, dest)
            finally:
                tmp.unlink(missing_ok=True)
            log(f"{src.dataset}/{src.filename}: ok (downloaded)")
        manifest.files.append(
            {
                "dataset": src.dataset,
                "filename": src.filename,
                "url": src.url,
                "md5": md5,
                "sha256": sha,
                "size": dest.stat().st_size,
                "downloaded_at": stamp,
            }
        )
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "checksums.json").write_text(json.dumps({"files": manifest.files}, indent=2) + "\n")
    return manifest


def main() -> int:
    try:
        download_all(get_settings().data_dir, log=print)
    except ChecksumError as exc:
        print(f"checksum error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
