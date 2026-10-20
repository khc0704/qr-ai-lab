"""Pure helpers of the vision module (no torch needed)."""

from __future__ import annotations

import pytest

pytest.importorskip("torch")

from trainer.models.vision import _heatmap_name


def test_heatmap_names_come_from_the_relative_path():
    seen: set[str] = set()
    assert _heatmap_name("a/x.jpg", seen) == "a__x.png"
    assert _heatmap_name("b/x.jpg", seen) == "b__x.png"
    assert _heatmap_name("b\\x.tif", seen) == "b__x_2.png"  # same flattened name → counter
    assert _heatmap_name("../../x.jpg", seen) == "x.png"
    assert _heatmap_name("", seen) == "image.png"


def test_yolo_augment_kwargs_sets_every_knob_explicitly():
    from trainer.models.vision import YOLO_AUGMENT, yolo_augment_kwargs

    on = yolo_augment_kwargs(["hflip", "crop", "brightness"])
    assert on["fliplr"] == 0.5 and on["scale"] == 0.5 and on["translate"] == 0.1 and on["hsv_v"] == 0.4
    assert on["flipud"] == 0.0 and on["degrees"] == 0.0
    off = yolo_augment_kwargs([])
    assert set(off) == {k for knobs in YOLO_AUGMENT.values() for k in knobs} and all(v == 0.0 for v in off.values())
    assert yolo_augment_kwargs("vflip,rotate90")["flipud"] == 0.5 and yolo_augment_kwargs(True)["fliplr"] == 0.5
    # an op YOLO has no knob for is ignored (warned), not an error
    assert yolo_augment_kwargs(["contrast", "hflip"])["fliplr"] == 0.5
    with pytest.raises(ValueError):
        yolo_augment_kwargs(["sepia"])
