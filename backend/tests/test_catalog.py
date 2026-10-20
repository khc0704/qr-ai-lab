"""model_catalog.yaml is the contract between backend, trainer and UI: keep it internally consistent."""

from __future__ import annotations

import re
from pathlib import Path

from app.catalog import loader

TRAINER_REGISTRY = Path(__file__).resolve().parents[2] / "trainer" / "trainer" / "models" / "registry.py"


def test_families_reference_known_data_types_and_tasks():
    cat = loader.load_catalog()
    for fid, fam in cat["families"].items():
        assert fam["supports"], fid
        for dt, tasks in fam["supports"].items():
            assert dt in cat["data_types"], (fid, dt)
            for t in tasks:
                assert t in cat["tasks"], (fid, t)
        assert fam["resources"]["gpu"] in ("none", "optional", "required"), fid
        assert fam["inference_modes"], fid
        for w in fam.get("weights", []):
            assert {"id", "file", "source", "license"} <= set(w), (fid, w)


def test_automl_candidates_support_their_tasks():
    cat = loader.load_catalog()
    for entry in cat["automl"]:
        for t in entry["tasks"]:
            for c in entry["candidates"]:
                assert loader.supports(c, entry["data_type"], t), (entry["data_type"], t, c)
        assert entry["budget"]["max_trials"] >= 1
    search = loader.automl_search("TABULAR", "classification", {"row_count": 500})
    assert search["candidates"][:2] == ["tabular.tabpfn", "tabular.random_forest"] and search["metric"] == "f1_macro"
    big = loader.automl_search("TABULAR", "classification", {"row_count": 20_000})
    assert "tabular.tabpfn" not in big["candidates"]
    search = loader.automl_search("TABULAR", "regression", {"row_count": 100_000})
    assert "tabular.svm" not in search["candidates"] and search["direction"] == "minimize"


def test_trainer_registry_matches_catalog():
    ids = set(re.findall(r'^\s+"([a-z_]+\.[a-z_]+)": \(', TRAINER_REGISTRY.read_text(encoding="utf-8"), re.M))
    assert ids == set(loader.load_catalog()["families"])


def test_required_weights_are_unique_and_public_catalog_hides_sources():
    weights = loader.required_weights()
    assert len({w["id"] for w in weights}) == len(weights)
    pub = loader.public_catalog()
    assert pub["families"]["vision.yolo"]["weights"] == [w["id"] for w in loader.family("vision.yolo")["weights"]]
    assert "source" not in str(pub["families"]["vision.yolo"]["weights"])
