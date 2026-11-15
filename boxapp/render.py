"""Gambar PNG rakitan 3D (z-buffer sederhana, tanpa GPU) supaya hasil bisa dilihat
dari baris perintah - termasuk oleh LLM."""
from __future__ import annotations

import numpy as np
import pymupdf
import trimesh

PALETTE = [(0.36, 0.62, 0.84), (0.95, 0.70, 0.33), (0.47, 0.76, 0.52), (0.80, 0.56, 0.78),
           (0.55, 0.78, 0.80), (0.93, 0.60, 0.56), (0.72, 0.72, 0.45), (0.62, 0.62, 0.86),
           (0.85, 0.75, 0.62), (0.60, 0.70, 0.62)]

# arah pandang: vektor dari kamera ke benda (X = depan->belakang, Y = lebar, Z = atas)
VIEWS = {
    "iso": (1.0, 0.75, -0.65), "iso2": (-1.0, -0.75, -0.65),
    "depan": (1, 0, 0), "belakang": (-1, 0, 0),
    "kanan": (0, 1, 0), "kiri": (0, -1, 0), "atas": (0, 0, -1),
}


def _basis(view):
    f = np.array(VIEWS[view], float)
    f /= np.linalg.norm(f)
    up0 = np.array([0, 0, 1.0]) if abs(f[2]) < 0.99 else np.array([1.0, 0, 0])
    r = np.cross(f, up0)
    r /= np.linalg.norm(r)
    u = np.cross(r, f)
    return r, u, f


def _raster(P, depth, zbuf, key, kval, colbuf, color, shade):
    """Rasterisasi segitiga (P: n x 3 x 2 piksel) dengan uji kedalaman."""
    H, W = zbuf.shape
    for i in range(len(P)):
        (x0, y0), (x1, y1), (x2, y2) = P[i]
        xa, xb = int(max(min(x0, x1, x2), 0)), int(min(max(x0, x1, x2) + 1, W - 1))
        ya, yb = int(max(min(y0, y1, y2), 0)), int(min(max(y0, y1, y2) + 1, H - 1))
        if xa > xb or ya > yb:
            continue
        den = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(den) < 1e-9:
            continue
        xs = np.arange(xa, xb + 1) + 0.5
        ys = (np.arange(ya, yb + 1) + 0.5)[:, None]
        w0 = ((y1 - y2) * (xs - x2) + (x2 - x1) * (ys - y2)) / den
        w1 = ((y2 - y0) * (xs - x2) + (x0 - x2) * (ys - y2)) / den
        w2 = 1 - w0 - w1
        inside = (w0 >= -1e-6) & (w1 >= -1e-6) & (w2 >= -1e-6)
        if not inside.any():
            continue
        z = w0 * depth[i, 0] + w1 * depth[i, 1] + w2 * depth[i, 2]
        zb = zbuf[ya:yb + 1, xa:xb + 1]
        m = inside & (z < zb)
        if m.any():
            zb[m] = z[m]
            key[ya:yb + 1, xa:xb + 1][m] = kval[i]
            colbuf[ya:yb + 1, xa:xb + 1][m] = color * shade[i]


def render(asm, out, view="iso", explode=0.0, width=1400, show_collisions=True):
    if view not in VIEWS:
        raise SystemExit(f"view tidak dikenal: {view} (pilihan: {', '.join(VIEWS)})")
    if not asm.items:
        raise SystemExit("belum ada panel yang ditempatkan")
    r, u, f = _basis(view)
    t = asm.t
    ids = list(asm.items)
    centers = {i: asm.items[i]["full"].bounds.mean(axis=0) for i in ids}
    mid = np.mean(list(centers.values()), axis=0)
    meshes, offs = [], {}
    for i in ids:
        it = asm.items[i]
        m = trimesh.creation.extrude_polygon(it["solid"].simplify(0.35), t) \
            if it["solid"].geom_type == "Polygon" else it["full"].copy()
        if it["solid"].geom_type == "Polygon":
            m.apply_transform(it["M"])
        offs[i] = (centers[i] - mid) * explode
        m.apply_translation(offs[i])
        meshes.append(m)

    allv = np.vstack([m.vertices for m in meshes])
    sx, sy = allv @ r, allv @ u
    SS = 2                                   # supersampling
    W = width * SS
    pad = 60 * SS
    scale = (W - 2 * pad) / max(sx.max() - sx.min(), 1e-6)
    H = int((sy.max() - sy.min()) * scale + 2 * pad + 50 * SS)
    if H > 1.3 * W:                           # benda tinggi: batasi tinggi gambar
        scale *= 1.3 * W / H
        H = int((sy.max() - sy.min()) * scale + 2 * pad + 50 * SS)

    def proj(v):
        return np.stack([(v @ r - sx.min()) * scale + pad, (sy.max() - v @ u) * scale + pad], axis=-1)

    zbuf = np.full((H, W), np.inf)
    key = np.zeros((H, W), np.int32)
    col = np.ones((H, W, 3))
    light = -(f + 0.35 * r - 0.5 * u)
    light /= np.linalg.norm(light)
    for k, m in enumerate(meshes):
        fn = m.face_normals
        front = fn @ f < 0
        tri = m.vertices[m.faces[front]]
        nrm = fn[front]
        shade = 0.55 + 0.45 * np.clip(nrm @ light, 0, 1)
        axis = np.argmax(np.abs(nrm @ np.stack([r, u, f]).T), axis=1)
        kval = (k + 1) * 8 + axis * 2 + (np.sum(nrm * np.stack([r, u, f])[axis], axis=1) > 0)
        _raster(proj(tri), tri @ f, zbuf, key, kval.astype(np.int32), col,
                np.array(PALETTE[k % len(PALETTE)]), shade)

    # garis tepi: batas antar panel / antar bidang
    edge = np.zeros((H, W), bool)
    edge[:, 1:] |= key[:, 1:] != key[:, :-1]
    edge[1:, :] |= key[1:, :] != key[:-1, :]
    col[edge] *= 0.25

    # tabrakan: merah, selalu terlihat (tembus pandang)
    if show_collisions and asm.collision_meshes and explode == 0:
        mask = np.zeros((H, W), bool)
        dummy_z = np.full((H, W), np.inf)
        dk = np.zeros((H, W), np.int32)
        dc = np.zeros((H, W, 3))
        for m in asm.collision_meshes:
            tri = m.vertices[m.faces]
            _raster(proj(tri), tri @ f, dummy_z, dk, np.ones(len(tri), np.int32), dc,
                    np.ones(3), np.ones(len(tri)))
        mask = dk > 0
        col[mask] = col[mask] * 0.35 + np.array([1.0, 0.1, 0.1]) * 0.65

    img = col.reshape(H // SS, SS, W // SS, SS, 3).mean(axis=(1, 3)) if H % SS == 0 else \
        col[:H - H % SS].reshape(H // SS, SS, W // SS, SS, 3).mean(axis=(1, 3))
    h, w = img.shape[:2]
    pix = pymupdf.Pixmap(pymupdf.csRGB, w, h, (np.clip(img, 0, 1) * 255).astype(np.uint8).tobytes(), False)

    # label lewat halaman PDF sementara
    doc = pymupdf.open()
    page = doc.new_page(width=w, height=h)
    page.insert_image(page.rect, pixmap=pix)
    for k, i in enumerate(ids):
        c = proj((centers[i] + offs[i])[None, :])[0] / SS
        name = asm.items[i]["panel"].name
        txt = f"{i} {name}" if name else i
        tw = pymupdf.get_text_length(txt, fontsize=11)
        box = pymupdf.Rect(c[0] - tw / 2 - 3, c[1] - 8, c[0] + tw / 2 + 3, c[1] + 6)
        page.draw_rect(box, color=None, fill=(1, 1, 1), fill_opacity=0.8)
        page.insert_text((c[0] - tw / 2, c[1] + 3), txt, fontsize=11, color=(0, 0, 0))
    lo = np.min([asm.items[i]["body"].bounds[0] for i in ids], axis=0)
    hi = np.max([asm.items[i]["body"].bounds[1] for i in ids], axis=0)
    d = hi - lo
    foot = (f"pandangan: {view}   urai: {explode:g}   ukuran rakitan X x Y x Z = "
            f"{d[0]:.1f} x {d[1]:.1f} x {d[2]:.1f} mm   tebal {t:g} mm")
    if show_collisions and asm.collision_meshes and explode == 0:
        foot += f"   merah = {len(asm.collision_meshes)} tabrakan"
    page.insert_text((12, h - 12), foot, fontsize=11, color=(0.2, 0.2, 0.2))
    page.get_pixmap(alpha=False).save(out)
    return out
