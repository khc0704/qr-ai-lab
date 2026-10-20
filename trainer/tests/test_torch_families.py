"""PyTorch families on CPU with tiny synthetic data and tiny locally-built 'zoo' weights (nothing downloaded)."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

torch = pytest.importorskip("torch")

from trainer.dataset import Dataset  # noqa: E402
from trainer.models import registry  # noqa: E402
from trainer.models.zoo import resolver  # noqa: E402


def spectra(n: int = 320, T: int = 128, seed: int = 0, shift_last: int = 40, spread: float = 0.0):
    rng = np.random.default_rng(seed)
    x = np.linspace(0, 1, T)
    X = np.zeros((n, T), np.float32)
    y = np.zeros(n, int)
    centers = rng.uniform(0.5 - spread, 0.5 + spread, size=n) + rng.normal(scale=0.01, size=n)
    if shift_last:
        centers[-shift_last:] = 0.72  # shifted peak = anomaly
        y[-shift_last:] = 1
    for i in range(n):
        X[i] = 0.2 + np.exp(-((x - centers[i]) ** 2) / (2 * 0.05**2)) + rng.normal(scale=0.01, size=T)
    return X, y, centers


@pytest.mark.parametrize(
    "fid,params",
    [
        ("sequence.patch_autoencoder", {"epochs": 30, "patch_size": 16, "latent": 16, "layers": 2, "lr": 3e-3}),
        (
            "spectrum.masked_autoencoder",
            {"epochs": 25, "patch_size": 16, "dim": 32, "depth": 1, "heads": 2, "mask_ratio": 0.5, "lr": 3e-3},
        ),
    ],
)
def test_autoencoder_anomaly_roundtrip(tmp_path, ctx, fid, params):
    X, y, _ = spectra()
    ds = Dataset("SPECTRUM", "anomaly_detection", {}, X=X, y=y, ids=[f"s{i}" for i in range(len(X))])
    epochs: list[int] = []
    ctx.on_epoch = lambda e, m: epochs.append(e)
    t = registry.create_trainer(fid, "anomaly_detection", params, ctx)
    t.fit(ds)
    m = t.evaluate()
    assert len(epochs) == params["epochs"] and "auroc" in m and m["auroc"] > 0.6, m
    arts = t.export(tmp_path)
    assert (tmp_path / "model" / "model.pt").exists() and (tmp_path / "model" / "reference.npz").exists()

    inf = registry.create_inferencer(fid, ctx)
    inf.load(tmp_path / "model", arts[0].metadata)
    probe = Dataset("SPECTRUM", "anomaly_detection", {}, X=X[-5:], ids=["a1", "a2", "a3", "a4", "a5"])
    res = inf.predict(probe, "score", {}, tmp_path)
    assert len(res.rows) == 5 and "threshold" in res.summary and res.summary["flagged"] >= 3
    res = inf.predict(probe, "embed", {}, tmp_path)
    assert len(res.rows[0]["embedding"]) == res.summary["dim"] and (tmp_path / "embeddings.npy").exists()
    res = inf.predict(probe, "retrieve", {"k": 3}, tmp_path)
    row = res.rows[0]
    assert len(row["most_similar"]) == 3 and len(row["least_similar"]) == 3 and 0 <= row["novelty"] <= 2
    assert row["most_similar"][0]["similarity"] >= row["least_similar"][0]["similarity"]
    assert res.summary["most_novel"] and res.summary["reference_size"] > 0
    # a different window length is resampled onto the training length
    res = inf.predict(Dataset("SPECTRUM", None, {}, X=X[:2, ::2], ids=["h1", "h2"]), "score", {}, tmp_path)
    assert len(res.rows) == 2


def test_mae_regression_head(tmp_path, ctx):
    X, _, centers = spectra(shift_last=0, spread=0.2)
    ds = Dataset("SPECTRUM", "regression", {}, X=X, y=centers * 100, ids=[str(i) for i in range(len(X))])
    params = {"epochs": 10, "patch_size": 16, "dim": 32, "depth": 1, "heads": 2, "mask_ratio": 0.4}
    t = registry.create_trainer("spectrum.masked_autoencoder", "regression", params, ctx)
    t.fit(ds)
    m = t.evaluate()
    assert m["rmse"] < 15 and "predict" in t.inference_modes, m
    arts = t.export(tmp_path)
    inf = registry.create_inferencer("spectrum.masked_autoencoder", ctx)
    inf.load(tmp_path / "model", arts[0].metadata)
    res = inf.predict(Dataset("SPECTRUM", "regression", {}, X=X[:4], ids=list("abcd")), "predict", {}, tmp_path)
    assert len(res.rows) == 4 and 20 < res.rows[0]["prediction"] < 80


# --- tiny local 'zoo' models ---------------------------------------------------------------------


def _tiny_bert(zoo: Path, texts: list[str]) -> None:
    from transformers import BertConfig, BertModel, BertTokenizerFast

    d = zoo / "bert-base-chinese"
    d.mkdir(parents=True)
    vocab = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]", *sorted({ch for t in texts for ch in t})]
    (d / "vocab.txt").write_text("\n".join(vocab), encoding="utf-8")
    BertTokenizerFast(vocab_file=str(d / "vocab.txt")).save_pretrained(d)
    cfg = BertConfig(
        vocab_size=len(vocab),
        hidden_size=32,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=64,
        max_position_embeddings=64,
    )
    BertModel(cfg).save_pretrained(d)


def test_bert_classifier_tiny(tmp_path, ctx):
    pytest.importorskip("transformers")
    alarms = ["機台溫度過高警報", "晶圓破片停機", "真空度異常警報", "冷卻水流量不足"]
    infos = ["例行保養完成", "批次作業正常結束", "配方更新完成", "每日點檢正常"]
    texts = [t + str(i % 7) for i in range(14) for t in alarms] + [t + str(i % 7) for i in range(14) for t in infos]
    labels = ["alarm"] * (14 * 4) + ["info"] * (14 * 4)
    zoo = tmp_path / "zoo"
    _tiny_bert(zoo, texts)
    ctx.zoo = resolver(zoo, {"bert-base-chinese": "bert-base-chinese/"})
    import pandas as pd

    ds = Dataset(
        "TEXT", "classification", {}, X=pd.Series(texts), y=pd.Series(labels), ids=[str(i) for i in range(len(texts))]
    )
    t = registry.create_trainer(
        "text.bert_classifier", "classification", {"epochs": 2, "batch": 8, "max_len": 16, "lr": 5e-4}, ctx
    )
    t.fit(ds)
    assert "f1_macro" in t.evaluate()
    arts = t.export(tmp_path / "out")
    assert (tmp_path / "out" / "model" / "bert" / "config.json").exists()
    inf = registry.create_inferencer("text.bert_classifier", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    res = inf.predict(
        Dataset("TEXT", "classification", {}, X=pd.Series(["溫度警報", "保養完成"]), ids=["a", "b"]),
        "predict",
        {},
        tmp_path,
    )
    assert {r["prediction"] for r in res.rows} <= {"alarm", "info"} and "proba_alarm" in res.rows[0]
    res = inf.predict(
        Dataset("TEXT", "classification", {}, X=pd.Series(["溫度警報"]), ids=["a"]), "embed", {}, tmp_path
    )
    assert len(res.rows[0]["embedding"]) == 32


def _tiny_dino(zoo: Path) -> None:
    from transformers import BitImageProcessor, Dinov2Config, Dinov2Model

    d = zoo / "dinov2-small"
    d.mkdir(parents=True)
    cfg = Dinov2Config(
        hidden_size=32, num_hidden_layers=1, num_attention_heads=2, intermediate_size=64, image_size=56, patch_size=14
    )
    Dinov2Model(cfg).save_pretrained(d)
    BitImageProcessor(size={"shortest_edge": 56}, crop_size={"height": 56, "width": 56}).save_pretrained(d)


def _images(root: Path, cls: str, n: int, kind: str, seed: int) -> list[Path]:
    from PIL import Image

    rng = np.random.default_rng(seed)
    out = []
    for i in range(n):
        a = (
            rng.integers(0, 60, size=(64, 64), dtype=np.uint8)
            if kind != "bright"
            else rng.integers(180, 255, size=(64, 64), dtype=np.uint8)
        )
        if kind == "blob":
            a[20:44, 20:44] = 255
        p = root / cls / f"{cls}_{i}.png"
        p.parent.mkdir(parents=True, exist_ok=True)
        Image.fromarray(a, mode="L").save(p)
        out.append(p)
    return out


def test_dino_fewshot_extend_and_patchcore(tmp_path, ctx):
    pytest.importorskip("transformers")
    pytest.importorskip("PIL")
    zoo = tmp_path / "zoo"
    _tiny_dino(zoo)
    ctx.zoo = resolver(zoo, {"dinov2-small": "dinov2-small/"})
    root = tmp_path / "imgs"
    a = _images(root, "BIN_A", 6, "dark", 1)
    b = _images(root, "BIN_B", 6, "bright", 2)
    ds = Dataset(
        "IMAGE", "classification", {}, X=a + b, y=["BIN_A"] * 6 + ["BIN_B"] * 6, ids=[p.name for p in a + b], root=root
    )
    t = registry.create_trainer("vision.dino_fewshot", "classification", {"backbone": "dinov2-small", "k": 3}, ctx)
    t.fit(ds)
    assert t.evaluate()["accuracy"] >= 0.5 and t.meta["classes"] == ["BIN_A", "BIN_B"]
    arts = t.export(tmp_path / "out")
    inf = registry.create_inferencer("vision.dino_fewshot", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    res = inf.predict(
        Dataset("IMAGE", "classification", {}, X=a[:2] + b[:2], ids=["a0", "a1", "b0", "b1"], root=root),
        "predict",
        {},
        tmp_path,
    )
    assert [r["prediction"] for r in res.rows] == ["BIN_A", "BIN_A", "BIN_B", "BIN_B"]
    res = inf.predict(
        Dataset("IMAGE", "classification", {}, X=a[:1], ids=["a0"], root=root), "retrieve", {"k": 2}, tmp_path
    )
    assert res.rows[0]["most_similar"][0]["label"] == "BIN_A"
    # add a new bin code without retraining the backbone
    c = _images(root, "BIN_C", 4, "blob", 3)
    out2 = tmp_path / "out2" / "output"
    out2.mkdir(parents=True)
    res = inf.predict(
        Dataset("IMAGE", "classification", {}, X=c, y=["BIN_C"] * 4, ids=[p.name for p in c], root=root),
        "extend",
        {},
        out2,
    )
    assert res.summary["new_classes"] == ["BIN_C"] and res.extra_artifacts[0].set_default
    bank = np.load(tmp_path / "out2" / "model" / "prototypes.npz")
    assert bank["classes"].tolist() == ["BIN_A", "BIN_B", "BIN_C"] and len(bank["support"]) == 16

    # PatchCore: normal = dark noise, anomaly = bright blob
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
    t = registry.create_trainer(
        "vision.dino_patchcore", "anomaly_detection", {"backbone": "dinov2-small", "coreset_ratio": 0.5, "k": 1}, ctx
    )
    t.fit(ds)
    m = t.evaluate()
    assert "auroc" in m and m["threshold"] > 0
    arts = t.export(tmp_path / "pc_out")
    inf = registry.create_inferencer("vision.dino_patchcore", ctx)
    inf.load(tmp_path / "pc_out" / "model", arts[0].metadata)
    out3 = tmp_path / "pc_pred"
    out3.mkdir()
    res = inf.predict(
        Dataset(
            "IMAGE", "anomaly_detection", {}, X=normal[:2] + bad[:2], ids=["n0", "n1", "d0", "d1"], root=tmp_path / "pc"
        ),
        "score",
        {},
        out3,
    )
    assert len(res.rows) == 4 and (out3 / "heatmaps").exists() and res.extra_artifacts[0].path == "output/heatmaps"
    assert max(r["anomaly_score"] for r in res.rows[2:]) > min(r["anomaly_score"] for r in res.rows[:2])
    assert json.dumps(res.summary)  # serialisable


@pytest.mark.parametrize("method", ["linear", "lora", "full"])
def test_dino_finetune_roundtrip(tmp_path, ctx, method):
    pytest.importorskip("transformers")
    pytest.importorskip("PIL")
    from trainer.models.vision import inject_lora, lora_state

    zoo = tmp_path / "zoo"
    _tiny_dino(zoo)
    ctx.zoo = resolver(zoo, {"dinov2-small": "dinov2-small/"})
    root = tmp_path / "imgs"
    a = _images(root, "BIN_A", 8, "dark", 1)
    b = _images(root, "BIN_B", 8, "bright", 2)
    ds = Dataset(
        "IMAGE", "classification", {}, X=a + b, y=["BIN_A"] * 8 + ["BIN_B"] * 8, ids=[p.name for p in a + b], root=root
    )
    epochs: list[int] = []
    ctx.on_epoch = lambda e, m: epochs.append(e)
    params = {"backbone": "dinov2-small", "method": method, "epochs": 4, "batch": 4, "lr": 5e-3, "rank": 2}
    t = registry.create_trainer("vision.dino_finetune", "classification", params, ctx)
    t.fit(ds)
    assert epochs == [1, 2, 3, 4] and t.meta["classes"] == ["BIN_A", "BIN_B"] and t.meta["method"] == method
    assert t.evaluate()["accuracy"] >= 0.5
    if method == "lora":
        assert t.net.lora_layers == 3  # one layer × query / key / value
        assert all(".lora_" in k for k in lora_state(t.net.backbone)) and lora_state(t.net.backbone)
        # the base projections never train; only adapters and the head do
        assert all(not p.requires_grad for n, p in t.net.backbone.named_parameters() if ".lora_" not in n)
    if method == "linear":
        assert not any(p.requires_grad for p in t.net.backbone.parameters())
    arts = t.export(tmp_path / "out")
    model_dir = tmp_path / "out" / "model"
    assert (model_dir / "head.pt").exists() and (model_dir / "reference.npz").exists()
    assert (model_dir / "lora.pt").exists() == (method == "lora")
    assert (model_dir / "backbone").is_dir() == (method == "full")
    assert arts[0].name == f"dino_{method}" and arts[0].metadata["inference_modes"] == ["predict", "embed", "retrieve"]

    inf = registry.create_inferencer("vision.dino_finetune", ctx)
    inf.load(model_dir, arts[0].metadata)
    probe = Dataset("IMAGE", "classification", {}, X=a[:2] + b[:2], ids=["a0", "a1", "b0", "b1"], root=root)
    res = inf.predict(probe, "predict", {}, tmp_path / "pred")
    assert [r["prediction"] for r in res.rows] == ["BIN_A", "BIN_A", "BIN_B", "BIN_B"], res.rows
    assert len(res.rows[0]["top3"]) == 2 and res.summary["class_counts"] == {"BIN_A": 2, "BIN_B": 2}
    assert res.rows[0]["attention"] == "attention/a0.png" and (tmp_path / "pred" / "attention" / "a0.png").exists()
    res = inf.predict(probe, "predict", {"min_confidence": 1.01}, tmp_path / "pred")
    assert {r["prediction"] for r in res.rows} == {"unknown"}
    res = inf.predict(probe, "retrieve", {"k": 2}, tmp_path / "pred")
    assert res.rows[0]["most_similar"][0]["label"] == "BIN_A" and len(res.rows[0]["most_similar"]) == 2
    assert res.rows[0]["neighbors"] == res.rows[0]["most_similar"] and res.rows[0]["attention"]
    res = inf.predict(probe, "embed", {}, tmp_path / "pred")
    assert len(res.rows[0]["embedding"]) == 64 and (tmp_path / "pred" / "embeddings.npy").exists()
    if method == "lora":
        # inject_lora is idempotent in count: a fresh backbone gets exactly the three wrapped layers
        from transformers import AutoModel

        m = AutoModel.from_pretrained(str(zoo / "dinov2-small"), local_files_only=True)
        assert inject_lora(m, 2, 4.0) == 3


def _tiny_dino3(zoo: Path, name: str = "dinov3-vits16") -> None:
    """A DINOv3-shaped backbone: 4 register tokens between CLS and the patches, patch size 16."""
    from transformers import BitImageProcessor, DINOv3ViTConfig, DINOv3ViTModel

    d = zoo / name
    d.mkdir(parents=True)
    cfg = DINOv3ViTConfig(
        hidden_size=32,
        num_hidden_layers=1,
        num_attention_heads=2,
        intermediate_size=64,
        image_size=64,
        patch_size=16,
        num_register_tokens=4,
    )
    DINOv3ViTModel(cfg).save_pretrained(d)
    BitImageProcessor(size={"shortest_edge": 64}, crop_size={"height": 64, "width": 64}).save_pretrained(d)


def test_dinov3_register_tokens_attention_and_retrieve_order(tmp_path, ctx):
    pytest.importorskip("transformers")
    pytest.importorskip("PIL")
    from PIL import Image

    from trainer.models.vision import _Dino

    zoo = tmp_path / "zoo"
    _tiny_dino3(zoo)
    ctx.zoo = resolver(zoo, {"dinov3-vits16": "dinov3-vits16/"})
    dino = _Dino(ctx, "dinov3-vits16")
    assert dino.n_special == 5  # CLS + 4 registers are not part of the spatial grid
    root = tmp_path / "imgs"
    a = _images(root, "BIN_A", 6, "dark", 1)
    b = _images(root, "BIN_B", 6, "bright", 2)
    _, patches = dino.embed(a[:2], patches=True)
    assert patches.shape[1] == 16  # (64 / 16)² patches, registers skipped
    ds = Dataset(
        "IMAGE", "classification", {}, X=a + b, y=["BIN_A"] * 6 + ["BIN_B"] * 6, ids=[p.name for p in a + b], root=root
    )
    t = registry.create_trainer("vision.dino_fewshot", "classification", {"backbone": "dinov3-vits16", "k": 3}, ctx)
    t.fit(ds)
    arts = t.export(tmp_path / "out")
    inf = registry.create_inferencer("vision.dino_fewshot", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    probe = Dataset("IMAGE", "classification", {}, X=a[:1] + b[:1], ids=["q/a0.png", "q/b0.png"], root=root)
    out = tmp_path / "pred"
    res = inf.predict(probe, "predict", {}, out)
    assert [r["prediction"] for r in res.rows] == ["BIN_A", "BIN_B"]
    assert res.rows[0]["attention"] == "attention/q__a0.png" and (out / "attention" / "q__a0.png").exists()
    overlay = Image.open(out / "attention" / "q__a0.png")
    assert overlay.mode == "RGBA" and overlay.size == (64, 64)
    # retrieve: the caller picks the direction; the overlay follows the chosen neighbour
    res = inf.predict(probe, "retrieve", {"k": 2, "order": "dissimilar"}, tmp_path / "ret")
    assert "least_similar" in res.rows[0] and "most_similar" not in res.rows[0]
    assert res.rows[0]["neighbors"][0]["label"] == "BIN_B" and res.summary["order"] == "dissimilar"
    assert (tmp_path / "ret" / "attention" / "q__a0.png").exists()
    res = inf.predict(probe, "retrieve", {"k": 2, "order": "similar", "attention": False}, tmp_path / "ret2")
    assert res.rows[0]["neighbors"][0]["label"] == "BIN_A" and "attention" not in res.rows[0]
    assert not (tmp_path / "ret2" / "attention").exists()
    with pytest.raises(ValueError):
        inf.predict(probe, "retrieve", {"order": "sideways"}, tmp_path / "ret3")


def _tiny_qwen(zoo: Path, texts: list[str], name: str = "qwen3-embedding-0.6b") -> None:
    """A character-level Qwen3 (hidden 32) saved like a Hugging Face snapshot: left-padding tokenizer + model."""
    from tokenizers import Regex, Tokenizer, models, pre_tokenizers
    from transformers import PreTrainedTokenizerFast, Qwen3Config, Qwen3Model

    d = zoo / name
    d.mkdir(parents=True)
    chars = sorted({ch for t in texts for ch in t})
    vocab = {"<|endoftext|>": 0, "<unk>": 1, **{c: i + 2 for i, c in enumerate(chars)}}
    tok = Tokenizer(models.WordLevel(vocab, unk_token="<unk>"))
    tok.pre_tokenizer = pre_tokenizers.Split(Regex("."), "isolated")
    PreTrainedTokenizerFast(
        tokenizer_object=tok,
        pad_token="<|endoftext|>",
        eos_token="<|endoftext|>",
        unk_token="<unk>",
        padding_side="left",
    ).save_pretrained(d)
    cfg = Qwen3Config(
        vocab_size=len(vocab),
        hidden_size=32,
        num_hidden_layers=1,
        num_attention_heads=2,
        num_key_value_heads=1,
        head_dim=16,
        intermediate_size=64,
        max_position_embeddings=64,
    )
    Qwen3Model(cfg).save_pretrained(d)


def test_qwen_embedding_classification_retrieve_and_embed(tmp_path, ctx):
    pytest.importorskip("transformers")
    import pandas as pd

    alarms = ["機台溫度過高警報", "晶圓破片停機", "真空度異常警報", "冷卻水流量不足"]
    infos = ["例行保養完成", "批次作業正常結束", "配方更新完成", "每日點檢正常"]
    texts = [t + str(i % 5) for i in range(6) for t in alarms] + [t + str(i % 5) for i in range(6) for t in infos]
    labels = ["alarm"] * (6 * 4) + ["info"] * (6 * 4)
    zoo = tmp_path / "zoo"
    _tiny_qwen(zoo, texts)
    ctx.zoo = resolver(zoo, {"qwen3-embedding-0.6b": "qwen3-embedding-0.6b/"})
    ds = Dataset(
        "TEXT", "classification", {}, X=pd.Series(texts), y=pd.Series(labels), ids=[f"t{i}" for i in range(len(texts))]
    )
    t = registry.create_trainer("text.qwen_embedding", "classification", {"max_len": 16, "batch": 8}, ctx)
    t.fit(ds)
    assert "f1_macro" in t.evaluate() and t.inference_modes == ["predict", "retrieve", "embed"]
    t.finalize(ds)
    arts = t.export(tmp_path / "out")
    model_dir = tmp_path / "out" / "model"
    assert (model_dir / "reference.npz").exists() and (model_dir / "head.joblib").exists()
    assert arts[0].metadata["dim"] == 32 and arts[0].metadata["base"] == "qwen3-embedding-0.6b"
    # the artifact holds no backbone: the inferencer loads it from the zoo again
    inf = registry.create_inferencer("text.qwen_embedding", ctx)
    inf.load(model_dir, arts[0].metadata)
    q = Dataset("TEXT", "classification", {}, X=pd.Series(["溫度警報", "保養完成"]), ids=["a", "b"])
    res = inf.predict(q, "predict", {}, tmp_path / "p1")
    assert {r["prediction"] for r in res.rows} <= {"alarm", "info"} and "proba_alarm" in res.rows[0]
    res = inf.predict(q, "predict", {"min_confidence": 1.01}, tmp_path / "p1b")
    assert {r["prediction"] for r in res.rows} == {"unknown"}
    res = inf.predict(q, "embed", {}, tmp_path / "p2")
    assert len(res.rows[0]["embedding"]) == 32 and (tmp_path / "p2" / "embeddings.npy").exists()
    assert abs(np.linalg.norm(res.rows[0]["embedding"]) - 1) < 1e-3
    res = inf.predict(q, "retrieve", {"order": "dissimilar", "k": 3}, tmp_path / "p3")
    row = res.rows[0]
    assert "least_similar" in row and "most_similar" not in row and len(row["neighbors"]) == 3
    assert row["neighbors"][0]["label"] in ("alarm", "info") and res.summary["order"] == "dissimilar"
    assert res.summary["reference_size"] == len(texts) and len(res.summary["most_novel"]) == 2
    res = inf.predict(q, "retrieve", {"reference": "self", "k": 1}, tmp_path / "p4")
    assert res.rows[0]["most_similar"][0]["id"] == "b" and res.rows[1]["most_similar"][0]["id"] == "a"
    with pytest.raises(ValueError, match="order"):
        inf.predict(q, "retrieve", {"order": "nearest"}, tmp_path / "p5")


def test_qwen_embedding_novelty_scores(tmp_path, ctx):
    pytest.importorskip("transformers")
    import pandas as pd

    normal = [f"例行保養完成 第{i}次" for i in range(30)]
    odd = ["真空幫浦起火 緊急停機", "冷卻水大量外漏"]
    zoo = tmp_path / "zoo"
    _tiny_qwen(zoo, normal + odd)
    ctx.zoo = resolver(zoo, {"qwen3-embedding-0.6b": "qwen3-embedding-0.6b/"})
    ds = Dataset(
        "TEXT",
        "anomaly_detection",
        {},
        X=pd.Series(normal + odd),
        y=pd.Series(["normal"] * 30 + ["odd"] * 2),
        ids=[str(i) for i in range(32)],
    )
    t = registry.create_trainer("text.qwen_embedding", "anomaly_detection", {"max_len": 16}, ctx)
    t.fit(ds)
    m = t.evaluate()
    assert m["threshold"] >= 0 and t.inference_modes == ["score", "retrieve", "embed"]
    arts = t.export(tmp_path / "out")
    assert not (tmp_path / "out" / "model" / "head.joblib").exists()
    inf = registry.create_inferencer("text.qwen_embedding", ctx)
    inf.load(tmp_path / "out" / "model", arts[0].metadata)
    res = inf.predict(
        Dataset("TEXT", None, {}, X=pd.Series([normal[0], odd[0]]), ids=["n", "o"]), "score", {}, tmp_path / "s"
    )
    assert res.summary["mode"] == "score" and res.rows[0]["anomaly_score"] <= res.rows[1]["anomaly_score"]
    assert {"anomaly_score", "is_anomaly"} <= set(res.rows[0])
    # predict on a novelty model is the same as score (no classification head)
    res = inf.predict(Dataset("TEXT", None, {}, X=pd.Series(["x"]), ids=["x"]), "predict", {}, tmp_path / "s2")
    assert res.summary["mode"] == "score" and "anomaly_score" in res.rows[0]
