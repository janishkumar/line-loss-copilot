import hashlib
import json
from pathlib import Path

import pytest

from linecopilot.ingest import download as dl
from linecopilot.ingest.download import ChecksumError, download_all, http_fetch
from linecopilot.ingest.sources import Source

CONTENT = b"a,b\n1,2\n"
MD5 = hashlib.md5(CONTENT).hexdigest()
SHA = hashlib.sha256(CONTENT).hexdigest()


def _src(md5: str = MD5) -> Source:
    return Source("ds", "f.csv", "https://example.test/f.csv", md5, len(CONTENT))


@pytest.fixture
def one_source(monkeypatch):
    monkeypatch.setattr(dl, "SOURCES", [_src()])


def _fake(calls):
    def fetch(url: str, dest: Path) -> None:
        calls.append(url)
        dest.write_bytes(CONTENT)

    return fetch


def test_writes_manifest_with_sha256(tmp_path, one_source):
    calls: list[str] = []
    manifest = download_all(tmp_path, fetch=_fake(calls))
    assert calls == ["https://example.test/f.csv"]
    assert (tmp_path / "raw" / "ds" / "f.csv").read_bytes() == CONTENT
    data = json.loads((tmp_path / "checksums.json").read_text())
    entry = data["files"][0]
    assert entry["sha256"] == SHA
    assert entry["md5"] == MD5
    assert entry["size"] == len(CONTENT)
    assert {"dataset", "filename", "url", "downloaded_at"} <= entry.keys()
    assert len(manifest.files) == 1


def test_skips_existing_matching_file(tmp_path, one_source):
    path = tmp_path / "raw" / "ds" / "f.csv"
    path.parent.mkdir(parents=True)
    path.write_bytes(CONTENT)
    calls: list[str] = []
    download_all(tmp_path, fetch=_fake(calls))
    assert calls == []
    assert json.loads((tmp_path / "checksums.json").read_text())["files"][0]["sha256"] == SHA


def test_mismatch_raises_and_removes_file(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "SOURCES", [_src(md5="0" * 32)])
    with pytest.raises(ChecksumError):
        download_all(tmp_path, fetch=_fake([]))
    assert not (tmp_path / "raw" / "ds" / "f.csv").exists()
    assert not list((tmp_path / "raw" / "ds").glob("*.part"))


def test_user_agent_has_no_email():
    assert dl.request_headers() == {"User-Agent": "line-loss-copilot/0.1"}
    assert callable(http_fetch)


def test_manifest_keeps_entries_from_other_downloaders(tmp_path, one_source):
    (tmp_path / "checksums.json").write_text(
        json.dumps({"files": [{"dataset": "visa", "filename": "x.tar"}, {"dataset": "ds"}]})
    )
    download_all(tmp_path, fetch=_fake([]))
    files = json.loads((tmp_path / "checksums.json").read_text())["files"]
    assert {"dataset": "visa", "filename": "x.tar"} in files
    assert sum(e["dataset"] == "ds" for e in files) == 1
