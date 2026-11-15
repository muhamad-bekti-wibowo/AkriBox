"""Pengukuran dan aturan angka, satu-satunya sumber untuk GUI, CLI, dan LLM.

Aturan: semua ukuran dan posisi berupa bilangan bulat (mm), kecuali sisi / bentuk miring
(sudut bukan kelipatan 90 derajat), yang boleh berkoma. Frontend tidak menghitung apa pun;
ia mengirim koordinat mentah ke sini dan menampilkan hasilnya.
"""
from __future__ import annotations

import math

SLANT_TOL = 0.5          # derajat: dianggap lurus bila selisih ke kelipatan 90 lebih kecil dari ini
DEFAULT_CIRCLE_D = 8.0   # klik tanpa seret
DEFAULT_RECT = (20.0, 6.0)


def fmt(v):
    """180 -> '180', 155.049 -> '155.05'"""
    r = round(float(v) + 0.0, 2)
    return f"{r:g}"


INT_TOL = 0.005          # mm: selisih ke bilangan bulat di bawah ini dianggap bulat (sisa angka dari gambar)


def is_int(v):
    return abs(v - round(v)) < INT_TOL


def snap(v, step):
    """Bulatkan ke kelipatan `step` (0 = bebas, hanya dirapikan 3 desimal)."""
    v = float(v)
    return round(round(v / step) * step, 3) if step and step > 0 else round(v, 3)


def snap_pt(p, step):
    return [snap(p[0], step), snap(p[1], step)]


def is_slanted(angle):
    a = angle % 90
    return min(a, 90 - a) > SLANT_TOL


# ---------------------------------------------------------------- pengukuran interaktif
def measure_point(p, step=0):
    return {"p": list(p), "text": f"x {fmt(p[0])}   y {fmt(p[1])} mm"}


def measure_drag(tool, c0, cur, step=0):
    """Lingkaran / kotak dari seretan. Hasil dipakai persis sama untuk pratinjau dan untuk membuat bentuk."""
    a, b = snap_pt(c0, step), snap_pt(cur, step)
    if tool == "circle":
        d = snap(math.hypot(b[0] - a[0], b[1] - a[1]) * 2, step)
        if d < 0.8:                                   # klik saja
            d = DEFAULT_CIRCLE_D
        return {"kind": "circle", "center": a, "r": round(d / 2, 3), "d": d, "text": f"Ø {fmt(d)} mm"}
    w, h = abs(b[0] - a[0]), abs(b[1] - a[1])
    if w < 0.4 and h < 0.4:                           # klik saja
        w, h = DEFAULT_RECT
        c = a
    else:
        w, h = max(w, 0.5), max(h, 0.5)
        c = [round((a[0] + b[0]) / 2, 3), round((a[1] + b[1]) / 2, 3)]
    return {"kind": "rect", "center": c, "size": [w, h], "angle": 0, "text": f"{fmt(w)} × {fmt(h)} mm"}


def measure_move(anchor, delta, step=0):
    """Pusat jangkar pindah ke titik kisi terdekat; semua yang dipilih bergeser sama besar."""
    nc = snap_pt([anchor[0] + delta[0], anchor[1] + delta[1]], step)
    dx, dy = round(nc[0] - anchor[0], 3), round(nc[1] - anchor[1], 3)
    return {"dx": dx, "dy": dy, "text": f"geser {dx:+g}, {dy:+g} mm"}


def measure_edge(edge, value):
    """Batas panel selalu bilangan bulat."""
    v = int(round(float(value)))
    return {"value": v, "text": f"{EDGE_LABEL[edge]} = {v} mm"}


EDGE_LABEL = {"left": "kiri x", "right": "kanan x", "bottom": "bawah y", "top": "atas y"}


def measure_box(inner, thickness, tab=20, joints=None):
    """Ukuran luar dan ringkasan sambungan untuk generator box (dipakai dialog sebagai pratinjau)."""
    from . import generator
    vals = [int(round(float(v))) for v in inner]
    t = float(thickness)
    outer = [v + 2 * t for v in vals]
    notes = [f"ukuran dalam dibulatkan ke {vals}"] if any(abs(float(a) - b) > 1e-6 for a, b in zip(inner, vals)) else []
    out = {"inner": vals, "outer": outer, "notes": notes,
           "text": f"luar {fmt(outer[0])} × {fmt(outer[1])} × {fmt(outer[2])} mm", "joints": []}
    if min(vals) < 10:
        out["error"] = "ukuran dalam minimal 10 mm di tiap sumbu"
        return out
    g = {"tab": tab, "joints": joints or {}}
    for kind, L, label in (("vertical", vals[2], "tegak depan/belakang ↔ kiri/kanan"),
                           ("side", vals[1], "alas/atas ↔ kiri/kanan"), ("span", vals[0], "alas/atas ↔ depan/belakang")):
        try:
            cs, ln = generator._joint(g, kind, L)
            out["joints"].append({"kind": kind, "text": f"{label}: {len(cs)} tab × {ln} mm"})
        except Exception as e:
            out["error"] = str(e)
    return out


def divide_plan(length, parts=3, pattern="alternate", start="tab", tab=None, margin=0):
    """Bagi sebuah sisi sepanjang `length` menjadi `parts` bagian, lalu tentukan di mana tab berada.

    alternate : `parts` bagian sama panjang; tab pada bagian 1, 3, 5, ... (start='tab') atau 2, 4, ...
                (start='gap'); sisanya jarak. Batas dibulatkan ke bilangan bulat.
    centered  : `parts` tab berpanjang sama, masing-masing di tengah selnya (panjang tab opsional)."""
    margin = float(margin or 0)
    total = float(length)
    L = total - 2 * margin
    parts = int(parts)
    if L < 6:
        raise ValueError(f"sisi sepanjang {fmt(total)} mm dengan jarak tepi {fmt(margin)} mm terlalu pendek")
    notes = []
    if pattern == "alternate":
        if parts < 2 or parts > 41:
            raise ValueError("pola selang-seling butuh 2 sampai 41 bagian")
        edges = [round(margin + i * L / parts) for i in range(parts + 1)]
        if abs(L / parts - round(L / parts)) > 1e-9:
            notes.append(f"{fmt(L)} mm tidak habis dibagi {parts}: batas bagian dibulatkan ke bilangan bulat")
        want_tab = 0 if start == "tab" else 1
        spans, kinds = [], []
        for i in range(parts):
            is_tab = i % 2 == want_tab
            kinds.append("tab" if is_tab else "jarak")
            if is_tab:
                spans.append([edges[i], edges[i + 1]])
        if parts % 2 == 0:
            notes.append("jumlah bagian genap: pola tidak simetris (salah satu ujung tab, ujung lain jarak)")
        parts_txt = " | ".join(f"{k} {fmt(edges[i])}–{fmt(edges[i + 1])}" for i, k in enumerate(kinds))
        head = f"{parts} bagian × {fmt(L / parts)} mm"
    elif pattern == "centered":
        from . import generator
        cs, ln = generator.layout(L, tab or max(4, int(L / parts / 2)), parts)
        spans = [[round(margin + c - ln / 2, 3), round(margin + c + ln / 2, 3)] for c in cs]
        parts_txt = " | ".join(f"tab {fmt(a)}–{fmt(b)}" for a, b in spans)
        head = f"{len(cs)} tab × {ln} mm"
    else:
        raise ValueError(f"pola '{pattern}' tidak dikenal (alternate | centered)")
    tabs = [round(b - a, 3) for a, b in spans]
    gaps = [round(spans[0][0], 3)] + [round(spans[i + 1][0] - spans[i][1], 3) for i in range(len(spans) - 1)] \
        + [round(total - spans[-1][1], 3)]
    return {"tab_spans": spans, "n_tabs": len(spans), "tab_lengths": tabs, "gap_lengths": gaps, "length": total,
            "text": f"{head}: {parts_txt}", "notes": notes,
            "summary": f"{len(spans)} tab, panjang {fmt(min(tabs))}" + ("" if min(tabs) == max(tabs) else f"–{fmt(max(tabs))}")
                       + f" mm, jarak {fmt(min(gaps[1:-1] or gaps))} mm"}


def corner_reserve(panel, edge, depth, inset):
    """Panjang di tiap ujung sisi `edge` yang sudah dipakai slot milik sisi tegak lurus (agar slot sudut tidak saling menimpa).
    Mengembalikan (ujung_awal, ujung_akhir, daftar_id)."""
    b = panel.outline.bounds
    horiz = edge in ("bottom", "top")
    a_ax, c_ax = (0, 1) if horiz else (1, 0)
    lo, hi = b[a_ax], b[a_ax + 2]
    e0 = {"bottom": b[1], "left": b[0]}.get(edge)
    reach = inset + depth / 2 + 0.5
    r_lo = r_hi = 0.0
    ids = []
    for f in panel.cuts():
        fb = f.poly.bounds
        along = (fb[a_ax], fb[a_ax + 2])
        across = (fb[c_ax], fb[c_ax + 2])
        if along[1] - along[0] > depth + 1:                 # milik sisi ini sendiri (lebih panjang dari tebal)
            continue
        near = across[0] <= e0 + reach if e0 is not None else across[1] >= b[c_ax + 2] - reach
        if not near:
            continue
        hit = False
        if along[0] <= lo + depth + 1:
            r_lo, hit = max(r_lo, along[1] - lo), True
        if along[1] >= hi - depth - 1:
            r_hi, hit = max(r_hi, hi - along[0]), True
        if hit:
            ids.append(f.id)
    return round(r_lo, 3), round(r_hi, 3), ids


# ---------------------------------------------------------------- magnet / garis panduan (smart guides)
def _targets(panel, exclude=(), verts=None):
    """Garis yang bisa ditempeli: tepi dan tengah panel, titik outline, serta tepi dan tengah tiap bentuk lain.
    Hasil (xs, ys); tiap elemen (posisi, nama, (awal, akhir) rentang garis pada sumbu lain)."""
    xs, ys = [], []
    b = panel.outline.bounds
    if verts is None:
        mx, my = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
        xs += [(b[0], "tepi kiri panel", (b[1], b[3])), (mx, "tengah panel", (b[1], b[3])), (b[2], "tepi kanan panel", (b[1], b[3]))]
        ys += [(b[1], "tepi bawah panel", (b[0], b[2])), (my, "tengah panel", (b[0], b[2])), (b[3], "tepi atas panel", (b[0], b[2]))]
        verts = list(panel.outline.exterior.coords)[:-1]
    for x, y in verts:
        xs.append((x, "titik outline", (y, y)))
        ys.append((y, "titik outline", (x, x)))
    for f in panel.features:
        if f.id in exclude or f.role in ("ignore", "detail"):
            continue
        fb = f.poly.bounds
        for pos, lab in ((fb[0], "tepi kiri"), ((fb[0] + fb[2]) / 2, "tengah"), (fb[2], "tepi kanan")):
            xs.append((pos, f"{lab} {f.id}", (fb[1], fb[3])))
        for pos, lab in ((fb[1], "tepi bawah"), ((fb[1] + fb[3]) / 2, "tengah"), (fb[3], "tepi atas")):
            ys.append((pos, f"{lab} {f.id}", (fb[0], fb[2])))
    return xs, ys


def _best(cands, targets, tol):
    out, hit = 0.0, False
    for c in cands:
        for pos, _, _ in targets:
            d = pos - c
            if abs(d) <= tol and (not hit or abs(d) < abs(out) - 1e-9):
                out, hit = d, True
    return out


def _guides(box, xs, ys, tol=1e-3):
    """Garis panduan untuk kotak `box` yang sudah di posisi akhir: tiap garis x/y yang tepat berimpit dengan target."""
    x0, y0, x1, y1 = box
    gx, gy, notes = {}, {}, []
    cx = (("tepi kiri", x0), ("tengah", (x0 + x1) / 2), ("tepi kanan", x1)) if x1 - x0 > 1e-6 else (("titik", x0),)
    cy = (("tepi bawah", y0), ("tengah", (y0 + y1) / 2), ("tepi atas", y1)) if y1 - y0 > 1e-6 else (("titik", y0),)
    for name, c in cx:
        for pos, lab, span in xs:
            if abs(pos - c) < tol:
                g = gx.setdefault(round(pos, 3), [min(y0, y1, *span), max(y0, y1, *span)])
                g[0], g[1] = min(g[0], *span, y0), max(g[1], *span, y1)
                notes.append(f"{name} = {lab}")
    for name, c in cy:
        for pos, lab, span in ys:
            if abs(pos - c) < tol:
                g = gy.setdefault(round(pos, 3), [min(x0, x1, *span), max(x0, x1, *span)])
                g[0], g[1] = min(g[0], *span, x0), max(g[1], *span, x1)
                notes.append(f"{name} = {lab}")
    guides = [{"axis": "x", "pos": p, "a": round(v[0], 3), "b": round(v[1], 3)} for p, v in gx.items()] + \
             [{"axis": "y", "pos": p, "a": round(v[0], 3), "b": round(v[1], 3)} for p, v in gy.items()]
    return guides[:8], list(dict.fromkeys(notes))[:3]


def magnet_move(panel, ids, dx, dy, tol):
    """Geseran (dx, dy) ditempelkan ke garis terdekat (dalam `tol` mm) pada tepi / tengah bentuk lain dan panel."""
    ids = set(ids)
    bs = [f.poly.bounds for f in panel.features if f.id in ids] + [t.poly.bounds for t in panel.tabs if t.id in ids]
    if not bs:
        return {"dx": dx, "dy": dy, "guides": [], "notes": []}
    x0, y0 = min(b[0] for b in bs) + dx, min(b[1] for b in bs) + dy
    x1, y1 = max(b[2] for b in bs) + dx, max(b[3] for b in bs) + dy
    xs, ys = _targets(panel, ids)
    ddx = _best((x0, (x0 + x1) / 2, x1), xs, tol)
    ddy = _best((y0, (y0 + y1) / 2, y1), ys, tol)
    guides, notes = _guides((x0 + ddx, y0 + ddy, x1 + ddx, y1 + ddy), xs, ys)
    return {"dx": round(dx + ddx, 3), "dy": round(dy + ddy, 3), "guides": guides, "notes": notes}


def magnet_draw(panel, res, tool, tol):
    """Lingkaran / kotak yang sedang digambar ditempelkan ke garis terdekat. `res` = hasil measure_drag."""
    xs, ys = _targets(panel)
    if tool == "circle":
        (cx, cy), r = res["center"], res["r"]
        ddx = _best((cx - r, cx, cx + r), xs, tol)
        ddy = _best((cy - r, cy, cy + r), ys, tol)
        res = dict(res, center=[round(cx + ddx, 3), round(cy + ddy, 3)])
        box = (res["center"][0] - r, res["center"][1] - r, res["center"][0] + r, res["center"][1] + r)
    else:
        (cx, cy), (w, h) = res["center"], res["size"]
        x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2
        x0, x1 = x0 + _best((x0,), xs, tol), x1 + _best((x1,), xs, tol)
        y0, y1 = y0 + _best((y0,), ys, tol), y1 + _best((y1,), ys, tol)
        if x1 - x0 >= 0.4 and y1 - y0 >= 0.4:
            res = dict(res, center=[round((x0 + x1) / 2, 3), round((y0 + y1) / 2, 3)], size=[round(x1 - x0, 3), round(y1 - y0, 3)])
        box = (x0, y0, x1, y1)
    res["guides"], notes = _guides(box, xs, ys)
    if tool == "rect":
        res["text"] = f"{fmt(res['size'][0])} × {fmt(res['size'][1])} mm"
    if notes:
        res["text"] = res["text"] + " · magnet: " + ", ".join(notes)
    return res


def magnet_vertex(panel, pts, i, to, tol):
    """Titik outline yang diseret ditempelkan sejajar titik lain / bentuk lain. Hasil: (titik, panduan, catatan)."""
    xs, ys = _targets(panel, (), [p for k, p in enumerate(pts) if k != i])
    nx, ny = to[0] + _best((to[0],), xs, tol), to[1] + _best((to[1],), ys, tol)
    guides, notes = _guides((nx, ny, nx, ny), xs, ys)
    return [round(nx, 3), round(ny, 3)], guides, notes


def _side_text(a, b):
    L = math.hypot(b[0] - a[0], b[1] - a[1])
    ang = math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180
    return f"{fmt(L)} mm" + (f" miring {ang:.1f}°" if is_slanted(ang) and L > 1e-6 else "")


def outline_edit(pts, act, step=0, **k):
    """Hitung outline baru dari titik `pts` untuk satu aksi. Dipakai pratinjau (/api/measure) dan penyimpanan.
    Mengembalikan {"pts": titik baru, "text": ..., "to"/"delta": nilai yang sudah dibulatkan backend}."""
    pts = [[float(x), float(y)] for x, y in pts]
    n = len(pts)
    out = {"act": act}
    if act in ("vertex", "set"):
        i = int(k["i"])
        to = snap_pt(k["to"], step)
        pts[i] = to
        out["to"] = to
        out["text"] = f"titik {i + 1}: x {fmt(to[0])}  y {fmt(to[1])} mm · sisi {_side_text(pts[i - 1], pts[i])} / {_side_text(pts[i], pts[(i + 1) % n])}"
    elif act == "edge":
        i = int(k["i"])
        d = snap_pt(k["delta"], step)
        j = (i + 1) % n
        for q in (i, j):
            pts[q] = [round(pts[q][0] + d[0], 3), round(pts[q][1] + d[1], 3)]
        out["delta"] = d
        out["text"] = f"geser sisi {i + 1}: {d[0]:+g}, {d[1]:+g} mm · panjang {_side_text(pts[i], pts[j])}"
    elif act == "insert":
        i = int(k["i"])
        a, b = pts[i], pts[(i + 1) % n]
        at = snap_pt(k["at"], step) if k.get("at") else snap_pt([(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], step or 1)
        pts.insert(i + 1, at)
        out["text"] = f"titik baru di x {fmt(at[0])}  y {fmt(at[1])} mm"
    elif act == "remove":
        if n <= 3:
            raise ValueError("outline minimal punya 3 titik")
        del pts[int(k["i"])]
        out["text"] = "titik dihapus"
    elif act == "trapezoid":
        side = k["side"]
        if side not in ("top", "bottom", "left", "right"):
            raise ValueError("sisi harus top, bottom, left, atau right")
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        tol = 0.3
        horiz = side in ("top", "bottom")
        edge_v = {"top": y1, "bottom": y0, "left": x0, "right": x1}[side]
        on = [p for p in pts if abs(p[1 if horiz else 0] - edge_v) <= tol]
        if len(on) < 2:
            raise ValueError("sisi itu tidak punya dua titik ujung")
        ax = 0 if horiz else 1
        lo = min(on, key=lambda p: p[ax])
        hi = max(on, key=lambda p: p[ax])
        a, b = snap(k.get("a", 0), step or 1), snap(k.get("b", 0), step or 1)
        lo[ax] = round(lo[ax] + a, 3)
        hi[ax] = round(hi[ax] - b, 3)
        if hi[ax] - lo[ax] < 1:
            raise ValueError("geseran terlalu besar: sisi habis")
        out["text"] = f"trapesium: sisi {EDGE_LABEL.get(side, side)} dipendekkan {fmt(a)} dan {fmt(b)} mm → panjang {fmt(hi[ax] - lo[ax])} mm"
    else:
        raise ValueError(f"aksi outline tidak dikenal: {act}")
    out["pts"] = pts
    return out


def run(body, project=None):
    """Pintu tunggal untuk /api/measure."""
    what, step = body["what"], float(body.get("step", 0) or 0)
    if what == "point":
        return measure_point(body["p"], step)
    if what in ("circle", "rect"):
        r = measure_drag(what, body["c0"], body["cur"], step)
        if body.get("magnet") and project is not None:
            r = magnet_draw(project.panel(body["panel"]), r, what, float(body.get("tol") or 0))
        return r
    if what == "move":
        r = measure_move(body["anchor"], body["delta"], step)
        if body.get("magnet") and project is not None and body.get("ids"):
            g = magnet_move(project.panel(body["panel"]), body["ids"], r["dx"], r["dy"], float(body.get("tol") or 0))
            r.update(dx=g["dx"], dy=g["dy"], guides=g["guides"])
            r["text"] = f"geser {g['dx']:+g}, {g['dy']:+g} mm" + (" · magnet: " + ", ".join(g["notes"]) if g["notes"] else "")
        return r
    if what == "edge":
        return measure_edge(body["edge"], body["value"])
    if what == "component":
        from . import components
        r = components.footprint(body["name"], body.get("params"), float(body.get("rotate", 0) or 0))
        r["text"] = f"{fmt(r['size'][0])} × {fmt(r['size'][1])} mm, {len(r['shapes'])} bentuk"
        return r
    if what == "divide":                       # butuh panel: panjang sisi dibaca dari outline
        if project is None:
            raise ValueError("pengukuran 'divide' butuh proyek")
        panel = project.panel(body["panel"])
        if panel is None:
            raise ValueError(f"panel tidak dikenal: {body['panel']}")
        b = panel.outline.bounds
        length = (b[2] - b[0]) if body["edge"] in ("bottom", "top") else (b[3] - b[1])
        margin, note = float(body.get("margin") or 0), None
        if body.get("corner", True):
            depth = float(body.get("depth") or project.thickness)
            inset = float(body["inset"]) if body.get("inset") not in (None, "") else depth / 2
            lo, hi, ids = corner_reserve(panel, body["edge"], depth, inset)
            if max(lo, hi) > margin:
                margin, note = max(lo, hi), f"jarak ujung {fmt(max(lo, hi))} mm dikurangi untuk slot sudut sisi lain ({', '.join(ids)})"
        r = divide_plan(length, body.get("parts", 3), body.get("pattern", "alternate"), body.get("start", "tab"),
                        body.get("tab"), margin)
        if note:
            r["notes"].insert(0, note)
        c = float(body.get("clearance") or 0)
        if c:
            d = float(body.get("depth") or project.thickness)
            r["slot_text"] = (f"celah slot {c:+g} mm: slot berukuran " + ", ".join(sorted({f"{fmt(x + c)} × {fmt(d + c)}" for x in r["tab_lengths"]}))
                              + f" mm untuk tab {fmt(d)} mm" + (" (pas ketat, mengunci)" if c < 0 else " (longgar)"))
        return r
    if what == "outline":
        a = dict(body)
        pts, act = a.pop("pts"), a.pop("act")
        kw = {q: v for q, v in a.items() if q not in ("what", "step", "magnet", "tol", "panel")}
        r = outline_edit(pts, act, step, **kw)
        if body.get("magnet") and project is not None and act == "vertex":
            to, guides, notes = magnet_vertex(project.panel(body["panel"]), pts, int(kw["i"]), r["to"], float(body.get("tol") or 0))
            if to != r["to"]:
                r = outline_edit(pts, act, 0, i=kw["i"], to=to)
            r["guides"] = guides
            if notes:
                r["text"] += " · magnet: " + ", ".join(notes)
        return r
    if what == "box":
        return measure_box(body["inner"], body.get("thickness", 5), body.get("tab", 20), body.get("joints"))
    raise ValueError(f"pengukuran tidak dikenal: {what}")


# ---------------------------------------------------------------- laporan ukuran
def _edge_list(b):
    vals = {"left": b[0], "right": b[2], "bottom": b[1], "top": b[3]}
    return [{"name": k, "label": EDGE_LABEL[k], "value": round(v, 3), "int": is_int(v), "text": fmt(v)}
            for k, v in vals.items()]


def outline_sides(outline):
    """Sisi outline. Sisi miring, dan sisi yang bersambung ke sisi miring, boleh berkoma."""
    segs = []
    c = list(outline.exterior.coords)
    for (x0, y0), (x1, y1) in zip(c, c[1:]):
        L = math.hypot(x1 - x0, y1 - y0)
        if L < 1e-6:
            continue
        ang = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 180
        segs.append({"from": [round(x0, 2), round(y0, 2)], "to": [round(x1, 2), round(y1, 2)],
                     "length": round(L, 3), "angle": round(ang, 2), "slanted": is_slanted(ang)})
    n = len(segs)
    for i, sg in enumerate(segs):
        touches_slant = sg["slanted"] or segs[i - 1]["slanted"] or segs[(i + 1) % n]["slanted"]
        sg["int"] = True if touches_slant else is_int(sg["length"])
        sg["text"] = f"{fmt(sg['length'])} mm" + (f" miring {sg['angle']:.1f}°" if sg["slanted"] else "")
    return segs


def panel_measure(panel):
    b = panel.outline.bounds
    w, h = b[2] - b[0], b[3] - b[1]
    edges = _edge_list(b)
    return {"bounds": [round(v, 3) for v in b], "size": [round(w, 3), round(h, 3)],
            "size_text": f"{fmt(w)} × {fmt(h)}", "edges": edges,
            "all_int": all(e["int"] for e in edges), "sides": outline_sides(panel.outline),
            "outline": [[round(x, 3), round(y, 3)] for x, y in list(panel.outline.exterior.coords)[:-1]]}


def _field(key, label, v, exempt=False, ro=False, check=None):
    """check: nilai yang diuji bulat atau tidak (bila beda dari v, mis. tepi bentuk, bukan titik tengahnya)."""
    return {"key": key, "label": label, "value": round(v, 3),
            "int": True if exempt else is_int(v if check is None else check), "ro": ro}


def panel_items(panel, thickness):
    """Fitur dan tab yang bisa dipilih di editor 2D, lengkap dengan teks dan kolom angkanya."""
    from . import geom
    out = []
    for t in panel.tabs:
        c = t.center
        out.append({"id": t.id, "type": "tab", "kind": "tab", "edge": t.edge, "role": "tab", "added": t.added,
                    "center": [round(c[0], 2), round(c[1], 2)], "size": [round(t.length, 2), round(t.depth, 2)],
                    "text": f"tab {t.edge} {fmt(t.length)}×{fmt(t.depth)}",
                    "fields": [_field("x", "x", c[0], check=t.poly.bounds[0]),
                               _field("y", "y", c[1], check=t.poly.bounds[1])]})
    for f in panel.features:
        if f.role == "detail":
            continue
        c = f.center
        d = {"id": f.id, "type": "feature", "kind": f.kind, "role": f.role, "added": f.added,
             "group": f.group, "comp": f.comp,
             "slot": geom.is_slot(f, thickness), "center": [round(c[0], 2), round(c[1], 2)]}
        if f.kind == "circle":
            d["r"] = round(f.r, 3)
            d["text"] = f"lingkaran Ø{fmt(f.r * 2)}"
            d["fields"] = [_field("x", "x", c[0]), _field("y", "y", c[1]), _field("d", "Ø", f.r * 2)]
        elif f.kind == "rect":
            sl = is_slanted(f.angle)
            d["size"], d["angle"] = [round(f.size[0], 3), round(f.size[1], 3)], round(f.angle, 2)
            d["text"] = ("slot" if d["slot"] else "kotak") + f" {fmt(f.size[0])}×{fmt(f.size[1])}" + \
                        (f" miring {f.angle:.1f}°" if sl else "")
            bb = f.poly.bounds        # yang menentukan bulat atau tidak: tepi kiri / bawah, bukan titik tengah
            d["fields"] = [_field("x", "x", c[0], sl, check=bb[0]), _field("y", "y", c[1], sl, check=bb[1]),
                           _field("w", "lebar", f.size[0], sl), _field("h", "tinggi", f.size[1], sl),
                           _field("a", "sudut", f.angle, True)]
        else:
            bb = f.poly.bounds
            d["size"] = [round(bb[2] - bb[0], 2), round(bb[3] - bb[1], 2)]
            d["text"] = f"bentuk bebas {fmt(d['size'][0])}×{fmt(d['size'][1])}"
            d["fields"] = [_field("x", "x", c[0], True), _field("y", "y", c[1], True)]
        out.append(d)
    return out


def describe(panel, thickness):
    """Teks laporan ukuran satu panel (untuk CLI / LLM)."""
    m = panel_measure(panel)
    lines = [f"{panel.id} {panel.name}".strip() + f": {m['size_text']} mm",
             "  batas   : " + "  ".join(f"{e['label']} {e['text']}" + ("" if e["int"] else " (berkoma)") for e in m["edges"]),
             "  sisi    : " + "; ".join(sg["text"] + ("" if sg["int"] else " (berkoma)") for sg in m["sides"])]
    items = panel_items(panel, thickness)
    for typ, nama in (("tab", "tab"), ("feature", "fitur")):
        bad = [i for i in items if i["type"] == typ and any(not f["int"] for f in i["fields"])]
        if bad:
            ex = bad[0]
            lines.append(f"  {nama:<8}: {len(bad)} dari {sum(1 for i in items if i['type'] == typ)} berkoma, mis. "
                         f"{ex['id']} {ex['text']}: " + ", ".join(f"{f['label']}={fmt(f['value'])}" for f in ex["fields"] if not f["int"]))
    return "\n".join(lines)
