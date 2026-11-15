"""Baca gambar vektor (AI / PDF) dan pisahkan menjadi panel 2D dalam satuan mm.

Hasilnya murni 2D: tiap panel punya outline, tab (tonjolan di luar outline) dan
fitur di dalam outline (lubang bulat, slot, bukaan). Koordinat tiap panel
bersifat lokal: (0, 0) = pojok kiri-bawah outline, sumbu y ke atas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import pymupdf
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon
from shapely.ops import unary_union

MM = 25.4 / 72.0          # 1 pt PDF = 0.3528 mm
TOUCH = 1.0               # mm: jarak maksimum tab dianggap milik panel di dekatnya
GUIDE_RATIO = 0.7         # bentuk dalam yang menutupi >= 70% panel = garis bantu


# ----------------------------------------------------------------------------
# 1. Baca path mentah
# ----------------------------------------------------------------------------
@dataclass
class Shape:
    poly: Polygon
    kind: str                       # circle | rect | poly
    layer: str | None = None
    center: tuple = (0.0, 0.0)
    r: float = 0.0                  # circle
    size: tuple = (0.0, 0.0)        # rect: (panjang, lebar)
    angle: float = 0.0              # rect: arah sisi panjang, derajat 0..180
    children: list = field(default_factory=list)
    parent: "Shape | None" = None

    @property
    def area(self):
        return self.poly.area


def _bezier(p0, p1, p2, p3, n=10):
    out = []
    for i in range(1, n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * t * (1 - t) ** 2, 3 * t * t * (1 - t), t ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0],
                    a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def _subpaths(items):
    """Pecah item path PyMuPDF menjadi daftar (titik, semua_kurva)."""
    subs, cur, curves = [], [], True

    def flush():
        nonlocal cur, curves
        if len(cur) >= 3:
            subs.append((cur, curves))
        cur, curves = [], True

    for it in items:
        op = it[0]
        if op == "re":
            flush()
            r = it[1]
            subs.append(([(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1)], False))
        elif op == "qu":
            flush()
            q = it[1]
            subs.append(([(q.ul.x, q.ul.y), (q.ur.x, q.ur.y), (q.lr.x, q.lr.y), (q.ll.x, q.ll.y)], False))
        elif op in ("l", "c"):
            a = (it[1].x, it[1].y)
            if not cur or math.dist(cur[-1], a) > 1e-3:
                flush()
                cur = [a]
            if op == "l":
                cur.append((it[2].x, it[2].y))
                curves = False
            else:
                cur.extend(_bezier(a, *[(p.x, p.y) for p in it[2:5]]))
    flush()
    return subs


def _classify(pts, all_curves, layer):
    poly = Polygon(pts)
    if not poly.is_valid:
        poly = poly.buffer(0)
    if poly.is_empty or poly.geom_type != "Polygon" or poly.area < 0.05:
        return None
    poly = Polygon(poly.exterior.coords)
    x0, y0, x1, y1 = poly.bounds
    w, h = x1 - x0, y1 - y0
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    if all_curves and abs(w - h) < 0.02 * max(w, h):
        r = (w + h) / 4
        dev = max(abs(math.dist((cx, cy), p) - r) for p in poly.exterior.coords)
        if dev < 0.03 * r + 0.02:
            return Shape(Point(cx, cy).buffer(r, 8), "circle", layer, (cx, cy), r=r)
    mrr = poly.minimum_rotated_rectangle
    if mrr.geom_type == "Polygon" and abs(mrr.area - poly.area) < 0.005 * poly.area + 0.01:
        c = list(mrr.exterior.coords)[:4]
        e = [(math.dist(c[i], c[(i + 1) % 4]), c[i], c[(i + 1) % 4]) for i in range(2)]
        e.sort(key=lambda t: -t[0])
        (L, a, b), (W, _, _) = e
        ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180
        if abs(ang - 180) < 1e-6:
            ang = 0.0
        return Shape(Polygon(c), "rect", layer, (mrr.centroid.x, mrr.centroid.y), size=(L, W), angle=ang)
    poly = poly.simplify(0.01)
    return Shape(poly, "poly", layer, (poly.centroid.x, poly.centroid.y))


def load_shapes(path):
    """Semua bentuk tertutup yang punya garis (stroke), dalam mm, y ke atas."""
    doc = pymupdf.open(path, filetype="pdf")
    page = doc[0]
    H = page.rect.height
    shapes, seen = [], set()
    stats = {"expanded_strokes": 0, "white_fills_skipped": 0, "open": 0, "duplicate": 0}
    for d in page.get_drawings():
        stroked = d.get("color") is not None and "s" in d.get("type", "s")
        cands = []
        for pts, curves in _subpaths(d["items"]):
            mm = [(x * MM, (H - y) * MM) for x, y in pts]
            s = _classify(mm, curves, d.get("layer"))
            if s is None:
                stats["open"] += 1
            else:
                cands.append(s)
        if not stroked:
            # Bentuk isian tanpa garis. Isian putih = bagian dalam dari garis yang
            # sudah di-"expand" (Outline Stroke) -> dibuang. Isian gelap = garis yang
            # di-expand: yang dipakai kontur terluarnya (ukuran nominal gambar).
            fill = d.get("fill")
            if fill is None or sum(fill) / len(fill) > 0.9:
                stats["white_fills_skipped"] += len(cands)
                continue
            cands.sort(key=lambda s: -s.area)
            outer = []
            for s in cands:
                if not any(o.poly.buffer(0.01).contains(s.poly) for o in outer):
                    outer.append(s)
            stats["expanded_strokes"] += len(outer)
            cands = outer
        for s in cands:
            b = s.poly.bounds
            key = tuple(round(v, 1) for v in b) + (round(s.area, 0),)
            if key in seen:
                stats["duplicate"] += 1
                continue
            seen.add(key)
            shapes.append(s)
    info = {"page_mm": (page.rect.width * MM, page.rect.height * MM), **stats}
    return shapes, info


# ----------------------------------------------------------------------------
# 2. Susun menjadi panel
# ----------------------------------------------------------------------------
def _build_tree(shapes):
    shapes.sort(key=lambda s: -s.area)
    grown = [s.poly.buffer(0.05) for s in shapes]
    bounds = [g.bounds for g in grown]
    for i, s in enumerate(shapes):
        sb = s.poly.bounds
        for j in range(i - 1, -1, -1):          # kandidat induk: dari yang terkecil
            b = bounds[j]
            if sb[0] >= b[0] and sb[1] >= b[1] and sb[2] <= b[2] and sb[3] <= b[3] \
                    and shapes[j].area > s.area * 1.02 and grown[j].contains(s.poly):
                s.parent = shapes[j]
                shapes[j].children.append(s)
                break
    return [s for s in shapes if s.parent is None]


@dataclass
class Feature:
    id: str
    kind: str
    poly: Polygon
    center: tuple
    r: float = 0.0
    size: tuple = (0.0, 0.0)
    angle: float = 0.0
    role: str = "cut"               # cut | guide | detail | ignore
    auto_role: str = "cut"
    depth: int = 0
    added: bool = False             # True = bentuk tambahan pengguna (bukan dari gambar sumber)
    group: str = ""                 # id grup komponen (bentuk dalam satu grup bergerak dan terhapus bersama)
    comp: str = ""                  # nama komponen pustaka


@dataclass
class Tab:
    id: str
    poly: Polygon
    center: tuple
    length: float                   # sepanjang tepi panel
    depth: float                    # tonjolan keluar dari tepi
    edge: str                       # atas | bawah | kiri | kanan | miring
    pos: float                      # posisi pusat sepanjang tepi
    normal: tuple                   # arah keluar (unit)
    gap: float = 0.0                # > 0: tab digambar terlepas dari tepi panel
    added: bool = False             # True = tab tambahan pengguna (misalnya dari fitur Bagi sisi)


@dataclass
class Panel:
    id: str
    outline: Polygon                # tanpa tab, koordinat lokal
    size: tuple
    tabs: list
    features: list
    src_center: tuple               # posisi di gambar sumber (mm)
    src_rotation: float             # rotasi yang dipakai untuk meluruskan panel
    name: str = ""
    generated: bool = False         # True = dibuat generator box (ukuran diatur lewat parameter generator)

    def feature(self, fid):
        return next((f for f in self.features if f.id == fid), None)

    def cuts(self):
        return [f for f in self.features if f.role == "cut"]

    def solid(self, kerf=0.0, with_tabs=True, with_cuts=True):
        """Bentuk 2D yang benar-benar terpotong (outline + tab - lubang)."""
        parts = [self.outline]
        if with_tabs:
            for t in self.tabs:      # sambungkan ke outline walau digambar sedikit terlepas
                d = t.gap + 0.05
                parts.append(t.poly.union(affinity.translate(
                    t.poly, -t.normal[0] * d, -t.normal[1] * d)).convex_hull)
        s = unary_union(parts)
        if with_cuts and self.cuts():
            s = s.difference(unary_union([f.poly for f in self.cuts()]))
        if kerf:
            s = s.buffer(-kerf / 2.0, join_style=2)
        return s


def _straighten_angle(poly):
    """Rotasi (derajat) supaya sisi terpanjang outline sejajar sumbu."""
    c = list(poly.exterior.coords)
    best = max(((math.dist(c[i], c[i + 1]), c[i], c[i + 1]) for i in range(len(c) - 1)),
               key=lambda t: t[0])
    a = math.degrees(math.atan2(best[2][1] - best[1][1], best[2][0] - best[1][0]))
    r = -(((a + 45) % 90) - 45)
    return 0.0 if abs(r) < 0.05 else r


def _edge_name(n):
    ax, ay = abs(n[0]), abs(n[1])
    if ay > 0.999:
        return "atas" if n[1] > 0 else "bawah"
    if ax > 0.999:
        return "kanan" if n[0] > 0 else "kiri"
    return "miring"


def _make_tab(tid, poly, outline):
    c = poly.centroid
    near = outline.exterior.interpolate(outline.exterior.project(c))
    dx, dy = c.x - near.x, c.y - near.y
    d = math.hypot(dx, dy) or 1.0
    n = (dx / d, dy / d)
    t = (-n[1], n[0])
    xs = [p[0] * t[0] + p[1] * t[1] for p in poly.exterior.coords]
    ns = [(p[0] - near.x) * n[0] + (p[1] - near.y) * n[1] for p in poly.exterior.coords]
    edge = _edge_name(n)
    if edge in ("atas", "bawah"):
        pos = c.x
    elif edge in ("kiri", "kanan"):
        pos = c.y
    else:
        pos = c.x * t[0] + c.y * t[1]
    return Tab(tid, poly, (c.x, c.y), max(xs) - min(xs), max(ns), edge, pos, n,
               gap=poly.distance(outline))


def extract_panels(path, roles=None):
    """roles: {panel_id: {feature_id: role}} untuk menimpa klasifikasi otomatis."""
    roles = roles or {}
    shapes, info = load_shapes(path)
    roots = _build_tree(shapes)

    # tab = bentuk kecil di luar panel yang menempel ke tepi panel yang jauh lebih besar
    tab_of = {}
    for t in roots:
        best = None
        tb = t.poly.buffer(TOUCH)
        for p in roots:
            if p is t or p.area < 8 * t.area or p.poly.distance(t.poly) > TOUCH:
                continue
            shared = p.poly.exterior.intersection(tb).length
            if best is None or shared > best[0]:
                best = (shared, p)
        if best:
            tab_of[id(t)] = best[1]
    panel_shapes = [s for s in roots if id(s) not in tab_of]
    panel_shapes.sort(key=lambda s: (-round(s.center[1] / 60.0), s.center[0]))

    panels = []
    for n, ps in enumerate(panel_shapes, 1):
        pid = f"P{n}"
        rot = _straighten_angle(ps.poly)
        origin = ps.center

        def loc(g, _rot=rot, _o=origin):
            return affinity.rotate(g, _rot, origin=_o) if _rot else g

        outline = loc(ps.poly)
        ox, oy = outline.bounds[0], outline.bounds[1]

        def tr(g):
            return affinity.translate(loc(g), -ox, -oy)

        outline = tr(ps.poly)
        if ps.kind == "rect":         # bersihkan galat pembulatan
            w, h = outline.bounds[2], outline.bounds[3]
            outline = Polygon([(0, 0), (w, 0), (w, h), (0, h)])

        tabs = sorted((tr(t.poly) for t in roots if tab_of.get(id(t)) is ps),
                      key=lambda g: (-round(g.centroid.y), g.centroid.x))
        tabs = [_make_tab(f"T{i}", g, outline) for i, g in enumerate(tabs, 1)]

        # semua turunan diberi id tetap (urut baca), lalu perannya ditentukan
        flat = []

        def walk(s, depth):
            for c in s.children:
                flat.append((c, depth))
                walk(c, depth + 1)
        walk(ps, 0)
        flat.sort(key=lambda t: (-round(t[0].center[1], 0), t[0].center[0]))
        feats, by_shape = [], {}
        for i, (s, depth) in enumerate(flat, 1):
            g = tr(s.poly)
            ang = (s.angle + rot) % 180 if s.kind == "rect" else 0.0
            if abs(ang - 180) < 0.01:
                ang = 0.0
            f = Feature(f"F{i}", s.kind, g, (g.centroid.x, g.centroid.y), s.r, s.size, ang, depth=depth)
            feats.append(f)
            by_shape[id(s)] = f
        over = roles.get(pid, {})

        def assign(s, inside_cut):
            for c in s.children:
                f = by_shape[id(c)]
                if inside_cut:
                    auto = "detail"
                elif c.area >= GUIDE_RATIO * ps.area:
                    auto = "guide"
                else:
                    auto = "cut"
                f.auto_role = auto
                f.role = over.get(f.id, auto)
                assign(c, inside_cut or f.role == "cut")
        assign(ps, False)

        b = outline.bounds
        panels.append(Panel(pid, outline, (b[2] - b[0], b[3] - b[1]), tabs, feats,
                            ps.center, rot))
    return panels, info


# ----------------------------------------------------------------------------
# 3. Ringkasan untuk manusia / LLM
# ----------------------------------------------------------------------------
def is_slot(f, thickness):
    return f.kind == "rect" and f.size[1] <= thickness * 1.3 and f.size[0] >= f.size[1] * 1.5


def slot_groups(panel, thickness):
    """Kelompokkan slot yang segaris. Hasil: list dict(dir, offset, pos[], ids[], size)."""
    groups = []
    for f in panel.cuts():
        if not is_slot(f, thickness):
            continue
        a = math.radians(f.angle)
        t = (math.cos(a), math.sin(a))
        n = (-t[1], t[0])
        off = f.center[0] * n[0] + f.center[1] * n[1]
        pos = f.center[0] * t[0] + f.center[1] * t[1]
        for g in groups:
            if abs(g["angle"] - f.angle) < 0.5 and abs(g["offset"] - off) < 0.5:
                g["items"].append((pos, f))
                break
        else:
            groups.append({"angle": f.angle, "offset": off, "items": [(pos, f)]})
    out = []
    for g in groups:
        g["items"].sort(key=lambda t: t[0])
        a = g["angle"]
        if abs(a) < 0.5:
            d, off = "mendatar", ("y", abs(g["offset"]))
        elif abs(a - 90) < 0.5:
            d, off = "tegak", ("x", abs(g["offset"]))
        else:
            d, off = f"miring {a:.1f}°", ("offset", g["offset"])
        f0 = g["items"][0][1]
        out.append({"dir": d, "axis": off[0], "offset": off[1],
                    "pos": [p for p, _ in g["items"]], "ids": [f.id for _, f in g["items"]],
                    "size": f0.size, "angle": a})
    out.sort(key=lambda g: (g["dir"], g["offset"]))
    return out


def tab_groups(panel):
    groups = {}
    for t in panel.tabs:
        key = t.edge if t.edge != "miring" else f"miring({t.normal[0]:+.2f},{t.normal[1]:+.2f})"
        groups.setdefault(key, []).append(t)
    out = []
    for k, ts in groups.items():
        ts.sort(key=lambda t: t.pos)
        out.append({"edge": k, "pos": [t.pos for t in ts], "ids": [t.id for t in ts],
                    "length": ts[0].length, "depth": ts[0].depth})
    return out


# ----------------------------------------------------------------------------
# 4. Penyuntingan: bentuk tambahan, geser/hapus, panel baru
# ----------------------------------------------------------------------------
def shape_to_feature(s):
    from .edits import shape_poly
    role = s.get("role", "cut")
    poly = shape_poly(s)
    grp = dict(group=s.get("group", ""), comp=s.get("comp", ""))
    if s["kind"] == "circle":
        c = tuple(s["center"])
        return Feature(s["id"], "circle", poly, c, r=s["r"], role=role, auto_role="cut", **grp)
    if s["kind"] == "rect":
        w, h = s["size"]
        ang = float(s.get("angle", 0)) % 180
        if w < h:
            w, h, ang = h, w, (ang + 90) % 180
        return Feature(s["id"], "rect", poly, tuple(s["center"]), size=(w, h), angle=ang,
                       role=role, auto_role="cut", **grp)
    return Feature(s["id"], "poly", poly, (poly.centroid.x, poly.centroid.y), role=role, auto_role="cut", **grp)


EDGE_TOL = 0.3          # mm: titik outline sedekat ini ke batas dianggap berada di batas itu


def apply_edges(panel, edges):
    """Pindahkan batas panel (kiri/kanan/bawah/atas) ke posisi mutlak (koordinat panel, mm).

    Semua titik outline yang berada di batas itu ikut pindah; sisi miring menyesuaikan sudutnya.
    Tab yang menempel di batas itu ikut bergeser. Fitur (lubang, slot) tidak berubah."""
    if not edges:
        return
    b = panel.outline.bounds
    pts = []
    for x, y in panel.outline.exterior.coords[:-1]:
        nx, ny = x, y
        if "left" in edges and abs(x - b[0]) <= EDGE_TOL:
            nx = edges["left"]
        if "right" in edges and abs(x - b[2]) <= EDGE_TOL:
            nx = edges["right"]
        if "bottom" in edges and abs(y - b[1]) <= EDGE_TOL:
            ny = edges["bottom"]
        if "top" in edges and abs(y - b[3]) <= EDGE_TOL:
            ny = edges["top"]
        pts.append((nx, ny))
    new = Polygon(pts)
    if not new.is_valid or new.area < 1e-6:
        from .project import ProjectError
        raise ProjectError(f"{panel.id}: batas baru membuat outline tidak valid (sisi saling melewati?)")
    old_tabs, panel.outline = panel.tabs, new
    tabs = []
    for t in old_tabs:
        tb = t.poly.bounds
        dx = dy = 0.0
        if t.edge == "kiri" and "left" in edges and abs(tb[2] - b[0]) <= 1.0:
            dx = edges["left"] - b[0]
        elif t.edge == "kanan" and "right" in edges and abs(tb[0] - b[2]) <= 1.0:
            dx = edges["right"] - b[2]
        elif t.edge == "bawah" and "bottom" in edges and abs(tb[3] - b[1]) <= 1.0:
            dy = edges["bottom"] - b[1]
        elif t.edge == "atas" and "top" in edges and abs(tb[1] - b[3]) <= 1.0:
            dy = edges["top"] - b[3]
        tabs.append(_make_tab(t.id, affinity.translate(t.poly, dx, dy), new) if dx or dy else
                    _make_tab(t.id, t.poly, new))
    panel.tabs = tabs
    nb = new.bounds
    panel.size = (nb[2] - nb[0], nb[3] - nb[1])


def apply_outline(panel, pts):
    """Ganti outline dengan titik-titik hasil edit (koordinat panel, mm). Tab yang menempel di sebuah sisi
    ikut bergeser sebesar pergeseran sisi itu (tidak ikut berputar bila sisinya jadi miring)."""
    if not pts:
        return
    from .project import ProjectError
    new = Polygon([(float(x), float(y)) for x, y in pts])
    if not new.is_valid or new.area < 1e-6:
        raise ProjectError(f"{panel.id}: outline hasil edit tidak valid (sisi saling memotong?)")
    old = list(panel.outline.exterior.coords)[:-1]
    n = len(old)
    disp = [(pts[i][0] - old[i][0], pts[i][1] - old[i][1]) for i in range(n)] if len(pts) == n else None
    tabs = []
    for t in panel.tabs:
        dx = dy = rot = 0.0
        piv = t.center
        if disp:
            c = Point(t.center)
            best = None
            for i in range(n):
                a, b = old[i], old[(i + 1) % n]
                seg = LineString([a, b])
                d = seg.distance(c)
                if best is None or d < best[0]:
                    best = (d, i, seg.project(c) / max(seg.length, 1e-9))
            if best and best[0] < t.depth / 2 + 1.5:
                _, i, s = best
                j = (i + 1) % n
                dx = disp[i][0] + (disp[j][0] - disp[i][0]) * s
                dy = disp[i][1] + (disp[j][1] - disp[i][1]) * s
                a0 = math.atan2(old[j][1] - old[i][1], old[j][0] - old[i][0])
                a1 = math.atan2(pts[j][1] - pts[i][1], pts[j][0] - pts[i][0])
                rot = (math.degrees(a1 - a0) + 180) % 360 - 180          # sisi berputar -> tab ikut berputar
                piv = (pts[i][0] + (pts[j][0] - pts[i][0]) * s, pts[i][1] + (pts[j][1] - pts[i][1]) * s)
        poly = affinity.translate(t.poly, dx, dy) if dx or dy else t.poly
        if abs(rot) > 0.01:
            poly = affinity.rotate(poly, rot, origin=piv)
        tabs.append(_make_tab(t.id, poly, new))
    panel.outline, panel.tabs = new, tabs
    nb = new.bounds
    panel.size = (nb[2] - nb[0], nb[3] - nb[1])


def apply_edits(panel, conf):
    apply_outline(panel, conf.get("outline"))
    apply_edges(panel, conf.get("edges"))
    ed = conf.get("edits") or {}
    dele, mv = set(ed.get("delete", [])), ed.get("move", {})
    tabs = []
    for t in panel.tabs:
        if t.id in dele:
            continue
        if t.id in mv:
            t = _make_tab(t.id, affinity.translate(t.poly, *mv[t.id]), panel.outline)
        tabs.append(t)
    panel.tabs = tabs
    feats = []
    for f in panel.features:
        if f.id in dele:
            continue
        if f.id in mv:
            dx, dy = mv[f.id]
            f.poly = affinity.translate(f.poly, dx, dy)
            f.center = (f.center[0] + dx, f.center[1] + dy)
        feats.append(f)
    for s in ed.get("add", []):
        if s["kind"] == "tab":                       # tab tambahan: menyatu dengan outline, ikut sambungan
            from .edits import shape_poly
            t = _make_tab(s["id"], shape_poly(s), panel.outline)
            t.added = True
            panel.tabs.append(t)
            continue
        f = shape_to_feature(s)
        f.added = True
        feats.append(f)
    panel.features = feats
    for gid, ids in (ed.get("groups") or {}).items():          # grup buatan pengguna (Ctrl+G)
        for f in feats:
            if f.id in ids:
                f.group, f.comp = gid, ""
    over = conf.get("roles", {})
    for f in feats:
        if f.id in over and not getattr(f, "added", False):
            f.role = over[f.id]


def make_new_panel(pid, conf):
    new = conf["new"]
    if "size" in new:
        w, h = new["size"]
        outline = Polygon([(0, 0), (w, 0), (w, h), (0, h)])
    else:
        g = Polygon(new["polygon"]).buffer(0)
        if g.geom_type != "Polygon":
            g = max(g.geoms, key=lambda x: x.area)
        b = g.bounds
        outline = Polygon(affinity.translate(g, -b[0], -b[1]).exterior.coords)
    b = outline.bounds
    return Panel(pid, outline, (b[2] - b[0], b[3] - b[1]), [], [], (0.0, 0.0), 0.0,
                 conf.get("name", ""))
