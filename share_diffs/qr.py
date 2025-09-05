#!/usr/bin/env python3
"""Create an animated GIF of QR frames for looped playback.

- Reads a bytes object (demo at bottom) -> builds fountain-coded frames
- Renders each frame as a black/white QR
- Saves an animated GIF with controlled frame duration and infinite loop
- Emits a minimal HTML file that displays the GIF without blurring

Notes:
- Keep a modest number of frames per loop (e.g., ~K*(1+ε)). Very large loops produce huge GIFs.
- GIF palette is forced to 2 colors (no dithering) to preserve crisp modules.
"""

import base64
import hashlib
import json
import math
import os

import qrcode
from PIL import Image
from qrcode.constants import ERROR_CORRECT_H, ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q


# --------- tiny helpers ----------
def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# --------- LT fountain (encoder only) ----------
class XorShift32:
    def __init__(self, seed: int):
        self.state = (seed or 0xDEADBEEF) & 0xFFFFFFFF

    def rand32(self) -> int:
        x = self.state
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= (x >> 17) & 0xFFFFFFFF
        x ^= (x << 5) & 0xFFFFFFFF
        self.state = x & 0xFFFFFFFF
        return self.state

    def randint(self, a: int, b: int) -> int:
        return a + (self.rand32() % (b - a + 1))


def robust_soliton_cdf(K: int, c: float = 0.1, delta: float = 0.5) -> list[float]:
    R = max(1, int(c * math.log(K / delta) * math.sqrt(K)))
    tau = [0.0] * (K + 1)
    for d in range(1, K):
        if 1 <= d < K // R:
            tau[d] = R / (d * K)
        elif d == K // R:
            tau[d] = R * math.log(R / delta) / K
    rho = [0.0] * (K + 1)
    rho[1] = 1.0 / K
    for d in range(2, K + 1):
        rho[d] = 1.0 / (d * (d - 1))
    Z = sum(rho[1:]) + sum(tau[1:])
    pmf = [(rho[d] + tau[d]) / Z for d in range(K + 1)]
    cdf = [0.0]
    s = 0.0
    for d in range(1, K + 1):
        s += pmf[d]
        cdf.append(s)
    cdf[-1] = 1.0
    return cdf


def sample_degree(cdf: list[float], rng: XorShift32) -> int:
    u = (rng.rand32() & 0xFFFFFFFF) / 0x100000000
    lo, hi = 1, len(cdf) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cdf[mid] >= u:
            hi = mid
        else:
            lo = mid + 1
    return lo


def lt_encode_symbol(chunks: list[bytes], sym_id: int, fec_seed: int, cdf: list[float]) -> bytes:
    K = len(chunks)
    rng = XorShift32((fec_seed ^ sym_id ^ (K << 16)) & 0xFFFFFFFF)
    d = max(1, min(K, sample_degree(cdf, rng)))
    chosen = set()
    while len(chosen) < d:
        chosen.add(rng.randint(0, K - 1))
    idxs = sorted(chosen)
    out = bytearray(chunks[idxs[0]])
    for j in idxs[1:]:
        cj = chunks[j]
        for i in range(len(out)):
            out[i] ^= cj[i]
    return bytes(out)


# --------- Build frames (metadata + payload) ----------
def build_frames(data: bytes, chunk_size: int = 512, overhead: float = 0.12) -> tuple[list[dict], str]:
    total_len = len(data)
    chunks = [bytearray(data[i : i + chunk_size]) for i in range(0, total_len, chunk_size)]
    if not chunks:
        chunks = [bytearray([0])]
    max_len = max(len(c) for c in chunks)
    for c in chunks:
        if len(c) < max_len:
            c.extend(b"\x00" * (max_len - len(c)))
    chunks = [bytes(c) for c in chunks]
    K = len(chunks)
    fec_seed = int.from_bytes(os.urandom(4), "big")
    session_id = os.urandom(8)
    sid_b64 = b64u(session_id)
    cdf = robust_soliton_cdf(K)
    N = int(math.ceil(K * (1.0 + overhead)))
    frames = []
    for sym in range(N):
        payload = lt_encode_symbol(chunks, sym, fec_seed, cdf)
        frames.append(
            {
                "v": 1,
                "sid": sid_b64,
                "len": total_len,
                "K": K,
                "cs": max_len,
                "i": sym,
                "r": fec_seed,
                "p": b64u(payload),
                "x": b64u(os.urandom(2)),
            }
        )
    return frames, sha256_hex(data)


# --------- QR rendering helpers ----------
def make_qr_image(text: str, version: int = 15, ecc: str = "M", box_size: int = 10, border: int = 4) -> Image.Image:
    ec_map = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "Q": ERROR_CORRECT_Q, "H": ERROR_CORRECT_H}
    qr = qrcode.QRCode(
        version=version,
        error_correction=ec_map.get(ecc, ERROR_CORRECT_M),
        box_size=box_size,
        border=border,
    )
    qr.add_data(text)
    qr.make(fit=False)
    img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    return img


def force_bw_palette(im: Image.Image) -> Image.Image:
    """
    Convert to a strict 2-color palette (black/white), no dithering.
    This avoids GIF dithering artifacts that can confuse QR scanners.
    """
    # Create a 2-color paletted image
    pal = Image.new("P", (1, 1))
    # palette: index 0 = black, index 1 = white
    palette = [0, 0, 0, 255, 255, 255] + [0, 0, 0] * 254
    pal.putpalette(palette)
    bw = im.convert("1")  # pure B/W threshold
    pal_im = bw.convert("P", dither=Image.NONE)
    pal_im.putpalette(palette)
    return pal_im


# --------- Main: build GIF + simple HTML ----------
def main():
    # 1) Your bytes here (or read from file)
    data = b"Hello QR stream over GIF! " * 200  # ~5 KB demo; replace as needed
    # params
    CHUNK = 512
    OVERHEAD = 0.12  # ~12% extra symbols per loop
    VERSION = 15  # QR version (10..18 good starting range)
    ECC = "M"  # L/M/Q/H
    WINDOW_PX = 900  # output dimensions (square)
    FPS = 5.0  # frame rate (1 frame every 200 ms)
    GIF_PATH = "qr_stream.gif"
    HTML_PATH = "qr_stream_player.html"

    # 2) Build fountain frames
    frames, file_hash = build_frames(data, chunk_size=CHUNK, overhead=OVERHEAD)
    frame_texts = ["QS1|" + json.dumps(fr, separators=(",", ":")) for fr in frames]

    # 3) Render QR images
    imgs: list[Image.Image] = []
    # Scale factor: ensure integer scaling to avoid interpolation
    box_size = max(2, WINDOW_PX // (4 * VERSION))
    for t in frame_texts:
        im = make_qr_image(t, version=VERSION, ecc=ECC, box_size=box_size, border=4)
        im = im.resize((WINDOW_PX, WINDOW_PX), Image.NEAREST)  # keep crisp modules
        im = force_bw_palette(im)  # strict 2-color palette, no dithering
        imgs.append(im)

    # 4) Save animated GIF (loop forever, per-frame duration in ms)
    duration_ms = int(1000 / FPS)
    # All frames must be mode "P" with identical palette; ensured by force_bw_palette.
    first, rest = imgs[0], imgs[1:] if len(imgs) > 1 else []
    first.save(
        GIF_PATH,
        save_all=True,
        append_images=rest,
        loop=0,  # 0 = infinite loop
        duration=duration_ms,  # per-frame delay
        disposal=2,  # restore to background between frames
    )
    print(f"[gif] wrote {GIF_PATH} with {len(imgs)} frames @ ~{FPS} FPS")
    print(f"[gif] file_sha256={file_hash}")
    est_payload_per_frame = (VERSION, ECC)  # for your own bookkeeping if desired

    # 5) Emit a minimal HTML page that displays the GIF without blurring
    html = f"""<!doctype html>
<html lang="en">
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>QR Stream GIF Player</title>
<style>
  body {{ margin:0; background:#111; color:#eee; font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif; }}
  main {{ display:flex; align-items:center; justify-content:center; min-height:100vh; flex-direction:column; gap:12px; }}
  img.qr {{ width: min(92vmin, 900px); height: auto; image-rendering: pixelated; image-rendering: crisp-edges; }}
  .info {{ opacity:.8; font-size:.9em; }}
</style>
<main>
  <img class="qr" src="{GIF_PATH}" alt="QR stream animation" />
  <div class="info">
    QR stream (v={VERSION}, ECC={ECC}, fps={FPS:g}) — looped. Keep the phone steady and fill the frame.
  </div>
</main>
</html>
"""
    with open(HTML_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"[html] wrote {HTML_PATH}")


if __name__ == "__main__":
    main()
