"""Feature-generation options: DINO layers / pooling / centring / background / metric / image size, few-shot
heads and the normal-patch bank, PatchCore layer fusion + projection, multi-layer fine-tuning, sequence MAE
embedding options + band scores, Qwen pooling, the analysis tool's label check and layer reading, and the
AutoML "default / none" augmentation choice. CPU only, tiny locally-built weights."""

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
    fuse_blocks,
    poincare_dist,
    resolve_layers,
    select_layers,
    to_ball,
)
from trainer.models.zoo import resolver  # noqa: E402


def test_layer_presets_scale_with_depth_and_lists_parse():
    assert resolve_layers("last", 12) == (12,) and resolve_layers(None, 12) == (12,)
    assert resolve_layers("mid", 12, "dinov2") == (6, 8, 10, 12) and resolve_layers("mid", 12, "dinov3") == (8, 10, 12)
    assert resolve_layers("last4", 12) == (9, 10, 11, 12) and resolve_layers("spread", 12) == (3, 6, 9, 12)
    assert resolve_layers("mid", 24, "dinov2") == (12, 16, 20, 24)  # ViT-L
    assert resolve_layers("last4", 3) == (2, 3) and resolve_layers("spread", 1) == (1,)
    assert resolve_layers("6,9,-1", 12) == (6, 9, 12) and resolve_layers([3, 3, 1], 12) == (1, 3)
    assert resolve_layers("all", 3) == (1, 2, 3) and resolve_layers("auto", 3) == (1, 2, 3)
    with pytest.raises(ValueError):
        resolve_layers("13", 12)
    with pytest.raises(ValueError):
        resolve_layers("deep", 12)
    spec = FeatureSpec.from_params({"layers": "mid", "pool": "cls+attn", "center": "support_mean", "image_size": "336"})
    assert spec.wants_attention and spec.image_size == 336 and FeatureSpec.from_dict(spec.to_dict()) == spec
    assert spec.block_dim(384) == 768 and spec.feature_dim(384, 4) == 3072
    assert FeatureSpec.from_params({"pool": "mean", "layer_fusion": "mean"}).feature_dim(384, 4) == 384
    for bad in ({"pool": "sum"}, {"metric": "l2"}, {"layers": "deep"}, {"image_size": 8}):
        with pytest.raises(ValueError):
            FeatureSpec.from_params(bad)


def test_auto_layer_selection_and_hyperbolic_distance():
    rng = np.random.default_rng(0)
    y = np.array(["a"] * 15 + ["b"] * 15)
    shift = np.array([4.0] * 4 + [0.0] * 4)
    good = np.concatenate([rng.normal(size=(15, 8)) + shift, rng.normal(size=(15, 8)) + shift[::-1]])
    noise = rng.normal(size=(30, 8))
    blocks = np.stack([noise, good, noise * 0.5], axis=1)
    chosen, report = select_layers(blocks, y, (1, 2, 3), max_layers=1)
    assert chosen == (2,) and [r["layer"] for r in report if r["selected"]] == [2]
    assert report[1]["loo_accuracy"] > report[0]["loo_accuracy"]
    fused = fuse_blocks(blocks[:, [1], :])
    assert fused.shape == (30, 8) and np.allclose(np.linalg.norm(fused, axis=1), 1, atol=1e-5)
    u = to_ball(rng.normal(size=(4, 8)))
    d = poincare_dist(u, u)
    assert d.shape == (4, 4) and np.allclose(np.diag(d), 0, atol=1e-4) and (d >= 0).all()
    for kind in HEADS:
        h = FewShotHead(kind, k=3, metric="hyperbolic").fit(good, y)
        preds, conf, proba, sims = h.predict(good[[0, 29]])
        assert preds == ["a", "b"] and proba.shape == (2, 2) and sims.shape == (2, 2) and conf.min() > 0


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
        {
            "layers": "mid",
            "pool": "cls+attn",
            "center": "support_mean",
            "background": "project_out_cls",
            "head": "logistic",
        },
        {"layers": "auto", "pool": "cls+gem", "head": "knn", "k": 3, "metric": "hyperbolic", "layer_fusion": "mean"},
        {"layers": "1,3", "pool": "mean", "head": "svm", "image_size": 84},
    ],
)
def test_fewshot_feature_options_roundtrip(tmp_path, ctx, params):
    from trainer.models.vision import _Dino

    zoo = tmp_path / "zoo"
    _tiny_dino(zoo, layers=3)
    ctx.zoo = resolver(zoo, {"dinov2-small": "dinov2-small/"})
    root, a, b, ds = _bins(tmp_path)
    t = registry.create_trainer("vision.dino_fewshot", "classification", {"backbone": "dinov2-small", **params}, ctx)
    t.fit(ds)
    assert t.evaluate()["accuracy"] >= 0.5 and t.meta["head"] == params["head"]
    feats = t.meta["features"]
    assert isinstance(feats["layers"], list) and feats["pool"] == params["pool"]
    if params["layers"] == "auto":
        assert t.meta["layer_report"] and any(r["selected"] for r in t.meta["layer_report"])
        assert 1 <= len(feats["layers"]) <= 3
    elif params["layers"] == "mid":
        assert feats["layers"] == [2, 3]  # (6, 8, 10, 12) scaled to a 3-layer backbone
    else:
        assert feats["layers"] == [1, 3]
    n_layers = len(feats["layers"]) if feats["layer_fusion"] == "concat" else 1
    assert t.meta["feature_dim"] == FeatureSpec.from_dict(feats).block_dim(32) * n_layers
    arts = t.export(tmp_path / "out")
    model_dir = tmp_path / "out" / "model"
    bank = np.load(model_dir / "prototypes.npz")
    assert ("center" in bank.files) == (params.get("center") == "support_mean")
    assert (model_dir / "head.joblib").exists() == (params["head"] in ("logistic", "svm", "prototype+logistic"))
    inf = registry.create_inferencer("vision.dino_fewshot", ctx)
    inf.load(model_dir, arts[0].metadata)
    assert inf.dino.layers == tuple(feats["layers"]) and inf.head.kind == params["head"]
    probe = Dataset("IMAGE", "classification", {}, X=a[:2] + b[:2], ids=["a0", "a1", "b0", "b1"], root=root)
    res = inf.predict(probe, "predict", {}, tmp_path / "pred")
    assert [r["prediction"] for r in res.rows] == ["BIN_A", "BIN_A", "BIN_B", "BIN_B"], res.rows
    assert res.summary["head"] == params["head"] and "probability" in res.rows[0]["top3"][0]
    assert (tmp_path / "pred" / "attention" / "a0.png").exists()
    res = inf.predict(probe, "retrieve", {"k": 2}, tmp_path / "ret")
    assert res.rows[0]["most_similar"][0]["label"] == "BIN_A" and res.rows[0]["attention"]
    res = inf.predict(probe, "embed", {}, tmp_path / "emb")
    assert res.summary["dim"] == t.meta["feature_dim"]
    if params.get("image_size"):
        dino = _Dino(ctx, "dinov2-small", FeatureSpec(image_size=84))
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


def test_fewshot_normal_bank_two_stage_defects(tmp_path, ctx):
    zoo = tmp_path / "zoo"
    _tiny_dino3(zoo, layers=2)
    ctx.zoo = resolver(zoo, {"dinov3-vits16": "dinov3-vits16/"})
    root = tmp_path / "imgs"
    good = _images(root, "good", 10, "dark", 1)
    scratch = _images(root, "scratch", 5, "blob", 2)
    void = _images(root, "void", 5, "bright", 3)
    paths = good + scratch + void
    labels = ["good"] * 10 + ["scratch"] * 5 + ["void"] * 5
    ds = Dataset("IMAGE", "classification", {}, X=paths, y=labels, ids=[p.name for p in paths], root=root)
    t = registry.create_trainer("vision.dino_fewshot", "classification", {"backbone": "dinov3-vits16"}, ctx)
    t.fit(ds)
    assert t.normal_class == "good" and t.bank is not None and t.meta["normal_bank"]["threshold"] > 0
    assert t.meta["normal_bank"]["normal_class"] == "good" and t.defect_head is not None
    assert set(t.defect_head.classes) == {"scratch", "void"}
    arts = t.export(tmp_path / "out")
    bank = np.load(tmp_path / "out" / "model" / "prototypes.npz")
    assert "normal_bank" in bank.files and "defect_support" in bank.files
    assert bank["defect_support"].shape[0] == 20  # a descriptor per support image
    inf = registry.create_inferencer("vision.dino_fewshot", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    assert inf.bank is not None and inf.defect_head is not None
    probe = Dataset("IMAGE", "classification", {}, X=good[:2] + scratch[:2] + void[:2], ids=list("gGsSvV"), root=root)
    res = inf.predict(probe, "predict", {}, tmp_path / "pred")
    preds = [r["prediction"] for r in res.rows]
    assert preds[:2] == ["good", "good"] and set(preds[2:4]) <= {"scratch", "void", "unknown"}, res.rows
    assert all({"anomaly_score", "is_anomaly", "hot_patch_row", "attention"} <= set(r) for r in res.rows)
    assert not res.rows[0]["is_anomaly"] and res.rows[2]["is_anomaly"] and res.rows[4]["is_anomaly"]
    assert res.summary["normal_class"] == "good" and res.summary["flagged"] == 4
    assert (tmp_path / "pred" / "attention" / "g.png").exists()
    # a forced threshold flags everything; the plain head is still there with the bank switched off
    res = inf.predict(probe, "predict", {"threshold": 0.0}, tmp_path / "pred2")
    assert all(r["is_anomaly"] for r in res.rows)
    res = inf.predict(probe, "predict", {"normal_bank": "off"}, tmp_path / "pred3")
    assert "anomaly_score" not in res.rows[0] and res.rows[0]["prediction"] in ("good", "scratch", "void")
    # extend with a new defect class and more normals: bank and defect head grow, no retraining
    crack = _images(root, "crack", 3, "bright", 9)
    more_good = _images(root, "good", 2, "dark", 11)
    out2 = tmp_path / "out2" / "output"
    out2.mkdir(parents=True)
    res = inf.predict(
        Dataset(
            "IMAGE",
            "classification",
            {},
            X=crack + more_good,
            y=["crack"] * 3 + ["good"] * 2,
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
    assert meta2["normal_bank"]["normal_class"] == "good" and "crack" in meta2["classes"]
    # an explicit normal_class that is not a folder is refused; a wrong folder set is refused too
    with pytest.raises(ValueError, match="normal_class"):
        registry.create_trainer(
            "vision.dino_fewshot", "classification", {"backbone": "dinov3-vits16", "normal_class": "ok"}, ctx
        ).fit(ds)


def test_patchcore_layer_fusion_and_projection(tmp_path, ctx):
    zoo = tmp_path / "zoo"
    _tiny_dino(zoo, layers=3)
    ctx.zoo = resolver(zoo, {"dinov2-small": "dinov2-small/"})
    normal = _images(tmp_path / "pc", "good", 12, "dark", 4)
    bad = _images(tmp_path / "pc", "defect", 4, "blob", 5)
    ds = Dataset(
        "IMAGE",
        "anomaly_detection",
        {},
        X=normal + bad,
        y=["normal"] * 12 + ["defect"] * 4,
        ids=[p.name for p in normal + bad],
        root=tmp_path / "pc",
    )
    params = {"backbone": "dinov2-small", "coreset_ratio": 0.5, "k": 1, "layers": "last4", "patch_dim": "auto"}
    t = registry.create_trainer("vision.dino_patchcore", "anomaly_detection", params, ctx)
    t.fit(ds)
    assert t.meta["features"]["layers"] == [2, 3] and t.bank.shape[1] == 32  # 2 × 32 projected back to 32
    assert t.meta["projection"] == {"dim_in": 64, "dim_out": 32, "seed": 0}
    arts = t.export(tmp_path / "out")
    inf = registry.create_inferencer("vision.dino_patchcore", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    assert inf.proj is not None and inf.proj.shape == (64, 32) and inf.dino.layers == (2, 3)
    probe = Dataset(
        "IMAGE", "anomaly_detection", {}, X=normal[:2] + bad[:2], ids=["n0", "n1", "d0", "d1"], root=tmp_path / "pc"
    )
    res = inf.predict(probe, "score", {}, tmp_path / "pred")
    assert len(res.rows) == 4 and max(r["anomaly_score"] for r in res.rows[2:]) > min(
        r["anomaly_score"] for r in res.rows[:2]
    )
    t2 = registry.create_trainer(
        "vision.dino_patchcore", "anomaly_detection", {**params, "patch_dim": 0, "background": "project_out_cls"}, ctx
    )
    t2.fit(ds)
    assert t2.bank.shape[1] == 64 and t2.meta["projection"] is None
    with pytest.raises(ValueError, match="layers"):
        registry.create_trainer("vision.dino_patchcore", "anomaly_detection", {**params, "layers": "auto"}, ctx).fit(ds)


def test_finetune_on_multi_layer_features(tmp_path, ctx):
    zoo = tmp_path / "zoo"
    _tiny_dino(zoo, layers=3)
    ctx.zoo = resolver(zoo, {"dinov2-small": "dinov2-small/"})
    root, a, b, ds = _bins(tmp_path, n=8)
    params = {
        "backbone": "dinov2-small",
        "method": "linear",
        "epochs": 3,
        "batch": 4,
        "lr": 5e-3,
        "layers": "1,3",
        "pool": "cls+gem",
        "augment": "none",
    }
    t = registry.create_trainer("vision.dino_finetune", "classification", params, ctx)
    t.fit(ds)
    assert t.net.layers == (1, 3) and t.net.feature_dim == 128 and t.meta["augment"] == []
    assert t.meta["features"]["layers"] == [1, 3] and t.meta["features"]["pool"] == "cls+gem"
    arts = t.export(tmp_path / "out")
    inf = registry.create_inferencer("vision.dino_finetune", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    assert inf.net.layers == (1, 3) and inf.net.feature_dim == 128
    probe = Dataset("IMAGE", "classification", {}, X=a[:2] + b[:2], ids=["a0", "a1", "b0", "b1"], root=root)
    res = inf.predict(probe, "predict", {}, tmp_path / "pred")
    assert [r["prediction"] for r in res.rows] == ["BIN_A", "BIN_A", "BIN_B", "BIN_B"], res.rows
    assert (tmp_path / "pred" / "attention" / "a0.png").exists()
    res = inf.predict(probe, "retrieve", {"k": 2}, tmp_path / "ret")
    assert res.rows[0]["most_similar"][0]["label"] == "BIN_A" and res.rows[0]["attention"]
    assert inf.predict(probe, "embed", {}, tmp_path / "emb").summary["dim"] == 128
    # the default augmentation is crop + hflip; "auto" layers are refused for fine-tuning
    t2 = registry.create_trainer("vision.dino_finetune", "classification", {**params, "augment": True}, ctx)
    from trainer.models.vision import DEFAULT_AUGMENT, parse_augment

    assert parse_augment(True) == DEFAULT_AUGMENT == ("crop", "hflip") and parse_augment("default") == DEFAULT_AUGMENT
    with pytest.raises(ValueError, match="auto"):
        registry.create_trainer("vision.dino_finetune", "classification", {**params, "layers": "auto"}, ctx).fit(ds)
    del t2


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


def test_qwen_pooling_and_layer_options(tmp_path, ctx):
    import pandas as pd

    texts = [f"例行保養完成 第{i}次" for i in range(12)] + [f"真空度異常警報 {i}" for i in range(12)]
    labels = ["info"] * 12 + ["alarm"] * 12
    zoo = tmp_path / "zoo"
    _tiny_qwen(zoo, texts)
    ctx.zoo = resolver(zoo, {"qwen3-embedding-0.6b": "qwen3-embedding-0.6b/"})
    ds = Dataset("TEXT", "classification", {}, X=pd.Series(texts), y=pd.Series(labels), ids=[str(i) for i in range(24)])
    t = registry.create_trainer(
        "text.qwen_embedding", "classification", {"max_len": 16, "pool": "mean", "layers": "last4"}, ctx
    )
    t.fit(ds)
    assert t.meta["pool"] == "mean" and t.meta["layers"] == "last4" and "f1_macro" in t.evaluate()
    arts = t.export(tmp_path / "out")
    inf = registry.create_inferencer("text.qwen_embedding", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    assert inf.encoder.pool == "mean" and inf.encoder.layers == "last4"
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
    assert any(g["name"] == "tool_a" and g["likely_mislabeled"] >= 1 for g in check["per_group"])
    layers = rep["layers"]
    assert layers["kind"] == "dinov2" and [r["layer"] for r in layers["rows"]] == [1, 2, 3]
    assert layers["mid_preset"] == [2, 3] and layers["separability"] and layers["suggested"]
    row = layers["rows"][-1]
    assert {"fisher", "loo_accuracy", "correlates", "description"} <= set(row) and row["description"]
    assert any(c["aspect"] == "brightness" for c in row["correlates"])
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
