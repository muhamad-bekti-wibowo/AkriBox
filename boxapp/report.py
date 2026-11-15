"""Ringkas laporan pemeriksaan menjadi baris-baris yang enak dibaca (dipakai CLI dan GUI).

level: gagal | sesak | awas | info | ok
"""
from __future__ import annotations


def _rng(vals):
    lo, hi = min(vals), max(vals)
    return f"{lo:.2f}" if hi - lo < 0.005 else f"{lo:.2f}..{hi:.2f}"


def _tabs(g):
    return ", ".join(j["tab"].split(".")[1] for j in g)


def summarize(pr, rep, detail=False):
    L = pr.label
    sections = []

    head = (f"Tebal {rep['thickness']:g} mm, kerf {rep['kerf']:g} mm. "
            f"Panel ditempatkan: {len(rep['placed'])}, belum: {len(rep['unplaced'])}"
            + (f" ({', '.join(L(p) for p in rep['unplaced'])})" if rep["unplaced"] else ""))
    size = ""
    if "size_body" in rep:
        s, w = rep["size_body"], rep["size_with_tabs"]
        size = (f"Ukuran nyata rakitan (X x Y x Z): {s[0]:.2f} x {s[1]:.2f} x {s[2]:.2f} mm"
                f"   (dengan ujung tab: {w[0]:.2f} x {w[1]:.2f} x {w[2]:.2f})")

    items = [{"level": "gagal" if c["level"] == "error" else "sesak",
              "text": f"{L(c['a'])} x {L(c['b'])}: {c['msg']}", "panels": [c["a"], c["b"]]}
             for c in sorted(rep["collisions"], key=lambda c: -c["depth"])]
    sections.append({"title": f"TABRAKAN BADAN PANEL ({len(items)})", "items": items})

    js = rep["joints"]
    n = {k: sum(j["kind"] == k for j in js) for k in ("ok", "tight", "misfit", "solid", "free")}
    groups = {}
    for j in js:
        groups.setdefault((j["kind"], j["a"], j["b"], j.get("dir")), []).append(j)
    order = {"solid": 0, "misfit": 1, "free": 2, "tight": 3, "ok": 4}
    lv = {"error": "gagal", "tight": "sesak", "warn": "awas", "ok": "ok"}
    items = []
    for (kind, x, y, d), g in sorted(groups.items(), key=lambda kv: order[kv[0][0]]):
        panels = [x] + ([y] if y else [])
        if detail and kind != "ok":
            items += [{"level": lv[j["level"]], "panels": panels,
                       "text": f"{j['tab']} -> {L(y) if y else '-'}: {j['msg']}"} for j in g]
            continue
        head_ = f"{L(x)} -> {L(y)}" if y else L(x)
        if kind == "solid":
            lvl, txt = "gagal", (f"{len(g)} tab menabrak bagian pejal, slot terdekat bergeser "
                                 f"{_rng([j.get('deficit', 0) for j in g])} mm ({_tabs(g)})")
        elif kind == "misfit":
            lvl, txt = "gagal", (f"{len(g)} tab tidak muat, kurang "
                                 f"{_rng([j['deficit'] for j in g])} mm {d} slot ({_tabs(g)})")
        elif kind == "free":
            lvl, txt = "awas", f"{len(g)} tab tidak masuk ke panel mana pun ({_tabs(g)})"
        elif kind == "tight":
            lvl, txt = "sesak", (f"{len(g)} tab kurang {_rng([j['deficit'] for j in g])} mm "
                                 f"{d} slot ({_tabs(g)})")
        else:
            plays = [j["play"] for j in g if "play" in j]
            txt = f"{len(g)} tab masuk."
            if plays:
                txt += (f" celah panjang {_rng([p[0] for p in plays])}, "
                        f"lebar {_rng([p[1] for p in plays])} mm")
            warn = [j for j in g if j["level"] == "warn"]
            lvl = "awas" if warn else "ok"
            if warn:
                txt += f"; {len(warn)} tab: " + warn[0]["msg"].split("; ", 1)[-1]
        items.append({"level": lvl, "text": f"{head_}: {txt}", "panels": panels})
    sections.append({"title": (f"SAMBUNGAN TAB ({len(js)}): {n['ok']} masuk, {n['tight']} sesak, "
                               f"{n['misfit'] + n['solid']} gagal, {n['free']} menggantung"),
                     "items": items})

    by = {}
    for s_ in rep["empty_slots"]:
        pid, fid = s_.split(".")
        by.setdefault(pid, []).append(fid)
    sections.append({"title": f"SLOT KOSONG ({len(rep['empty_slots'])})", "items": [
        {"level": "awas", "panels": [pid],
         "text": f"{L(pid)}: {len(fs)} slot tidak dimasuki tab ({', '.join(fs)})"}
        for pid, fs in by.items()]})

    sections.append({"title": f"GAMBAR 2D ({len(rep['drawing'])})", "items": [
        {"level": "awas" if d["level"] == "warn" else "info", "panels": [d["panel"]] if d["panel"] else [],
         "text": (f"{L(d['panel'])}: " if d["panel"] else "") + d["msg"]} for d in rep["drawing"]]})

    verdict = (f"HASIL: {'LOLOS' if rep['ok'] else 'TIDAK LOLOS'} - {rep['errors']} gagal, "
               f"{rep['tight']} sesak (kurang <= 0.5 mm), {rep['warnings']} peringatan")
    return {"head": head, "size": size, "sections": sections, "verdict": verdict}


def to_text(summary):
    out = [summary["head"]]
    if summary["size"]:
        out.append(summary["size"])
    out.append("")
    for s in summary["sections"]:
        out.append(s["title"])
        for it in s["items"]:
            out.append(f"  [{it['level']:<5}] {it['text']}")
        out.append("")
    out.append(summary["verdict"])
    return "\n".join(out)
