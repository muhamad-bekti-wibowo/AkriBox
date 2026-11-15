"""Ekspor panel siap potong: DXF (mm) dan SVG (mm, skala 1:1).

Bedanya dengan gambar sumber:
  - tab sudah menyatu dengan outline panel (satu kontur tertutup, tidak terpotong lepas)
  - tiap bentuk hanya satu kontur (bukan kontur ganda dari garis yang di-expand)
  - garis bantu dipisah ke layer sendiri
"""
from __future__ import annotations

import os

import ezdxf
from shapely import affinity

from . import geom

GAP = 8.0   # mm jarak antar panel di lembar


def _layout(panels, sheet_width):
    """Tata letak rak sederhana. Hasil: {pid: (dx, dy)} dan ukuran lembar."""
    pos, x, y, row_h, width = {}, GAP, GAP, 0.0, 0.0
    for p in sorted(panels, key=lambda p: -(p.bounds[3] - p.bounds[1])):
        b = p.bounds
        w, h = b[2] - b[0], b[3] - b[1]
        if x + w + GAP > sheet_width and x > GAP:
            x, y, row_h = GAP, y + row_h + GAP, 0.0
        pos[p.id] = (x - b[0], y - b[1])
        x += w + GAP
        row_h = max(row_h, h)
        width = max(width, x)
    return pos, (width, y + row_h + GAP)


class _Item:
    def __init__(self, panel, kerf_comp):
        self.id, self.name = panel.id, panel.name
        self.outer = panel.solid(with_cuts=False)
        cuts = panel.cuts()
        if kerf_comp:      # garis potong digeser keluar setengah kerf dari bahan yang tersisa
            self.outer = self.outer.buffer(kerf_comp / 2, join_style=2)
        self.cuts = []
        for f in cuts:
            if f.kind == "circle":
                self.cuts.append(("circle", f.center, max(f.r - kerf_comp / 2, 0.01)))
            else:
                g = f.poly.buffer(-kerf_comp / 2, join_style=2) if kerf_comp else f.poly
                if not g.is_empty:
                    self.cuts.append(("poly", list(g.exterior.coords), None))
        self.guides = [list(f.poly.exterior.coords) for f in panel.features if f.role == "guide"]
        self.bounds = self.outer.bounds
        self.size = panel.size

    def outlines(self):
        gs = [self.outer] if self.outer.geom_type == "Polygon" else list(self.outer.geoms)
        return [list(g.exterior.coords) for g in gs]


def export(pr, outdir, formats=("dxf", "svg"), sheet_width=600.0, kerf_comp=False):
    os.makedirs(outdir, exist_ok=True)
    k = pr.kerf if kerf_comp else 0.0
    items = [_Item(p, k) for p in pr.panels]
    pos, sheet = _layout(items, sheet_width)
    base = os.path.splitext(os.path.basename(pr.path))[0].replace(".box", "")
    files = []
    if "dxf" in formats:
        files.append(_dxf(items, pos, os.path.join(outdir, base + "_potong.dxf")))
    if "svg" in formats:
        files.append(_svg(items, pos, sheet, os.path.join(outdir, base + "_potong.svg")))
    return files


def _dxf(items, pos, path):
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    doc.layers.add("POTONG", color=1)          # merah
    doc.layers.add("GARIS_BANTU", color=5)     # biru
    doc.layers.add("LABEL", color=3)           # hijau
    msp = doc.modelspace()
    for it in items:
        dx, dy = pos[it.id]
        for c in it.outlines():
            msp.add_lwpolyline([(x + dx, y + dy) for x, y in c[:-1]], close=True,
                               dxfattribs={"layer": "POTONG"})
        for kind, a, b in it.cuts:
            if kind == "circle":
                msp.add_circle((a[0] + dx, a[1] + dy), b, dxfattribs={"layer": "POTONG"})
            else:
                msp.add_lwpolyline([(x + dx, y + dy) for x, y in a[:-1]], close=True,
                                   dxfattribs={"layer": "POTONG"})
        for g in it.guides:
            msp.add_lwpolyline([(x + dx, y + dy) for x, y in g[:-1]], close=True,
                               dxfattribs={"layer": "GARIS_BANTU"})
        label = f"{it.id} {it.name}".strip()
        msp.add_text(label, height=4, dxfattribs={"layer": "LABEL"}).set_placement(
            (dx + it.size[0] / 2, dy + it.size[1] / 2), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
    doc.saveas(path)
    return path


def _svg(items, pos, sheet, path):
    W, H = sheet
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.2f}mm" height="{H:.2f}mm" '
           f'viewBox="0 0 {W:.2f} {H:.2f}">']

    def pts(c, dx, dy):
        return " ".join(f"{x + dx:.3f},{H - (y + dy):.3f}" for x, y in c[:-1])

    for layer, color in (("POTONG", "#ff0000"), ("GARIS_BANTU", "#0000ff"), ("LABEL", "#008000")):
        out.append(f'<g id="{layer}" fill="none" stroke="{color}" stroke-width="0.1">')
        for it in items:
            dx, dy = pos[it.id]
            if layer == "POTONG":
                for c in it.outlines():
                    out.append(f'<polygon points="{pts(c, dx, dy)}"/>')
                for kind, a, b in it.cuts:
                    if kind == "circle":
                        out.append(f'<circle cx="{a[0] + dx:.3f}" cy="{H - (a[1] + dy):.3f}" r="{b:.3f}"/>')
                    else:
                        out.append(f'<polygon points="{pts(a, dx, dy)}"/>')
            elif layer == "GARIS_BANTU":
                for g in it.guides:
                    out.append(f'<polygon points="{pts(g, dx, dy)}"/>')
            else:
                label = f"{it.id} {it.name}".strip()
                out.append(f'<text x="{dx + it.size[0] / 2:.2f}" y="{H - (dy + it.size[1] / 2):.2f}" '
                           f'font-size="4" text-anchor="middle" fill="{color}" stroke="none">{label}</text>')
        out.append("</g>")
    out.append("</svg>")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    return path


def panel_svg(panel, thickness):
    """SVG satu panel untuk editor 2D. Tiap tab/fitur punya data-id; atribut data-b0, data-b1,
    data-m, data-h dipakai untuk mengubah titik layar menjadi koordinat panel (mm)."""
    solid = panel.solid(with_cuts=False)
    b = solid.bounds
    m = 15
    W, H = b[2] - b[0] + 2 * m, b[3] - b[1] + 2 * m

    def pts(c):
        return " ".join(f"{x - b[0] + m:.2f},{H - (y - b[1] + m):.2f}" for x, y in c[:-1])

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W:.2f} {H:.2f}" '
           f'data-w="{W:.2f}" data-h="{H:.2f}" data-b0="{b[0]:.4f}" data-b1="{b[1]:.4f}" data-m="{m}" '
           f'style="overflow:visible">']
    for g in ([solid] if solid.geom_type == "Polygon" else solid.geoms):
        out.append(f'<polygon class="outline" points="{pts(list(g.exterior.coords))}"/>')
    for t in panel.tabs:
        out.append(f'<polygon class="tab" data-id="{t.id}" points="{pts(list(t.poly.exterior.coords))}">'
                   f'<title>{panel.id}.{t.id} tab {t.edge}</title></polygon>')
    order = {"guide": 0, "ignore": 0, "cut": 1}      # garis bantu di bawah, supaya tidak menutupi lubang
    for f in sorted((f for f in panel.features if f.role != "detail"), key=lambda f: order.get(f.role, 1)):
        cls = "guide" if f.role != "cut" else ("slot" if geom.is_slot(f, thickness) else "cut")
        out.append(f'<polygon class="{cls}{" added" if f.added else ""}" data-id="{f.id}" '
                   f'points="{pts(list(f.poly.exterior.coords))}">'
                   f'<title>{panel.id}.{f.id} {f.role} {f.kind}</title></polygon>')
    out.append("</svg>")
    return "".join(out)
