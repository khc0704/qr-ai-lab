"""Pull the user's data source into the job input dir. Credentials come only from env (never logged).

Object keys and download names are chosen by the user's server, so every file lands through ``safe_join``:
a listing such as ``../../model_zoo/x.pt`` fails the job with the offending key in the message instead of
writing outside the input dir.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote, urlparse

from trainer.log import info
from trainer.paths import safe_filename, safe_join


def fetch_data_source(ds: dict, input_dir: Path, progress) -> None:
    input_dir.mkdir(parents=True, exist_ok=True)
    if ds["kind"] == "minio":
        _fetch_minio(ds, input_dir, progress)
    elif ds["kind"] == "url":
        _fetch_url(ds, input_dir, progress)
    else:
        raise ValueError(f"unknown data source kind {ds['kind']}")


def _object_relpath(object_name: str, base: str) -> str:
    return object_name[len(base) :] if base and object_name.startswith(base) else object_name


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
    # validate every key before downloading anything: one bad key fails the job with a readable message
    targets: list[tuple[str, Path]] = []
    for o in objects:
        try:
            targets.append((o.object_name, safe_join(input_dir, _object_relpath(o.object_name, base))))
        except ValueError as e:
            raise ValueError(f"資料來源物件名稱不安全，已中止：{o.object_name!r}（{e}）") from e
    total = 0
    for i, (o, (key, target)) in enumerate(zip(objects, targets, strict=True), 1):
        target.parent.mkdir(parents=True, exist_ok=True)
        client.fget_object(bucket, key, str(target))
        total += o.size or 0
        if i % 200 == 0 or i == len(objects):
            progress(i / len(objects))
    info(f"fetch: done {len(objects)} files, {total / 2**20:.1f} MB")


_DISPOSITION_EXT = re.compile(r"filename\*\s*=\s*(?:[\w-]+)?''([^;]+)", re.IGNORECASE)
_DISPOSITION = re.compile(r'filename\s*=\s*"?([^";]+)"?', re.IGNORECASE)


def download_name(url: str, content_disposition: str | None = None) -> str:
    """File name for a URL download: Content-Disposition if present, else the URL path; never a directory."""
    if content_disposition:
        m = _DISPOSITION_EXT.search(content_disposition) or _DISPOSITION.search(content_disposition)
        if m:
            name = safe_filename(unquote(m.group(1)), default="")
            if name:
                return name
    return safe_filename(unquote(Path(urlparse(url).path).name), default="data")


def _fetch_url(ds: dict, input_dir: Path, progress) -> None:
    import httpx

    url = ds["url"]
    with (
        httpx.Client(timeout=60, follow_redirects=True) as client,
        client.stream("GET", url, headers=ds.get("headers") or {}) as r,
    ):
        r.raise_for_status()
        name = download_name(url, r.headers.get("content-disposition"))
        target = safe_join(input_dir, name)
        info(f"fetch: url {url} → {name}")
        total = int(r.headers.get("content-length") or 0)
        done = 0
        with target.open("wb") as f:
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
                done += len(chunk)
                if total:
                    progress(done / total)
    info(f"fetch: done {target.stat().st_size / 2**20:.1f} MB")
