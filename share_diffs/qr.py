#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
qr.py — Generate a self-contained QR streaming website for air-gapped transfer.

Changes vs previous version:
- Adds "d" (LT degree) to every frame so the receiver can decode deterministically.
- Keeps the fountain seed as an UNSIGNED 32-bit value end-to-end.
- Enforces version cap when 'version' is provided (fit=False). If None, auto-sizes.
- Patches SVGs for crisp rendering.

Outputs:
  out_dir/
    index.html
    manifest.json
    frames/frame_0001.svg ... frame_00NN.svg

Dependency: 'qrcode' (pure Python, with SVG image factory). No Pillow, no ffmpeg.
  pip install qrcode
"""

import os, json, math, base64, hashlib, pathlib
from typing import List, Tuple

import qrcode
from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H
from qrcode.image.svg import SvgPathImage
from qrcode.exceptions import DataOverflowError

# ----------------- tiny helpers -----------------


def b64u(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode("ascii").rstrip("=")


def sha256_hex(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# ----------------- LT fountain (encoder only) -----------------


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


def robust_soliton_cdf(K: int, c: float = 0.1, delta: float = 0.5) -> List[float]:
    R = max(1, int(c * math.log(K / delta) * math.sqrt(K)))
    tau = [0.0] * (K + 1)
    for d in range(1, K):
        cut = max(1, K // R)
        if 1 <= d < cut:
            tau[d] = R / (d * K)
        elif d == cut:
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


def sample_degree(cdf: List[float], rng: XorShift32) -> int:
    u = (rng.rand32() & 0xFFFFFFFF) / 0x100000000
    lo, hi = 1, len(cdf) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if cdf[mid] >= u:
            hi = mid
        else:
            lo = mid + 1
    return lo


def lt_encode_symbol(chunks: List[bytes], sym_id: int, fec_seed: int, cdf: List[float]) -> Tuple[bytes, int]:
    """
    Generate one LT symbol by XORing a random subset of source chunks.
    Returns (payload_bytes, degree_d). The receiver will use 'd' to avoid any float drift.
    """
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
    return bytes(out), d


# ----------------- Frames -----------------


def build_frames(data: bytes, chunk_size: int, overhead: float):
    total_len = len(data)
    # chunk & pad
    chunks = [bytearray(data[i : i + chunk_size]) for i in range(0, total_len, chunk_size)]
    if not chunks:
        chunks = [bytearray([0])]
    cs = max(len(c) for c in chunks)
    for c in chunks:
        if len(c) < cs:
            c.extend(b"\x00" * (cs - len(c)))
    chunks = [bytes(c) for c in chunks]
    K = len(chunks)

    # Fountain seed as UNSIGNED 32-bit
    fec_seed = int.from_bytes(os.urandom(4), "big") & 0xFFFFFFFF
    sid = os.urandom(8)
    sid_b64 = b64u(sid)
    cdf = robust_soliton_cdf(K)

    N = int(math.ceil(K * (1.0 + overhead)))  # frames per loop
    frames = []
    for sym in range(N):
        payload, d = lt_encode_symbol(chunks, sym, fec_seed, cdf)
        frame = {
            "v": 1,
            "sid": sid_b64,
            "len": total_len,
            "K": K,
            "cs": cs,
            "i": sym,
            "r": fec_seed,  # unsigned 32-bit
            "d": d,  # degree for deterministic decoding
            "p": b64u(payload),
            "x": b64u(os.urandom(2)),  # small salt to bust renderer caching
        }
        frames.append(frame)
    return frames


# ----------------- QR (SVG) rendering -----------------

_ECC_MAP = {"L": ERROR_CORRECT_L, "M": ERROR_CORRECT_M, "Q": ERROR_CORRECT_Q, "H": ERROR_CORRECT_H}


def save_qr_svg(text: str, path: str, ecc: str = "M", version: int | None = None, crisp_px: int | None = 1000):
    """
    Render a QR as SVG (no Pillow). If version is None -> auto-size (fit=True).
    If version is an int -> enforce cap (fit=False); raise DataOverflowError if it won't fit.
    Optionally patch the SVG for crisp rendering and fixed pixel width/height.
    """
    if version is None:
        qr = qrcode.QRCode(
            version=None,
            error_correction=_ECC_MAP.get(ecc, ERROR_CORRECT_M),
            box_size=10,
            border=4,
        )
        qr.add_data(text)
        qr.make(fit=True)
    else:
        qr = qrcode.QRCode(
            version=version,
            error_correction=_ECC_MAP.get(ecc, ERROR_CORRECT_M),
            box_size=10,
            border=4,
        )
        qr.add_data(text)
        # fit=False to enforce the cap; if it doesn't fit, this will raise on make_image
        # (library raises on make() too sometimes; keep fit=False to be explicit)
        qr.make(fit=False)

    img = qr.make_image(image_factory=SvgPathImage)
    img.save(path)

    if crisp_px:
        # Patch the top-level <svg ...> tag to add crisp rendering hints and fixed pixel size
        try:
            txt = pathlib.Path(path).read_text(encoding="utf-8")
            if "<svg " in txt:
                txt = txt.replace(
                    "<svg ",
                    f'<svg shape-rendering="crispEdges" text-rendering="optimizeSpeed" '
                    f'image-rendering="pixelated" width="{crisp_px}" height="{crisp_px}" ',
                    1,
                )
                pathlib.Path(path).write_text(txt, encoding="utf-8")
        except Exception:
            pass


# ----------------- HTML player -----------------

_HTML_TEMPLATE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
  :root{{color-scheme:dark light}}
  body{{font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;margin:0;background:#111;color:#eee}}
  header{{padding:12px 16px;background:#222;position:sticky;top:0}}
  main{{padding:16px}}
  .row{{display:flex;gap:16px;flex-wrap:wrap}}
  .card{{background:#1b1b1b;border-radius:12px;padding:12px}}
  img.qr{{width:min(92vmin, {max_px}px);height:auto;image-rendering:pixelated;image-rendering:crisp-edges;background:#fff;border-radius:12px}}
  input[type=range]{{width:220px}}
  button{{background:#4caf50;border:none;color:#fff;border-radius:8px;padding:8px 12px;font-weight:600;cursor:pointer}}
  button.secondary{{background:#333}}
  button[disabled]{{opacity:.5;cursor:not-allowed}}
  .small{{opacity:.85;font-size:.9em}}
</style>
<header><b>{title}</b></header>
<main>
  <div class="row">
    <div class="card" style="flex:1;min-width:300px">
      <div style="display:flex;gap:8px;align-items:center;flex-wrap:wrap">
        <button id="playBtn">▶ Play</button>
        <button id="pauseBtn" class="secondary" disabled>⏸ Pause</button>
        <button id="prevBtn" class="secondary">⟲ Prev</button>
        <button id="nextBtn" class="secondary">Next ⟶</button>
        <label class="small" for="fps">FPS</label>
        <input id="fps" type="range" min="1" max="15" step="1" value="{fps_default}">
        <span id="fpsVal" class="small">{fps_default}</span>
      </div>
      <div style="margin-top:10px;display:flex;justify-content:center">
        <img id="qr" class="qr" src="frames/{first_name}" alt="QR frame">
      </div>
      <div class="small" style="margin-top:10px" id="info"></div>
    </div>
    <div class="card" style="flex:1;min-width:260px">
      <div><b>Session</b></div>
      <div class="small">sid: <code id="sid"></code></div>
      <div class="small">len: <span id="len"></span> bytes</div>
      <div class="small">K / cs: <span id="K"></span> / <span id="cs"></span></div>
      <div class="small">Frames per loop: <span id="N"></span></div>
      <div class="small">SHA-256 (file): <code id="sha"></code></div>
      <div class="small">Tip: open the <i>receiver</i> page via https or http://localhost so the camera works.</div>
    </div>
  </div>
</main>
<script>
const MANIFEST = {manifest_json};
const pad = n => String(n).padStart({pad_width}, '0');
const img = document.getElementById('qr');
const info = document.getElementById('info');
const sidEl = document.getElementById('sid');
const lenEl = document.getElementById('len');
const KEl = document.getElementById('K');
const csEl = document.getElementById('cs');
const NEl = document.getElementById('N');
const shaEl = document.getElementById('sha');
const playBtn = document.getElementById('playBtn');
const pauseBtn = document.getElementById('pauseBtn');
const prevBtn = document.getElementById('prevBtn');
const nextBtn = document.getElementById('nextBtn');
const fpsSlider = document.getElementById('fps');
const fpsVal = document.getElementById('fpsVal');

let idx = 0, running = false, lastTime = 0, acc = 0;
let fps = Number(fpsSlider.value);

// ESCAPED: ${{...}} so Python .format won't eat the JS template braces
function frameName(i){{ return `frame_${{pad(i+1)}}.svg`; }}

function setFrame(i){{
  idx = (i + MANIFEST.N) % MANIFEST.N;
  img.src = `frames/${{frameName(idx)}}`;
  info.textContent = `Frame ${{idx+1}} / ${{MANIFEST.N}}`;
}}

function start(){{
  if (running) return;
  running = true;
  playBtn.disabled = true;
  pauseBtn.disabled = false;
  lastTime = performance.now();
  acc = 0;
  requestAnimationFrame(tick);
}}
function pause(){{
  running = false;
  playBtn.disabled = false;
  pauseBtn.disabled = true;
}}
function tick(now){{
  if (!running) return;
  const dt = now - lastTime; lastTime = now;
  acc += dt;
  const interval = 1000 / fps;
  while (acc >= interval){{
    acc -= interval;
    setFrame(idx + 1);
  }}
  requestAnimationFrame(tick);
}}

// UI wiring
playBtn.onclick = start;
pauseBtn.onclick = pause;
prevBtn.onclick = () => setFrame(idx - 1);
nextBtn.onclick = () => setFrame(idx + 1);
fpsSlider.oninput = () => {{ fps = Number(fpsSlider.value); fpsVal.textContent = fps; }};

// Show meta
sidEl.textContent = MANIFEST.sid;
lenEl.textContent = MANIFEST.len;
KEl.textContent = MANIFEST.K;
csEl.textContent = MANIFEST.cs;
NEl.textContent = MANIFEST.N;
shaEl.textContent = MANIFEST.sha256;

// Initial
setFrame(0);
</script>
</html>
"""

# ----------------- top-level convenience -----------------


def generate_qr_site(
    data: bytes,
    out_dir: str,
    *,
    chunk_size: int = 512,
    overhead: float = 0.12,
    ecc: str = "M",
    version: int | None = None,  # 1..40 to CAP, or None to auto-size
    fps_default: int = 5,
    title: str = "QR Stream Sender",
    crisp_svg_px: int = 1000,
) -> str:
    """
    Build frames + website into out_dir. Returns path to index.html.

    Notes:
      - If version is None: QR size auto-scales per frame.
      - If version is an int: we ENFORCE the cap; if a frame doesn't fit, a DataOverflowError is raised
        with guidance to either increase 'version' or lower 'chunk_size'.
    """
    out = pathlib.Path(out_dir)
    frames_dir = out / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)

    frames = build_frames(data, chunk_size=chunk_size, overhead=overhead)
    meta = frames[0]  # for manifest
    file_hash = sha256_hex(data)

    # Render frames
    N = len(frames)
    pad_width = max(4, len(str(N)))
    for i, fr in enumerate(frames, 1):
        txt = "QS1|" + json.dumps(fr, separators=(",", ":"))
        fname = f"frame_{str(i).zfill(pad_width)}.svg"
        try:
            save_qr_svg(txt, str(frames_dir / fname), ecc=ecc, version=version, crisp_px=crisp_svg_px)
        except DataOverflowError as e:
            raise DataOverflowError(
                f"QR content for frame {i} will not fit into version={version} (ECC={ecc}). "
                f"Increase 'version' or reduce 'chunk_size'. Original error: {e}"
            ) from e

    # Manifest
    manifest = {
        "sid": meta["sid"],
        "len": meta["len"],
        "K": meta["K"],
        "cs": meta["cs"],
        "N": N,
        "ecc": ecc,
        "version": version if version is not None else "auto",
        "sha256": file_hash,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    # HTML
    first_name = f"frame_{str(1).zfill(pad_width)}.svg"
    html = _HTML_TEMPLATE.format(
        title=title,
        max_px=crisp_svg_px,
        fps_default=fps_default,
        first_name=first_name,
        pad_width=pad_width,
        manifest_json=json.dumps(manifest, separators=(",", ":")),
    )
    index_path = out / "index.html"
    index_path.write_text(html, encoding="utf-8")

    print(f"[ok] Site written to: {index_path}")
    print(f"Serve it with:  python -m http.server -d {out} 8000")
    print(f"Open sender at: http://localhost:8000")
    return str(index_path)


# ----------------- example CLI -----------------

if __name__ == "__main__":
    # DEMO: replace with your own bytes (or read a file)
    payload = b"Hello QR stream over SVG frames! " * 400  # ~13 KB example
    out_path = generate_qr_site(
        payload,
        out_dir="qr_site_out4",
        chunk_size=512,  # scan-friendly default
        overhead=0.12,
        ecc="L",
        version=None,  # cap size; set to None for auto
        fps_default=5,
        title="QR Stream Sender (SVG, deterministic)",
        crisp_svg_px=1000,
    )
