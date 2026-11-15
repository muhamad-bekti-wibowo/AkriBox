"""Ubah gambar raster (PNG/JPG/foto) menjadi bentuk vektor berukuran nyata (mm).

Alur: gambar -> abu-abu -> kontras / CLAHE -> blur -> pisah latar (ambang | adaptif | tepi)
      -> kontur -> sederhanakan -> skala ke mm (dari satu ukuran acuan).

Skala (pilih satu, urutan prioritas):
  width_mm   lebar nyata seluruh bentuk hasil (kotak pembatas semua bentuk)
  height_mm  tinggi nyata seluruh bentuk hasil
  ppmm       piksel per mm
Tanpa ketiganya, 1 piksel = 1 mm dan hasil diberi peringatan.

Hasil: koordinat mm, y ke atas, pojok kiri-bawah kotak pembatas = (0, 0).
"""
from __future__ import annotations

import base64
from dataclasses import dataclass, fields

import cv2
import numpy as np
from shapely.geometry import Polygon

from .project import ProjectError

MODES = ("ambang", "adaptif", "tepi")


@dataclass
class Params:
    mode: str = "ambang"          # ambang (Otsu / manual) | adaptif (foto tak rata cahayanya) | tepi (Canny)
    contrast: float = 1.0         # pengali kontras di sekitar abu-abu tengah (1 = tetap)
    brightness: float = 0.0       # -255..255
    clahe: bool = False           # pemerataan kontras lokal
    blur: int = 1                 # ukuran blur Gaussian (piksel, ganjil)
    threshold: int = -1           # 0..255; -1 = otomatis (Otsu)
    invert: bool = False          # False: objek GELAP di latar terang; True: objek terang
    block: int = 31               # adaptif: ukuran jendela (ganjil)
    c: float = 8.0                # adaptif: penurun ambang
    canny_lo: int = 50
    canny_hi: int = 150
    close: int = 3                # tutup celah / rapikan (piksel)
    holes: bool = True            # ikutkan lubang di dalam bentuk
    drop_border: bool = False     # buang bentuk yang menyentuh tepi gambar (bingkai foto, tepi kertas)
    min_area_mm2: float = 4.0     # buang bentuk lebih kecil dari ini (bintik)
    simplify_mm: float = 0.2      # toleransi penyederhanaan garis
    width_mm: float = 0.0
    height_mm: float = 0.0
    ppmm: float = 0.0
    max_side: int = 1600          # gambar lebih besar diperkecil dulu


def params_from(d):
    names = {f.name for f in fields(Params)}
    bad = set(d) - names
    if bad:
        raise ProjectError(f"parameter tidak dikenal: {', '.join(sorted(bad))}")
    p = Params(**d)
    if p.mode not in MODES:
        raise ProjectError(f"mode harus salah satu dari {MODES}")
    p.blur = max(1, int(p.blur)) | 1
    p.block = max(3, int(p.block)) | 1
    p.close = max(0, int(p.close))
    return p


def decode(data):
    """bytes (atau data-URL base64) -> citra BGR uint8. Latar transparan jadi putih."""
    if isinstance(data, str):
        data = base64.b64decode(data.split(",", 1)[-1])
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_UNCHANGED)
    if img is None:
        raise ProjectError("gambar tidak bisa dibaca (pakai PNG atau JPG)")
    if img.ndim == 2:
        img = cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.dtype != np.uint8:
        img = cv2.convertScaleAbs(img, alpha=255.0 / max(float(img.max()), 1.0))
    if img.shape[2] == 4:
        a = img[:, :, 3:4].astype(np.float32) / 255.0
        img = (img[:, :, :3] * a + 255 * (1 - a)).astype(np.uint8)
    return img


def _mask(img, p):
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if p.clahe:
        g = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(g)
    if p.contrast != 1.0 or p.brightness:
        g = np.clip((g.astype(np.float32) - 128) * p.contrast + 128 + p.brightness, 0, 255).astype(np.uint8)
    if p.blur > 1:
        g = cv2.GaussianBlur(g, (p.blur, p.blur), 0)
    kind = cv2.THRESH_BINARY if p.invert else cv2.THRESH_BINARY_INV    # objek = putih di mask
    if p.mode == "ambang":
        if p.threshold < 0:
            _, m = cv2.threshold(g, 0, 255, kind | cv2.THRESH_OTSU)
        else:
            _, m = cv2.threshold(g, int(p.threshold), 255, kind)
    elif p.mode == "adaptif":
        m = cv2.adaptiveThreshold(g, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, kind, p.block, p.c)
    else:                                                          # tepi: garis tepi -> daerah tertutup
        e = cv2.Canny(g, p.canny_lo, p.canny_hi)
        k = max(p.close, 1)
        m = cv2.morphologyEx(e, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * k + 1, 2 * k + 1)),
                             iterations=2)
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        m = np.zeros_like(m)
        cv2.drawContours(m, cnts, -1, 255, thickness=cv2.FILLED)
        return m
    if p.close:
        m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (p.close | 1, p.close | 1)))
    return m


def _png(m):
    ok, buf = cv2.imencode(".png", m)
    return "data:image/png;base64," + base64.b64encode(buf.tobytes()).decode()


def trace(data, params):
    p = params if isinstance(params, Params) else params_from(params or {})
    img = decode(data)
    H0, W0 = img.shape[:2]
    if max(H0, W0) > p.max_side:
        f = p.max_side / max(H0, W0)
        img = cv2.resize(img, (round(W0 * f), round(H0 * f)), interpolation=cv2.INTER_AREA)
    H, W = img.shape[:2]
    m = _mask(img, p)
    cnts, hier = cv2.findContours(m, cv2.RETR_CCOMP if p.holes else cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    hier = hier[0] if hier is not None else []
    warnings = []

    def ring(c):
        return c[:, 0, :].astype(float)

    def touches(c):
        x, y, w, h = cv2.boundingRect(c)
        return x <= 1 or y <= 1 or x + w >= W - 1 or y + h >= H - 1

    raw = []                                    # (exterior px, [holes px])
    for i, c in enumerate(cnts):
        if len(c) < 3 or (p.holes and hier[i][3] >= 0):
            continue
        if p.drop_border and touches(c):
            continue
        holes = []
        if p.holes:
            j = hier[i][2]
            while j >= 0:
                if len(cnts[j]) >= 3 and cv2.contourArea(cnts[j]) >= 6:
                    holes.append(ring(cnts[j]))
                j = hier[j][0]
        if cv2.contourArea(c) >= 12:
            raw.append((ring(c), holes))
    if not raw:
        return {"shapes": [], "px_shapes": [], "mask": _png(m), "img_size": [W, H], "ppmm": p.ppmm or 1.0,
                "size_mm": [0, 0], "vertices": 0,
                "warnings": ["tidak ada bentuk terdeteksi: ubah ambang / kontras / centang 'objek terang'"]}

    def scale_for(items):
        pts = np.vstack([e for e, _ in items])
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        if p.ppmm > 0:
            return p.ppmm
        if p.width_mm > 0:
            return max(hi[0] - lo[0], 1.0) / p.width_mm
        if p.height_mm > 0:
            return max(hi[1] - lo[1], 1.0) / p.height_mm
        return 1.0

    ppmm = scale_for(raw)                       # skala sementara: untuk filter bintik dan penyederhanaan
    min_px = p.min_area_mm2 * ppmm ** 2
    eps = max(p.simplify_mm * ppmm, 0.0)

    def simp(r):
        if eps <= 0 or len(r) < 4:
            return r
        a = cv2.approxPolyDP(r.astype(np.float32).reshape(-1, 1, 2), eps, True)
        return a[:, 0, :].astype(float) if len(a) >= 3 else r

    polys = []
    for e, hs in raw:
        if Polygon(e).buffer(0).area < min_px:
            continue
        hs = [h for h in hs if Polygon(h).buffer(0).area >= min_px]      # lubang noise ikut dibuang
        # Kontur melewati titik tengah piksel tepi; batas sebenarnya setengah piksel di luarnya.
        # buffer(+0.5) melebarkan bagian luar dan menyempitkan lubang sekaligus.
        g = Polygon(simp(e), [simp(h) for h in hs]).buffer(0.5, join_style=2, mitre_limit=2.0)
        if g.geom_type != "Polygon":
            g = max(g.geoms, key=lambda x: x.area) if g.geoms else None
        if g is not None and not g.is_empty:
            polys.append(g)
    if not polys:
        polys = [Polygon(e).buffer(0) for e, _ in raw]
        warnings.append(f"semua bentuk lebih kecil dari {p.min_area_mm2} mm2; filter diabaikan")
    allb = np.array([g.bounds for g in polys])
    lo, hi = allb[:, :2].min(axis=0), allb[:, 2:].max(axis=0)
    if p.ppmm > 0:
        ppmm = p.ppmm
    elif p.width_mm > 0:
        ppmm = max(hi[0] - lo[0], 1.0) / p.width_mm
    elif p.height_mm > 0:
        ppmm = max(hi[1] - lo[1], 1.0) / p.height_mm
    else:
        ppmm = 1.0
        warnings.append("skala belum diisi: 1 piksel dianggap 1 mm. Isi lebar nyata (mm) bentuk ini.")

    def mm(r):
        return [[round((x - lo[0]) / ppmm, 3), round((hi[1] - y) / ppmm, 3)] for x, y in r]

    px, shapes = [], []
    for g in polys:
        px.append({"exterior": [list(c) for c in g.exterior.coords[:-1]],
                   "holes": [[list(c) for c in h.coords[:-1]] for h in g.interiors]})
        shapes.append({"exterior": mm(g.exterior.coords[:-1]),
                       "holes": [mm(h.coords[:-1]) for h in g.interiors],
                       "area_mm2": round(g.area / ppmm ** 2, 2),
                       "size_mm": [round((g.bounds[2] - g.bounds[0]) / ppmm, 2),
                                   round((g.bounds[3] - g.bounds[1]) / ppmm, 2)]})
    shapes.sort(key=lambda s: -s["area_mm2"])
    def px_touch(sh):
        a = np.array(sh["exterior"])
        return a[:, 0].min() <= 1 or a[:, 1].min() <= 1 or a[:, 0].max() >= W - 1 or a[:, 1].max() >= H - 1

    if not p.drop_border and len(px) > 1 and any(px_touch(sh) for sh in px):
        warnings.append("ada bentuk yang menyentuh tepi gambar (bingkai foto?); centang 'buang yang menyentuh tepi'")
    return {"shapes": shapes, "px_shapes": px, "mask": _png(m), "img_size": [W, H], "ppmm": round(ppmm, 4),
            "size_mm": [round(float(hi[0] - lo[0]) / ppmm, 2), round(float(hi[1] - lo[1]) / ppmm, 2)],
            "vertices": sum(len(s["exterior"]) + sum(len(h) for h in s["holes"]) for s in shapes),
            "warnings": warnings}


def apply_trace(pr, result, mode="cut", target=None, at=None, anchor="center", role="cut",
                largest_only=False, name=""):
    """Terapkan hasil trace ke proyek `pr` (menyimpan perubahan ke spec; panggil pr.save()).

    mode 'cut'       : tiap bentuk jadi potongan (poligon) pada panel `target`, diletakkan di `at`
                       (pusat atau pojok kiri-bawah kelompok, menurut `anchor`; bawaan: tengah panel).
    mode 'new_panel' : bentuk terbesar jadi outline panel baru; lubangnya dan bentuk lain yang ada
                       di dalamnya jadi potongan.
    Lubang di dalam bentuk pada mode 'cut' tidak dibawa (potongan berupa poligon penuh).
    """
    from shapely.geometry import Polygon as P
    from . import edits
    shapes = result["shapes"][:1] if largest_only else result["shapes"]
    if not shapes:
        raise ProjectError("tidak ada bentuk untuk dipakai")
    if mode == "new_panel":
        main = shapes[0]
        pid = edits.apply_ops(pr, [{"op": "new_panel", "name": name or "dari_gambar",
                                    "polygon": main["exterior"]}])[0]["id"]
        outline = P(main["exterior"]).buffer(0)
        bx, by = outline.bounds[0], outline.bounds[1]
        inner = list(main["holes"]) + [s["exterior"] for s in shapes[1:]
                                       if outline.contains(P(s["exterior"]).buffer(0))]
        ops = [{"op": "add", "panel": pid, "shape": {"kind": "poly", "role": role,
                "points": [[round(x - bx, 3), round(y - by, 3)] for x, y in pts]}} for pts in inner]
        edits.apply_ops(pr, ops)
        return {"panel": pid, "shapes": len(ops), "size_mm": [round(outline.bounds[2] - bx, 2),
                                                               round(outline.bounds[3] - by, 2)]}
    if pr.panel(target) is None:
        raise ProjectError(f"panel tidak dikenal: {target}")
    w, h = result["size_mm"]
    if at is None:
        at, anchor = (pr.panel(target).size[0] / 2, pr.panel(target).size[1] / 2), "center"
    ox, oy = (at[0] - w / 2, at[1] - h / 2) if anchor == "center" else (at[0], at[1])
    ops = [{"op": "add", "panel": target, "shape": {"kind": "poly", "role": role,
            "points": [[round(x + ox, 3), round(y + oy, 3)] for x, y in sh["exterior"]]}} for sh in shapes]
    ids = [r["id"] for r in edits.apply_ops(pr, ops)]
    return {"panel": target, "shapes": len(ids), "ids": ids, "origin": [round(ox, 2), round(oy, 2)],
            "size_mm": [w, h]}


def overlay(data, result, max_side=1600):
    """PNG pratinjau: gambar asli + kontur hasil (merah) untuk diperiksa mata."""
    img = decode(data)
    H0, W0 = img.shape[:2]
    if max(H0, W0) > max_side:
        f = max_side / max(H0, W0)
        img = cv2.resize(img, (round(W0 * f), round(H0 * f)), interpolation=cv2.INTER_AREA)
    for sh in result["px_shapes"]:
        for ring in [sh["exterior"]] + sh["holes"]:
            cv2.polylines(img, [np.round(np.array(ring)).astype(np.int32).reshape(-1, 1, 2)], True, (40, 40, 230), 2)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes()
