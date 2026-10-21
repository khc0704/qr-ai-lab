"""The consolidated DINO pipeline: layer presets (last / cross / list), patch-token-only features, heads with
``auto`` resolution, PatchCore as a shared patch bank (two-stage defect classification, anomaly detection),
CAM overlays for linear heads, LoRA fine-tuning with auto epochs / batch, the analysis tool's label check and
layer reading, the sequence / text option trims and the AutoML "default / none" augmentation choice.
CPU only, tiny locally-built weights."""

from __future__ import annotations

import json

import numpy as np
import pytest

torch = pytest.importorskip("torch")
pytest.importorskip("transformers")
pytest.importorskip("PIL")

from tests.test_torch_families import _images, _tiny_dino, _tiny_dino3, _tiny_qwen, spectra  # noqa: E402
from trainer.dataset import Dataset  # noqa: E402
from trainer.models import registry  # noqa: E402
from trainer.models.dino_features import (  # noqa: E402
    HEADS,
    FeatureSpec,
    FewShotHead,
    aggregate_scores,
    fuse_blocks,
    resolve_head,
    resolve_layers,
    select_layers,
)
from trainer.models.zoo import resolver  # noqa: E402


def test_layer_presets_scale_with_depth_and_lists_parse():
    assert resolve_layers("last", 12) == (12,) and resolve_layers(None, 12) == (12,)
    assert resolve_layers("cross", 12) == (9, 10, 11) and resolve_layers("cross", 24) == (18, 20, 22)
    assert resolve_layers("cross", 40) == (30, 33, 37) and resolve_layers("cross", 3) == (2, 3)
    assert resolve_layers("cross", 1) == (1,)
    assert resolve_layers("6,9,-1", 12) == (6, 9, 12) and resolve_layers([3, 3, 1], 12) == (1, 3)
    assert resolve_layers("all", 3) == (1, 2, 3) and resolve_layers("auto", 3) == (1, 2, 3)
    for bad in ("13", "deep", "mid", "last4"):
        with pytest.raises(ValueError):
            resolve_layers(bad, 12)
    spec = FeatureSpec.from_params({"layers": "cross", "image_size": "336", "neighborhood": 3})
    assert spec.image_size == 336 and spec.neighborhood == 3 and FeatureSpec.from_dict(spec.to_dict()) == spec
    assert spec.feature_dim(384, 3) == 1152
    # artifacts from earlier versions carry keys that no longer exist: they are ignored
    old = FeatureSpec.from_dict({"layers": [12], "pool": "cls+mean", "center": "none", "image_size": 224})
    assert old.layers == (12,) and old.image_size == 224
    for bad in ({"layers": "deep"}, {"image_size": 8}, {"neighborhood": 2}):
        with pytest.raises(ValueError):
            FeatureSpec.from_params(bad)


def test_heads_auto_resolution_scores_and_class_weights():
    rng = np.random.default_rng(0)
    y = np.array(["a"] * 15 + ["b"] * 15)
    shift = np.array([4.0] * 4 + [0.0] * 4)
    good = np.concatenate([rng.normal(size=(15, 8)) + shift, rng.normal(size=(15, 8)) + shift[::-1]])
    noise = rng.normal(size=(30, 8))
    blocks = np.stack([noise, good, noise * 0.5], axis=1)
    chosen, report = select_layers(blocks, y, (1, 2, 3), max_layers=1)
    assert chosen == (2,) and [r["layer"] for r in report if r["selected"]] == [2]
    fused = fuse_blocks(blocks[:, [1, 2], :])
    assert fused.shape == (30, 16) and np.allclose(np.linalg.norm(fused, axis=1), 1, atol=1e-5)
    assert resolve_head("auto", 3) == ("prototype", "smallest class has 3 images (< 10) → prototypes")
    assert resolve_head("auto", 10)[0] == "linear" and resolve_head("logistic", 1)[0] == "linear"
    with pytest.raises(ValueError):
        resolve_head("mlp", 5)
    for kind in HEADS:
        h = FewShotHead(kind, k=3).fit(good, y)
        preds, conf, proba, sims = h.predict(good[[0, 29]])
        assert preds == ["a", "b"] and proba.shape == (2, 2) and sims.shape == (2, 2) and conf.min() > 0
        assert (h.center is not None) == (kind in ("prototype", "knn"))
        w = h.class_weights()
        assert (w is None) == (kind in ("prototype", "knn")) or w.shape == (2, 8)
    assert FewShotHead("knn", k="auto").fit(good[:4], y[[0, 1, 15, 16]]).k == 2  # k ≤ smallest class
    maps = np.arange(300.0).reshape(1, 300)
    assert aggregate_scores(maps, "max")[0] == 299 and aggregate_scores(maps, "top1")[0] == 298


def _bins(tmp_path, n=6):
    root = tmp_path / "imgs"
    a = _images(root, "BIN_A", n, "dark", 1)
    b = _images(root, "BIN_B", n, "bright", 2)
    ds = Dataset(
        "IMAGE", "classification", {}, X=a + b, y=["BIN_A"] * n + ["BIN_B"] * n, ids=[p.name for p in a + b], root=root
    )
    return root, a, b, ds


@pytest.mark.parametrize(
    "params",
    [
        {"layers": "cross", "head": "linear"},
        {"layers": "auto", "head": "knn", "k": 3},
        {"layers": "1,3", "head": "svm", "image_size": 84},
        {"layers": "last", "head": "auto"},
    ],
)
def test_fewshot_feature_options_roundtrip(tmp_path, ctx, params):
    from trainer.models.vision import _Dino

    zoo = tmp_path / "zoo"
    _tiny_dino(zoo, layers=3)
    ctx.zoo = resolver(zoo, {"dinov2-small": "dinov2-small/"})
    root, a, b, ds = _bins(tmp_path)
    t = registry.create_trainer("vision.dino", "classification", {"backbone": "dinov2-small", **params}, ctx)
    t.fit(ds)
    expected_head = "prototype" if params["head"] == "auto" else params["head"]  # 6 per class < 10 → prototypes
    assert t.evaluate()["accuracy"] >= 0.5 and t.meta["resolved"]["head"] == expected_head
    assert t.meta["finetune"] == "none" and t.meta["resolved"]["finetune"] == "none"
    feats = t.meta["features"]
    assert isinstance(feats["layers"], list) and "pool" not in feats
    if params["layers"] == "auto":
        assert t.meta["layer_report"] and any(r["selected"] for r in t.meta["layer_report"])
        assert 1 <= len(feats["layers"]) <= 3
    elif params["layers"] == "cross":
        assert feats["layers"] == [2, 3]  # 9 / 10 / 11 of 12 scaled to a 3-layer backbone
    elif params["layers"] == "last":
        assert feats["layers"] == [3]
    else:
        assert feats["layers"] == [1, 3]
    assert t.meta["feature_dim"] == 32 * len(feats["layers"])
    arts = t.export(tmp_path / "out")
    model_dir = tmp_path / "out" / "model"
    assert (model_dir / "head.joblib").exists() == (expected_head in ("linear", "svm"))
    inf = registry.create_inferencer("vision.dino", ctx)
    inf.load(model_dir, arts[0].metadata)
    assert inf.dino.layers == tuple(feats["layers"]) and inf.head.kind == expected_head
    probe = Dataset("IMAGE", "classification", {}, X=a[:2] + b[:2], ids=["a0", "a1", "b0", "b1"], root=root)
    res = inf.predict(probe, "predict", {}, tmp_path / "pred")
    assert [r["prediction"] for r in res.rows] == ["BIN_A", "BIN_A", "BIN_B", "BIN_B"], res.rows
    assert res.summary["head"] == expected_head and "probability" in res.rows[0]["top3"][0]
    assert (tmp_path / "pred" / "attention" / "a0.png").exists()  # CAM for linear / svm, similarity otherwise
    res = inf.predict(probe, "retrieve", {"k": 2}, tmp_path / "ret")
    assert res.rows[0]["most_similar"][0]["label"] == "BIN_A" and res.rows[0]["attention"]
    res = inf.predict(probe, "embed", {}, tmp_path / "emb")
    assert res.summary["dim"] == t.meta["feature_dim"]
    if params.get("image_size"):
        dino = _Dino(ctx, "dinov2-small", FeatureSpec(image_size=84, layers="last"))
        _, patches = dino.embed(a[:1], patches=True)
        assert patches.shape[1] == 36  # (84 / 14)² instead of (56 / 14)² = 16
    # extend: the head is re-fitted on cached features, new class appears
    c = _images(root, "BIN_C", 4, "blob", 3)
    out2 = tmp_path / "out2" / "output"
    out2.mkdir(parents=True)
    res = inf.predict(
        Dataset("IMAGE", "classification", {}, X=c, y=["BIN_C"] * 4, ids=[p.name for p in c], root=root),
        "extend",
        {},
        out2,
    )
    assert res.summary["new_classes"] == ["BIN_C"]
    meta2 = json.loads((tmp_path / "out2" / "model" / "metadata.json").read_text(encoding="utf-8"))
    assert meta2["classes"] == ["BIN_A", "BIN_B", "BIN_C"] and meta2["features"] == feats


def test_neighborhood_pooling_keeps_the_grid():
    from trainer.models.dino_features import aggregate_neighborhood

    tok = torch.arange(2 * 16 * 4, dtype=torch.float32).reshape(2, 16, 4)
    out = aggregate_neighborhood(tok, 3)
    assert out.shape == tok.shape and torch.equal(aggregate_neighborhood(tok, 1), tok)
    # the centre patch of a 4×4 grid averages its 3×3 neighbourhood; a corner averages 4 patches
    grid = tok[0, :, 0].reshape(4, 4)
    assert torch.isclose(out[0, 5, 0], grid[0:3, 0:3].mean()) and torch.isclose(out[0, 0, 0], grid[0:2, 0:2].mean())


def test_fewshot_patchcore_two_stage_defects(tmp_path, ctx):
    zoo = tmp_path / "zoo"
    _tiny_dino3(zoo, layers=2)
    ctx.zoo = resolver(zoo, {"dinov3-vits16": "dinov3-vits16/"})
    root = tmp_path / "imgs"
    good = _images(root, "pass_wafer", 10, "dark", 1)  # a normal folder with a custom name
    scratch = _images(root, "scratch", 5, "blob", 2)
    void = _images(root, "void", 5, "bright", 3)
    paths = good + scratch + void
    labels = ["pass_wafer"] * 10 + ["scratch"] * 5 + ["void"] * 5
    ds = Dataset("IMAGE", "classification", {}, X=paths, y=labels, ids=[p.name for p in paths], root=root)
    # no known normal folder name → patchcore=auto stays off
    t0 = registry.create_trainer("vision.dino", "classification", {"backbone": "dinov3-vits16"}, ctx)
    t0.fit(ds)
    assert t0.bank is None and t0.meta["resolved"]["patchcore"] is False
    with pytest.raises(ValueError, match="normal_class"):
        registry.create_trainer(
            "vision.dino", "classification", {"backbone": "dinov3-vits16", "patchcore": "on"}, ctx
        ).fit(ds)
    t = registry.create_trainer(
        "vision.dino",
        "classification",
        {"backbone": "dinov3-vits16", "normal_class": "pass_wafer", "neighborhood": 3, "score_agg": "top1"},
        ctx,
    )
    t.fit(ds)
    assert t.normal_class == "pass_wafer" and t.bank is not None and t.meta["patchcore"]["threshold"] > 0
    r = t.meta["resolved"]
    assert r["patchcore"] is True and r["score_agg"] == "top1" and r["bank_augment"] is True  # < 20 normals
    assert 0 < r["coreset_ratio"] <= 1 and t.meta["features"]["neighborhood"] == 3
    assert t.defect_head is not None and set(t.defect_head.classes) == {"scratch", "void"}
    arts = t.export(tmp_path / "out")
    bank = np.load(tmp_path / "out" / "model" / "prototypes.npz")
    assert "normal_bank" in bank.files and bank["defect_support"].shape[0] == 20
    inf = registry.create_inferencer("vision.dino", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    assert inf.bank is not None and inf.defect_head is not None and inf.bank.score_agg == "top1"
    probe = Dataset("IMAGE", "classification", {}, X=good[:2] + scratch[:2] + void[:2], ids=list("gGsSvV"), root=root)
    res = inf.predict(probe, "predict", {}, tmp_path / "pred")
    preds = [r["prediction"] for r in res.rows]
    assert preds[:2] == ["pass_wafer", "pass_wafer"] and set(preds[2:]) <= {"scratch", "void", "unknown"}, res.rows
    assert all({"anomaly_score", "is_anomaly", "hot_patch_row", "attention"} <= set(r) for r in res.rows)
    assert not res.rows[0]["is_anomaly"] and res.rows[2]["is_anomaly"] and res.rows[4]["is_anomaly"]
    assert res.summary["normal_class"] == "pass_wafer" and res.summary["flagged"] == 4
    assert (tmp_path / "pred" / "attention" / "g.png").exists()
    res = inf.predict(probe, "predict", {"threshold": 0.0}, tmp_path / "pred2")
    assert all(r["is_anomaly"] for r in res.rows)
    res = inf.predict(probe, "predict", {"patchcore": "off"}, tmp_path / "pred3")
    assert "anomaly_score" not in res.rows[0] and res.rows[0]["prediction"] in ("pass_wafer", "scratch", "void")
    # extend with a new defect class and more normals: bank and defect head grow, no retraining
    crack = _images(root, "crack", 3, "bright", 9)
    more_good = _images(root, "pass_wafer", 2, "dark", 11)
    out2 = tmp_path / "out2" / "output"
    out2.mkdir(parents=True)
    res = inf.predict(
        Dataset(
            "IMAGE",
            "classification",
            {},
            X=crack + more_good,
            y=["crack"] * 3 + ["pass_wafer"] * 2,
            ids=[p.name for p in crack + more_good],
            root=root,
        ),
        "extend",
        {},
        out2,
    )
    assert res.summary["new_classes"] == ["crack"]
    bank2 = np.load(tmp_path / "out2" / "model" / "prototypes.npz")
    assert len(bank2["normal_bank"]) > len(bank["normal_bank"]) and bank2["defect_support"].shape[0] == 25
    meta2 = json.loads((tmp_path / "out2" / "model" / "metadata.json").read_text(encoding="utf-8"))
    assert meta2["patchcore"]["normal_class"] == "pass_wafer" and "crack" in meta2["classes"]


def test_patchcore_anomaly_detection_options(tmp_path, ctx):
    zoo = tmp_path / "zoo"
    _tiny_dino(zoo, layers=3)
    ctx.zoo = resolver(zoo, {"dinov2-small": "dinov2-small/"})
    normal = _images(tmp_path / "pc", "good", 30, "dark", 4)
    bad = _images(tmp_path / "pc", "defect", 4, "blob", 5)
    ds = Dataset(
        "IMAGE",
        "anomaly_detection",
        {},
        X=normal + bad,
        y=["normal"] * 30 + ["defect"] * 4,
        ids=[p.name for p in normal + bad],
        root=tmp_path / "pc",
    )
    t = registry.create_trainer("vision.dino_patchcore", "anomaly_detection", {"backbone": "dinov2-small"}, ctx)
    t.fit(ds)
    r = t.meta["resolved"]
    assert r["layers"] == [2, 3] and r["score_agg"] == "max" and r["bank_augment"] is False  # 24 train normals ≥ 20
    assert t.bank.bank.shape[1] == 64 and t.meta["patchcore"]["projection"] is None and "auroc" in t.evaluate()
    arts = t.export(tmp_path / "out")
    inf = registry.create_inferencer("vision.dino_patchcore", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    assert inf.dino.layers == (2, 3) and inf.bank.k == 3
    probe = Dataset(
        "IMAGE", "anomaly_detection", {}, X=normal[:2] + bad[:2], ids=["n0", "n1", "d0", "d1"], root=tmp_path / "pc"
    )
    res = inf.predict(probe, "score", {}, tmp_path / "pred")
    assert len(res.rows) == 4 and max(r["anomaly_score"] for r in res.rows[2:]) > min(
        r["anomaly_score"] for r in res.rows[:2]
    )
    assert (
        res.rows[0]["heatmap"] and res.rows[0]["attention"] == "attention/n0.png" and res.summary["score_agg"] == "max"
    )
    t2 = registry.create_trainer(
        "vision.dino_patchcore",
        "anomaly_detection",
        {
            "backbone": "dinov2-small",
            "layers": "last",
            "bank_augment": "on",
            "coreset_ratio": 0.5,
            "score_agg": "top1",
        },
        ctx,
    )
    t2.fit(ds)
    r2 = t2.meta["resolved"]
    assert (
        r2["layers"] == [3] and r2["bank_augment"] is True and r2["coreset_ratio"] == 0.5 and r2["score_agg"] == "top1"
    )
    with pytest.raises(ValueError, match="layers"):
        registry.create_trainer(
            "vision.dino_patchcore", "anomaly_detection", {"backbone": "dinov2-small", "layers": "auto"}, ctx
        ).fit(ds)


def test_lora_finetune_auto_epochs_batch_and_cam(tmp_path, ctx):
    from trainer.models.vision import DEFAULT_AUGMENT, parse_augment, resolve_batch, resolve_epochs

    assert resolve_epochs("auto", 64, 16) == (40, "64 images / batch 16 → 40 epochs ≈ 400 steps")
    assert resolve_epochs("auto", 6400, 16)[0] == 5 and resolve_epochs(7, 10, 2) == (7, "chosen by the user")
    assert resolve_batch("auto", None)[0] == 16 and resolve_batch("auto", 448)[0] == 4 and resolve_batch(3, 224)[0] == 3
    assert parse_augment(True) == DEFAULT_AUGMENT == ("crop", "hflip") and parse_augment("none") == ()
    zoo = tmp_path / "zoo"
    _tiny_dino(zoo, layers=3)
    ctx.zoo = resolver(zoo, {"dinov2-small": "dinov2-small/"})
    root, a, b, ds = _bins(tmp_path, n=8)
    params = {
        "backbone": "dinov2-small",
        "epochs": 3,
        "batch": 4,
        "lr": 5e-3,
        "rank": 2,
        "layers": "1,3",
        "augment": "none",
    }
    t = registry.create_trainer("vision.dino_finetune", "classification", params, ctx)
    t.fit(ds)
    assert t.net.layers == (1, 3) and t.net.feature_dim == 64 and t.meta["augment"] == [] and t.meta["head"] == "linear"
    assert t.meta["resolved"] == {"layers": [1, 3], "epochs": 3, "batch": 4, "lr": 5e-3}
    arts = t.export(tmp_path / "out")
    inf = registry.create_inferencer("vision.dino_finetune", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    assert inf.net.layers == (1, 3) and inf.net.feature_dim == 64 and not inf.net.legacy_head
    probe = Dataset("IMAGE", "classification", {}, X=a[:2] + b[:2], ids=["a0", "a1", "b0", "b1"], root=root)
    res = inf.predict(probe, "predict", {}, tmp_path / "pred")
    assert [r["prediction"] for r in res.rows] == ["BIN_A", "BIN_A", "BIN_B", "BIN_B"], res.rows
    assert (tmp_path / "pred" / "attention" / "a0.png").exists()  # CAM, no gradients
    cam = inf.net.cam(inf.net.pixels(a[:1]), np.array([0]))
    assert cam.shape == (1, 16) and (cam >= 0).all()
    res = inf.predict(probe, "retrieve", {"k": 2}, tmp_path / "ret")
    assert res.rows[0]["most_similar"][0]["label"] == "BIN_A" and res.rows[0]["attention"]
    assert inf.predict(probe, "embed", {}, tmp_path / "emb").summary["dim"] == 64
    # auto epochs / batch resolve from the data; auto layers are refused
    t2 = registry.create_trainer(
        "vision.dino_finetune", "classification", {**params, "epochs": "auto", "batch": "auto"}, ctx
    )
    t2.fit(ds)
    assert t2.meta["resolved"]["batch"] == 16 and t2.meta["resolved"]["epochs"] == 40
    with pytest.raises(ValueError, match="auto"):
        registry.create_trainer("vision.dino_finetune", "classification", {**params, "layers": "auto"}, ctx).fit(ds)


def test_yolo_freeze_auto():
    from trainer.models.vision import resolve_freeze

    assert resolve_freeze("auto", 50) == (10, "50 images < 200 → backbone (10 modules) frozen")
    assert resolve_freeze("auto", 50, 9)[0] == 9  # classification models have a 9-module backbone
    assert resolve_freeze("auto", 50, 10, pretrained=False) == (0, "from scratch → nothing to freeze")
    assert resolve_freeze("auto", 500)[0] == 0 and resolve_freeze(0, 50) == (0, "chosen by the user")
    assert resolve_freeze("10", 5000)[0] == 10


def test_sequence_embedding_options_and_band_scores(tmp_path, ctx):
    X, y, _ = spectra(n=200, shift_last=30)
    ds = Dataset("SPECTRUM", "anomaly_detection", {}, X=X, y=y, ids=[f"s{i}" for i in range(len(X))])
    params = {
        "epochs": 25,
        "patch_size": 16,
        "dim": 32,
        "depth": 2,
        "heads": 2,
        "mask_ratio": 0.5,
        "embed_layers": "all",
        "embed_pool": "meanmax",
    }
    t = registry.create_trainer("spectrum.masked_autoencoder", "anomaly_detection", params, ctx)
    t.fit(ds)
    assert t.config["embed_layers"] == "all" and t.config["embed_pool"] == "meanmax"
    arts = t.export(tmp_path / "mae")
    inf = registry.create_inferencer("spectrum.masked_autoencoder", ctx)
    inf.load(tmp_path / "mae" / "model", arts[0].metadata)
    probe = Dataset("SPECTRUM", "anomaly_detection", {}, X=X[-3:], ids=["a", "b", "c"])
    res = inf.predict(probe, "embed", {}, tmp_path / "e")
    assert res.summary["dim"] == 2 * 2 * 32  # 2 layers × (mean ⊕ max) × dim
    res = inf.predict(probe, "score", {}, tmp_path / "s")
    row = res.rows[0]
    assert len(row["patch_scores"]) == 8 and 0 <= row["hot_patch"] < 8 and row["hot_band_end"] <= 128
    assert row["hot_band_start"] == row["hot_patch"] * 16 and res.summary["score_method"] == "recon"
    assert res.summary["patch_size"] == 16 and res.summary["window_length"] == 128 and "hot_bands" in res.summary
    # the probe windows all carry the shifted peak (around sample 92): the hottest band of at least one covers it
    assert any(r["hot_band_start"] <= 92 < r["hot_band_end"] for r in res.rows), res.rows
    # patch bank scoring (1-D PatchCore) for both families
    for fid, extra in (
        ("spectrum.masked_autoencoder", {"dim": 32, "depth": 1, "heads": 2, "mask_ratio": 0.5}),
        ("sequence.patch_autoencoder", {"latent": 16, "layers": 2}),
    ):
        t = registry.create_trainer(
            fid, "anomaly_detection", {"epochs": 5, "patch_size": 16, "score_method": "patch_bank", **extra}, ctx
        )
        t.fit(ds)
        assert t.patch_bank is not None and "auroc" in t.evaluate()
        arts = t.export(tmp_path / fid)
        inf = registry.create_inferencer(fid, ctx)
        inf.load(tmp_path / fid / "model", arts[0].metadata)
        assert inf.patch_bank is not None
        res = inf.predict(probe, "score", {}, tmp_path / f"{fid}-s")
        assert res.summary["score_method"] == "patch_bank" and len(res.rows[0]["patch_scores"]) == 8
    with pytest.raises(ValueError, match="score_method"):
        registry.create_trainer("sequence.patch_autoencoder", "anomaly_detection", {"score_method": "knn"}, ctx).fit(ds)


def test_qwen_pooling_option(tmp_path, ctx):
    import pandas as pd

    texts = [f"例行保養完成 第{i}次" for i in range(12)] + [f"真空度異常警報 {i}" for i in range(12)]
    labels = ["info"] * 12 + ["alarm"] * 12
    zoo = tmp_path / "zoo"
    _tiny_qwen(zoo, texts)
    ctx.zoo = resolver(zoo, {"qwen3-embedding-0.6b": "qwen3-embedding-0.6b/"})
    ds = Dataset("TEXT", "classification", {}, X=pd.Series(texts), y=pd.Series(labels), ids=[str(i) for i in range(24)])
    t = registry.create_trainer("text.qwen_embedding", "classification", {"max_len": 16, "pool": "mean"}, ctx)
    t.fit(ds)
    assert t.meta["pool"] == "mean" and "f1_macro" in t.evaluate()
    arts = t.export(tmp_path / "out")
    inf = registry.create_inferencer("text.qwen_embedding", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    assert inf.encoder.pool == "mean"
    res = inf.predict(Dataset("TEXT", None, {}, X=pd.Series(["真空度異常"]), ids=["q"]), "embed", {}, tmp_path / "e")
    assert abs(np.linalg.norm(res.rows[0]["embedding"]) - 1) < 1e-3
    with pytest.raises(ValueError, match="pool"):
        registry.create_trainer("text.qwen_embedding", "classification", {"max_len": 16, "pool": "cls"}, ctx).fit(ds)


def test_image_analysis_label_check_and_layer_reading(tmp_path, ctx):
    from trainer.analysis import image as image_analysis

    zoo = tmp_path / "zoo"
    _tiny_dino(zoo, layers=3)
    ctx.zoo = resolver(zoo, {"dinov2-small": "dinov2-small/"})
    root = tmp_path / "data"
    _images(root, "tool_a", 8, "dark", 1)
    _images(root, "tool_b", 8, "bright", 2)
    # one bright image filed under tool_a: both feature views should send it to tool_b
    _images(root, "tool_a", 1, "bright", 7)
    rep = image_analysis.quality_report(root, embedding="dino", backbone="dinov2-small", ctx=ctx)
    assert rep["embedding"] == "dino:dinov2-small"
    check = rep["label_check"]
    assert check and set(check["accuracy"]) == {"last", "cross"} and check["accuracy"]["cross"] > 0.8
    bad = [r for r in check["flagged"] if r["verdict"] == "likely_mislabeled"]
    assert bad and bad[0]["id"] == "tool_a/tool_a_0.png" and bad[0]["pred_cross"] == "tool_b" and bad[0]["agree"]
    layers = rep["layers"]
    assert layers["kind"] == "dinov2" and [r["layer"] for r in layers["rows"]] == [1, 2, 3]
    assert layers["cross_preset"] == [2, 3] and layers["separability"] and layers["suggested"]
    row = layers["rows"][-1]
    assert {"fisher", "loo_accuracy", "correlates", "description"} <= set(row) and row["description"]
    texts = " ".join(r["text"] for r in rep["recommendations"])
    assert "標籤一致性" in texts and "layers 參數" in texts
    assert json.dumps(rep)  # serialisable (no NaN)


def test_automl_samples_default_or_none_augmentation():
    from trainer.automl import _sample

    class Trial:
        def __init__(self, pick):
            self.pick = pick

        def suggest_categorical(self, key, choices):
            assert key.endswith(".augment") and choices == ["default", "none"]
            return self.pick

        def suggest_float(self, *a, **k):
            return 0.5

        def suggest_int(self, *a, **k):
            return 1

    space = {"augment": {"type": "categorical", "choices": ["default", "none"]}}
    assert _sample(Trial("default"), "vision.yolo", space) == {}  # the family default stays
    assert _sample(Trial("none"), "vision.yolo", space) == {"augment": []}


@pytest.mark.parametrize("finetune", ["lora", "full"])
def test_dino_finetune_then_features_heads_and_patchcore(tmp_path, ctx, finetune):
    """The merged family: fine-tune first (LoRA adapters or every weight), then the frozen-feature pipeline on the
    fine-tuned backbone; the adapters / backbone travel with the artifact and survive ``extend``."""
    zoo = tmp_path / "zoo"
    _tiny_dino(zoo, layers=3)
    ctx.zoo = resolver(zoo, {"dinov2-small": "dinov2-small/"})
    root = tmp_path / "imgs"
    good = _images(root, "good", 12, "dark", 1)
    scratch = _images(root, "scratch", 6, "blob", 2)
    paths = good + scratch
    ds = Dataset(
        "IMAGE",
        "classification",
        {},
        X=paths,
        y=["good"] * 12 + ["scratch"] * 6,
        ids=[p.name for p in paths],
        root=root,
    )
    params = {
        "backbone": "dinov2-small",
        "finetune": finetune,
        "epochs": 2,
        "batch": 6,
        "lr": 5e-3,
        "rank": 2,
        "head": "linear",
    }
    progress: list[float] = []
    ctx.on_progress = lambda f, stage: progress.append(f)
    t = registry.create_trainer("vision.dino", "classification", params, ctx)
    t.fit(ds)
    assert t.finetune == finetune and t.ft is not None and t.meta["finetune"] == finetune
    assert (
        t.meta["resolved"]["finetune"] == finetune and t.meta["resolved"]["epochs"] == 2 and t.meta["finetune_metrics"]
    )
    assert t.bank is not None and t.normal_class == "good"  # the two-stage classifier runs on fine-tuned features
    assert progress == sorted(progress) and max(progress) <= 1.0  # the nested fine-tune bar never runs backwards
    arts = t.export(tmp_path / "out")
    model_dir = tmp_path / "out" / "model"
    assert (model_dir / "prototypes.npz").exists() and (model_dir / "head.joblib").exists()
    assert (model_dir / "lora.pt").exists() == (finetune == "lora") and (model_dir / "backbone").is_dir() == (
        finetune == "full"
    )
    inf = registry.create_inferencer("vision.dino", ctx)
    inf.load(model_dir, arts[0].metadata)
    assert inf.dino.adapted and inf.bank is not None
    probe = Dataset("IMAGE", "classification", {}, X=good[:2] + scratch[:2], ids=["g0", "g1", "s0", "s1"], root=root)
    res = inf.predict(probe, "predict", {}, tmp_path / "pred")
    assert [r["prediction"] for r in res.rows][:2] == ["good", "good"] and res.rows[2]["is_anomaly"]
    assert (tmp_path / "pred" / "attention" / "g0.png").exists()
    # extend keeps the fine-tuned backbone next to the grown bank
    more = _images(root, "void", 3, "bright", 5)
    out2 = tmp_path / "out2" / "output"
    out2.mkdir(parents=True)
    res = inf.predict(
        Dataset("IMAGE", "classification", {}, X=more, y=["void"] * 3, ids=[p.name for p in more], root=root),
        "extend",
        {},
        out2,
    )
    assert res.summary["new_classes"] == ["void"]
    new_dir = tmp_path / "out2" / "model"
    assert (new_dir / "lora.pt").exists() == (finetune == "lora") and (new_dir / "backbone").is_dir() == (
        finetune == "full"
    )
    inf2 = registry.create_inferencer("vision.dino", ctx)
    inf2.load(new_dir, res.extra_artifacts[0].metadata)
    assert inf2.dino.adapted and "void" in inf2.classes
    with pytest.raises(ValueError, match="finetune"):
        registry.create_trainer("vision.dino", "classification", {**params, "finetune": "adapter"}, ctx).fit(ds)


def test_legacy_family_ids_still_resolve(tmp_path, ctx):
    from trainer.models import vision

    assert registry.create_trainer("vision.dino_fewshot", "classification", {}, ctx).__class__ is vision.DinoTrainer
    assert registry.create_inferencer("vision.dino_fewshot", ctx).__class__ is vision.DinoInferencer
    assert registry.create_inferencer("vision.dino_finetune", ctx).__class__ is vision.DinoFinetuneInferencer
