"""VisA download, partial extraction and the official 1cls splits.

VisA (Amazon, CC BY 4.0). The S3 archive's ETag is multipart, so no md5 is published: the
download is checked against the known size and a sha256 is recorded in data/checksums.json.
Only the six food subsets are extracted.
"""

import csv
import hashlib
import json
import random
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from linecopilot.config import get_settings
from linecopilot.ingest.download import ChecksumError, request_headers

VISA_ARCHIVE_URL = "https://amazon-visual-anomaly.s3.us-west-2.amazonaws.com/VisA_20220922.tar"
VISA_ARCHIVE_NAME = "VisA_20220922.tar"
VISA_ARCHIVE_SIZE = 1_929_840_640
VISA_CSV_URL = "https://raw.githubusercontent.com/amazon-science/spot-diff/main/split_csv/1cls.csv"
VISA_CSV_NAME = "1cls.csv"
SUBSETS = ("cashew", "chewinggum", "fryum", "pipe_fryum", "macaroni1", "macaroni2")


class SizeError(RuntimeError):
    pass


class ChecksumMismatch(ChecksumError):
    pass


@dataclass(frozen=True)
class Sample:
    subset: str
    split: str  # "train" or "test" (official 1cls split)
    label: int  # 0 normal, 1 anomalous
    image_path: Path
    mask_path: Path | None
    image_id: str  # path relative to the VisA root, e.g. cashew/Data/Images/Normal/0836.JPG


def content_hash(path: Path) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def _safe_rel(rel: str) -> str:
    parts = rel.replace("\\", "/").split("/")
    if not rel or rel.startswith("/") or ".." in parts:
        raise ValueError(f"unsafe path in {VISA_CSV_NAME}: {rel!r}")
    return rel


def overlap(train: list[Sample], others: list[Sample]) -> list[Sample]:
    """Samples in `others` that also appear in `train`, by relative path or by content hash.

    Call it on every validation and test partition before fitting or fixing a threshold;
    a non-empty result means leakage.
    """
    paths = {s.image_id for s in train} | {str(s.image_path) for s in train}
    hashes = {content_hash(s.image_path) for s in train}
    return [
        s
        for s in others
        if s.image_id in paths or str(s.image_path) in paths or content_hash(s.image_path) in hashes
    ]


def load_split(root: Path, subset: str, split: str | None = None) -> list[Sample]:
    """Samples of one subset from <root>/1cls.csv; images and masks live under <root>."""
    root = Path(root)
    out: list[Sample] = []
    with open(root / VISA_CSV_NAME, newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if row["object"] != subset or (split is not None and row["split"] != split):
                continue
            image = root / _safe_rel(row["image"])
            if not image.exists():
                raise FileNotFoundError(f"{image} listed in {VISA_CSV_NAME} is missing")
            mask = None
            if row["label"] == "anomaly" and row["mask"]:
                mask = root / _safe_rel(row["mask"])
                if not mask.exists():
                    raise FileNotFoundError(f"{mask} listed in {VISA_CSV_NAME} is missing")
            out.append(
                Sample(
                    subset,
                    row["split"],
                    1 if row["label"] == "anomaly" else 0,
                    image,
                    mask,
                    row["image"],
                )
            )
    return out


def val_test_split(samples: list[Sample], seed: int = 0) -> tuple[list[Sample], list[Sample]]:
    """Stratified 50/50 split by label; the same input and seed always give the same split.

    Samples are ordered by image_id before shuffling so the result does not depend on row order.
    """
    rng = random.Random(seed)
    val: list[Sample] = []
    test: list[Sample] = []
    for label in (0, 1):
        group = sorted((s for s in samples if s.label == label), key=lambda s: s.image_id)
        rng.shuffle(group)
        half = len(group) // 2
        val.extend(group[:half])
        test.extend(group[half:])
    return val, test


def _member_target(name: str) -> tuple[str, ...] | None:
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if ".." in parts:
        return None
    for i in range(min(2, len(parts))):  # tolerate one wrapper folder
        if parts[i] in SUBSETS:
            return tuple(parts[i:])
    return None


def extract_subsets(
    tar_path: Path, out_dir: Path, log: Callable[[str], None] = lambda _m: None
) -> int:
    """Extract only the six subsets (regular files) into out_dir; returns files newly written."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = 0
    with tarfile.open(tar_path, "r|") as tf:  # stream: never seeks, never loads the whole tar
        for member in tf:
            if not member.isfile():
                continue
            parts = _member_target(member.name)
            if parts is None or len(parts) < 2:  # a subset is a directory, never a file
                continue
            dest = out_dir.joinpath(*parts)
            if dest.exists() and dest.stat().st_size == member.size:
                continue
            src = tf.extractfile(member)
            if src is None:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_name(dest.name + ".part")
            with src, open(tmp, "wb") as fh:
                shutil.copyfileobj(src, fh, length=1 << 20)
            tmp.replace(dest)
            written += 1
            if written % 2000 == 0:
                log(f"extracted {written} files")
    return written


def http_fetch_resumable(url: str, dest: Path, retries: int = 5) -> None:
    """Stream to dest, resuming from a partial file with a Range request when it exists."""
    for attempt in range(retries):
        have = dest.stat().st_size if dest.exists() else 0
        headers = request_headers()
        if have:
            headers["Range"] = f"bytes={have}-"
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                mode = "ab" if have and resp.status == 206 else "wb"
                with open(dest, mode) as out:
                    shutil.copyfileobj(resp, out, length=1 << 20)
            return
        except urllib.error.HTTPError as exc:
            if exc.code == 416:  # already complete
                return
            raise
        except (urllib.error.URLError, TimeoutError, ConnectionError):
            if attempt == retries - 1:
                raise
            time.sleep(2**attempt)


def _merge_manifest(data_dir: Path, entries: list[dict]) -> None:
    path = data_dir / "checksums.json"
    existing: list[dict] = []
    if path.exists():
        existing = json.loads(path.read_text()).get("files", [])
    keys = {(e["dataset"], e["filename"]) for e in entries}
    kept = [e for e in existing if (e.get("dataset"), e.get("filename")) not in keys]
    path.write_text(json.dumps({"files": kept + entries}, indent=2) + "\n")


def _recorded_sha(data_dir: Path, filename: str) -> str | None:
    path = data_dir / "checksums.json"
    if not path.exists():
        return None
    for e in json.loads(path.read_text()).get("files", []):
        if e.get("dataset") == "visa" and e.get("filename") == filename:
            return e.get("sha256")
    return None


def download_visa(
    data_dir: Path,
    fetch: Callable[[str, Path], None] = http_fetch_resumable,
    log: Callable[[str], None] = lambda _m: None,
) -> list[dict]:
    """Fetch the archive and the 1cls csv into data/raw/visa/ and record sha256 and size.

    A second run verifies the files against the manifest instead of fetching again.
    """
    data_dir = Path(data_dir)
    entries = []
    for url, name, size in (
        (VISA_ARCHIVE_URL, VISA_ARCHIVE_NAME, VISA_ARCHIVE_SIZE),
        (VISA_CSV_URL, VISA_CSV_NAME, None),
    ):
        dest = data_dir / "raw" / "visa" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        recorded = _recorded_sha(data_dir, name)
        if dest.exists() and (size is None or dest.stat().st_size == size) and recorded:
            sha = content_hash(dest)
            if sha != recorded:
                raise ChecksumMismatch(f"visa/{name}: sha256 {sha} != recorded {recorded}")
            stamp = datetime.fromtimestamp(dest.stat().st_mtime, UTC).isoformat(timespec="seconds")
            log(f"visa/{name}: ok (verified)")
        else:
            tmp = dest.with_name(name + ".part")  # kept on a dropped connection, so it resumes
            if dest.exists():
                dest.unlink()
            fetch(url, tmp)
            if size is not None and tmp.stat().st_size != size:
                got = tmp.stat().st_size
                tmp.unlink(missing_ok=True)
                raise SizeError(f"visa/{name}: {got} bytes, expected {size}")
            sha = content_hash(tmp)
            tmp.replace(dest)
            stamp = datetime.now(UTC).isoformat(timespec="seconds")
            log(f"visa/{name}: ok (downloaded)")
        entries.append(
            {
                "dataset": "visa",
                "filename": name,
                "url": url,
                "sha256": sha,
                "size": dest.stat().st_size,
                "downloaded_at": stamp,
            }
        )
    _merge_manifest(data_dir, entries)
    return entries


def main() -> int:
    data_dir = get_settings().data_dir
    try:
        download_visa(data_dir, log=print)
    except (ChecksumError, SizeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    tar = data_dir / "raw" / "visa" / VISA_ARCHIVE_NAME
    root = data_dir / "visa"
    n = extract_subsets(tar, root, log=print)
    shutil.copyfile(data_dir / "raw" / "visa" / VISA_CSV_NAME, root / VISA_CSV_NAME)
    print(f"extracted {n} new files into {root}")
    for sub in SUBSETS:
        tr, te = load_split(root, sub, "train"), load_split(root, sub, "test")
        print(f"{sub}: train {len(tr)}, test {len(te)} ({sum(s.label for s in te)} anomalous)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
