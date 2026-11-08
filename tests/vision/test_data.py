import csv
import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest
from PIL import Image

from linecopilot.vision import data as vd
from linecopilot.vision.data import (
    SUBSETS,
    Sample,
    content_hash,
    download_visa,
    extract_subsets,
    load_split,
    val_test_split,
)


def _png(color: int, size: int = 8) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (size, size), (color, color, color)).save(buf, format="PNG")
    return buf.getvalue()


def _build_tree(root: Path, subset: str = "cashew", dup: bool = True) -> None:
    """Mirror the VisA layout: <subset>/Data/Images/{Normal,Anomaly}/N.JPG and Masks/Anomaly."""
    rows = []
    n = 0

    def add(split: str, label: str, color: int) -> None:
        nonlocal n
        folder = "Normal" if label == "normal" else "Anomaly"
        rel = f"{subset}/Data/Images/{folder}/{n:04d}.JPG"
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_bytes(_png(color))
        mask = ""
        if label == "anomaly":
            mask = f"{subset}/Data/Masks/Anomaly/{n:04d}.png"
            (root / mask).parent.mkdir(parents=True, exist_ok=True)
            (root / mask).write_bytes(_png(255))
        rows.append([subset, split, label, rel, mask])
        n += 1

    for i in range(6):
        add("train", "normal", 10 + i)
    for i in range(4):
        add("test", "normal", 100 + i)
    for i in range(4):
        add("test", "anomaly", 200 + i)
    if dup:
        # a test normal whose pixels equal a train normal, under a different path
        rel = f"{subset}/Data/Images/Normal/{n:04d}.JPG"
        (root / rel).write_bytes(_png(10))
        rows.append([subset, "test", "normal", rel, ""])
    with open(root / "1cls.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["object", "split", "label", "image", "mask"])
        w.writerows(rows)


@pytest.fixture
def tree(tmp_path):
    _build_tree(tmp_path)
    return tmp_path


def test_load_split_parses_rows(tree):
    train = load_split(tree, "cashew", split="train")
    test = load_split(tree, "cashew", split="test")
    assert len(train) == 6 and all(s.label == 0 and s.mask_path is None for s in train)
    assert len(test) == 9
    anomalies = [s for s in test if s.label == 1]
    assert len(anomalies) == 4
    assert all(s.mask_path is not None and s.mask_path.exists() for s in anomalies)
    s = train[0]
    assert isinstance(s, Sample) and s.subset == "cashew" and s.split == "train"
    assert s.image_path.exists() and s.image_id == "cashew/Data/Images/Normal/0000.JPG"


def test_load_split_default_returns_all_and_unknown_subset_empty(tree):
    assert len(load_split(tree, "cashew")) == 15
    assert load_split(tree, "fryum") == []


def test_load_split_rejects_missing_file(tree):
    (tree / "cashew/Data/Images/Normal/0000.JPG").unlink()
    with pytest.raises(FileNotFoundError):
        load_split(tree, "cashew")


def test_val_test_split_stratified_deterministic_disjoint(tree):
    test = load_split(tree, "cashew", split="test")
    val, tst = val_test_split(test, seed=0)
    assert set(map(id, val)).isdisjoint(map(id, tst))
    assert len(val) + len(tst) == len(test)
    for label in (0, 1):
        v = sum(s.label == label for s in val)
        t = sum(s.label == label for s in tst)
        assert abs(v - t) <= 1
    val2, tst2 = val_test_split(test, seed=0)
    assert [s.image_id for s in val] == [s.image_id for s in val2]
    assert [s.image_id for s in tst] == [s.image_id for s in tst2]
    val3, _ = val_test_split(test, seed=1)
    assert [s.image_id for s in val] != [s.image_id for s in val3]


def test_val_test_split_official_sizes():
    # 50 normal + 100 anomalous -> 25+50 val, 25+50 test; macaroni 100+100 -> 50+50
    def mk(n_norm, n_anom):
        out = []
        for i in range(n_norm):
            out.append(Sample("s", "test", 0, Path(f"n{i}"), None, f"n{i}"))
        for i in range(n_anom):
            out.append(Sample("s", "test", 1, Path(f"a{i}"), Path(f"m{i}"), f"a{i}"))
        return out

    val, tst = val_test_split(mk(50, 100))
    assert (len(val), len(tst)) == (75, 75)
    assert sum(s.label for s in val) == 50
    val, tst = val_test_split(mk(100, 100))
    assert (len(val), len(tst)) == (100, 100)


def test_train_test_disjoint_by_path_and_planted_duplicate_detected(tree):
    train = load_split(tree, "cashew", split="train")
    test = load_split(tree, "cashew", split="test")
    assert {s.image_id for s in train}.isdisjoint({s.image_id for s in test})
    train_hashes = {content_hash(s.image_path) for s in train}
    dups = [s for s in test if content_hash(s.image_path) in train_hashes]
    assert len(dups) == 1 and dups[0].label == 0


def test_content_hash_is_sha256_of_bytes(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"abc")
    assert content_hash(p) == hashlib.sha256(b"abc").hexdigest()


def _tar(path: Path, members: dict[str, bytes], prefix: str = "") -> None:
    with tarfile.open(path, "w") as tf:
        for name, data in members.items():
            info = tarfile.TarInfo(prefix + name)
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))


def test_extract_picks_only_six_subsets(tmp_path):
    members = {}
    for sub in [*SUBSETS, "candle", "capsules", "pcb1", "macaroni3"]:
        members[f"{sub}/Data/Images/Normal/0.JPG"] = sub.encode()
    members["split_csv/1cls.csv"] = b"object,split,label,image,mask\n"
    members["README.txt"] = b"x"
    tar = tmp_path / "v.tar"
    _tar(tar, members)
    out = tmp_path / "out"
    n = extract_subsets(tar, out)
    assert n == 6
    assert {p.name for p in out.iterdir()} == set(SUBSETS)
    assert (out / "cashew/Data/Images/Normal/0.JPG").read_bytes() == b"cashew"


def test_extract_handles_leading_dot_slash_prefix_and_is_idempotent(tmp_path):
    members = {f"{s}/Data/Images/Normal/0.JPG": b"x" for s in SUBSETS}
    tar = tmp_path / "v.tar"
    _tar(tar, members, prefix="./")
    out = tmp_path / "out"
    assert extract_subsets(tar, out) == 6
    assert extract_subsets(tar, out) == 0  # nothing new
    assert {p.name for p in out.iterdir()} == set(SUBSETS)


def test_extract_refuses_path_escape(tmp_path):
    tar = tmp_path / "v.tar"
    _tar(tar, {"cashew/../../evil.txt": b"x"})
    out = tmp_path / "out"
    assert extract_subsets(tar, out) == 0
    assert not (tmp_path / "evil.txt").exists()


def test_download_visa_records_sha256_and_verifies_second_run(tmp_path, monkeypatch):
    payload = b"tar-bytes" * 10
    csv_bytes = b"object,split,label,image,mask\n"
    monkeypatch.setattr(vd, "VISA_ARCHIVE_SIZE", len(payload))
    calls = []

    def fetch(url: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes(payload if url == vd.VISA_ARCHIVE_URL else csv_bytes)

    # a pre-existing entry from the other downloader must survive
    (tmp_path / "checksums.json").write_text(json.dumps({"files": [{"dataset": "brick"}]}))
    download_visa(tmp_path, fetch=fetch)
    manifest = json.loads((tmp_path / "checksums.json").read_text())["files"]
    visa = {e["filename"]: e for e in manifest if e["dataset"] == "visa"}
    assert visa["VisA_20220922.tar"]["sha256"] == hashlib.sha256(payload).hexdigest()
    assert visa["VisA_20220922.tar"]["size"] == len(payload)
    assert visa["1cls.csv"]["sha256"] == hashlib.sha256(csv_bytes).hexdigest()
    assert {"url", "downloaded_at"} <= visa["1cls.csv"].keys()
    assert any(e["dataset"] == "brick" for e in manifest)
    assert len(calls) == 2
    download_visa(tmp_path, fetch=fetch)  # verifies, does not re-fetch
    assert len(calls) == 2


def test_download_visa_wrong_size_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(vd, "VISA_ARCHIVE_SIZE", 999)

    def fetch(url: str, dest: Path) -> None:
        dest.write_bytes(b"short")

    with pytest.raises(vd.SizeError):
        download_visa(tmp_path, fetch=fetch)
    assert not (tmp_path / "raw" / "visa" / "VisA_20220922.tar").exists()


def test_download_visa_changed_file_fails_verification(tmp_path, monkeypatch):
    payload = b"abcd"
    monkeypatch.setattr(vd, "VISA_ARCHIVE_SIZE", len(payload))

    def fetch(url: str, dest: Path) -> None:
        dest.write_bytes(payload if url == vd.VISA_ARCHIVE_URL else b"c\n")

    download_visa(tmp_path, fetch=fetch)
    (tmp_path / "raw" / "visa" / "VisA_20220922.tar").write_bytes(b"abce")  # same size, corrupted
    with pytest.raises(vd.ChecksumMismatch):
        download_visa(tmp_path, fetch=fetch)
