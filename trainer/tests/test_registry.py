from __future__ import annotations

from tests.conftest import catalog
from trainer.models import registry


def test_registry_ids_match_catalog():
    assert set(registry.ids()) == set(catalog()["families"]), "trainer registry and model_catalog.yaml drifted"


def test_sklearn_families_importable():
    for fid in registry.ids():
        if fid.startswith("tabular."):
            assert registry._load(fid, 0) is not None
