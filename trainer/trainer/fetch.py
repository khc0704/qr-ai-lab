"""Pull the user's data source into the job input dir. Credentials come only from env (never logged)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from trainer.log import info


def fetch_data_source(ds: dict, input_dir: Path, progress) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    if ds["kind"] == "minio":
        _fetch_minio(ds, input_dir, progress)
    elif ds["kind"] == "url":
        _fetch_url(ds, input_dir, progress)
    else:
        raise ValueError(f"unknown data source kind {ds['kind']}")


def _fetch_minio(ds: dict, input_dir: Path, progress) -> None:
    from minio import Minio

    u = urlparse(ds["endpoint"])
    client = Minio(
        u.netloc,
        access_key=ds.get("access_key") or None,
        secret_key=ds.get("secret_key") or None,
        secure=(u.scheme == "https"),
        region=ds.get("region") or None,
    )
    bucket, prefix = ds["bucket"], ds.get("object_path", "").lstrip("/")
    objects = [o for o in client.list_objects(bucket, prefix=prefix, recursive=True) if not o.is_dir]
    if not objects:
        raise FileNotFoundError(f"no objects under {bucket}/{prefix}")
    info(f"fetch: minio {u.netloc}/{bucket}/{prefix} → {len(objects)} objects")
    base = prefix if prefix.endswith("/") else prefix.rsplit("/", 1)[0] + "/" if "/" in prefix else ""
    total = 0
    for i, o in enumerate(objects, 1):
        rel = o.object_name[len(base) :] if o.object_name.startswith(base) else Path(o.object_name).name
        target = input_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        client.fget_object(bucket, o.object_name, str(target))
        total += o.size or 0
        if i % 200 == 0 or i == len(objects):
            progress(i / len(objects))
    info(f"fetch: done {len(objects)} files, {total / 2**20:.1f} MB")


def _fetch_url(ds: dict, input_dir: Path, progress) -> None:
    import httpx

    url = ds["url"]
    name = Path(urlparse(url).path).name or "data"
    target = input_dir / name
    info(f"fetch: url {url} → {name}")
    with (
        httpx.Client(timeout=60, follow_redirects=True) as client,
        client.stream("GET", url, headers=ds.get("headers") or {}) as r,
    ):
        r.raise_for_status()
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with target.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    progress(done / total)
    info(f"fetch: done {target.stat().st_size / 2**20:.1f} MB")
