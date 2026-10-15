"""Image ops on lists of PIL images. Geometric ops are refused for detection / segmentation (box / mask labels)."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter, ImageOps

from qrlab_preprocess.base import Context, Op, Param, register, unjson_image

IMG = ("IMAGE",)


class _ImageMap(Op):
    data_types = IMG

    def one(self, im: Image.Image) -> Image.Image:
        raise NotImplementedError

    def apply(self, images: list[Image.Image], ctx: Context) -> list[Image.Image]:
        return [self.one(im) for im in images]


@register
class Resize(_ImageMap):
    id = "image.resize"
    label = "縮放"
    geometric = True
    params = (
        Param("width", "寬", "int", default=512, min=8, max=8192),
        Param("height", "高（0 = 依比例）", "int", default=0, min=0, max=8192),
    )

    def one(self, im: Image.Image) -> Image.Image:
        w = self.p["width"]
        h = self.p["height"] or max(1, round(im.height * w / im.width))
        return im.resize((w, h), Image.BILINEAR)


@register
class Grayscale(_ImageMap):
    id = "image.grayscale"
    label = "轉灰階"

    def one(self, im: Image.Image) -> Image.Image:
        return im.convert("L")


@register
class Crop(_ImageMap):
    id = "image.crop"
    label = "裁切（比例）"
    description = "以 0–1 的比例指定保留區域，例如去掉 SEM 底部的資訊列：bottom=0.9。"
    geometric = True
    params = (
        Param("left", "左", "float", default=0.0, min=0, max=1),
        Param("top", "上", "float", default=0.0, min=0, max=1),
        Param("right", "右", "float", default=1.0, min=0, max=1),
        Param("bottom", "下", "float", default=1.0, min=0, max=1),
    )

    def one(self, im: Image.Image) -> Image.Image:
        w, h = im.size
        box = (int(self.p["left"] * w), int(self.p["top"] * h), int(self.p["right"] * w), int(self.p["bottom"] * h))
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("裁切範圍無效")
        return im.crop(box)


@register
class CenterCrop(_ImageMap):
    id = "image.center_crop"
    label = "中央裁切"
    geometric = True
    params = (Param("fraction", "保留比例", "float", default=0.8, min=0.05, max=1.0),)

    def one(self, im: Image.Image) -> Image.Image:
        w, h = im.size
        f = self.p["fraction"]
        cw, ch = max(1, int(w * f)), max(1, int(h * f))
        left, top = (w - cw) // 2, (h - ch) // 2
        return im.crop((left, top, left + cw, top + ch))


@register
class Autocontrast(_ImageMap):
    id = "image.autocontrast"
    label = "自動對比"
    params = (Param("cutoff", "忽略兩端百分比", "float", default=1.0, min=0, max=20),)

    def one(self, im: Image.Image) -> Image.Image:
        return ImageOps.autocontrast(im, cutoff=self.p["cutoff"])


@register
class Equalize(_ImageMap):
    id = "image.equalize"
    label = "直方圖均衡"

    def one(self, im: Image.Image) -> Image.Image:
        return ImageOps.equalize(im)


@register
class Gamma(_ImageMap):
    id = "image.gamma"
    label = "Gamma 校正"
    params = (Param("gamma", "gamma", "float", default=1.0, min=0.1, max=5.0),)

    def one(self, im: Image.Image) -> Image.Image:
        lut = [int(255 * ((i / 255) ** (1 / self.p["gamma"]))) for i in range(256)]
        return im.point(lut * len(im.getbands()))


@register
class PercentileStretch(_ImageMap):
    id = "image.stretch"
    label = "百分位拉伸"
    description = "把 low–high 百分位的亮度拉到 0–255，壓掉極端亮暗點。"
    params = (
        Param("low", "低百分位", "float", default=1.0, min=0, max=49),
        Param("high", "高百分位", "float", default=99.0, min=51, max=100),
    )

    def one(self, im: Image.Image) -> Image.Image:
        a = np.asarray(im).astype(np.float32)
        lo, hi = np.percentile(a, [self.p["low"], self.p["high"]])
        a = np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1) * 255
        return Image.fromarray(a.astype(np.uint8), mode=im.mode if im.mode in ("L", "RGB") else None)


@register
class Denoise(_ImageMap):
    id = "image.denoise"
    label = "去雜訊"
    params = (
        Param("method", "方法", "choice", default="median", choices=("median", "gaussian")),
        Param("size", "大小", "int", default=3, min=1, max=15),
    )

    def one(self, im: Image.Image) -> Image.Image:
        if self.p["method"] == "median":
            size = self.p["size"] if self.p["size"] % 2 else self.p["size"] + 1
            return im.filter(ImageFilter.MedianFilter(size))
        return im.filter(ImageFilter.GaussianBlur(self.p["size"] / 2))


@register
class Sharpen(_ImageMap):
    id = "image.sharpen"
    label = "銳利化（unsharp mask）"
    params = (
        Param("radius", "半徑", "float", default=2.0, min=0.1, max=20),
        Param("percent", "強度 %", "int", default=150, min=1, max=500),
    )

    def one(self, im: Image.Image) -> Image.Image:
        return im.filter(ImageFilter.UnsharpMask(radius=self.p["radius"], percent=self.p["percent"]))


@register
class Invert(_ImageMap):
    id = "image.invert"
    label = "反相"

    def one(self, im: Image.Image) -> Image.Image:
        return ImageOps.invert(im.convert("RGB") if im.mode not in ("L", "RGB") else im)


@register
class Flip(_ImageMap):
    id = "image.flip"
    label = "翻轉"
    geometric = True
    params = (Param("direction", "方向", "choice", default="horizontal", choices=("horizontal", "vertical")),)

    def one(self, im: Image.Image) -> Image.Image:
        return ImageOps.mirror(im) if self.p["direction"] == "horizontal" else ImageOps.flip(im)


@register
class Rotate(_ImageMap):
    id = "image.rotate"
    label = "旋轉"
    geometric = True
    params = (Param("angle", "角度", "choice", default=90, choices=(90, 180, 270)),)

    def one(self, im: Image.Image) -> Image.Image:
        return im.rotate(int(self.p["angle"]), expand=True)


def _gray_array(im: Image.Image, size: tuple[int, int] | None = None) -> np.ndarray:
    g = im.convert("L")
    if size and g.size != size:
        g = g.resize(size, Image.BILINEAR)
    a = np.asarray(g, dtype=np.float32)
    return a - a.mean()


def phase_shift(ref: np.ndarray, img: np.ndarray) -> tuple[int, int]:
    """Translation (dx, dy) that aligns img onto ref, by phase correlation."""
    f = np.fft.fft2(ref) * np.conj(np.fft.fft2(img))
    f /= np.abs(f) + 1e-8
    corr = np.fft.ifft2(f).real
    dy, dx = np.unravel_index(int(np.argmax(corr)), corr.shape)
    h, w = corr.shape
    if dy > h // 2:
        dy -= h
    if dx > w // 2:
        dx -= w
    return int(dx), int(dy)


@register
class Align(Op):
    id = "image.align"
    label = "對位（平移）"
    description = "以第一張（或指定）影像為參考，用相位相關求平移量後對齊；參考影像存在模型裡，推論沿用。"
    data_types = IMG
    geometric = True
    fitted = True
    params = (
        Param("reference", "參考影像索引", "int", default=0, min=0),
        Param("max_shift", "最大平移（像素，0 = 不限）", "int", default=0, min=0),
    )

    def fit(self, images: list[Image.Image], ctx: Context) -> None:
        if not images:
            raise ValueError("沒有影像可當參考")
        ref = images[min(self.p["reference"], len(images) - 1)]
        self.state = {"reference": ref.convert("L"), "size": list(ref.size)}

    def apply(self, images: list[Image.Image], ctx: Context) -> list[Image.Image]:
        ref_im = unjson_image(self.state["reference"])
        size = tuple(self.state["size"])
        ref = _gray_array(ref_im, size)
        out = []
        limit = self.p["max_shift"]
        for im in images:
            dx, dy = phase_shift(ref, _gray_array(im, size))
            sx, sy = dx * im.width / size[0], dy * im.height / size[1]
            if limit and (abs(sx) > limit or abs(sy) > limit):
                out.append(im)
                continue
            out.append(im.transform(im.size, Image.AFFINE, (1, 0, -sx, 0, 1, -sy), Image.BILINEAR))
        return out
