"""Untrusted names never escape the job dirs: MinIO keys, URL / Content-Disposition names, zip members."""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pytest
from PIL import Image

from trainer import fetch
from trainer.data.image import materialize
from trainer.paths import safe_filename, safe_join


@dataclass
class _Obj:
    object_name: str
    size: int = 3
    is_dir: bool = False


class _FakeMinio:
    objects: list[_Obj] = []
    downloaded: list[tuple[str, str]] = []

    def __init__(self, *a, **kw) -> None:
        pass

    def list_objects(self, bucket, prefix="", recursive=True):
        return [o for o in self.objects if o.object_name.startswith(prefix)]

    def fget_object(self, bucket, key, path):
        Path(path).write_bytes(b"abc")
        self.downloaded.append((key, path))


@pytest.fixture
def minio(monkeypatch):
    import minio

    _FakeMinio.objects, _FakeMinio.downloaded = [], []
    monkeypatch.setattr(minio, "Minio", _FakeMinio)
    return _FakeMinio


def _ds(prefix: str = "lots/wat/") -> dict:
    return {"kind": "minio", "endpoint": "http://minio.local:9000", "bucket": "b", "object_path": prefix}


def test_minio_objects_land_under_the_input_dir(tmp_path, minio):
    minio.objects = [_Obj("lots/wat/a.csv"), _Obj("lots/wat/sub/b.csv"), _Obj("lots/wat/dir/", is_dir=True)]
    fetch.fetch_data_source(_ds(), tmp_path / "input", lambda f: None)
    assert (tmp_path / "input" / "a.csv").read_bytes() == b"abc" and (tmp_path / "input" / "sub" / "b.csv").exists()


def test_minio_traversal_key_fails_before_any_download(tmp_path, minio):
    minio.objects = [_Obj("lots/wat/a.csv"), _Obj("lots/wat/../../model_zoo/x.pt")]
    with pytest.raises(ValueError, match=r"model_zoo/x\.pt"):
        fetch.fetch_data_source(_ds(), tmp_path / "input", lambda f: None)
    assert minio.downloaded == [] and not (tmp_path / "model_zoo").exists()
    minio.objects = [_Obj("lots/wat/a.csv"), _Obj("lots/wat//etc/passwd")]
    with pytest.raises(ValueError, match="passwd"):
        fetch.fetch_data_source(_ds(), tmp_path / "input", lambda f: None)


def test_download_name_from_url_and_content_disposition():
    assert fetch.download_name("http://h/x/data.csv?sig=1") == "data.csv"
    assert fetch.download_name("http://h/") == "data"
    assert fetch.download_name("http://h/x", 'attachment; filename="../../evil.sh"') == "evil.sh"
    assert fetch.download_name("http://h/x", "attachment; filename*=UTF-8''%E5%85%89%E8%AD%9C.csv") == "光譜.csv"
    assert fetch.download_name("http://h/x", "attachment; filename=/etc/passwd") == "passwd"
    assert safe_filename("..") == "data" and safe_filename("a\\b\\c.txt") == "c.txt"


def test_url_download_uses_safe_name(tmp_path, monkeypatch):
    import httpx

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, content=b"1,2\n", headers={"content-disposition": 'attachment; filename="../../x.csv"'}
        )

    transport = httpx.MockTransport(handler)
    real = httpx.Client

    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=transport, **kw))
    fetch.fetch_data_source({"kind": "url", "url": "http://h/d"}, tmp_path / "input", lambda f: None)
    assert (tmp_path / "input" / "x.csv").read_bytes() == b"1,2\n" and not (tmp_path / "x.csv").exists()


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("L", (8, 8), 7).save(buf, format="PNG")
    return buf.getvalue()


def test_zip_with_traversal_entry_is_refused(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    with zipfile.ZipFile(input_dir / "imgs.zip", "w") as z:
        z.writestr("good/a.png", _png())
        z.writestr("../../escape.png", _png())
    with pytest.raises(ValueError, match=r"escape\.png"):
        materialize(input_dir, tmp_path / "work")
    assert not (tmp_path / "escape.png").exists() and not list((tmp_path / "work").rglob("*.png"))


def test_zip_extraction_keeps_layout(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()
    with zipfile.ZipFile(input_dir / "imgs.zip", "w") as z:
        z.writestr("good/", "")
        z.writestr("good/a.png", _png())
        z.writestr("bad\\b.png", _png())  # windows separators are normalised
    root = materialize(input_dir, tmp_path / "work")
    assert (root / "good" / "a.png").exists() and (root / "bad" / "b.png").exists()
    assert safe_join(root, "good/a.png") == root / "good" / "a.png"
