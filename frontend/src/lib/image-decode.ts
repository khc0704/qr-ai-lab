// Browser-side decoding of image formats an <img> cannot show. SEM / TEM tools export TIFF (8-bit, 16-bit,
// LZW …), which Chrome / Firefox / Edge do not render natively: the sample viewer turns those into a PNG blob
// with UTIF before showing them. The decoder is loaded on first use only (it is not part of the main bundle),
// and nothing leaves the browser.
const TIFF_EXT = /\.tiff?$/i;

/** True for the formats `decodeToPng` has to convert before an <img> can show them. */
export function needsDecode(name: string): boolean {
  return TIFF_EXT.test(name);
}

type Utif = typeof import("utif");

async function loadUtif(): Promise<Utif> {
  const mod = (await import("utif")) as unknown as Utif & { default?: Utif };
  return mod.default ?? mod;
}

/** Decode a TIFF blob (first page) into a PNG blob: 16-bit samples are scaled to 8 bits, grey / RGB / palette
 * and the compressions UTIF knows (none, LZW, PackBits, deflate …) are handled. Throws with a Chinese reason. */
export async function decodeToPng(blob: Blob, name = ""): Promise<Blob> {
  const UTIF = await loadUtif();
  const buf = await blob.arrayBuffer();
  const ifds = UTIF.decode(buf);
  if (!ifds.length) throw new Error(`${name || "TIFF"} 裡沒有影像`);
  const ifd = ifds[0];
  UTIF.decodeImage(buf, ifd);
  const { width, height } = ifd;
  if (!width || !height) throw new Error(`${name || "TIFF"} 的影像尺寸無效`);
  const rgba = UTIF.toRGBA8(ifd);
  const canvas = document.createElement("canvas");
  canvas.width = width;
  canvas.height = height;
  const ctx = canvas.getContext("2d");
  if (!ctx) throw new Error("瀏覽器不支援 canvas，無法轉換影像");
  const pixels = new Uint8ClampedArray(rgba.length); // a copy: ImageData wants a plain ArrayBuffer-backed array
  pixels.set(rgba);
  ctx.putImageData(new ImageData(pixels, width, height), 0, 0);
  return new Promise((resolve, reject) => {
    canvas.toBlob((b) => (b ? resolve(b) : reject(new Error("無法把影像轉成 PNG"))), "image/png");
  });
}
