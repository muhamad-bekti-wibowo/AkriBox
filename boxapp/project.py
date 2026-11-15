"""File proyek (*.box.json): sumber gambar + tebal + posisi rakitan tiap panel.

Geometri TIDAK disimpan di file proyek; selalu dibaca ulang dari gambar sumber,
sehingga file proyek tetap kecil dan mudah diedit manusia maupun LLM.

Format:
{
  "source": "gambar.ai",
  "thickness": 5.0,            # tebal material (mm)
  "kerf": 0.0,                 # lebar garis potong laser (mm)
  "panels": {
    "P4": {
      "name": "samping_kiri",
      "roles": {"F12": "guide"},          # timpa peran fitur: cut | guide | ignore
      "placement": {"origin": [0, 0, 0], "u": "+X", "v": "+Z"}
    }
  }
}

placement: titik (x, y) lokal panel dipetakan ke  origin + x*u + y*v.
Tebal panel memanjang dari bidang itu sejauh `thickness` ke arah n = u x v.
u dan v boleh ditulis "+X", "-Y", ... atau vektor [x, y, z].
"""
from __future__ import annotations

import json
import os

import numpy as np

from . import geom

AXES = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0),
        "+Z": (0, 0, 1), "-Z": (0, 0, -1)}


class ProjectError(Exception):
    pass


def _vec(v, what):
    if isinstance(v, str):
        if v.upper() not in AXES:
            raise ProjectError(f"{what}: sumbu '{v}' tidak dikenal (pakai +X, -X, +Y, -Y, +Z, -Z)")
        return np.array(AXES[v.upper()], float)
    a = np.array(v, float)
    if a.shape != (3,):
        raise ProjectError(f"{what}: harus 3 angka [x, y, z]")
    return a


class Project:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.dir = os.path.dirname(self.path)
        with open(self.path, encoding="utf-8") as f:
            self.spec = json.load(f)
        self.spec.setdefault("thickness", 5.0)
        self.spec.setdefault("kerf", 0.0)
        self.spec.setdefault("panels", {})
        self.reload()

    # -- geometri ------------------------------------------------------------
    @property
    def source(self):
        src = self.spec.get("source")
        return os.path.join(self.dir, src) if src else None

    def reload(self):
        """Susun panel: dari gambar sumber (bila ada), generator box, dan panel baru; lalu terapkan edit."""
        if self.source:
            if not os.path.exists(self.source):
                raise ProjectError(f"gambar sumber tidak ditemukan: {self.source}")
            roles = {pid: p.get("roles", {}) for pid, p in self.spec["panels"].items()}
            self.panels, self.info = geom.extract_panels(self.source, roles)
        else:
            self.panels, self.info = [], {}
        self._gen_place = {}
        if self.spec.get("generator"):
            from . import generator
            gp, self._gen_place = generator.build(self.spec)
            self.panels += gp
        for pid, conf in self.spec["panels"].items():
            if "new" in conf:
                self.panels.append(geom.make_new_panel(pid, conf))
        self.panels = [p for p in self.panels if not self.spec["panels"].get(p.id, {}).get("removed")]
        for p in self.panels:
            conf = self.spec["panels"].get(p.id, {})
            p.name = conf.get("name", p.name)
            geom.apply_edits(p, conf)
        self._by_id = {p.id: p for p in self.panels}

    @property
    def thickness(self):
        return float(self.spec["thickness"])

    @property
    def kerf(self):
        return float(self.spec["kerf"])

    def panel(self, pid):
        return self._by_id.get(pid)

    def label(self, pid):
        p = self._by_id.get(pid)
        return f"{pid} ({p.name})" if p and p.name else pid

    # -- penempatan 3D ---------------------------------------------------------
    def matrix(self, pid):
        """Matriks 4x4 lokal->dunia, atau None bila panel belum ditempatkan."""
        pl = self.spec["panels"].get(pid, {}).get("placement") or getattr(self, "_gen_place", {}).get(pid)
        if not pl:
            return None
        u = _vec(pl.get("u", "+X"), f"{pid}.u")
        v = _vec(pl.get("v", "+Y"), f"{pid}.v")
        o = _vec(pl.get("origin", [0, 0, 0]), f"{pid}.origin")
        if np.linalg.norm(u) < 1e-9 or np.linalg.norm(v) < 1e-9:
            raise ProjectError(f"{pid}: u / v tidak boleh nol")
        u = u / np.linalg.norm(u)
        v = v / np.linalg.norm(v)
        if abs(float(u @ v)) > 1e-3:
            raise ProjectError(f"{pid}: u dan v harus saling tegak lurus (dot = {float(u @ v):.4f})")
        n = np.cross(u, v)
        m = np.eye(4)
        m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = u, v, n, o
        return m

    def placed(self):
        return [p for p in self.panels if self.matrix(p.id) is not None]

    # -- simpan ------------------------------------------------------------------
    def save(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(self.spec, f, indent=2, ensure_ascii=False)
            f.write("\n")


def new_project(out, inner, thickness=5.0, kerf=0.0, tab=20, top=True):
    """Proyek kosong (tanpa gambar sumber) berisi generator box."""
    from . import generator
    if os.path.exists(out):
        raise ProjectError(f"{out} sudah ada; pilih nama lain atau hapus dulu")
    spec = {"thickness": thickness, "kerf": kerf, "generator": generator.default_generator(inner, tab, top),
            "panels": {}}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return out


def init(source, out=None, thickness=5.0):
    source = os.path.abspath(source)
    out = out or os.path.splitext(source)[0] + ".box.json"
    spec = {"source": os.path.relpath(source, os.path.dirname(os.path.abspath(out))),
            "thickness": thickness, "kerf": 0.0, "panels": {}}
    panels, _ = geom.extract_panels(source)
    for p in panels:
        spec["panels"][p.id] = {"name": ""}
    with open(out, "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return out
