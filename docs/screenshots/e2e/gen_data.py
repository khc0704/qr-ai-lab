"""Sample datasets for the end-to-end walkthrough (semiconductor-flavoured, fully synthetic)."""
import csv, io, random, sys, zipfile
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
rng = random.Random(42)

# 1) WAT / yield table: 480 lots, process params → yield_pct, with a few gaps and a categorical line column
with (out / "wat_yield.csv").open("w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["lot_id", "line", "vth_mv", "idsat_ua", "rs_ohm", "cd_nm", "thk_a", "temp_c", "yield_pct"])
    for i in range(480):
        line = rng.choice(["A", "B", "C"])
        vth = rng.gauss(420, 12); idsat = rng.gauss(650, 30); rs = rng.gauss(35, 3)
        cd = rng.gauss(28, 1.2); thk = rng.gauss(52, 2.5); temp = rng.gauss(23.0, 0.6)
        y = 94 - 0.08 * abs(vth - 420) - 0.03 * abs(idsat - 650) - 0.4 * abs(cd - 28) - 0.25 * abs(thk - 52) + (0.8 if line == "A" else 0) + rng.gauss(0, 0.6)
        row = [f"L{24000 + i}", line, round(vth, 2), round(idsat, 2), round(rs, 2), round(cd, 3), round(thk, 2), round(temp, 2), round(y, 3)]
        if rng.random() < 0.04: row[4] = ""      # missing rs_ohm
        if rng.random() < 0.02: row[6] = ""      # missing thk_a
        w.writerow(row)

# 2) SEM-style images: golden tool (sharp) vs tuned tool (slightly blurrier / darker) vs bad tool
def tool_images(name: str, n: int, blur: tuple[float, float], brightness: float, noise: float, seed: int) -> list[tuple[str, bytes]]:
    """A tool = a distribution of images: per-image jitter in focus (blur), brightness and sensor noise."""
    r = np.random.default_rng(seed); files = []
    for i in range(n):
        b = brightness + r.normal(0, 4)
        base = r.normal(size=(128, 128)) * (noise + r.normal(0, 3)) + b
        xx, yy = np.meshgrid(np.arange(128), np.arange(128))
        base += 30 * np.sin(xx / 7.0 + r.uniform(0, 6)) + 20 * ((xx // 32 + yy // 32) % 2)
        im = Image.fromarray(np.clip(base, 0, 255).astype(np.uint8), mode="L")
        im = im.filter(ImageFilter.GaussianBlur(r.uniform(*blur)))
        buf = io.BytesIO(); im.save(buf, format="PNG"); files.append((f"{name}/{name}_{i:03d}.png", buf.getvalue()))
    return files

def zipped(path: Path, files):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for n, data in files: z.writestr(n, data)

zipped(out / "sem_golden_tool.zip", tool_images("golden", 40, (0.3, 0.7), 128, 35, 1))
zipped(out / "sem_tuned_tool.zip", tool_images("tool_b", 16, (0.5, 1.0), 121, 37, 2))
zipped(out / "sem_bad_tool.zip", tool_images("tool_c", 12, (1.8, 2.6), 92, 48, 3))

# 3) OCD spectra: 240 normal + 24 drifted, wide CSV (one row per wafer, 200 wavelengths) with a label column
wl = np.linspace(400, 800, 200)
rows = []
r = np.random.default_rng(7)
for i in range(264):
    drift = i >= 240
    # film thickness sets the fringe period; drifted wafers are ~15% thicker and show an absorption dip
    t = 300 + r.normal(0, 3) + (45 if drift else 0)
    spec = 0.55 + 0.25 * np.cos(2 * np.pi * t / (wl / 1.0) * 1.0) * np.exp(-((wl - 600) / 220) ** 2) + r.normal(0, 0.004, wl.shape)
    if drift:
        spec -= 0.06 * np.exp(-((wl - 520) / 25) ** 2)
    rows.append([f"W{i:04d}", int(drift)] + [round(float(v), 5) for v in spec])
with (out / "ocd_spectra.csv").open("w", newline="") as f:
    w = csv.writer(f); w.writerow(["wafer_id", "label"] + [f"wl_{int(x)}" for x in wl]); w.writerows(rows)

# 4) Inline inference rows for the tabular model (no target column)
print("ok", sorted(p.name for p in out.iterdir()))
