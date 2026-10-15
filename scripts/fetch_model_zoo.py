#!/usr/bin/env python3
"""Prepare the offline model zoo: download every pretrained weight listed in model_catalog.yaml on a machine
WITH internet access, verify / record sha256, and write manifest.json. Copy the resulting folder to the
server's MODEL_ZOO_ROOT (default DATA_ROOT/model_zoo). The server itself never downloads anything.

    python3 scripts/fetch_model_zoo.py --dest ./model_zoo               # download all
    python3 scripts/fetch_model_zoo.py --dest ./model_zoo --only yolo11s dinov2-small
    python3 scripts/fetch_model_zoo.py --dest /srv/qr-ai-lab/model_zoo --verify   # on the server, no network

Hugging Face repos (kind: hf_repo) need `pip install huggingface_hub`; plain files use urllib only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "backend" / "app" / "catalog" / "model_catalog.yaml"


def load_weights() -> list[dict]:
    import yaml  # PyYAML

    cat = yaml.safe_load(CATALOG.read_text(encoding="utf-8"))
    seen: dict[str, dict] = {}
    for fid, fam in cat["families"].items():
        for w in fam.get("weights", []):
            seen.setdefault(w["id"], {**w, "families": []})["families"].append(fid)
    return list(seen.values())


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    if path.is_dir():
        for f in sorted(p for p in path.rglob("*") if p.is_file()):
            h.update(f.relative_to(path).as_posix().encode())
            h.update(f.read_bytes())
    else:
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


def download_file(url: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    print(f"  GET {url}")
    with urllib.request.urlopen(url) as r, tmp.open("wb") as f:
        total = int(r.headers.get("Content-Length") or 0)
        done = 0
        while chunk := r.read(1 << 20):
            f.write(chunk)
            done += len(chunk)
            if total:
                print(f"\r  {done / 2**20:8.1f} / {total / 2**20:.1f} MB", end="", flush=True)
    print()
    tmp.replace(dest)


def download_hf_repo(source: str, dest: Path) -> None:
    try:
        from huggingface_hub import snapshot_download
    except ImportError:
        sys.exit("hf_repo weights need `pip install huggingface_hub`")
    repo_id = source.split("huggingface.co/", 1)[1].strip("/")
    print(f"  snapshot {repo_id}")
    snapshot_download(
        repo_id,
        local_dir=str(dest),
        allow_patterns=["*.json", "*.safetensors", "*.txt", "*.model", "tokenizer*", "*.py"],
        ignore_patterns=["*.bin", "*.h5", "*.msgpack", "*.onnx", "*.ot"],
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dest", required=True, type=Path, help="model zoo folder to fill / verify")
    ap.add_argument("--only", nargs="*", default=None, help="weight ids to process (default: all)")
    ap.add_argument("--verify", action="store_true", help="no downloads: check files against manifest.json")
    args = ap.parse_args()
    dest: Path = args.dest
    dest.mkdir(parents=True, exist_ok=True)
    manifest_path = dest / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"weights": {}}
    weights = [w for w in load_weights() if not args.only or w["id"] in args.only]
    problems = 0
    for w in weights:
        target = dest / w["file"].rstrip("/")
        print(f"[{w['id']}] {w['file']}  ({', '.join(w['families'])}; {w['license']})")
        if args.verify:
            if not target.exists():
                print("  MISSING")
                problems += 1
                continue
            digest = sha256_of(target)
            expected = (manifest["weights"].get(w["id"]) or {}).get("sha256") or w.get("sha256")
            if expected and digest != expected:
                print(f"  CHECKSUM MISMATCH {digest[:12]} != {expected[:12]}")
                problems += 1
            else:
                print(f"  ok {digest[:12]}")
            continue
        if target.exists():
            print("  exists, skipping download")
        elif w.get("kind") == "hf_repo":
            download_hf_repo(w["source"], target)
        else:
            download_file(w["source"], target)
        digest = sha256_of(target)
        if w.get("sha256") and digest != w["sha256"]:
            print(f"  WARNING checksum differs from catalog: {digest}")
            problems += 1
        manifest["weights"][w["id"]] = {
            "file": w["file"],
            "sha256": digest,
            "source": w["source"],
            "license": w["license"],
            "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        print(f"  sha256 {digest[:12]}")
    if not args.verify:
        manifest["generated_at"] = datetime.now(UTC).isoformat(timespec="seconds")
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\nmanifest written: {manifest_path}")
    if problems:
        print(f"\n{problems} problem(s)")
        return 1
    print("\nall weights present")
    return 0


if __name__ == "__main__":
    sys.exit(main())
