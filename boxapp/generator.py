"""Generator box akrilik dari nol: isi ukuran DALAM + tebal, enam panel dengan sambungan
tab-slot yang pasti berpasangan terbentuk otomatis, lengkap dengan posisi rakitannya.

Sumbu rakitan: X = lebar (kiri-kanan), Y = kedalaman (depan-belakang), Z = tinggi.
Ukuran luar = ukuran dalam + 2 x tebal pada tiap sumbu.

Susunan panel (G1..G6):
  G1 alas     W x D     tab di keempat sisinya
  G2 atas     W x D     sama dengan alas (opsional)
  G3 depan    W x Ho    tab kiri/kanan; slot untuk tab alas dan atas
  G4 belakang W x Ho    sama dengan depan
  G5 kiri     Do x Ho   slot untuk tab depan, belakang, alas, atas
  G6 kanan    Do x Ho   sama dengan kiri
(W, D, H = ukuran dalam; Wo, Do, Ho = ukuran luar.) Lebar tab = tebal, panjang tab dan slot sama
persis (celah nominal 0); kerf laser ditangani saat ekspor / pemeriksaan.

Tiga jenis sambungan, tiap jenis boleh diatur sendiri lewat "joints":
  vertical  tab tepi tegak panel depan/belakang  <-> slot tegak panel kiri/kanan   (sepanjang tinggi)
  side      tab sisi kiri/kanan alas/atas        <-> slot datar panel kiri/kanan   (sepanjang kedalaman)
  span      tab sisi depan/belakang alas/atas    <-> slot datar panel depan/belakang (sepanjang lebar)

Semua posisi dan panjang tab berupa bilangan bulat (mm) bila ukuran dalam bulat.
"""
from __future__ import annotations

import math

from shapely.geometry import Polygon

from . import geom
from .project import ProjectError

IDS = {"alas": "G1", "atas": "G2", "depan": "G3", "belakang": "G4", "kiri": "G5", "kanan": "G6"}
JOINT_KINDS = ("vertical", "side", "span")


def default_generator(inner=(100, 80, 50), tab=20, top=True):
    return {"type": "box", "inner": [inner[0], inner[1], inner[2]], "tab": tab, "top": top, "joints": {}}


def layout(length, tab, count=None):
    """Posisi pusat tab sepanjang sisi sepanjang `length`, simetris, dan panjang tab.
    Semua tepi tab bilangan bulat: tab genap bila `length` genap, ganjil bila `length` ganjil."""
    length = int(length)
    tab = int(tab)
    if length < 6:
        raise ProjectError(f"sisi sepanjang {length} mm terlalu pendek untuk sambungan tab")
    n = int(count) if count else max(1, length // (2 * max(tab, 2)))
    cell = length / n
    ln = max(int(min(tab, math.floor(cell * 0.8))), 2)
    half = length % 2 == 1
    if (ln % 2 == 1) != half:
        ln -= 1
    ln = max(ln, 1 if half else 2)
    cs = []
    for k in range(n // 2):
        v = (k + 0.5) * cell
        cs.append(math.floor(v) + 0.5 if half else math.floor(v + 0.5))
    mid = [length / 2] if n % 2 else []
    return cs + mid + [length - q for q in reversed(cs)], ln


def _joint(g, kind, length):
    j = g.get("joints", {}).get(kind, {})
    return layout(length, j.get("tab", g.get("tab", 20)), j.get("count"))


def _panel(pid, name, w, h, t, tabs, slots):
    """tabs: [(sisi, pusat, panjang)], slots: [(cx, cy, lebar, tinggi)] dalam koordinat panel."""
    outline = Polygon([(0, 0), (w, 0), (w, h), (0, h)])
    polys = []
    for edge, c, ln in tabs:
        a, b = c - ln / 2, c + ln / 2
        polys.append({"kiri": (-t, a, 0, b), "kanan": (w, a, w + t, b),
                      "bawah": (a, -t, b, 0), "atas": (a, h, b, h + t)}[edge])
    tab_objs = [geom._make_tab(f"T{i}", Polygon([(x0, y0), (x1, y0), (x1, y1), (x0, y1)]), outline)
                for i, (x0, y0, x1, y1) in enumerate(polys, 1)]
    feats = [geom.shape_to_feature({"id": f"F{i}", "kind": "rect", "center": [cx, cy], "size": [sw, sh],
                                    "angle": 0, "role": "cut"})
             for i, (cx, cy, sw, sh) in enumerate(slots, 1)]
    return geom.Panel(pid, outline, (float(w), float(h)), tab_objs, feats, (0.0, 0.0), 0.0, name)


def outer_size(spec):
    g, t = spec["generator"], float(spec["thickness"])
    W, D, H = (int(round(v)) for v in g["inner"])
    return W + 2 * t, D + 2 * t, H + 2 * t


def build(spec):
    """Hasil: (daftar Panel, {id: placement}) dari spec["generator"]."""
    g, t = spec["generator"], float(spec["thickness"])
    if g.get("type", "box") != "box":
        raise ProjectError(f"jenis generator '{g.get('type')}' tidak dikenal (box)")
    W, D, H = (int(round(v)) for v in g["inner"])
    if min(W, D, H) < 10:
        raise ProjectError("ukuran dalam minimal 10 mm di tiap sumbu")
    Wo, Do, Ho = W + 2 * t, D + 2 * t, H + 2 * t
    cv, lv = _joint(g, "vertical", H)          # sepanjang tinggi dalam
    cs, ls = _joint(g, "side", D)              # sepanjang kedalaman dalam
    cp, lp = _joint(g, "span", W)              # sepanjang lebar dalam
    zc = [t + c for c in cv]                   # posisi tab tegak pada panel depan/belakang (y = z)

    def flat(pid, name):                       # alas / atas
        tabs = [("kiri", c, ls) for c in cs] + [("kanan", c, ls) for c in cs] + \
               [("bawah", c, lp) for c in cp] + [("atas", c, lp) for c in cp]
        return _panel(pid, name, W, D, t, tabs, [])

    def front_back(pid, name, mirror):         # depan / belakang
        tabs = [("kiri", z, lv) for z in zc] + [("kanan", z, lv) for z in zc]
        xs = [W - c for c in cp] if mirror else list(cp)
        slots = [(x, t / 2, lp, t) for x in xs] + ([(x, Ho - t / 2, lp, t) for x in xs] if g.get("top", True) else [])
        return _panel(pid, name, W, Ho, t, tabs, slots)

    def side_panel(pid, name):                 # kiri / kanan
        slots = [(t / 2, z, t, lv) for z in zc] + [(Do - t / 2, z, t, lv) for z in zc]
        slots += [(t + c, t / 2, ls, t) for c in cs]
        if g.get("top", True):
            slots += [(t + c, Ho - t / 2, ls, t) for c in cs]
        return _panel(pid, name, Do, Ho, t, [], slots)

    panels = [flat(IDS["alas"], "alas")]
    place = {IDS["alas"]: {"origin": [t, t, 0], "u": "+X", "v": "+Y"}}
    if g.get("top", True):
        panels.append(flat(IDS["atas"], "atas"))
        place[IDS["atas"]] = {"origin": [t, t, Ho - t], "u": "+X", "v": "+Y"}
    panels += [front_back(IDS["depan"], "depan", False), front_back(IDS["belakang"], "belakang", True),
               side_panel(IDS["kiri"], "kiri"), side_panel(IDS["kanan"], "kanan")]
    place.update({IDS["depan"]: {"origin": [t, t, 0], "u": "+X", "v": "+Z"},
                  IDS["belakang"]: {"origin": [Wo - t, Do - t, 0], "u": "-X", "v": "+Z"},
                  IDS["kiri"]: {"origin": [0, 0, 0], "u": "+Y", "v": "+Z"},
                  IDS["kanan"]: {"origin": [Wo - t, 0, 0], "u": "+Y", "v": "+Z"}})
    for p in panels:
        p.generated = True
    return panels, place


def describe(spec):
    g = spec["generator"]
    Wo, Do, Ho = outer_size(spec)
    W, D, H = (int(round(v)) for v in g["inner"])
    out = [f"Box {W} x {D} x {H} mm (dalam) -> {Wo:g} x {Do:g} x {Ho:g} mm (luar), tebal {spec['thickness']:g} mm"]
    for kind, L, label in (("vertical", H, "tegak depan/belakang <-> kiri/kanan"),
                           ("side", D, "alas/atas <-> kiri/kanan"), ("span", W, "alas/atas <-> depan/belakang")):
        cs, ln = _joint(g, kind, L)
        out.append(f"  sambungan {kind:<8} {label}: {len(cs)} tab x {ln} mm sepanjang {L} mm")
    return "\n".join(out)
