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


def test_augment_image_runs_every_op():
    import numpy as np
    from PIL import Image

    from trainer.models.vision import AUGMENT_OPS, augment_image, parse_augment

    im = Image.fromarray(np.random.default_rng(0).integers(0, 255, size=(40, 60, 3), dtype=np.uint8), "RGB")
    ops = parse_augment(list(AUGMENT_OPS))
    assert ops == AUGMENT_OPS
    seen_rotated = seen_cropped = False
    for seed in range(40):  # each op fires with p = 0.5: a few dozen draws exercise every branch
        out = augment_image(im, ops, np.random.default_rng(seed))
        assert out.mode == "RGB" and all(1 <= v <= 60 for v in out.size)
        seen_rotated |= out.size[0] < out.size[1] and out.size in ((40, 60), (32, 48))
        seen_cropped |= out.size not in ((60, 40), (40, 60))
    assert seen_rotated and seen_cropped
    assert augment_image(im, ()).size == (60, 40)
