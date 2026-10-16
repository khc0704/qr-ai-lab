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
