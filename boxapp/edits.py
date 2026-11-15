"""Penyuntingan bentuk 2D tanpa menyentuh gambar sumber.

Semua perubahan disimpan di file proyek, per panel:

  "edits": {
    "add":    [ {"id":"A1","kind":"circle","center":[x,y],"r":4,"role":"cut"},
                {"id":"A2","kind":"rect","center":[x,y],"size":[w,h],"angle":0},
                {"id":"A3","kind":"poly","points":[[x,y],...]} ],
    "move":   {"F12": [dx, dy], "T3": [dx, dy]},     # geser fitur / tab bawaan gambar
    "delete": ["F5", "T2"]                            # buang fitur / tab bawaan gambar
  }

Panel baru (tidak ada di gambar sumber) ditulis sebagai  "N1": {"new": {"size":[w,h]}}
atau {"new": {"polygon": [[x,y], ...]}}.

Koordinat: milik panel, (0,0) = pojok kiri-bawah, y ke atas, mm.
Fungsi di sini bekerja pada dict spec; `apply_ops` membungkusnya untuk satu Project.
"""
from __future__ import annotations

import math

from shapely import affinity
from shapely.geometry import Point, Polygon, box

from . import measure
from .project import ProjectError

ROLES = ("cut", "guide", "ignore")


def _r(x):
    return round(float(x), 3)


def _pt(v, what):
    try:
        x, y = float(v[0]), float(v[1])
    except Exception:
        raise ProjectError(f"{what}: butuh dua angka [x, y]")
    if not (math.isfinite(x) and math.isfinite(y)):
        raise ProjectError(f"{what}: angka tidak valid")
    return [_r(x), _r(y)]


def clean_shape(s):
    """Rapikan dan validasi satu bentuk; hasil berisi kind, role, dan data geometrinya."""
    kind = s.get("kind")
    role = s.get("role", "tab" if s.get("kind") == "tab" else "cut")
    if role not in ROLES and role != "tab":
        raise ProjectError(f"role harus salah satu dari {ROLES}")
    out = {"kind": kind, "role": role}
    if s.get("id"):
        out["id"] = str(s["id"])
    for k in ("group", "comp"):
        if s.get(k):
            out[k] = str(s[k])
    if kind == "circle":
        r = float(s["r"]) if "r" in s else float(s["d"]) / 2
        if not r > 0:
            raise ProjectError("lingkaran: jari-jari harus > 0")
        out.update(center=_pt(s["center"], "center"), r=_r(r))
    elif kind == "rect":
        w, h = (float(v) for v in s["size"])
        if not (w > 0 and h > 0):
            raise ProjectError("kotak: lebar dan tinggi harus > 0")
        out.update(center=_pt(s["center"], "center"), size=[_r(w), _r(h)], angle=_r(s.get("angle", 0)))
    elif kind == "tab":
        w, h = (float(v) for v in s["size"])
        if not (w > 0 and h > 0):
            raise ProjectError("tab: lebar dan tinggi harus > 0")
        out.update(center=_pt(s["center"], "center"), size=[_r(w), _r(h)], angle=0)
        out["role"] = "tab"
    elif kind == "poly":
        pts = [_pt(p, "titik") for p in s["points"]]
        if len(pts) < 3 or Polygon(pts).buffer(0).area < 1e-6:
            raise ProjectError("poligon: butuh minimal 3 titik yang membentuk luas")
        out["points"] = pts
    else:
        raise ProjectError(f"bentuk '{kind}' tidak dikenal (circle | rect | poly | tab)")
    return out


def shape_poly(s):
    """Polygon shapely dari dict bentuk (untuk pengecekan tumpang-tindih / di dalam panel)."""
    if s["kind"] == "circle":
        return Point(*s["center"]).buffer(s["r"], 16)
    if s["kind"] in ("rect", "tab"):
        (cx, cy), (w, h) = s["center"], s["size"]
        g = box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)
        return affinity.rotate(g, s.get("angle", 0), origin=(cx, cy)) if s.get("angle") else g
    return Polygon(s["points"]).buffer(0)


# ----------------------------------------------------------------------------
def _conf(spec, pid):
    if pid not in spec["panels"]:
        raise ProjectError(f"panel tidak dikenal: {pid}")
    return spec["panels"][pid]


def _ed(spec, pid):
    c = _conf(spec, pid)
    ed = c.setdefault("edits", {})
    ed.setdefault("add", [])
    ed.setdefault("move", {})
    ed.setdefault("delete", [])
    return ed


def _tidy(spec, pid):
    c = spec["panels"].get(pid)
    if not c or "edits" not in c:
        return
    ed = c["edits"]
    for k in ("add", "move", "delete", "groups"):
        if not ed.get(k):
            ed.pop(k, None)
    if not any(k in ed for k in ("add", "move", "delete", "groups")):
        c.pop("edits")


def add_shape(spec, pid, shape):
    s = clean_shape(shape)
    ed = _ed(spec, pid)
    used = {a["id"] for a in ed["add"]}
    n = int(ed.get("seq", 0))
    while True:
        n += 1
        if f"A{n}" not in used:
            break
    ed["seq"] = n
    s["id"] = f"A{n}"
    ed["add"].append(s)
    _tidy(spec, pid)
    return s["id"]


def _find_added(ed, fid):
    return next((a for a in ed["add"] if a["id"] == fid), None)


def group(pr, pid, ids):
    """Satukan bentuk terpilih jadi satu grup: dipilih, digeser, dan dihapus bersama."""
    panel = pr.panel(pid)
    have = {f.id for f in panel.features}
    ids = [i for i in dict.fromkeys(ids) if i in have]
    if len(ids) < 2:
        raise ProjectError("pilih minimal 2 bentuk (lubang / kotak) untuk dijadikan grup; tab tidak bisa digrup")
    ungroup(pr, pid, ids, quiet=True)
    ed = _ed(pr.spec, pid)
    ed["gseq"] = int(ed.get("gseq", 0)) + 1
    gid = f"K{ed['gseq']}"
    ed.setdefault("groups", {})[gid] = ids
    return {"group": gid, "ids": ids, "text": f"{len(ids)} bentuk digrup ({gid})"}


def ungroup(pr, pid, ids, quiet=False):
    ed = _ed(pr.spec, pid)
    feats = pr.panel(pid).features
    gone = set(ids)
    for f in feats:                                     # seluruh anggota grup dari bentuk-bentuk itu ikut lepas
        if f.id in set(ids) and f.group:
            gone |= {g.id for g in feats if g.group == f.group}
    for gid in list(ed.get("groups", {})):
        ed["groups"][gid] = [i for i in ed["groups"][gid] if i not in gone]
        if len(ed["groups"][gid]) < 2:
            del ed["groups"][gid]
    for a in ed["add"]:
        if a["id"] in gone:
            a.pop("group", None)
            a.pop("comp", None)
    _tidy(pr.spec, pid)
    return None if quiet else {"text": f"{len(gone)} bentuk dilepas dari grup"}


def move(spec, pid, ids, dx, dy):
    ed = _ed(spec, pid)
    for fid in ids:
        a = _find_added(ed, fid)
        if a is None:
            m = ed["move"].get(fid, [0.0, 0.0])
            ed["move"][fid] = [_r(m[0] + dx), _r(m[1] + dy)]
        elif a["kind"] == "poly":
            a["points"] = [[_r(x + dx), _r(y + dy)] for x, y in a["points"]]
        else:
            a["center"] = [_r(a["center"][0] + dx), _r(a["center"][1] + dy)]
    _tidy(spec, pid)


def delete(spec, pid, ids):
    ed = _ed(spec, pid)
    for fid in ids:
        a = _find_added(ed, fid)
        if a is not None:
            ed["add"].remove(a)
        else:
            ed["move"].pop(fid, None)
            if fid not in ed["delete"]:
                ed["delete"].append(fid)
    _tidy(spec, pid)


def restore(spec, pid, ids):
    ed = _ed(spec, pid)
    for fid in ids:
        if fid in ed["delete"]:
            ed["delete"].remove(fid)
        ed["move"].pop(fid, None)
    _tidy(spec, pid)


def replace(spec, pid, fid, shape):
    """Ubah bentuk. Bentuk tambahan diubah di tempat; bentuk bawaan gambar diganti
    (yang lama dibuang, yang baru ditambahkan). Mengembalikan id bentuk sekarang."""
    ed = _ed(spec, pid)
    a = _find_added(ed, fid)
    new = clean_shape({**(a or {}), **shape, "id": fid})
    if a is not None:
        ed["add"][ed["add"].index(a)] = new
        _tidy(spec, pid)
        return fid
    delete(spec, pid, [fid])
    return add_shape(spec, pid, shape)


def set_role(spec, pid, fid, role):
    if role not in ROLES:
        raise ProjectError(f"role harus salah satu dari {ROLES}")
    a = _find_added(_ed(spec, pid), fid)
    if a is not None:
        a["role"] = role
    else:
        _conf(spec, pid).setdefault("roles", {})[fid] = role
    _tidy(spec, pid)


def new_panel(spec, name="", size=None, polygon=None):
    if size is not None:
        w, h = float(size[0]), float(size[1])
        if not (w > 0 and h > 0):
            raise ProjectError("ukuran panel harus > 0")
        new = {"size": [_r(w), _r(h)]}
    elif polygon is not None:
        pts = [_pt(p, "titik") for p in polygon]
        if len(pts) < 3 or Polygon(pts).buffer(0).area < 1e-6:
            raise ProjectError("outline panel butuh minimal 3 titik yang membentuk luas")
        new = {"polygon": pts}
    else:
        raise ProjectError("panel baru butuh size atau polygon")
    n = 1
    while f"N{n}" in spec["panels"]:
        n += 1
    pid = f"N{n}"
    spec["panels"][pid] = {"name": name or f"panel_baru_{n}", "new": new}
    return pid


def remove_panel(spec, pid):
    """Panel baru dihapus total; panel dari gambar / generator ditandai 'removed' (bisa dipulihkan)."""
    c = _conf(spec, pid)
    if "new" in c:
        del spec["panels"][pid]
    else:
        c["removed"] = True


def restore_panel(spec, pid):
    c = spec["panels"].get(pid)
    if not c or not c.pop("removed", None):
        raise ProjectError(f"{pid} tidak sedang dihapus")


def resize_panel(spec, pid, size):
    c = _conf(spec, pid)
    if "new" not in c or "size" not in c["new"]:
        raise ProjectError(f"{pid}: ukuran hanya bisa diubah untuk panel baru berbentuk kotak")
    w, h = float(size[0]), float(size[1])
    if not (w > 0 and h > 0):
        raise ProjectError("ukuran panel harus > 0")
    c["new"]["size"] = [_r(w), _r(h)]


EDGE_NAMES = ("left", "right", "bottom", "top")


def set_edges(spec, pid, vals):
    """vals: {"left": x, "right": x, "bottom": y, "top": y}; nilai None = kembalikan ke bawaan gambar."""
    c = _conf(spec, pid)
    ed = c.setdefault("edges", {})
    for k, v in vals.items():
        if k not in EDGE_NAMES:
            raise ProjectError(f"batas '{k}' tidak dikenal ({', '.join(EDGE_NAMES)})")
        if v is None:
            ed.pop(k, None)
        else:
            v = float(v)
            if not math.isfinite(v):
                raise ProjectError(f"batas {k}: angka tidak valid")
            ed[k] = _r(v)
    if not ed:
        c.pop("edges")


def _world_corners(pr, pid):
    """Titik sudut badan panel (outline tanpa tab, kedua muka) di koordinat dunia, atau None bila belum ditempatkan."""
    import numpy as np
    M = pr.matrix(pid)
    if M is None:
        return None
    out = []
    for x, y in list(pr.panel(pid).outline.exterior.coords)[:-1]:
        for z in (0.0, pr.thickness):
            out.append(M @ np.array([x, y, z, 1.0]))
    return np.array(out)[:, :3]


def snap_place(pr, pid, delta=(0, 0, 0), tol=8.0, step=0.0, magnet=True, target=None):
    """Geser panel `pid` sebesar `delta` (dunia, mm; dibulatkan ke kisi `step`), lalu bila `magnet` aktif tempelkan
    permukaannya ke permukaan panel lain yang berdekatan (selisih <= `tol` mm dan saling berhadapan).
    Menempel = muka panel ini bersentuhan dengan muka panel lain, sehingga sisi rak menempel di dinding."""
    import numpy as np
    from .project import _vec
    pl = pr.spec["panels"].get(pid, {}).get("placement") or getattr(pr, "_gen_place", {}).get(pid)
    if not pl:
        raise ProjectError(f"{pid}: belum ditempatkan di rakitan")
    d = np.array([measure.snap(float(v), step) for v in delta], float)
    A = _world_corners(pr, pid) + d
    others = [p for p in pr.panels if p.id != pid and pr.matrix(p.id) is not None and (not target or p.id == target)]
    corners = {p.id: _world_corners(pr, p.id) for p in others}
    normal = lambda q: pr.matrix(q)[:3, 2] / np.linalg.norm(pr.matrix(q)[:3, 2])
    nA = normal(pid)
    shift, stuck, used = np.zeros(3), [], set()
    for _ in range(3 if magnet else 0):                    # koreksi terkecil dulu, hitung ulang, paling banyak 3 sumbu
        cands = []
        Acur = A + shift
        for p in others:
            B = corners[p.id]
            for n in (normal(p.id), nA):                   # muka panel lain, lalu muka panel ini
                key = tuple(np.round(np.abs(n), 2))
                if key in used:
                    continue
                a, b = Acur @ n, B @ n
                sv = min((b.max() - a.min(), b.min() - a.max()), key=abs)
                e1 = np.cross(n, [1.0, 0, 0] if abs(n[0]) < 0.9 else [0, 1.0, 0])
                e1 /= np.linalg.norm(e1)
                e2 = np.cross(n, e1)
                if any(min((Acur @ e).max(), (B @ e).max()) - max((Acur @ e).min(), (B @ e).min()) < 1.0 for e in (e1, e2)):
                    continue                               # tidak berhadapan (tidak saling beririsan di bidang)
                if abs(sv) <= tol:
                    cands.append((abs(sv), float(sv), n, p.id, key))
        if not cands:
            break
        mag, sv, n, name, key = min(cands, key=lambda c: c[0])
        used.add(key)
        shift += sv * n
        if mag > 1e-6:
            stuck.append((name, mag))
    o = _vec(pl.get("origin", [0, 0, 0]), "origin") + d + shift
    _conf(pr.spec, pid)["placement"] = {"origin": [round(float(x), 2) for x in o], "u": pl.get("u", "+X"), "v": pl.get("v", "+Y")}
    moved = [round(float(x), 2) for x in d + shift]
    if stuck:
        text = f"{pid} menempel ke " + ", ".join(f"{n} (geser {m:.2f} mm)" for n, m in stuck)
    elif magnet:
        text = f"{pid} digeser {moved}; sudah menempel atau tidak ada permukaan panel lain dalam {tol:g} mm"
    else:
        text = f"{pid} digeser {moved}"
    return {"moved": moved, "snapped": [n for n, _ in stuck], "text": text}


MAGNET_DEG = 2.0         # hasil putaran yang sedekat ini ke sumbu dunia dikunci lurus tepat


def rotate_panel(pr, pid, axis, angle, center, step=0.0):
    """Putar panel `angle` derajat mengitari garis lewat `center` searah `axis` (koordinat dunia).
    Sudut dibulatkan ke kelipatan `step` (0 = bebas, 0.01 derajat); bila u dan v hasilnya hampir sejajar sumbu dunia
    (dalam MAGNET_DEG) keduanya dikunci tepat ke sumbu itu, sehingga panel benar-benar lurus."""
    import numpy as np
    from .project import _vec
    pl = pr.spec["panels"].get(pid, {}).get("placement") or getattr(pr, "_gen_place", {}).get(pid)
    if not pl:
        raise ProjectError(f"{pid}: belum ditempatkan di rakitan")
    k = np.array(axis, float)
    if np.linalg.norm(k) < 1e-9:
        raise ProjectError("sumbu putar tidak valid")
    k /= np.linalg.norm(k)
    step = float(step or 0)
    ang = round(round(float(angle) / step) * step, 4) if step > 0 else round(float(angle), 2)
    a = math.radians(ang)

    def rot(v):
        return v * math.cos(a) + np.cross(k, v) * math.sin(a) + k * float(k @ v) * (1 - math.cos(a))
    u, v = rot(_vec(pl.get("u", "+X"), "u")), rot(_vec(pl.get("v", "+Y"), "v"))
    c = np.array(center, float)
    o = c + rot(_vec(pl.get("origin", [0, 0, 0]), "origin") - c)
    axes = {"+X": (1, 0, 0), "-X": (-1, 0, 0), "+Y": (0, 1, 0), "-Y": (0, -1, 0), "+Z": (0, 0, 1), "-Z": (0, 0, -1)}

    def near(w):
        n, d = min(((n, float(np.clip(w @ np.array(d_), -1, 1))) for n, d_ in axes.items()), key=lambda t: -t[1])
        return n if math.degrees(math.acos(d)) <= MAGNET_DEG else None
    nu, nv = near(u), near(v)
    locked = bool(nu and nv)
    if locked:                                           # titik tengah panel tetap di tempatnya saat u, v dikunci
        b = pr.panel(pid).outline.bounds
        cx, cy = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        nu_v, nv_v = np.array(axes[nu], float), np.array(axes[nv], float)
        o = o + cx * u + cy * v - cx * nu_v - cy * nv_v
    u_out = nu if locked else [round(float(x), 5) for x in u]
    v_out = nv if locked else [round(float(x), 5) for x in v]
    _conf(pr.spec, pid)["placement"] = {"origin": [round(float(x), 2) for x in o], "u": u_out, "v": v_out}
    return {"angle": ang, "locked": locked, "text": f"{pid} diputar {ang:g}°" + (" (dikunci lurus ke sumbu)" if locked else "")}


def outline(pr, pid, op):
    """Ubah bentuk outline panel: geser titik / sisi, sisipkan / hapus titik, trapesium, atau reset."""
    panel = pr.panel(pid)
    if panel is None:
        raise ProjectError(f"tidak ada panel {pid}")
    conf = _conf(pr.spec, pid)
    act = op.get("act")
    if act == "reset":
        conf.pop("outline", None)
        return {"text": "bentuk outline dikembalikan ke bawaan"}
    pts = [[x, y] for x, y in list(panel.outline.exterior.coords)[:-1]]
    step = op.get("step", 1)
    step = 1.0 if step is None else float(step)
    args = {q: op[q] for q in ("i", "to", "delta", "at", "side", "a", "b") if q in op}
    try:
        r = measure.outline_edit(pts, act, step, **args)
    except ValueError as e:
        raise ProjectError(str(e))
    if op.get("magnet") and act == "vertex":
        to, _, _ = measure.magnet_vertex(panel, pts, int(op["i"]), r["to"], float(op.get("tol") or 0))
        if to != r["to"]:
            r = measure.outline_edit(pts, act, 0, i=op["i"], to=to)
    poly = Polygon(r["pts"])
    if not poly.is_valid or poly.area < 1e-6:
        raise ProjectError("bentuk baru tidak valid (sisi saling memotong atau luasnya nol)")
    conf["outline"] = [[round(x, 3), round(y, 3)] for x, y in r["pts"]]
    return {"text": r["text"], "outline": conf["outline"]}


def set_fields(pr, pid, fid, values, step=0.0):
    """Ubah kolom angka satu bentuk. Panjang dibulatkan ke kisi `step`, kecuali bentuk miring / sudut."""
    panel = pr.panel(pid)
    it = next((i for i in measure.panel_items(panel, pr.thickness) if i["id"] == fid), None)
    if it is None:
        raise ProjectError(f"{pid}: tidak ada bentuk/tab dengan id {fid}")
    v = {k: float(x) for k, x in values.items()}
    exempt = it["kind"] == "rect" and measure.is_slanted(v.get("a", it["angle"]))

    def sn(key, cur):
        if key not in v:
            return cur
        return v[key] if exempt else measure.snap(v[key], step)

    cx, cy = sn("x", it["center"][0]), sn("y", it["center"][1])
    if it["kind"] == "circle":
        d = sn("d", it["r"] * 2)
        return replace(pr.spec, pid, fid, {"kind": "circle", "center": [cx, cy], "r": d / 2, "role": it["role"]})
    if it["kind"] == "rect":
        w, h = sn("w", it["size"][0]), sn("h", it["size"][1])
        return replace(pr.spec, pid, fid, {"kind": "rect", "center": [cx, cy], "size": [w, h],
                                           "angle": v.get("a", it["angle"]), "role": it["role"]})
    move(pr.spec, pid, [fid], round(cx - it["center"][0], 3), round(cy - it["center"][1], 3))
    return fid


# ---------------------------------------------------------------- tengahkan, skala, bagi sisi
ALIGN_MODES = ("center", "center-x", "center-y", "left", "right", "top", "bottom")
EDGE_TAB = {"left": "kiri", "right": "kanan", "bottom": "bawah", "top": "atas"}


def feature_shape(f):
    """Bentuk (dict) dari sebuah fitur panel, untuk dibuat ulang dengan ukuran / posisi baru."""
    c = [round(f.center[0], 3), round(f.center[1], 3)]
    if f.kind == "circle":
        return {"kind": "circle", "center": c, "r": round(f.r, 3), "role": f.role}
    if f.kind == "rect":
        return {"kind": "rect", "center": c, "size": [round(f.size[0], 3), round(f.size[1], 3)],
                "angle": round(f.angle, 3), "role": f.role}
    return {"kind": "poly", "points": [[round(x, 3), round(y, 3)] for x, y in list(f.poly.exterior.coords)[:-1]],
            "role": f.role}


def duplicate(pr, pid, ids, to=None, dx=0.0, dy=0.0, step=0.0):
    """Salin bentuk (lubang / kotak, termasuk grup dan komponen) ke panel `to` (bawaan: panel yang sama) dengan geseran
    (dx, dy). Grup disalin sebagai grup baru. Tab tidak ikut disalin."""
    src = pr.panel(pid)
    dst = pr.panel(to or pid)
    if src is None or dst is None:
        raise ProjectError(f"panel tidak dikenal: {to or pid}")
    ids = set(ids)
    feats = [f for f in src.features if f.id in ids]
    skipped_tabs = sum(1 for t in src.tabs if t.id in ids)
    if not feats:
        raise ProjectError("tidak ada lubang / kotak untuk disalin" + (" (tab tidak bisa disalin)" if skipped_tabs else ""))
    dx, dy = float(dx or 0), float(dy or 0)
    if src is dst and dx == 0 and dy == 0:
        dx, dy = 10.0, -10.0                      # salinan di tempat yang sama digeser agar terlihat
    dx, dy = measure.snap(dx, step), measure.snap(dy, step)
    pr.spec["panels"].setdefault(dst.id, {})
    ed = _ed(pr.spec, dst.id)
    gmap, new_ids, outside = {}, [], 0
    for f in feats:
        sh = feature_shape(f)
        if sh["kind"] == "poly":
            sh["points"] = [[round(x + dx, 3), round(y + dy, 3)] for x, y in sh["points"]]
        else:
            sh["center"] = [round(sh["center"][0] + dx, 3), round(sh["center"][1] + dy, 3)]
        if f.group:
            if f.group not in gmap:
                ed["gseq"] = int(ed.get("gseq", 0)) + 1
                gmap[f.group] = f"K{ed['gseq']}"
            sh["group"], sh["comp"] = gmap[f.group], f.comp
        if not dst.outline.buffer(0.01).contains(shape_poly(sh)):
            outside += 1
        new_ids.append(add_shape(pr.spec, dst.id, sh))
    text = f"{len(new_ids)} bentuk disalin" + (f" ke {dst.id}" if dst is not src else "") + f" (geser {dx:+g}, {dy:+g} mm)"
    if gmap:
        text += f", {len(gmap)} grup"
    notes = []
    if outside:
        notes.append(f"{outside} bentuk keluar dari tepi panel: geser atau hapus")
    if skipped_tabs:
        notes.append(f"{skipped_tabs} tab tidak ikut disalin")
    return {"ids": new_ids, "text": text, "notes": notes, "panel": dst.id}


def auto_slots(pr, src=None, clear=0.0, only_b=None):
    """Buat slot di panel lawan untuk setiap tab yang menabrak bagian pejal (belum ada slotnya).
    Ukuran dan posisi slot = penampang tab pada bidang panel lawan, ditambah celah `clear` (mm)."""
    from .assembly import Assembly
    clear = float(clear or 0)
    if abs(clear) > 2:
        raise ProjectError("celah slot harus antara -2 dan +2 mm")
    asm = Assembly(pr)
    joints, _ = asm.joints()
    todo = [j for j in joints if j.get("kind") == "solid" and j.get("b") and (not src or j["a"] == src)
            and (not only_b or j["b"] == only_b)]
    made, seen, outside = {}, set(), 0
    for j in todo:
        S = asm.sections.get((j["tab"], j["b"]))
        if S is None:
            continue
        x0, y0, x1, y1 = S.bounds
        c, size, ang = [(x0 + x1) / 2, (y0 + y1) / 2], [x1 - x0, y1 - y0], 0.0
        rr = S.minimum_rotated_rectangle
        if rr.geom_type == "Polygon" and rr.area < S.envelope.area * 0.98:          # penampang miring: kotak berputar
            p = list(rr.exterior.coords)
            e1, e2 = (p[1][0] - p[0][0], p[1][1] - p[0][1]), (p[2][0] - p[1][0], p[2][1] - p[1][1])
            w, h = math.hypot(*e1), math.hypot(*e2)
            ang = math.degrees(math.atan2(e1[1], e1[0])) % 180
            c, size = [rr.centroid.x, rr.centroid.y], [w, h]
        shape = {"kind": "rect", "role": "cut", "center": [round(c[0], 3), round(c[1], 3)],
                 "size": [round(size[0] + clear, 3), round(size[1] + clear, 3)], "angle": round(ang, 3)}
        key = (j["b"], tuple(shape["center"]), tuple(shape["size"]))
        if key in seen:
            continue
        seen.add(key)
        panel_b = pr.panel(j["b"])
        if not panel_b.outline.buffer(0.01).contains(shape_poly(shape)):
            outside += 1
        pr.spec["panels"].setdefault(j["b"], {})
        made.setdefault(j["b"], []).append(add_shape(pr.spec, j["b"], shape))
    n = sum(len(v) for v in made.values())
    if not n:
        return {"ids": {}, "count": 0, "notes": [], "text": "tidak ada tab yang menabrak bagian pejal: semua tab sudah punya slot"}
    notes = [f"{outside} slot keluar dari tepi panel lawan (tab menembus melewati tepi): periksa"] if outside else []
    return {"ids": made, "count": n, "notes": notes,
            "text": f"{n} slot dibuat: " + ", ".join(f"{b} ({len(v)})" for b, v in made.items())
                    + (f", celah {clear:+g} mm" if clear else "")}


def contact_edge(pr, a, b):
    """Sisi panel `a` (left/right/bottom/top) yang bertumpu pada bidang panel `b` di rakitan 3D.
    Hasil: (nama sisi, panjang yang beririsan dengan outline b) atau None."""
    import numpy as np
    from shapely.geometry import LineString
    pa, pb = pr.panel(a), pr.panel(b)
    Ma, Mb = pr.matrix(a), pr.matrix(b)
    if pa is None or pb is None or Ma is None or Mb is None:
        raise ProjectError("kedua panel harus sudah ditempatkan di rakitan 3D")
    T = np.linalg.inv(Mb) @ Ma
    t = pr.thickness
    bx = pa.outline.bounds
    to_b = lambda x, y: T @ np.array([x, y, 0.0, 1.0])
    cen = to_b((bx[0] + bx[2]) / 2, (bx[1] + bx[3]) / 2)
    edges = {"bottom": ((bx[0], bx[1]), (bx[2], bx[1])), "top": ((bx[0], bx[3]), (bx[2], bx[3])),
             "left": ((bx[0], bx[1]), (bx[0], bx[3])), "right": ((bx[2], bx[1]), (bx[2], bx[3]))}
    best, near = None, None
    for name, (p, q) in edges.items():
        P, Q = to_b(*p), to_b(*q)
        if abs(P[2] - Q[2]) > 0.3:                      # sisi harus sejajar bidang b
            continue
        z = float(P[2])
        dz = min(abs(z), abs(z - t))
        if LineString([(P[0], P[1]), (Q[0], Q[1])]).intersection(pb.outline).length > 1.0 and (near is None or dz < near[1]):
            near = (name, round(dz, 2))
        face = 0.0 if abs(z) < 1.5 and cen[2] < z - 0.5 else (t if abs(z - t) < 1.5 and cen[2] > z + 0.5 else None)
        if face is None:
            continue
        ov = LineString([(P[0], P[1]), (Q[0], Q[1])]).intersection(pb.outline).length
        if ov > 1.0 and (best is None or ov > best[1]):
            best = (name, round(ov, 3), round(z - face, 2))
    contact_edge.near = near                            # untuk pesan galat: sisi terdekat dan jaraknya
    return best


def auto_joint(pr, a, b, parts=5, pattern="alternate", start="tab", tab=None, margin=0.0, clear=0.0):
    """Sambungan tab-slot otomatis: tab di sisi panel `a` yang menempel ke panel `b`, lalu slot pasangannya di `b`
    dipotong tepat di penampang tab (dari geometri 3D)."""
    if a == b:
        raise ProjectError("pilih dua panel yang berbeda")
    hit = contact_edge(pr, a, b)
    if hit is None:
        nr = getattr(contact_edge, "near", None)
        why = (f" Sisi terdekat ({EDGE_TAB[nr[0]]}) berjarak {nr[1]:g} mm dari permukaan {b}: geser {a} sampai menempel."
               if nr else f" Tidak ada sisi {a} yang sejajar dan berhadapan dengan {b}.")
        raise ProjectError(f"{a} belum menempel pada {b} di rakitan 3D." + why)
    name = {"left": "left", "right": "right", "bottom": "bottom", "top": "top"}[hit[0]]
    pa = pr.panel(a)
    bx = pa.outline.bounds
    full = (bx[2] - bx[0]) if name in ("bottom", "top") else (bx[3] - bx[1])
    notes = []
    if abs(hit[2]) > 0.1:
        notes.append(f"sisi {a} berjarak {abs(hit[2]):g} mm dari permukaan {b} (tidak menempel tepat): geser panel agar pas")
    if hit[1] < full - 0.5:                              # b lebih pendek dari sisi: pakai bagian yang beririsan saja
        notes.append(f"panel {b} hanya menutupi {hit[1]:g} dari {full:g} mm sisi {a}; tab dibagi di sepanjang sisi penuh")
    # slot lama di panel lawan yang dipakai tab yang akan diganti dibuang dulu (kalau tidak, tab baru jatuh di slot lama)
    from .assembly import Assembly
    from . import geom
    joints0, _ = Assembly(pr).joints()
    old_tabs = {t.id for t in pa.tabs if t.edge == EDGE_TAB[name]}
    keep = {j["slot"] for j in joints0 if j.get("b") == b and j.get("slot") and j["tab"].split(".", 1)[0] != a}
    keep |= {j["slot"] for j in joints0 if j.get("b") == b and j.get("slot") and j["tab"].split(".", 1)[0] == a
             and j["tab"].split(".", 1)[1] not in old_tabs}
    fb = {f.id: f for f in pr.panel(b).features}
    gone = sorted({j["slot"] for j in joints0 if j.get("a") == a and j.get("b") == b and j.get("slot")
                   and j["tab"].split(".", 1)[1] in old_tabs and j["slot"] in fb
                   and geom.is_slot(fb[j["slot"]], pr.thickness)} - keep)
    if gone:
        pr.spec["panels"].setdefault(b, {})
        delete(pr.spec, b, gone)
        notes.append(f"{len(gone)} slot lama di {b} dibuang ({', '.join(gone)}) karena tab-nya diganti")
        pr.reload()
    d = divide(pr, a, {"edge": name, "parts": parts, "pattern": pattern, "start": start, "tab": tab, "margin": margin,
                       "mode": "tab", "replace": True, "corner": False})
    pr.reload()
    s = auto_slots(pr, a, clear, only_b=b)
    return {"edge": name, "tabs": d["ids"], "slots": s["ids"], "count": s["count"], "notes": notes + s["notes"],
            "text": f"sisi {EDGE_TAB[name]} {a} menempel ke {b}: {len(d['ids'])} tab dibuat; " + s["text"]}


def align(pr, pid, ids, mode):
    """Tengahkan / ratakan bentuk terpilih terhadap kotak pembatas outline panel (tanpa tab)."""
    from shapely.ops import unary_union
    if mode not in ALIGN_MODES:
        raise ProjectError(f"mode harus salah satu dari {ALIGN_MODES}")
    panel = pr.panel(pid)
    fs = [f for f in panel.features if f.id in set(ids)]
    if not fs:
        raise ProjectError("pilih bentuk (lubang, kotak, ...) yang akan diratakan; tab tidak ikut")
    sel = unary_union([f.poly for f in fs]).bounds
    tb = panel.outline.bounds
    cx, cy = (sel[0] + sel[2]) / 2, (sel[1] + sel[3]) / 2
    tx, ty = (tb[0] + tb[2]) / 2, (tb[1] + tb[3]) / 2
    dx = dy = 0.0
    if mode in ("center", "center-x"):
        dx = tx - cx
    if mode in ("center", "center-y"):
        dy = ty - cy
    if mode == "left":
        dx = tb[0] - sel[0]
    elif mode == "right":
        dx = tb[2] - sel[2]
    elif mode == "bottom":
        dy = tb[1] - sel[1]
    elif mode == "top":
        dy = tb[3] - sel[3]
    dx, dy = round(dx, 3), round(dy, 3)
    move(pr.spec, pid, [f.id for f in fs], dx, dy)
    return {"dx": dx, "dy": dy, "n": len(fs), "text": f"{len(fs)} bentuk digeser ({dx:+g}, {dy:+g}) mm"}


def scale(pr, pid, ids, percent, about="each", step=0.0):
    """Perbesar / perkecil bentuk terpilih. percent: 100 = tetap. about: 'each' = tiap bentuk terhadap
    pusatnya sendiri; 'selection' = seluruh pilihan terhadap pusat gabungannya (jarak antar bentuk ikut berubah).
    Ukuran dibulatkan ke kisi `step`, kecuali bentuk miring."""
    from shapely.ops import unary_union
    factor = float(percent) / 100.0
    if not 0.05 <= factor <= 20:
        raise ProjectError("skala harus antara 5% dan 2000%")
    panel = pr.panel(pid)
    fs = [f for f in panel.features if f.id in set(ids)]
    if not fs:
        raise ProjectError("pilih bentuk yang akan diskala; tab tidak bisa diskala")
    sel = unary_union([f.poly for f in fs]).bounds
    ox, oy = (sel[0] + sel[2]) / 2, (sel[1] + sel[3]) / 2

    def sn(v, exempt=False):
        return v if exempt else (measure.snap(v, step) if step else round(v, 3))

    new_ids = []
    for f in fs:
        sh = feature_shape(f)
        cx, cy = f.center
        ncx, ncy = (ox + (cx - ox) * factor, oy + (cy - oy) * factor) if about == "selection" else (cx, cy)
        if f.kind == "circle":
            d = max(sn(2 * f.r * factor), step or 0.5)
            sh["r"] = round(d / 2, 3)
        elif f.kind == "rect":
            ex = measure.is_slanted(f.angle)
            sh["size"] = [max(sn(f.size[0] * factor, ex), step or 0.5), max(sn(f.size[1] * factor, ex), step or 0.5)]
        else:
            c = f.poly.centroid
            sh["points"] = [[round(c.x + (x - c.x) * factor + (ncx - cx), 3), round(c.y + (y - c.y) * factor + (ncy - cy), 3)]
                            for x, y in sh["points"]]
        if f.kind != "poly":
            sh["center"] = [round(ncx, 3), round(ncy, 3)]
        new_ids.append(replace(pr.spec, pid, f.id, sh))
    return {"ids": new_ids, "factor": round(factor, 4), "text": f"{len(fs)} bentuk diskala {percent:g}%"}


def _joint_shapes(kind, bounds, edge, spans, start, depth, inset, clear=0.0):
    """Bentuk sambungan sepanjang `edge` panel ber-kotak-pembatas `bounds`.
    kind 'tab': tab keluar dari tepi; kind 'slot': slot di dalam panel, pusatnya `inset` dari tepi."""
    out = []
    for a, b in spans:
        c, ln = start + (a + b) / 2, b - a
        if edge in ("bottom", "top"):
            e = bounds[1] if edge == "bottom" else bounds[3]
            sgn = 1 if edge == "bottom" else -1
            y = e - sgn * depth / 2 if kind == "tab" else e + sgn * inset
            cen, size = [c, y], [ln, depth]
        else:
            e = bounds[0] if edge == "left" else bounds[2]
            sgn = 1 if edge == "left" else -1
            x = e - sgn * depth / 2 if kind == "tab" else e + sgn * inset
            cen, size = [x, c], [depth, ln]
        sh = {"kind": "tab" if kind == "tab" else "rect", "center": [round(cen[0], 3), round(cen[1], 3)],
              "size": [round(size[0], 3), round(size[1], 3)], "angle": 0}
        if kind == "slot":
            sh["role"] = "cut"
            sh["size"] = [round(size[0] + clear, 3), round(size[1] + clear, 3)]       # celah: + longgar, - pas ketat
        out.append(sh)
    return out


def divide(pr, pid, op):
    """Bagi satu sisi panel menjadi N bagian, tempatkan tab (atau slot) selang-seling, dan opsional buat
    pasangannya di panel lain dengan pembagian yang sama persis."""
    edge = op["edge"]
    if edge not in EDGE_TAB:
        raise ProjectError(f"sisi harus salah satu dari {tuple(EDGE_TAB)}")
    panel = pr.panel(pid)
    b = panel.outline.bounds
    horizontal = edge in ("bottom", "top")
    length = (b[2] - b[0]) if horizontal else (b[3] - b[1])
    start = b[0] if horizontal else b[1]
    mode = op.get("mode", "tab")
    if mode not in ("tab", "slot"):
        raise ProjectError("mode harus 'tab' atau 'slot'")
    depth = float(op.get("depth") or pr.thickness)
    inset = float(op["inset"]) if op.get("inset") not in (None, "") else depth / 2
    clear = float(op.get("clearance") or 0)
    if abs(clear) > 2 or depth + clear <= 0:
        raise ProjectError("celah slot harus antara -2 dan +2 mm dan tidak menghabiskan lebar slot")
    margin, note = float(op.get("margin") or 0), None
    if op.get("corner", True):        # slot sisi tegak lurus yang sudah ada di sudut: jangan ditimpa
        lo, hi, cids = measure.corner_reserve(panel, edge, depth, inset)
        if max(lo, hi) > margin:
            margin, note = max(lo, hi), f"jarak ujung {measure.fmt(max(lo, hi))} mm (slot sudut {', '.join(cids)})"
    if int(op.get("rows") or 0) > 0 and mode == "slot" and margin < depth:    # rak berada di antara dua dinding tegak
        margin, note = depth, f"jarak ujung {measure.fmt(depth)} mm (tebal dinding di kedua ujung rak)"
    try:
        plan = measure.divide_plan(length, op.get("parts", 3), op.get("pattern", "alternate"), op.get("start", "tab"),
                                   op.get("tab"), margin)
    except ValueError as e:
        raise ProjectError(str(e))
    if note:
        plan["notes"].insert(0, note)
    if mode == "tab" and op.get("replace", True):          # buang tab lama di sisi yang sama
        old = [t.id for t in panel.tabs if t.edge == EDGE_TAB[edge]]
        if old:
            delete(pr.spec, pid, old)
    rows = int(op.get("rows") or 0)
    insets = [inset]
    where = ""
    if rows > 0 and mode == "slot":          # slot di tengah panel: 1 baris = tepat di tengah, 2+ = dibagi rata
        if rows > 12:
            raise ProjectError("jumlah baris slot maksimal 12")
        if op.get("mate", {}) and op["mate"].get("panel") and rows > 1:
            raise ProjectError("pasangan otomatis hanya untuk 1 baris; buat pasangan tiap rak secara terpisah")
        perp = (b[3] - b[1]) if horizontal else (b[2] - b[0])
        insets = [round(perp * (k + 1) / (rows + 1)) for k in range(rows)]
        if rows > 1 and len(set(insets)) < rows:
            raise ProjectError("baris slot terlalu rapat untuk panel sekecil ini")
        where = f"; {rows} baris slot, jarak pusat dari tepi: " + ", ".join(f"{measure.fmt(v)}" for v in insets) + f" mm (panel {measure.fmt(perp)} mm)"
        if abs(perp * 1 / (rows + 1) - round(perp * 1 / (rows + 1))) > 1e-9:
            where += " (dibulatkan ke bilangan bulat)"
    ids = [add_shape(pr.spec, pid, sh) for ins in insets
           for sh in _joint_shapes(mode, b, edge, plan["tab_spans"], start, depth, ins, clear)]
    res = {"ids": ids, "plan": plan, "mate_ids": [], "text": f"{plan['text']}{where}"}
    m = op.get("mate")
    if m and m.get("panel"):
        other = pr.panel(m["panel"])
        if other is None:
            raise ProjectError(f"panel pasangan tidak dikenal: {m['panel']}")
        if m["panel"] == pid:
            raise ProjectError("panel pasangan harus berbeda dari panel ini")
        pr.spec["panels"].setdefault(m["panel"], {})        # panel generator / gambar belum tentu punya catatan
        ob = other.outline.bounds
        e2 = m.get("edge") or edge
        if e2 not in EDGE_TAB:
            raise ProjectError(f"sisi pasangan harus salah satu dari {tuple(EDGE_TAB)}")
        h2 = e2 in ("bottom", "top")
        start2 = (ob[0] if h2 else ob[1]) + float(m.get("offset") or 0)
        spans = [[length - bb, length - a] for a, bb in reversed(plan["tab_spans"])] if m.get("mirror") else plan["tab_spans"]
        kind2 = "slot" if mode == "tab" else "tab"
        in2 = float(m["inset"]) if m.get("inset") not in (None, "") else depth / 2
        res["mate_ids"] = [add_shape(pr.spec, m["panel"], sh) for sh in
                           _joint_shapes(kind2, ob, e2, spans, start2, depth, in2, clear)]
        res["text"] += f"; pasangan di {m['panel']}: {len(res['mate_ids'])} {kind2}"
        if clear and kind2 == "slot":
            res["text"] += f" (celah {clear:+g} mm)"
    return res


def array(pr, pid, proto, nx, ny, px, py, start, stagger=False, margin=0.0, avoid=True):
    """Larik bentuk (grid atau selang-seling/heksagonal). `start` = pusat bentuk pertama.
    Bentuk yang keluar dari panel (dikurangi `margin`) atau menabrak potongan lain dilewati."""
    nx, ny = int(nx), int(ny)
    if nx < 1 or ny < 1 or nx * ny > 2000:
        raise ProjectError("jumlah larik harus 1..2000 bentuk")
    panel = pr.panel(pid)
    if panel is None:
        raise ProjectError(f"panel tidak dikenal: {pid}")
    inside = panel.outline.buffer(-margin) if margin >= 0 else panel.outline
    others = [f.poly.buffer(margin) for f in panel.cuts()] if avoid else []
    made, skipped = [], 0
    for j in range(ny):
        for i in range(nx):
            off = px / 2 if stagger and j % 2 else 0.0
            c = [start[0] + i * px + off, start[1] + j * py]
            s = clean_shape({**proto, "center": c})
            g = shape_poly(s)
            if not inside.contains(g) or any(g.intersects(o) for o in others):
                skipped += 1
                continue
            made.append(add_shape(pr.spec, pid, s))
    return made, skipped


# ----------------------------------------------------------------------------
def apply_ops(pr, ops):
    """Jalankan daftar operasi pada Project `pr` (lalu simpan). Hasil: daftar jawaban per operasi."""
    spec, res = pr.spec, []
    for op in ops:
        kind = op.get("op")
        pid = op.get("panel")
        for q in (pid, op.get("from"), op.get("to")):
            if q and q not in spec["panels"] and pr.panel(q) is not None:
                spec["panels"][q] = {}                # panel dari generator / gambar yang belum punya catatan
        if kind == "add":
            res.append({"id": add_shape(spec, pid, op["shape"])})
        elif kind == "move":
            dx, dy = float(op["dx"]), float(op["dy"])
            if op.get("anchor"):                       # pusat jangkar mendarat di titik kisi
                a = next((i for i in measure.panel_items(pr.panel(pid), pr.thickness) if i["id"] == op["anchor"]), None)
                if a is not None:
                    m = measure.measure_move(a["center"], [dx, dy], float(op.get("step", 0) or 0))
                    dx, dy = m["dx"], m["dy"]
            if op.get("magnet"):                       # tempel ke tepi / tengah bentuk lain (hitungan sama dengan pratinjau)
                g = measure.magnet_move(pr.panel(pid), op["ids"], dx, dy, float(op.get("tol") or 0))
                dx, dy = g["dx"], g["dy"]
            move(spec, pid, op["ids"], dx, dy)
            res.append({"dx": dx, "dy": dy})
        elif kind == "align":
            res.append(align(pr, pid, op["ids"], op.get("mode", "center")))
        elif kind == "scale":
            res.append(scale(pr, pid, op["ids"], op["percent"], op.get("about", "each"), float(op.get("step", 0) or 0)))
        elif kind == "divide":
            res.append(divide(pr, pid, op))
        elif kind == "place":                          # komponen pustaka -> beberapa bentuk dalam satu grup
            from . import components
            panel = pr.panel(pid)
            step = float(op.get("step", 0) or 0)
            at = measure.snap_pt(op["at"], step) if op.get("at") else \
                [round(panel.size[0] / 2 + panel.outline.bounds[0]), round(panel.size[1] / 2 + panel.outline.bounds[1])]
            shapes = components.build(op["component"], op.get("params") or {}, at, float(op.get("rotate", 0) or 0))
            ed = _ed(spec, pid)
            ed["gseq"] = int(ed.get("gseq", 0)) + 1
            gid = f"K{ed['gseq']}"
            ids = [add_shape(spec, pid, {**sh, "group": gid, "comp": op["component"]}) for sh in shapes]
            res.append({"ids": ids, "group": gid, "text": f"{components.LIB[op['component']]['label']} di {at}"})
        elif kind == "draw":                           # lingkaran / kotak dari seretan mentah
            m = measure.measure_drag(op["tool"], op["c0"], op["cur"], float(op.get("step", 0) or 0))
            if op.get("magnet"):
                m = measure.magnet_draw(pr.panel(pid), m, op["tool"], float(op.get("tol") or 0))
            shape = {k: m[k] for k in ("kind", "center", "r", "size", "angle") if k in m}
            res.append({"id": add_shape(spec, pid, shape), "text": m["text"]})
        elif kind == "set_fields":                     # ubah angka bentuk terpilih (x, y, d, lebar, tinggi, sudut)
            res.append({"id": set_fields(pr, pid, op["id"], op["values"], float(op.get("step", 0) or 0))})
        elif kind == "delete":
            delete(spec, pid, op["ids"])
            res.append({})
        elif kind == "restore":
            restore(spec, pid, op["ids"])
            res.append({})
        elif kind == "replace":
            res.append({"id": replace(spec, pid, op["id"], op["shape"])})
        elif kind == "role":
            set_role(spec, pid, op["id"], op["role"])
            res.append({})
        elif kind == "edges":
            vals, notes = {}, []
            for k in EDGE_NAMES:
                if k in op:
                    if op[k] is None:
                        vals[k] = None
                        continue
                    v = measure.measure_edge(k, op[k])["value"]            # batas selalu bilangan bulat
                    if abs(v - float(op[k])) > 1e-6:
                        notes.append(f"{measure.EDGE_LABEL[k]} dibulatkan ke {v}")
                    vals[k] = v
            if op.get("round"):                 # bulatkan semua batas yang masih berkoma
                b = pr.panel(pid).outline.bounds
                for k, v in zip(EDGE_NAMES, (b[0], b[2], b[1], b[3])):
                    if k not in vals and abs(v - round(v)) > 1e-6:
                        vals[k] = round(v)
            set_edges(spec, pid, vals)
            res.append({"edges": spec["panels"][pid].get("edges", {}), "notes": notes})
        elif kind == "place_move":                     # geser panel di rakitan 3D, dengan magnet ke permukaan panel lain
            res.append(snap_place(pr, pid, op.get("delta", (0, 0, 0)), float(op.get("tol", 8) or 8), float(op.get("step", 0) or 0), bool(op.get("magnet", True)), op.get("target")))
        elif kind == "auto_joint":
            res.append(auto_joint(pr, op["from"], op["to"], op.get("parts", 5), op.get("pattern", "alternate"), op.get("start", "tab"),
                                  op.get("tab"), op.get("margin", 0), op.get("clearance", 0)))
            pr.reload()
        elif kind == "auto_slots":
            res.append(auto_slots(pr, op.get("from"), op.get("clearance", 0)))
            pr.reload()
        elif kind == "duplicate":
            res.append(duplicate(pr, pid, op["ids"], op.get("to"), op.get("dx", 0), op.get("dy", 0), float(op.get("step", 0) or 0)))
            pr.reload()
        elif kind == "group":
            res.append(group(pr, pid, op["ids"]))
            pr.reload()
        elif kind == "ungroup":
            res.append(ungroup(pr, pid, op["ids"]))
            pr.reload()
        elif kind == "outline":
            res.append(outline(pr, pid, op))
        elif kind == "rotate":                         # putar panel di rakitan 3D (gizmo): sudut dibulatkan backend
            res.append(rotate_panel(pr, pid, op["axis"], op["angle"], op["center"], op.get("step", 0)))
        elif kind == "array":
            made, skipped = array(pr, pid, op["shape"], op["nx"], op["ny"], float(op["px"]), float(op["py"]),
                                  op["start"], bool(op.get("stagger")), float(op.get("margin", 0)),
                                  bool(op.get("avoid", True)))
            res.append({"ids": made, "skipped": skipped})
        elif kind == "new_panel":
            res.append({"id": new_panel(spec, op.get("name", ""), op.get("size"), op.get("polygon"))})
        elif kind == "remove_panel":
            remove_panel(spec, pid)
            res.append({})
        elif kind == "restore_panel":
            restore_panel(spec, pid)
            res.append({})
        elif kind == "resize_panel":
            resize_panel(spec, pid, op["size"])
            res.append({})
        else:
            raise ProjectError(f"operasi tidak dikenal: {kind}")
        if kind in ("array", "add", "new_panel", "edges", "remove_panel", "restore_panel", "place", "divide", "outline"):
            pr.reload()               # larik berikutnya perlu geometri terbaru
    return res
