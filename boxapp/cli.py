"""Perintah baris: python -m boxapp <perintah> ...  (atau box.bat <perintah> ...)"""
from __future__ import annotations

import argparse
import json
import os
import sys

from . import geom
from .project import Project, ProjectError, init


def _fl(xs):
    return "[" + ", ".join(f"{x:.2f}" for x in xs) + "]"


# ------------------------------------------------------------------------ info
def info_data(pr):
    t = pr.thickness
    out = []
    for p in pr.panels:
        feats = [f for f in p.features if f.role != "detail"]
        d = {"id": p.id, "name": p.name, "size": [round(v, 2) for v in p.size],
             "placed": pr.matrix(p.id) is not None,
             "bounds": [round(v, 3) for v in p.outline.bounds],
             "outline": [[round(x, 2), round(y, 2)] for x, y in p.outline.exterior.coords[:-1]],
             "tabs": [{"edge": g["edge"], "ids": g["ids"], "pos": [round(v, 2) for v in g["pos"]],
                       "length": round(g["length"], 2)} for g in geom.tab_groups(p)],
             "tab_depth": {tb.id: round(tb.depth, 2) for tb in p.tabs},
             "slots": [{"dir": g["dir"], "axis": g["axis"], "offset": round(g["offset"], 2),
                        "ids": g["ids"], "pos": [round(v, 2) for v in g["pos"]],
                        "size": [round(v, 2) for v in g["size"]]} for g in geom.slot_groups(p, t)],
             "holes": sum(f.kind == "circle" and f.role == "cut" for f in feats),
             "other": [{"id": f.id, "role": f.role, "kind": f.kind,
                        "bbox": [round(v, 2) for v in f.poly.bounds]}
                       for f in feats if not (f.kind == "circle" or geom.is_slot(f, t)) or f.role != "cut"]}
        out.append(d)
    return out


def cmd_info(a):
    pr = Project(a.project)
    data = info_data(pr)
    if a.json:
        print(json.dumps({"source": pr.spec.get("source"), "thickness": pr.thickness,
                          "kerf": pr.kerf, "panels": data}, indent=1, ensure_ascii=False))
        return 0
    print(f"Sumber : {pr.spec.get('source') or '(tanpa gambar; generator box)'}")
    print(f"Tebal  : {pr.thickness} mm   Kerf: {pr.kerf} mm   Panel: {len(data)}")
    print("Koordinat tiap panel: (0,0) = pojok kiri-bawah outline, y ke atas, satuan mm.\n")
    for d in data:
        nm = f" \"{d['name']}\"" if d["name"] else ""
        st = "ditempatkan" if d["placed"] else "BELUM ditempatkan"
        print(f"{d['id']}{nm}  {d['size'][0]:.2f} x {d['size'][1]:.2f} mm  [{st}]")
        bb = d["bounds"]
        print(f"   batas   : kiri x={bb[0]:g}  kanan x={bb[2]:g}  bawah y={bb[1]:g}  atas y={bb[3]:g}")
        if len(d["outline"]) != 4:
            print(f"   outline : {d['outline']}")
        for g in d["tabs"]:
            print(f"   tab  {g['edge']:<22} x{len(g['pos'])}  pos {_fl(g['pos'])}  ({g['ids'][0]}..{g['ids'][-1]})")
        for g in d["slots"]:
            print(f"   slot {g['dir']:<10} {g['axis']}={g['offset']:<7.2f} x{len(g['pos'])}  pos {_fl(g['pos'])}"
                  f"  {g['size'][0]:.2f}x{g['size'][1]:.2f}  ({g['ids'][0]}..{g['ids'][-1]})")
        if d["holes"]:
            print(f"   lubang bulat: {d['holes']}")
        for f in d["other"]:
            print(f"   {f['id']:<5} {f['role']:<6} {f['kind']:<5} bbox {f['bbox']}")
        print()
    return 0


# ----------------------------------------------------------------------- mates
def cmd_mates(a):
    pr = Project(a.project)
    t = pr.thickness
    tabs = [(p, g) for p in pr.panels for g in geom.tab_groups(p)]
    slots = [(p, g) for p in pr.panels for g in geom.slot_groups(p, t)]
    print("Kemungkinan pasangan tab -> slot (jumlah sama, jarak antar-tab sama):\n")
    for p, tg in tabs:
        dt = [b - a_ for a_, b in zip(tg["pos"], tg["pos"][1:])]
        cands = []
        for q, sg in slots:
            if q is p or len(sg["pos"]) != len(tg["pos"]):
                continue
            ds = [b - a_ for a_, b in zip(sg["pos"], sg["pos"][1:])]
            for rev, dd in ((False, ds), (True, ds[::-1])):
                err = max((abs(x - y) for x, y in zip(dt, dd)), default=0.0)
                if err <= a.tol:
                    shift = (sg["pos"][0] - tg["pos"][0]) if not rev else None
                    cands.append((err, q, sg, rev, shift))
                    break
        print(f"{pr.label(p.id)} tab {tg['edge']} x{len(tg['pos'])} pos {_fl(tg['pos'])}")
        if not cands:
            print("     (tidak ada slot yang cocok)")
        for err, q, sg, rev, shift in sorted(cands, key=lambda c: c[0])[:a.top]:
            extra = " (urutan terbalik)" if rev else f" geser {shift:+.2f}"
            print(f"     -> {pr.label(q.id)} slot {sg['dir']} {sg['axis']}={sg['offset']:.2f} "
                  f"pos {_fl(sg['pos'])}  selisih jarak {err:.2f}{extra}")
    return 0


# ----------------------------------------------------------------------- check
def print_report(pr, rep, detail=False):
    from .report import summarize, to_text
    print(to_text(summarize(pr, rep, detail)))


def cmd_check(a):
    from .assembly import Assembly
    pr = Project(a.project)
    if a.kerf is not None:
        pr.spec["kerf"] = a.kerf
    if a.tebal is not None:
        pr.spec["thickness"] = a.tebal
    rep = Assembly(pr).report()
    if a.json:
        print(json.dumps(rep, indent=1, ensure_ascii=False))
    else:
        print_report(pr, rep, a.detail)
    return 0 if rep["ok"] else 1


# ------------------------------------------------------------- render / export
def cmd_render(a):
    from .assembly import Assembly
    from .render import render
    pr = Project(a.project)
    asm = Assembly(pr)
    asm.collisions()
    out = render(asm, a.output, view=a.view, explode=a.explode, width=a.width,
                 show_collisions=not a.no_collisions)
    print(f"tersimpan: {out}")
    return 0


def cmd_export(a):
    from .export import export
    pr = Project(a.project)
    for f in export(pr, a.output, formats=a.format.split(","), sheet_width=a.sheet,
                    kerf_comp=a.kompensasi_kerf):
        print(f"tersimpan: {f}")
    return 0


def cmd_gui(a):
    from .server import serve
    serve(a.project, port=a.port, open_browser=not a.no_browser)
    return 0


def cmd_init(a):
    out = init(a.source, a.output, a.tebal)
    pr = Project(out)
    print(f"proyek dibuat: {out}  ({len(pr.panels)} panel)")
    print("lanjut: `info` untuk melihat panel, lalu isi `placement` tiap panel di file proyek.")
    return 0


# ---------------------------------------------------------------- penyuntingan
def _xy(text, what):
    try:
        v = [float(t) for t in text.replace(" ", "").split(",")]
        assert len(v) == 2
        return v
    except Exception:
        raise ProjectError(f"{what}: tulis dua angka 'x,y', misalnya 20,30")


def _ids(a):
    return [i for chunk in a.ids for i in chunk.replace(" ", "").split(",") if i]


def _commit(pr, ops):
    from . import edits
    res = edits.apply_ops(pr, ops)
    pr.save()
    return res


def cmd_add_circle(a):
    pr = Project(a.project)
    if (a.d is None) == (a.r is None):
        raise ProjectError("isi salah satu: --d (diameter) atau --r (jari-jari)")
    shape = {"kind": "circle", "center": _xy(a.at, "--at"), "r": a.r if a.r is not None else a.d / 2,
             "role": a.role}
    res = _commit(pr, [{"op": "add", "panel": a.panel, "shape": shape}])
    print(f"lingkaran {res[0]['id']} ditambahkan ke {a.panel} di {shape['center']}, d={shape['r'] * 2:g} mm")
    return 0


def cmd_add_rect(a):
    pr = Project(a.project)
    w, h = _xy(a.size, "--size")
    if (a.at is None) == (a.corner is None):
        raise ProjectError("isi salah satu: --at (pusat) atau --corner (pojok kiri-bawah)")
    c = _xy(a.at, "--at") if a.at else [v + s / 2 for v, s in zip(_xy(a.corner, "--corner"), (w, h))]
    shape = {"kind": "rect", "center": c, "size": [w, h], "angle": a.angle, "role": a.role}
    res = _commit(pr, [{"op": "add", "panel": a.panel, "shape": shape}])
    print(f"kotak {res[0]['id']} ditambahkan ke {a.panel}: pusat {c}, {w:g} x {h:g} mm, sudut {a.angle:g}")
    return 0


def cmd_add_poly(a):
    pr = Project(a.project)
    pts = [_xy(t, "titik") for t in a.points.split()]
    res = _commit(pr, [{"op": "add", "panel": a.panel, "shape": {"kind": "poly", "points": pts, "role": a.role}}])
    print(f"poligon {res[0]['id']} ({len(pts)} titik) ditambahkan ke {a.panel}")
    return 0


def cmd_array(a):
    pr = Project(a.project)
    if (a.circle is None) == (a.rect is None):
        raise ProjectError("isi salah satu: --circle D (diameter) atau --rect W,H")
    proto = {"kind": "circle", "r": a.circle / 2} if a.circle is not None else \
        {"kind": "rect", "size": _xy(a.rect, "--rect"), "angle": a.angle}
    proto["role"] = a.role
    nx, ny = _xy(a.count, "--count")
    px, py = _xy(a.pitch, "--pitch")
    res = _commit(pr, [{"op": "array", "panel": a.panel, "shape": proto, "nx": nx, "ny": ny, "px": px, "py": py,
                        "start": _xy(a.start, "--from"), "stagger": a.stagger, "margin": a.margin,
                        "avoid": not a.no_avoid}])[0]
    if res["ids"]:
        print(f"{len(res['ids'])} bentuk ditambahkan ke {a.panel} ({res['ids'][0]}..{res['ids'][-1]}); "
              f"{res['skipped']} dilewati karena keluar panel atau menabrak potongan lain")
    else:
        print(f"tidak ada bentuk yang muat ({res['skipped']} dilewati)")
    return 0


def cmd_move(a):
    pr = Project(a.project)
    dx, dy = _xy(a.by, "--by")
    _commit(pr, [{"op": "move", "panel": a.panel, "ids": _ids(a), "dx": dx, "dy": dy}])
    print(f"{', '.join(_ids(a))} di {a.panel} digeser ({dx:+g}, {dy:+g}) mm")
    return 0


def cmd_delete(a):
    pr = Project(a.project)
    _commit(pr, [{"op": "delete", "panel": a.panel, "ids": _ids(a)}])
    print(f"{', '.join(_ids(a))} dibuang dari {a.panel} (kembalikan dengan `restore`)")
    return 0


def cmd_restore(a):
    pr = Project(a.project)
    _commit(pr, [{"op": "restore", "panel": a.panel, "ids": _ids(a)}])
    print(f"{', '.join(_ids(a))} dikembalikan di {a.panel}")
    return 0


def cmd_new_panel(a):
    pr = Project(a.project)
    w, h = _xy(a.size, "--size")
    res = _commit(pr, [{"op": "new_panel", "name": a.name, "size": [w, h]}])
    print(f"panel {res[0]['id']} dibuat: {w:g} x {h:g} mm. Isi `placement`-nya agar ikut dirakit.")
    return 0


def _inner(text):
    try:
        v = [float(t) for t in text.replace(" ", "").lower().replace("x", ",").split(",")]
        assert len(v) == 3
        return [int(round(x)) for x in v]
    except Exception:
        raise ProjectError("--inner: tulis lebar,kedalaman,tinggi (mm), misalnya 120,90,60")


def cmd_new(a):
    from .project import new_project
    from . import generator
    inner = _inner(a.inner)
    out = new_project(a.output, inner, a.tebal, a.kerf, a.tab, not a.no_top)
    pr = Project(out)
    print(f"proyek dibuat: {out}")
    print(generator.describe(pr.spec))
    print("Panel sudah ditempatkan di rakitan. Lanjut: `check` untuk memeriksa, `gui` untuk mengedit, "
          "`export` untuk DXF/SVG.")
    return 0


def cmd_generator(a):
    from . import generator
    pr = Project(a.project)
    if a.remove:
        pr.spec.pop("generator", None)
        pr.save()
        print("generator dihapus dari proyek (panel hasil generator ikut hilang)")
        return 0
    g = pr.spec.get("generator") or generator.default_generator()
    if a.inner:
        g["inner"] = _inner(a.inner)
    if a.tab is not None:
        g["tab"] = a.tab
    if a.no_top or a.top:
        g["top"] = not a.no_top
    for kind in ("vertical", "side", "span"):
        c = getattr(a, f"count_{kind}")
        if c is not None:
            g.setdefault("joints", {}).setdefault(kind, {})["count"] = c
    pr.spec["generator"] = g
    if a.tebal:
        pr.spec["thickness"] = a.tebal
    pr.reload()
    pr.save()
    print(generator.describe(pr.spec))
    return 0


def cmd_components(a):
    from . import components
    for c in components.catalog():
        print(f"{c['name']:<14} {c['label']}")
        print(f"{'':<14} {c['note']}")
        for p in c["params"]:
            if p["type"] == "select":
                print(f"{'':<14}   --param {p['key']}=<{'|'.join(str(o[1]) for o in p['options'])}>  {p['label']}  (bawaan {p['default']:g})")
            else:
                print(f"{'':<14}   --param {p['key']}=<angka>  {p['label']}  (bawaan {p['default']:g})")
    return 0


def cmd_component(a):
    pr = Project(a.project)
    params = {}
    for kv in a.param or []:
        if "=" not in kv:
            raise ProjectError(f"--param: tulis kunci=nilai, mis. size=80 (dapat: {kv})")
        k, v = kv.split("=", 1)
        params[k.strip()] = v.strip()
    op = {"op": "place", "panel": a.panel, "component": a.name, "params": params, "rotate": a.rotate, "step": a.snap}
    if a.at:
        op["at"] = _xy(a.at, "--at")
    res = _commit(pr, [op])[0]
    print(f"{res['text']}: {len(res['ids'])} bentuk ({res['ids'][0]}..{res['ids'][-1]}), grup {res['group']}")
    return 0


def cmd_align(a):
    pr = Project(a.project)
    r = _commit(pr, [{"op": "align", "panel": a.panel, "ids": _ids(a), "mode": a.mode}])[0]
    print(r["text"])
    return 0


def cmd_scale(a):
    pr = Project(a.project)
    r = _commit(pr, [{"op": "scale", "panel": a.panel, "ids": _ids(a), "percent": a.percent, "about": a.about,
                      "step": a.snap}])[0]
    print(f"{r['text']}; id baru: {', '.join(r['ids'])}")
    return 0


def cmd_divide(a):
    pr = Project(a.project)
    op = {"op": "divide", "panel": a.panel, "edge": a.edge, "parts": a.parts, "pattern": a.pattern, "start": a.start,
          "margin": a.margin, "tab": a.tab, "mode": a.mode, "depth": a.depth, "inset": a.inset,
          "replace": not a.keep_existing, "clearance": a.clearance, "rows": a.rows}
    if a.mate_panel:
        op["mate"] = {"panel": a.mate_panel, "edge": a.mate_edge, "offset": a.mate_offset,
                      "inset": a.mate_inset, "mirror": a.mirror}
    r = _commit(pr, [op])[0]
    pl = r["plan"]
    print(r["text"])
    print(f"ringkasan: {pl['summary']}; panjang sisi {pl['length']:g} mm")
    for n in pl["notes"]:
        print(f"  [awas] {n}")
    return 0


def cmd_outline(a):
    pr = Project(a.project)
    op = {"op": "outline", "panel": a.panel, "step": a.snap}
    if a.reset:
        op["act"] = "reset"
    elif a.trapezoid:
        op.update(act="trapezoid", side=a.trapezoid[0], a=float(a.trapezoid[1]), b=float(a.trapezoid[2]))
    elif a.vertex:
        op.update(act="vertex", i=int(a.vertex[0]) - 1, to=[float(a.vertex[1]), float(a.vertex[2])])
    elif a.insert is not None:
        op.update(act="insert", i=a.insert - 1)
    elif a.remove is not None:
        op.update(act="remove", i=a.remove - 1)
    else:
        for i, p in enumerate(pr.panel(a.panel).outline.exterior.coords[:-1], 1):
            print(f"titik {i}: x {p[0]:g}  y {p[1]:g}")
        return 0
    print(_commit(pr, [op])[0]["text"])
    return 0


def cmd_group(a):
    pr = Project(a.project)
    ids = [i.strip() for i in a.ids.split(",") if i.strip()]
    r = _commit(pr, [{"op": "ungroup" if a.ungroup else "group", "panel": a.panel, "ids": ids}])[0]
    print(r["text"])
    return 0


def cmd_duplicate(a):
    pr = Project(a.project)
    ids = [i.strip() for i in a.ids.split(",") if i.strip()]
    r = _commit(pr, [{"op": "duplicate", "panel": a.panel, "to": a.to, "ids": ids, "dx": a.dx, "dy": a.dy, "step": a.snap}])[0]
    print(r["text"] + "; id baru: " + ", ".join(r["ids"]))
    for n in r["notes"]:
        print("  [awas] " + n)
    return 0


def cmd_autoslots(a):
    pr = Project(a.project)
    r = _commit(pr, [{"op": "auto_slots", "from": a.dari, "clearance": a.clearance}])[0]
    print(r["text"])
    for n in r["notes"]:
        print("  [awas] " + n)
    return 0


def cmd_autojoint(a):
    pr = Project(a.project)
    r = _commit(pr, [{"op": "auto_joint", "from": a.dari, "to": a.ke, "parts": a.parts, "pattern": a.pattern, "start": a.start,
                      "tab": a.tab, "margin": a.margin, "clearance": a.clearance}])[0]
    print(r["text"])
    for n in r["notes"]:
        print("  [awas] " + n)
    return 0


def cmd_snap(a):
    pr = Project(a.project)
    d = [float(v) for v in a.delta.split(",")] if a.delta else [0, 0, 0]
    r = _commit(pr, [{"op": "place_move", "panel": a.panel, "delta": d, "tol": a.tol, "step": a.snap, "magnet": not a.no_magnet, "target": a.ke}])[0]
    print(r["text"])
    return 0


def cmd_remove_panel(a):
    pr = Project(a.project)
    _commit(pr, [{"op": "restore_panel" if a.restore else "remove_panel", "panel": a.panel}])
    print(f"{a.panel} " + ("dipulihkan" if a.restore else "dihapus (pulihkan dengan --restore)"))
    return 0


def cmd_measure(a):
    from . import measure
    pr = Project(a.project)
    panels = [pr.panel(a.panel)] if a.panel else pr.panels
    if None in panels:
        raise ProjectError(f"panel tidak dikenal: {a.panel}")
    if a.json:
        print(json.dumps({p.id: {**measure.panel_measure(p), "items": measure.panel_items(p, pr.thickness)}
                          for p in panels}, indent=1, ensure_ascii=False))
        return 0
    print("Aturan: ukuran dan posisi bilangan bulat (mm), kecuali sisi/bentuk miring.\n")
    for p in panels:
        print(measure.describe(p, pr.thickness) + "\n")
    bad = [p.id for p in panels if not measure.panel_measure(p)["all_int"]]
    if bad:
        print(f"Batas berkoma di: {', '.join(bad)}  ->  box edge {a.project} <panel> --round")
    return 0


def cmd_edge(a):
    pr = Project(a.project)
    op = {"op": "edges", "panel": a.panel, "round": a.round}
    for k in ("left", "right", "bottom", "top"):
        v = getattr(a, k)
        if v is not None:
            op[k] = v
    if len(op) == 3 and not a.round:
        raise ProjectError("isi minimal satu: --left --right --bottom --top, atau --round")
    res = _commit(pr, [op])[0]
    b = pr.panel(a.panel).outline.bounds
    print(f"{a.panel}: kiri x={b[0]:g}  kanan x={b[2]:g}  bawah y={b[1]:g}  atas y={b[3]:g}  "
          f"(ukuran {b[2] - b[0]:g} x {b[3] - b[1]:g} mm); disimpan: {res['edges']}")
    return 0


def cmd_edit(a):
    pr = Project(a.project)
    text = sys.stdin.read() if a.ops == "-" else a.ops
    if os.path.exists(text):
        text = open(text, encoding="utf-8").read()
    res = _commit(pr, json.loads(text))
    print(json.dumps(res, ensure_ascii=False))
    return 0


def cmd_trace(a):
    from . import trace as tr
    pr = Project(a.project)
    data = open(a.image, "rb").read()
    d = {"mode": a.mode, "contrast": a.kontras, "brightness": a.terang, "clahe": a.clahe, "blur": a.blur,
         "threshold": a.ambang, "invert": a.objek_terang, "block": a.block, "c": a.c,
         "close": a.tutup, "holes": not a.tanpa_lubang, "drop_border": a.buang_tepi,
         "min_area_mm2": a.min_area, "simplify_mm": a.sederhana, "width_mm": a.lebar or 0.0,
         "height_mm": a.tinggi or 0.0, "ppmm": a.ppmm or 0.0}
    if a.canny:
        d["canny_lo"], d["canny_hi"] = (int(v) for v in _xy(a.canny, "--canny"))
    res = tr.trace(data, d)
    print(f"{len(res['shapes'])} bentuk, kotak pembatas {res['size_mm'][0]:g} x {res['size_mm'][1]:g} mm, "
          f"skala {res['ppmm']:g} px/mm, {res['vertices']} titik")
    for i, s in enumerate(res["shapes"][:8], 1):
        print(f"  {i}. {s['size_mm'][0]:g} x {s['size_mm'][1]:g} mm, luas {s['area_mm2']:g} mm2, "
              f"lubang {len(s['holes'])}")
    if len(res["shapes"]) > 8:
        print(f"  ... {len(res['shapes']) - 8} bentuk lain")
    for w in res["warnings"]:
        print(f"  [awas] {w}")
    if a.preview:
        with open(a.preview, "wb") as f:
            f.write(tr.overlay(data, res))
        print(f"pratinjau: {a.preview}  (kontur merah di atas gambar)")
    if a.panel or a.new_panel:
        out = tr.apply_trace(pr, res, "new_panel" if a.new_panel else "cut", a.panel,
                             _xy(a.at, "--at") if a.at else None, a.anchor, a.role, a.largest, a.name)
        pr.save()
        print(f"diterapkan: {json.dumps(out, ensure_ascii=False)}")
    else:
        print("(belum diterapkan: tambahkan --panel P4 atau --new-panel)")
    return 0


# ------------------------------------------------------------ lihat / kendalikan GUI
def _size(text):
    try:
        w, h = text.lower().split("x")
        return int(w), int(h)
    except Exception:
        raise ProjectError("--size: tulis seperti 1500x900")


def cmd_shot(a):
    from .drive import drive
    steps = [{"do": "tab", "to": a.tab}]
    if a.panel:
        steps.append({"do": "select", "panel": a.panel})
    if a.explode and a.tab == "3d":
        steps.append({"do": "eval", "js": f"(()=>{{const e=document.getElementById('explode'); e.value={a.explode}; e.dispatchEvent(new Event('input'));}})()"})
        steps.append({"do": "wait", "ms": 400})
    steps.append({"do": "shot", "path": os.path.abspath(a.output)})
    return 0 if drive(a.project, steps, size=_size(a.size), apply=False) else 1


def cmd_drive(a):
    from .drive import drive
    text = sys.stdin.read() if a.script == "-" else a.script
    if os.path.exists(text):
        text = open(text, encoding="utf-8").read()
    try:
        steps = json.loads(text)
    except json.JSONDecodeError as e:
        raise ProjectError(f"skrip bukan JSON yang valid: {e}")
    return 0 if drive(a.project, steps, a.outdir, _size(a.size), a.apply) else 1


def main(argv=None):
    for s in (sys.stdout, sys.stderr):
        if hasattr(s, "reconfigure"):
            s.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="box", description="Rakit dan periksa box akrilik dari gambar 2D.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="buat file proyek dari gambar AI/PDF")
    p.add_argument("source")
    p.add_argument("-o", "--output")
    p.add_argument("--tebal", type=float, default=5.0, help="tebal material, mm")
    p.set_defaults(fn=cmd_init)

    p = sub.add_parser("info", help="daftar panel, tab, dan slot")
    p.add_argument("project")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_info)

    p = sub.add_parser("mates", help="saran pasangan tab -> slot")
    p.add_argument("project")
    p.add_argument("--tol", type=float, default=0.3, help="toleransi beda jarak, mm")
    p.add_argument("--top", type=int, default=4)
    p.set_defaults(fn=cmd_mates)

    p = sub.add_parser("check", help="rakit 3D dan periksa sambungan, tabrakan, ukuran nyata")
    p.add_argument("project")
    p.add_argument("--json", action="store_true")
    p.add_argument("--kerf", type=float, help="timpa kerf, mm")
    p.add_argument("--tebal", type=float, help="timpa tebal material, mm")
    p.add_argument("--detail", action="store_true", help="tampilkan tiap tab satu per satu")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("render", help="gambar PNG rakitan 3D")
    p.add_argument("project")
    p.add_argument("-o", "--output", default="rakitan.png")
    p.add_argument("--view", default="iso", help="iso | iso2 | depan | belakang | kiri | kanan | atas")
    p.add_argument("--explode", type=float, default=0.0, help="0 = rapat, 1 = terurai")
    p.add_argument("--width", type=int, default=1400)
    p.add_argument("--no-collisions", action="store_true", help="jangan tandai tabrakan")
    p.set_defaults(fn=cmd_render)

    p = sub.add_parser("export", help="ekspor panel siap potong (DXF / SVG)")
    p.add_argument("project")
    p.add_argument("-o", "--output", default="hasil")
    p.add_argument("--format", default="dxf,svg")
    p.add_argument("--sheet", type=float, default=600.0, help="lebar lembar untuk tata letak, mm")
    p.add_argument("--kompensasi-kerf", action="store_true",
                   help="geser garis potong setengah kerf agar ukuran jadi = ukuran gambar")
    p.set_defaults(fn=cmd_export)

    p = sub.add_parser("gui", help="buka tampilan GUI di browser")
    p.add_argument("project")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true")
    p.set_defaults(fn=cmd_gui)

    def target(p, ids=False):
        p.add_argument("project")
        p.add_argument("panel", help="id panel, misalnya P4 atau N1")
        if ids:
            p.add_argument("ids", nargs="+", help="id fitur/tab, misalnya F12 T3 A1 (boleh dipisah koma)")

    ROLE = dict(default="cut", choices=["cut", "guide", "ignore"])

    p = sub.add_parser("add-circle", help="tambah lubang bulat ke panel (koordinat panel, mm)")
    target(p)
    p.add_argument("--at", required=True, help="pusat: x,y")
    p.add_argument("--d", type=float, help="diameter, mm")
    p.add_argument("--r", type=float, help="jari-jari, mm")
    p.add_argument("--role", **ROLE)
    p.set_defaults(fn=cmd_add_circle)

    p = sub.add_parser("add-rect", help="tambah potongan kotak ke panel")
    target(p)
    p.add_argument("--at", help="pusat: x,y")
    p.add_argument("--corner", help="pojok kiri-bawah: x,y")
    p.add_argument("--size", required=True, help="lebar,tinggi (mm)")
    p.add_argument("--angle", type=float, default=0.0, help="putar, derajat")
    p.add_argument("--role", **ROLE)
    p.set_defaults(fn=cmd_add_rect)

    p = sub.add_parser("add-poly", help="tambah potongan poligon ke panel")
    target(p)
    p.add_argument("--points", required=True, help='"x,y x,y x,y ..."')
    p.add_argument("--role", **ROLE)
    p.set_defaults(fn=cmd_add_poly)

    p = sub.add_parser("array", help="larik lubang/kotak (grid atau selang-seling untuk ventilasi)")
    target(p)
    p.add_argument("--circle", type=float, help="diameter lubang, mm")
    p.add_argument("--rect", help="ukuran kotak: lebar,tinggi")
    p.add_argument("--angle", type=float, default=0.0)
    p.add_argument("--from", dest="start", required=True, help="pusat bentuk pertama: x,y")
    p.add_argument("--count", required=True, help="jumlah: kolom,baris")
    p.add_argument("--pitch", required=True, help="jarak pusat ke pusat: x,y (mm)")
    p.add_argument("--stagger", action="store_true", help="baris genap digeser setengah jarak (heksagonal)")
    p.add_argument("--margin", type=float, default=2.0, help="jarak minimum ke tepi panel / potongan lain, mm")
    p.add_argument("--no-avoid", action="store_true", help="jangan hindari potongan yang sudah ada")
    p.add_argument("--role", **ROLE)
    p.set_defaults(fn=cmd_array)

    p = sub.add_parser("move", help="geser fitur/tab di panel")
    target(p, ids=True)
    p.add_argument("--by", required=True, help="dx,dy (mm)")
    p.set_defaults(fn=cmd_move)

    p = sub.add_parser("delete", help="buang fitur/tab dari panel")
    target(p, ids=True)
    p.set_defaults(fn=cmd_delete)

    p = sub.add_parser("restore", help="kembalikan fitur/tab yang dibuang atau digeser")
    target(p, ids=True)
    p.set_defaults(fn=cmd_restore)

    p = sub.add_parser("new-panel", help="buat panel baru berbentuk kotak")
    p.add_argument("project")
    p.add_argument("--size", required=True, help="lebar,tinggi (mm)")
    p.add_argument("--name", default="")
    p.set_defaults(fn=cmd_new_panel)

    p = sub.add_parser("new", help="proyek BARU tanpa gambar: generator box dengan tab-slot berpasangan")
    p.add_argument("output", help="nama file proyek, mis. kotak.box.json")
    p.add_argument("--inner", required=True, help="ukuran DALAM: lebar,kedalaman,tinggi (mm, bulat)")
    p.add_argument("--tebal", type=float, default=5.0)
    p.add_argument("--kerf", type=float, default=0.0)
    p.add_argument("--tab", type=int, default=20, help="panjang tab yang diinginkan (mm)")
    p.add_argument("--no-top", action="store_true", help="tanpa tutup atas")
    p.set_defaults(fn=cmd_new)

    p = sub.add_parser("generator", help="ubah / tambahkan generator box pada proyek")
    p.add_argument("project")
    p.add_argument("--inner")
    p.add_argument("--tebal", type=float)
    p.add_argument("--tab", type=int)
    p.add_argument("--top", action="store_true")
    p.add_argument("--no-top", action="store_true")
    p.add_argument("--count-vertical", type=int, help="jumlah tab sambungan tegak (depan/belakang <-> kiri/kanan)")
    p.add_argument("--count-side", type=int, help="jumlah tab alas/atas <-> kiri/kanan")
    p.add_argument("--count-span", type=int, help="jumlah tab alas/atas <-> depan/belakang")
    p.add_argument("--remove", action="store_true")
    p.set_defaults(fn=cmd_generator)

    p = sub.add_parser("components", help="daftar komponen pustaka dan parameternya")
    p.set_defaults(fn=cmd_components)

    p = sub.add_parser("component", help="tempatkan komponen pustaka di panel (lubang baut, kipas, tombol, layar, ventilasi)")
    p.add_argument("project")
    p.add_argument("panel")
    p.add_argument("name", help="nama komponen (lihat `components`)")
    p.add_argument("--at", help="titik pusat x,y (bawaan: tengah panel)")
    p.add_argument("--param", action="append", help="kunci=nilai, boleh berulang")
    p.add_argument("--rotate", type=float, default=0.0)
    p.add_argument("--snap", type=float, default=1.0, help="kisi untuk --at (mm); 0 = bebas")
    p.set_defaults(fn=cmd_component)

    p = sub.add_parser("align", help="tengahkan / ratakan bentuk terhadap panel")
    target(p, ids=True)
    p.add_argument("--mode", default="center", choices=["center", "center-x", "center-y", "left", "right", "top", "bottom"])
    p.set_defaults(fn=cmd_align)

    p = sub.add_parser("scale", help="perbesar / perkecil bentuk (persen; 100 = tetap)")
    target(p, ids=True)
    p.add_argument("--percent", type=float, required=True)
    p.add_argument("--about", default="each", choices=["each", "selection"], help="terhadap pusat tiap bentuk atau pusat gabungan")
    p.add_argument("--snap", type=float, default=1.0, help="bulatkan ukuran ke kelipatan ini (mm); 0 = bebas")
    p.set_defaults(fn=cmd_scale)

    p = sub.add_parser("snap", help="tempelkan panel ke permukaan panel lain terdekat di rakitan 3D (magnet), opsional geser dulu")
    p.add_argument("project")
    p.add_argument("panel")
    p.add_argument("--delta", help="geser dulu x,y,z (mm, koordinat dunia)")
    p.add_argument("--tol", type=float, default=30.0, help="jarak maksimal ke permukaan yang ditempeli (mm)")
    p.add_argument("--snap", type=float, default=0.0)
    p.add_argument("--no-magnet", action="store_true")
    p.add_argument("--ke", help="hanya tempel ke panel ini (bawaan: permukaan terdekat)")
    p.set_defaults(fn=cmd_snap)

    p = sub.add_parser("auto-joint", help="sambungan otomatis: tab di sisi panel DARI yang menempel ke panel KE, slot di KE dibuat dari 3D")
    p.add_argument("project")
    p.add_argument("dari", help="panel yang diberi tab")
    p.add_argument("ke", help="panel yang diberi slot")
    p.add_argument("--parts", type=int, default=5)
    p.add_argument("--pattern", default="alternate", choices=["alternate", "centered"])
    p.add_argument("--start", default="tab", choices=["tab", "gap"])
    p.add_argument("--tab", type=float)
    p.add_argument("--margin", type=float, default=0.0)
    p.add_argument("--clearance", type=float, default=0.0)
    p.set_defaults(fn=cmd_autojoint)

    p = sub.add_parser("auto-slots", help="buat slot di panel lawan untuk semua tab yang menabrak bagian pejal (belum ada slotnya)")
    p.add_argument("project")
    p.add_argument("--dari", help="hanya tab milik panel ini (bawaan: semua panel)")
    p.add_argument("--clearance", type=float, default=0.0, help="celah slot (mm): + longgar, - pas ketat")
    p.set_defaults(fn=cmd_autoslots)

    p = sub.add_parser("duplicate", help="salin bentuk / grup (di panel yang sama atau ke panel lain)")
    p.add_argument("project")
    p.add_argument("panel", help="panel asal")
    p.add_argument("ids", help="id bentuk dipisah koma, mis. A1,A2 (grup ikut utuh jadi grup baru)")
    p.add_argument("--to", help="panel tujuan (bawaan: panel yang sama)")
    p.add_argument("--dx", type=float, default=0.0)
    p.add_argument("--dy", type=float, default=0.0)
    p.add_argument("--snap", type=float, default=1.0)
    p.set_defaults(fn=cmd_duplicate)

    p = sub.add_parser("group", help="gabungkan bentuk jadi satu grup (bergerak/terhapus bersama), atau lepas dengan --ungroup")
    p.add_argument("project")
    p.add_argument("panel")
    p.add_argument("ids", help="id bentuk dipisah koma, mis. A1,A2,A3")
    p.add_argument("--ungroup", action="store_true")
    p.set_defaults(fn=cmd_group)

    p = sub.add_parser("outline", help="ubah bentuk outline panel (trapesium, geser titik); tanpa opsi = daftar titik")
    p.add_argument("project")
    p.add_argument("panel")
    p.add_argument("--trapezoid", nargs=3, metavar=("SISI", "A", "B"),
                   help="pendekkan sisi (top/bottom/left/right) dari ujung 1 sebesar A mm dan ujung 2 sebesar B mm")
    p.add_argument("--vertex", nargs=3, metavar=("NOMOR", "X", "Y"), help="pindahkan titik nomor N (mulai 1) ke x, y")
    p.add_argument("--insert", type=int, metavar="SISI", help="sisipkan titik di tengah sisi nomor N (sisi N = titik N ke N+1)")
    p.add_argument("--remove", type=int, metavar="NOMOR", help="hapus titik nomor N")
    p.add_argument("--reset", action="store_true", help="kembalikan outline ke bawaan")
    p.add_argument("--snap", type=float, default=1.0, help="bulatkan ke kelipatan ini (mm); 0 = bebas")
    p.set_defaults(fn=cmd_outline)

    p = sub.add_parser("divide", help="bagi sisi panel jadi N bagian sama, tab/slot selang-seling (+ pasangannya di panel lain)")
    p.add_argument("project")
    p.add_argument("panel")
    p.add_argument("--edge", required=True, choices=["left", "right", "bottom", "top"])
    p.add_argument("--parts", type=int, default=3, help="jumlah bagian (selang-seling) atau jumlah tab (centered)")
    p.add_argument("--pattern", default="alternate", choices=["alternate", "centered"])
    p.add_argument("--start", default="tab", choices=["tab", "gap"], help="bagian pertama berupa tab atau jarak")
    p.add_argument("--margin", type=float, default=0.0, help="jarak dari kedua ujung sisi (mm)")
    p.add_argument("--tab", type=float, help="panjang tab (pola centered)")
    p.add_argument("--mode", default="tab", choices=["tab", "slot"], help="tab keluar dari tepi, atau slot di dalam panel")
    p.add_argument("--depth", type=float, help="tonjolan / lebar slot; bawaan = tebal material")
    p.add_argument("--inset", type=float, help="mode slot: jarak pusat slot dari tepi; bawaan = depth/2")
    p.add_argument("--rows", type=int, default=0, help="mode slot: baris slot di tengah panel (1 = tepat di tengah, 2+ = dibagi rata, 0 = dekat tepi)")
    p.add_argument("--clearance", type=float, default=0.0, help="celah slot (mm): + longgar, - pas ketat; ditambahkan ke lebar dan panjang slot")
    p.add_argument("--keep-existing", action="store_true", help="jangan hapus tab lama di sisi ini")
    p.add_argument("--mate-panel", help="buat pasangannya (slot untuk tab, tab untuk slot) di panel ini")
    p.add_argument("--mate-edge", choices=["left", "right", "bottom", "top"], help="sisi acuan di panel pasangan (bawaan sama)")
    p.add_argument("--mate-offset", type=float, default=0.0, help="posisi awal sisi ini sepanjang panel pasangan (mm)")
    p.add_argument("--mate-inset", type=float, help="jarak pusat garis slot dari tepi pasangan; bawaan = depth/2")
    p.add_argument("--mirror", action="store_true", help="balik urutan di panel pasangan (panel yang berhadapan)")
    p.set_defaults(fn=cmd_divide)

    p = sub.add_parser("remove-panel", help="hapus panel (dari gambar / generator / baru)")
    p.add_argument("project")
    p.add_argument("panel")
    p.add_argument("--restore", action="store_true", help="pulihkan panel yang dihapus")
    p.set_defaults(fn=cmd_remove_panel)

    p = sub.add_parser("measure", help="laporan ukuran panel: batas, sisi (termasuk miring), bentuk berkoma")
    p.add_argument("project")
    p.add_argument("panel", nargs="?")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_measure)

    p = sub.add_parser("edge", help="atur batas panel (kiri/kanan/bawah/atas) ke posisi mutlak, mm")
    p.add_argument("project")
    p.add_argument("panel")
    p.add_argument("--left", type=float, help="x batas kiri")
    p.add_argument("--right", type=float, help="x batas kanan")
    p.add_argument("--bottom", type=float, help="y batas bawah")
    p.add_argument("--top", type=float, help="y batas atas")
    p.add_argument("--round", action="store_true", help="bulatkan semua batas yang berkoma ke bilangan bulat")
    p.set_defaults(fn=cmd_edge)

    p = sub.add_parser("edit", help="jalankan daftar operasi JSON (dari argumen, file, atau '-' = stdin)")
    p.add_argument("project")
    p.add_argument("ops")
    p.set_defaults(fn=cmd_edit)

    p = sub.add_parser("trace", help="gambar PNG/JPG -> bentuk vektor berukuran nyata")
    p.add_argument("project")
    p.add_argument("image")
    g = p.add_argument_group("skala (isi salah satu)")
    g.add_argument("--lebar", type=float, help="lebar nyata seluruh bentuk, mm")
    g.add_argument("--tinggi", type=float, help="tinggi nyata seluruh bentuk, mm")
    g.add_argument("--ppmm", type=float, help="piksel per mm")
    g = p.add_argument_group("pengolahan gambar")
    g.add_argument("--mode", default="ambang", choices=["ambang", "adaptif", "tepi"])
    g.add_argument("--kontras", type=float, default=1.0, help="pengali kontras, mis. 2.5")
    g.add_argument("--terang", type=float, default=0.0, help="geser kecerahan -255..255")
    g.add_argument("--clahe", action="store_true", help="pemerataan kontras lokal")
    g.add_argument("--blur", type=int, default=1, help="blur Gaussian (piksel, ganjil); 5 untuk foto berbintik")
    g.add_argument("--ambang", type=int, default=-1, help="0..255; bawaan otomatis (Otsu)")
    g.add_argument("--objek-terang", action="store_true", help="objek lebih terang dari latar")
    g.add_argument("--block", type=int, default=31, help="mode adaptif: ukuran jendela")
    g.add_argument("--c", type=float, default=8.0, help="mode adaptif: penurun ambang")
    g.add_argument("--canny", help="mode tepi: lo,hi (bawaan 50,150)")
    g.add_argument("--tutup", type=int, default=3, help="tutup celah kecil (piksel)")
    g.add_argument("--tanpa-lubang", action="store_true", help="abaikan lubang di dalam bentuk")
    g.add_argument("--buang-tepi", action="store_true", help="buang bentuk yang menyentuh tepi gambar")
    g.add_argument("--min-area", type=float, default=4.0, help="buang bintik lebih kecil dari ini, mm2")
    g.add_argument("--sederhana", type=float, default=0.2, help="toleransi penyederhanaan garis, mm")
    g = p.add_argument_group("hasil")
    g.add_argument("--preview", help="simpan PNG pratinjau kontur")
    g.add_argument("--panel", help="tempel sebagai potongan pada panel ini")
    g.add_argument("--new-panel", action="store_true", help="jadikan bentuk terbesar sebagai panel baru")
    g.add_argument("--at", help="titik penempatan di panel: x,y (bawaan tengah panel)")
    g.add_argument("--anchor", default="center", choices=["center", "ll"], help="titik --at = pusat | pojok kiri-bawah")
    g.add_argument("--role", **ROLE)
    g.add_argument("--largest", action="store_true", help="hanya bentuk terbesar")
    g.add_argument("--name", default="", help="nama panel baru")
    p.set_defaults(fn=cmd_trace)

    p = sub.add_parser("shot", help="tangkapan layar GUI (browser tanpa kepala; butuh Playwright)")
    p.add_argument("project")
    p.add_argument("-o", "--output", default="layar.png")
    p.add_argument("--tab", default="3d", choices=["3d", "2d"])
    p.add_argument("--panel", help="panel yang dipilih / dibuka di tab 2D")
    p.add_argument("--explode", type=float, default=0.0, help="tab 3d: 0..1.2")
    p.add_argument("--size", default="1500x900")
    p.set_defaults(fn=cmd_shot)

    p = sub.add_parser("drive", help="kendalikan GUI dengan skrip langkah JSON (klik, seret, ketik, tangkapan layar)")
    p.add_argument("project")
    p.add_argument("script", help="JSON langkah, nama file, atau '-' (stdin); lihat boxapp/drive.py")
    p.add_argument("--outdir", default=".", help="folder untuk tangkapan layar")
    p.add_argument("--size", default="1500x900")
    p.add_argument("--apply", action="store_true", help="simpan perubahan ke proyek asli (bawaan: salinan sementara)")
    p.set_defaults(fn=cmd_drive)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except ProjectError as e:
        print(f"kesalahan proyek: {e}", file=sys.stderr)
        return 2
