# QR AI Lab trainer image: CUDA runtime + Python 3.12 + the trainer package (all model families).
# Build (context = repo root, because trainer depends on libs/preprocess):
#   docker build -t qr-ai-lab/trainer:dev -f infra/trainer/Dockerfile .
# The image never downloads weights: pretrained models are mounted read-only at /job/zoo (MODEL_ZOO_ROOT).
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu24.04

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    HF_DATASETS_OFFLINE=1 \
    YOLO_OFFLINE=1 \
    YOLO_CONFIG_DIR=/tmp/ultralytics \
    MPLCONFIGDIR=/tmp/matplotlib \
    HOME=/tmp

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv libgl1 libglib2.0-0 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY libs/preprocess /libs/preprocess
WORKDIR /app
COPY trainer/pyproject.toml trainer/uv.lock ./
# uv.lock pins the PyPI torch build (bundles CUDA libraries; needs a driver that supports it). To pin a
# different CUDA line instead, add e.g. `--index https://download.pytorch.org/whl/cu124 --index-strategy unsafe-best-match`
# and drop --frozen so the resolution can change.
RUN uv sync --frozen --no-dev --extra dl --no-install-project
COPY trainer/trainer ./trainer

# Hardened at runtime by the scheduler (read-only rootfs, cap_drop ALL, user 1000); make the dirs it needs.
RUN mkdir -p /job/input /job/output /job/model /job/zoo && chown -R 1000:1000 /job
USER 1000:1000
ENV PATH="/opt/venv/bin:$PATH"
ENTRYPOINT ["python", "-m", "trainer"]
CMD ["run"]
