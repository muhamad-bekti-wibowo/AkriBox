"""Rakitan 3D virtual: tiap panel 2D diberi tebal, ditempatkan di ruang, lalu diperiksa.

Yang diperiksa:
  1. gambar 2D   - tab terlepas dari tepi, tepi yang miring tipis, dsb.
  2. sambungan   - tiap tab: masuk ke slot mana, muat atau tidak, celahnya berapa
  3. tabrakan    - badan panel yang saling menembus
  4. slot kosong - slot yang tidak dimasuki tab mana pun
  5. ukuran nyata hasil rakitan
"""
from __future__ import annotations

import math

import numpy as np
import trimesh
from shapely.geometry import MultiPoint

from . import geom

MIN_VOL = 1.0     # mm3: tumpang-tindih lebih kecil dari ini diabaikan
TOL = 0.05        # mm: batas "pas"
TIGHT = 0.5       # mm: kurang sampai segini = "sesak" (ketidaktelitian gambar), lebih = gagal


def _extrude(shape, h):
    polys = [shape] if shape.geom_type == "Polygon" else \
        [g for g in getattr(shape, "geoms", []) if g.geom_type == "Polygon"]
    meshes = [trimesh.creation.extrude_polygon(p, h) for p in polys if p.area > 1e-6]
    if not meshes:
        return None
    return meshes[0] if len(meshes) == 1 else trimesh.util.concatenate(meshes)


def _intersect(a, b):
    try:
        m = trimesh.boolean.intersection([a, b], engine="manifold")
    except Exception:
        return None
    if m is None or m.is_empty or len(m.faces) == 0 or abs(m.volume) < 1e-6:
        return None
    return m


def _r(x, n=2):
    return round(float(x), n)


class Assembly:
    def __init__(self, project):
        self.pr = project
        self.t = project.thickness
        self.items = {}
        for p in project.placed():
            M = project.matrix(p.id)
            full = _extrude(p.solid(), self.t)
            body = _extrude(p.solid(with_tabs=False), self.t)
            full.apply_transform(M)
            body.apply_transform(M)
            self.items[p.id] = {"panel": p, "M": M, "Minv": np.linalg.inv(M),
                                "full": full, "body": body,
                                "plain": p.solid(with_cuts=False), "solid": p.solid()}
        self.collision_meshes = []
        self.sections = {}        # (tab, panel b) -> penampang tab pada bidang b (koordinat lokal b), untuk slot otomatis

    # ------------------------------------------------------------------ gambar
    def lint(self):
        out = []
        info = self.pr.info
        if info.get("expanded_strokes"):
            out.append({"level": "info", "panel": None, "msg":
                        f"{info['expanded_strokes']} bentuk di gambar berupa garis yang sudah di-expand "
                        "(kontur ganda). Yang dipakai kontur luarnya; file asli tidak bisa langsung "
                        "dipotong, pakai hasil `export`."})
        for p in self.pr.panels:
            loose = [t for t in p.tabs if t.gap > TOL]
            if loose:
                out.append({"level": "warn", "panel": p.id, "msg":
                            f"{len(loose)} tab digambar terlepas dari tepi panel (celah maks "
                            f"{max(t.gap for t in loose):.2f} mm): {', '.join(t.id for t in loose)}. "
                            "Di rakitan dan hasil export tab disambungkan otomatis."})
            if p.generated and self.pr.spec["panels"].get(p.id, {}).get("edges"):
                out.append({"level": "warn", "panel": p.id, "msg":
                            "ukuran panel hasil generator diubah manual (batas); sambungan dengan panel lain bisa "
                            "tidak pas. Ubah ukuran lewat parameter Generator box."})
            for f in p.features:
                if f.added and f.role == "cut" and not p.outline.buffer(0.01).contains(f.poly):
                    out.append({"level": "warn", "panel": p.id, "msg":
                                f"bentuk tambahan {f.id} ({f.kind}) keluar dari tepi panel; "
                                "bagian di luar akan memotong tepinya"})
            c = list(p.outline.exterior.coords)
            for a, b in zip(c, c[1:]):
                L = math.dist(a, b)
                if L < 5:
                    continue
                ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 90
                dev = min(ang, 90 - ang)
                if 0.01 < dev < 1.0:
                    out.append({"level": "warn", "panel": p.id, "msg":
                                f"tepi dari ({a[0]:.2f}, {a[1]:.2f}) ke ({b[0]:.2f}, {b[1]:.2f}) hampir "
                                f"lurus tetapi miring {dev:.2f}° (melenceng "
                                f"{L * math.sin(math.radians(dev)):.2f} mm)"})
        return out

    # --------------------------------------------------------------- sambungan
    def _tab_in(self, a, tab, b):
        """Periksa tab milik panel a terhadap panel b. None bila tab tidak menyentuh b."""
        A, B = self.items[a], self.items[b]
        t, kerf = self.t, self.pr.kerf
        prism = _extrude(tab.poly, t)
        prism.apply_transform(B["Minv"] @ A["M"])                 # ke koordinat lokal b
        lo, hi = prism.bounds
        if hi[2] < 0.2 or lo[2] > t - 0.2:
            return None
        bx0, by0, bx1, by1 = B["plain"].bounds
        if hi[0] < bx0 or lo[0] > bx1 or hi[1] < by0 or lo[1] > by1:
            return None
        slab = trimesh.creation.box(bounds=[[lo[0] - 1, lo[1] - 1, 0], [hi[0] + 1, hi[1] + 1, t]])
        part = _intersect(prism, slab)
        if part is None or abs(part.volume) < 2.0:
            return None
        S = MultiPoint([(x, y) for x, y, _ in part.vertices]).convex_hull
        if S.geom_type != "Polygon" or S.intersection(B["plain"]).area < 1.0:
            return None

        # arah masuk tab, dilihat dari panel b
        nw = A["M"][:3, :3] @ np.array([tab.normal[0], tab.normal[1], 0.0])
        dz = float((B["Minv"][:3, :3] @ nw)[2])
        if dz >= 0:      # masuk dari sisi z<0
            seat_gap, flush = -(hi[2] - tab.depth), hi[2] - t
        else:
            seat_gap, flush = (lo[2] + tab.depth) - t, -lo[2]
        j = {"tab": f"{a}.{tab.id}", "a": a, "b": b, "slot": None,
             "seat_gap": _r(seat_gap), "flush": _r(flush), "level": "ok", "kind": "ok"}
        if abs(dz) < 0.5:
            seat_gap = flush = 0.0
            j["seat_gap"] = j["flush"] = None

        cuts = B["panel"].cuts()
        near_cuts = [f for f in cuts if not (
            f.poly.bounds[0] > S.bounds[2] or f.poly.bounds[2] < S.bounds[0] or
            f.poly.bounds[1] > S.bounds[3] or f.poly.bounds[3] < S.bounds[1])]
        slots = [f for f in cuts if geom.is_slot(f, t)]

        # 1) bukaan non-slot (jendela, lubang besar) yang memuat seluruh penampang tab
        for f in near_cuts:
            if not geom.is_slot(f, t) and f.poly.buffer(kerf / 2 + 1e-6).contains(S):
                j.update(slot=f.id, kind="ok", msg=f"masuk bukaan {f.id}")
                return j

        # 2) slot yang bersinggungan dengan penampang tab
        best, best_ov = None, 0.0
        for f in near_cuts:
            if geom.is_slot(f, t):
                ov = S.intersection(f.poly).area
                if ov > best_ov:
                    best, best_ov = f, ov
        if best is None:
            self.sections[(j["tab"], b)] = S
            j["level"], j["kind"] = "error", "solid"
            if slots:
                near = min(slots, key=lambda f: f.poly.distance(S))
                dx, dy = near.center[0] - S.centroid.x, near.center[1] - S.centroid.y
                j["nearest_slot"] = near.id
                j["nearest_offset"] = [_r(dx), _r(dy)]
                j["deficit"] = _r(math.hypot(dx, dy))
                j["msg"] = (f"menabrak bagian pejal {b}: tidak ada slot di posisi ini. Slot terdekat "
                            f"{near.id} bergeser {math.hypot(dx, dy):.2f} mm "
                            f"(dx {dx:+.2f}, dy {dy:+.2f} di koordinat {b})")
            else:
                j["msg"] = f"menabrak bagian pejal {b}: panel ini tidak punya slot"
            return j

        j["slot"] = best.id
        ang = math.radians(best.angle)
        ax = (math.cos(ang), math.sin(ang))
        L, W = best.size
        ls = [(x - best.center[0]) * ax[0] + (y - best.center[1]) * ax[1] for x, y in S.exterior.coords]
        ws = [-(x - best.center[0]) * ax[1] + (y - best.center[1]) * ax[0] for x, y in S.exterior.coords]
        # kerf: slot melebar kerf/2 per sisi; panjang tab menyusut kerf/2 per sisi
        cl = [min(ls) + L / 2 + kerf, L / 2 - max(ls) + kerf,
              min(ws) + W / 2 + kerf / 2, W / 2 - max(ws) + kerf / 2]
        j["slot_size"] = [_r(L), _r(W)]
        j["tab_section"] = [_r(max(ls) - min(ls)), _r(max(ws) - min(ws))]
        j["shift"] = [_r((max(ls) + min(ls)) / 2), _r((max(ws) + min(ws)) / 2)]
        j["play"] = [_r(cl[0] + cl[1]) + 0.0, _r(cl[2] + cl[3]) + 0.0]   # total celah panjang, lebar
        worst = min(cl)
        j["min_clearance"] = _r(worst)
        if worst < -TOL:
            dl, dw = -min(cl[0], cl[1]), -min(cl[2], cl[3])
            j["deficit"] = _r(-worst)
            j["dir"] = "sepanjang" if dl >= dw else "selebar"
            j["kind"] = "misfit" if -worst > TIGHT else "tight"
            j["level"] = "error" if -worst > TIGHT else "tight"
            why = []
            if dl > TOL:
                why.append(f"sepanjang slot kurang {dl:.2f} mm "
                           f"(tab {j['tab_section'][0]:.2f}, slot {L:.2f}, geser {j['shift'][0]:+.2f})")
            if dw > TOL:
                why.append(f"selebar slot kurang {dw:.2f} mm "
                           f"(tab {j['tab_section'][1]:.2f}, slot {W:.2f}, geser {j['shift'][1]:+.2f})")
            j["msg"] = ("tidak muat di slot " if j["kind"] == "misfit" else "sesak di slot ") \
                + best.id + ": " + "; ".join(why)
        else:
            j["kind"] = "ok"
            j["msg"] = (f"masuk slot {best.id}, celah total {j['play'][0]:.2f} (panjang) x "
                        f"{j['play'][1]:.2f} (lebar) mm")
        notes = []
        if j["kind"] == "ok" and j["seat_gap"] is not None:
            if seat_gap > 0.1:
                notes.append(f"tepi panel tidak menempel, celah {seat_gap:.2f} mm")
                j["level"] = "warn"
            if flush < -0.1:
                notes.append(f"ujung tab kurang {-flush:.2f} mm dari rata")
            elif flush > 0.1:
                notes.append(f"ujung tab menonjol {flush:.2f} mm")
        if notes:
            j["msg"] += "; " + "; ".join(notes)
        return j

    def joints(self):
        out, used = [], set()
        ids = list(self.items)
        for a in ids:
            for tab in self.items[a]["panel"].tabs:
                hits = [j for b in ids if b != a for j in [self._tab_in(a, tab, b)] if j]
                if not hits:
                    out.append({"tab": f"{a}.{tab.id}", "a": a, "b": None, "slot": None, "level": "warn",
                                "kind": "free", "msg": "tab tidak masuk ke panel mana pun"})
                for j in hits:
                    if j["slot"]:
                        used.add((j["b"], j["slot"]))
                    out.append(j)
        empty = []
        for b in ids:
            for f in self.items[b]["panel"].cuts():
                if geom.is_slot(f, self.t) and (b, f.id) not in used:
                    empty.append(f"{b}.{f.id}")
        return out, empty

    # ----------------------------------------------------------------- tabrakan
    def collisions(self):
        out = []
        self.collision_meshes = []
        ids = list(self.items)
        for i, a in enumerate(ids):
            for b in ids[i + 1:]:
                A, B = self.items[a], self.items[b]
                (al, ah), (bl, bh) = A["body"].bounds, B["body"].bounds
                if np.any(ah < bl + 1e-6) or np.any(bh < al + 1e-6):
                    continue
                m = _intersect(A["body"], B["body"])
                if m is None or abs(m.volume) < MIN_VOL:
                    continue
                ext = [m.extents]
                for it in (A, B):
                    loc = trimesh.transform_points(m.vertices, it["Minv"])
                    ext.append(loc.max(axis=0) - loc.min(axis=0))
                depth = float(min(e.min() for e in ext))
                self.collision_meshes.append(m)
                out.append({"a": a, "b": b, "volume": _r(abs(m.volume), 1), "depth": _r(depth),
                            "level": "error" if depth > TIGHT else "tight",
                            "size": [_r(v) for v in m.extents],
                            "center": [_r(v) for v in m.bounds.mean(axis=0)],
                            "msg": f"badan panel saling menembus sedalam {depth:.2f} mm "
                                   f"(volume {abs(m.volume):.0f} mm3, area tumpang-tindih "
                                   f"{' x '.join(f'{v:.1f}' for v in m.extents)} mm di sekitar "
                                   f"{', '.join(f'{v:.1f}' for v in m.bounds.mean(axis=0))})"})
        return out

    # ------------------------------------------------------------------ laporan
    def report(self):
        joints, empty = self.joints()
        cols = self.collisions()
        lint = self.lint()
        placed = list(self.items)
        rep = {"thickness": self.t, "kerf": self.pr.kerf,
               "placed": placed,
               "unplaced": [p.id for p in self.pr.panels if p.id not in self.items],
               "drawing": lint, "joints": joints, "collisions": cols, "empty_slots": empty,
               "panels": []}
        if placed:
            lo = np.min([self.items[i]["full"].bounds[0] for i in placed], axis=0)
            hi = np.max([self.items[i]["full"].bounds[1] for i in placed], axis=0)
            blo = np.min([self.items[i]["body"].bounds[0] for i in placed], axis=0)
            bhi = np.max([self.items[i]["body"].bounds[1] for i in placed], axis=0)
            rep["size_with_tabs"] = [_r(v) for v in hi - lo]
            rep["size_body"] = [_r(v) for v in bhi - blo]
            rep["bounds"] = [[_r(v) for v in lo], [_r(v) for v in hi]]
            for i in placed:
                b = self.items[i]["body"].bounds
                rep["panels"].append({"id": i, "name": self.items[i]["panel"].name,
                                      "min": [_r(v) for v in b[0]], "max": [_r(v) for v in b[1]]})
        both = joints + cols
        rep["errors"] = sum(j["level"] == "error" for j in both)
        rep["tight"] = sum(j["level"] == "tight" for j in both)
        rep["warnings"] = sum(j["level"] == "warn" for j in joints) + len(empty) + \
            sum(d["level"] == "warn" for d in lint)
        rep["ok"] = rep["errors"] == 0 and bool(placed)
        return rep

    # ------------------------------------------------------------- untuk viewer
    def scene(self):
        out = []
        for pid, it in self.items.items():
            m = it["full"]
            out.append({"id": pid, "name": it["panel"].name,
                        "v": np.round(m.vertices, 3).ravel().tolist(),
                        "f": m.faces.ravel().tolist(),
                        "center": [_r(v) for v in m.bounds.mean(axis=0)]})
        return out
