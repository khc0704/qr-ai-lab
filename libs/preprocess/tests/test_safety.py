"""Untrusted names (zip members, object keys), zip bombs in previews, catastrophic regexes, bounded align state."""

from __future__ import annotations

import io
import zipfile

import numpy as np
import pytest
from PIL import Image

from qrlab_preprocess import Pipeline
from qrlab_preprocess.paths import safe_join, safe_relpath
from qrlab_preprocess.preview import MAX_ZIP_ENTRY_BYTES, check_zip_entry, run_preview
from qrlab_preprocess.process import process_image_stream, run_full
from qrlab_preprocess.text import check_regex


@pytest.mark.parametrize("bad", ["", ".", "..", "../x.png", "a/../../x.png", "/etc/passwd", "C:\\x\\y.png", "a\x00b"])
def test_safe_relpath_rejects_escapes(bad):
    with pytest.raises(ValueError):
        safe_relpath(bad)


def test_safe_relpath_accepts_nested_and_normalises():
    assert safe_relpath("a/b/c.png").as_posix() == "a/b/c.png"
    assert safe_relpath("./a//b\\c.png").as_posix() == "a/b/c.png"


def test_safe_join_stays_under_root(tmp_path):
    assert safe_join(tmp_path, "sub/img.png") == tmp_path / "sub" / "img.png"
    with pytest.raises(ValueError, match=r"x\.png"):
        safe_join(tmp_path, "../x.png")
    # a symlinked parent pointing outside the root is caught by the resolve check
    outside = tmp_path.parent / "outside-dir"
    outside.mkdir(exist_ok=True)
    (tmp_path / "link").symlink_to(outside)
    with pytest.raises(ValueError, match="逃出"):
        safe_join(tmp_path, "link/evil.png")


def _png(w: int = 16, h: int = 12, color: int = 100) -> bytes:
    buf = io.BytesIO()
    Image.new("L", (w, h), color).save(buf, format="PNG")
    return buf.getvalue()


def test_run_full_rejects_traversal_zip_entry(tmp_path):
    zpath = tmp_path / "evil.zip"
    with zipfile.ZipFile(zpath, "w") as z:
        z.writestr("ok/a.png", _png())
        z.writestr("../../evil.png", _png())
    with pytest.raises(ValueError, match=r"evil\.png"):
        run_full("IMAGE", zpath, "image_folder", [{"op": "image.grayscale"}], tmp_path / "out")
    assert not (tmp_path.parent / "evil.png").exists()


def test_process_image_stream_fits_on_first_sample_then_streams():
    images = [(f"i{k}.png", Image.new("L", (16, 16), k * 10)) for k in range(10)]
    pipe = Pipeline.from_spec("IMAGE", [{"op": "image.align"}, {"op": "image.resize", "params": {"width": 8}}])
    out = list(process_image_stream(pipe, iter(images), fit_sample=3, batch=4))
    assert [n for n, _ in out] == [n for n, _ in images] and all(im.size == (8, 8) for _, im in out)
    assert pipe.ops[0].state["size"] == [16, 16]  # fitted on the first batch only
    replay = Pipeline.from_json("IMAGE", pipe.to_json())
    again = list(process_image_stream(replay, iter(images[:2]), fit=False))
    assert len(again) == 2 and again[0][1].size == (8, 8)


def test_preview_rejects_oversized_zip_entry(tmp_path, monkeypatch):
    zpath = tmp_path / "bomb.zip"
    with zipfile.ZipFile(zpath, "w", compression=zipfile.ZIP_DEFLATED) as z:
        z.writestr("a/big.png", b"\0" * (2 * 2**20))  # 2 MB of zeros: ratio ≫ 100
        z.writestr("a/small.png", _png())
    with pytest.raises(ValueError, match="zip bomb"):
        run_preview("IMAGE", zpath, "image_folder", [{"op": "image.grayscale"}], sample=4)
    info = zipfile.ZipInfo("huge.png")
    info.file_size, info.compress_size = MAX_ZIP_ENTRY_BYTES + 1, MAX_ZIP_ENTRY_BYTES
    with pytest.raises(ValueError, match="超過預覽上限"):
        check_zip_entry(info)


@pytest.mark.parametrize("pattern", ["(a+)+", "(a*)*", "(a+)*", "(a*)+", "(a{2,})+", "(?:x|y+)*z", "((ab)+c)+"])
def test_regex_guard_rejects_nested_quantifiers(pattern):
    with pytest.raises(ValueError, match="巢狀量詞"):
        check_regex(pattern)
    with pytest.raises(ValueError):
        Pipeline.from_spec("TEXT", [{"op": "text.replace_regex", "params": {"pattern": pattern}}])


@pytest.mark.parametrize("pattern", [r"\s+", r"[0-9]{3,}", r"(abc)+", r"^(foo|bar)$", r"(\d+)-(\d+)", r"a+b*c?"])
def test_regex_guard_accepts_linear_patterns(pattern):
    check_regex(pattern)


def test_regex_guard_limits_length():
    with pytest.raises(ValueError, match="太長"):
        check_regex("a" * 201)


def test_align_reference_is_downsampled_to_work_size():
    big = Image.fromarray(np.random.default_rng(0).integers(0, 255, (400, 600), dtype=np.uint8), mode="L")
    pipe = Pipeline.from_spec("IMAGE", [{"op": "image.align", "params": {"work_size": 128}}])
    out = pipe.fit_transform([big, big])
    assert out[0].size == (600, 400) and pipe.ops[0].state["size"] == [128, 85]
    state = pipe.to_json()
    assert len(state[0]["state"]["reference"]["__png__"]) < 40_000
    with pytest.raises(ValueError, match="參考影像"):
        Pipeline.from_json("IMAGE", [{"op": "image.align", "params": {}}]).transform([big])
