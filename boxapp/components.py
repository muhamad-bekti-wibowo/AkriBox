"""Pustaka komponen: potongan standar (lubang baut, kipas, tombol, layar, ventilasi, ...) yang
ditempatkan sekali klik. Satu komponen = beberapa bentuk (lingkaran / kotak) yang bergerak dan
terhapus bersama (satu grup).

PENTING: ukuran di sini adalah nilai UMUM (lubang baut menurut ISO 273, pola baut kipas PC, lubang
tombol standar). Komponen yang ukurannya berbeda antar pabrik (soket, layar, jack) sengaja dibuat
"kustom": Anda isi ukurannya dari datasheet komponen Anda. Cocokkan dengan komponen asli
sebelum memotong akrilik.
"""
from __future__ import annotations

import math

from shapely.geometry import MultiPolygon, Polygon

from .project import ProjectError

SCREWS = [["M2", 2.4], ["M2.5", 2.9], ["M3", 3.4], ["M4", 4.5], ["M5", 5.5], ["M6", 6.6]]
BUTTONS = [["Ø12", 12], ["Ø16", 16], ["Ø19", 19], ["Ø22", 22], ["Ø25", 25], ["Ø30", 30]]
# kipas PC: ukuran -> (diameter bukaan, jarak antar lubang baut)
FANS = {40: (36, 32), 50: (46, 40), 60: (56, 50), 70: (66, 61.5), 80: (76, 71.5), 92: (88, 82.5), 120: (114, 105)}


def _num(key, label, default, step=0.5, minimum=0.5):
    return {"key": key, "label": label, "type": "number", "default": default, "step": step, "min": minimum}


def _sel(key, label, options, default):
    return {"key": key, "label": label, "type": "select", "options": options, "default": default}


def _circle(x, y, d, role="cut"):
    return {"kind": "circle", "center": [round(x, 3), round(y, 3)], "r": round(d / 2, 3), "role": role}


def _rect(x, y, w, h, role="cut"):
    return {"kind": "rect", "center": [round(x, 3), round(y, 3)], "size": [round(w, 3), round(h, 3)], "angle": 0, "role": role}


def _corners(sx, sy, d):
    return [_circle(x * sx / 2, y * sy / 2, d) for x in (-1, 1) for y in (-1, 1)]


def _screw(p):
    return [_circle(0, 0, p["d"])]


def _pcb(p):
    return _corners(p["w"], p["h"], p["d"])


def _fan(p):
    size = int(p["size"])
    if size not in FANS:
        raise ProjectError(f"ukuran kipas {size} tidak ada (pilih {sorted(FANS)})")
    bore, sp = FANS[size]
    return [_circle(0, 0, bore)] + _corners(sp, sp, p["d"])


def _button(p):
    return [_circle(0, 0, p["d"])]


def _window(p):
    return [_rect(0, p.get("oy", 0), p["w"], p["h"])] + _corners(p["sx"], p["sy"], p["d"])


def _lcd1602(p):
    return [_rect(0, p["oy"], p["w"], p["h"])] + _corners(75, 31, p["d"])


def _inlet(p):
    return [_rect(0, 0, p["w"], p["h"])] + [_circle(x * p["sp"] / 2, 0, p["d"]) for x in (-1, 1)]


def _esp32(p):
    """Modul ESP32-4827S043 (layar 4,3 inci): PCB, kaca layar, jendela tampilan, dan 4 lubang baut.
    Angka dari gambar teknis: PCB 123 x 74, lubang D3,2 berjarak 3,5 dari tiap tepi, kaca 105,5 x 67,2."""
    w, h, i = p["w"], p["h"], p["inset"]
    sx, sy = w - 2 * i, h - 2 * i
    return [_rect(0, 0, w, h, "guide"), _rect(0, p["gy"], p["gw"], p["gh"], "guide"),
            _rect(0, p["gy"] + p["oy"], p["ww"], p["wh"])] + [_circle(x * sx / 2, y * sy / 2, p["d"]) for x in (-1, 1) for y in (-1, 1)]


# port USB betina: (lebar, tinggi) cangkang logam menurut ukuran umum; cek datasheet soket Anda
USB = {1: ("USB-A", 13.1, 5.7), 2: ("USB-B", 12.0, 10.9), 3: ("Micro-USB B", 7.5, 2.6), 4: ("USB-C", 8.94, 3.26)}


def _usb(p):
    """Soket USB betina: cangkang logam (garis bantu, tidak dipotong), bukaan potong = cangkang + celah, dan 2 lubang baut opsional."""
    t = int(p["type"])
    if t not in USB:
        raise ProjectError("jenis USB tidak dikenal")
    _, w, h = USB[t]
    w = p["w"] or w
    h = p["h"] or h
    c = p["clear"]
    out = [_rect(0, 0, w, h, "guide"), _rect(0, 0, w + c, h + c)]
    if p["sp"] > 0:
        out += [_circle(x * p["sp"] / 2, 0, p["d"]) for x in (-1, 1)]
    return out


def _oled(p):
    """OLED 0,96 inci SSD1306 (modul 7 pin SPI): PCB, kaca, area aktif (garis bantu), jendela potong, dan 4 lubang baut."""
    w, h, i = p["w"], p["h"], p["inset"]
    sx, sy = w - 2 * i, h - 2 * i
    return [_rect(0, 0, w, h, "guide"), _rect(0, p["gy"], p["gw"], p["gh"], "guide"),
            _rect(0, p["gy"] + p["ay"], p["aw"], p["ah"], "guide"),
            _rect(0, p["gy"] + p["ay"], p["aw"] + p["m"], p["ah"] + p["m"])] +            ([_circle(x * sx / 2, y * sy / 2, p["d"]) for x in (-1, 1) for y in (-1, 1)] if p["d"] > 0 else [])


def _vent(p):
    W, H, d, pitch = p["w"], p["h"], p["d"], p["pitch"]
    if d >= min(W, H) or pitch <= d:
        raise ProjectError("ventilasi: diameter harus lebih kecil dari area dan dari jarak antar lubang")
    rows = pitch * math.sqrt(3) / 2
    out, y, j = [], -H / 2 + d / 2, 0
    while y <= H / 2 - d / 2 + 1e-6:
        x0 = -W / 2 + d / 2 + (pitch / 2 if j % 2 else 0)
        x = x0
        while x <= W / 2 - d / 2 + 1e-6:
            out.append(_circle(x, y, d))
            x += pitch
        y += rows
        j += 1
    if not out:
        raise ProjectError("ventilasi: tidak ada lubang yang muat di area itu")
    # pusatkan pola di area
    xs = [s["center"][0] for s in out]
    ys = [s["center"][1] for s in out]
    cx, cy = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    for s in out:
        s["center"] = [round(s["center"][0] - cx, 3), round(s["center"][1] - cy, 3)]
    return out


LIB = {
    "baut": {"label": "Lubang baut (M2–M6)", "note": "Diameter lubang longgar menurut ISO 273 (M3 = 3,4 mm).",
             "params": [_sel("d", "Baut", SCREWS, 3.4)], "build": _screw},
    "pcb-4-baut": {"label": "PCB: 4 lubang baut", "note": "Jarak antar lubang diukur dari PCB Anda.",
                   "params": [_num("w", "Jarak lubang horizontal (mm)", 60, 1), _num("h", "Jarak lubang vertikal (mm)", 40, 1),
                              _sel("d", "Baut", SCREWS, 3.4)], "build": _pcb},
    "kipas": {"label": "Kipas PC (bukaan + 4 baut)", "note": "Bukaan = ukuran − 4 mm; jarak baut standar kipas PC. Cek kipas Anda.",
              "params": [_sel("size", "Ukuran kipas", [[f"{s} mm", s] for s in sorted(FANS)], 80), _num("d", "Diameter lubang baut (mm)", 4.3, 0.1)],
              "build": _fan},
    "tombol": {"label": "Tombol / lampu indikator (bulat)", "note": "Ukuran lubang standar tombol tekan.",
               "params": [_sel("d", "Diameter lubang", BUTTONS, 16)], "build": _button},
    "lcd-1602": {"label": "LCD 16×2 (modul 80×36)", "note": "Baut 75×31 mm (umum). Jendela dan posisinya berbeda antar pabrik: ukur modul Anda.",
                 "params": [_num("w", "Lebar jendela (mm)", 71, 1), _num("h", "Tinggi jendela (mm)", 24, 1),
                            _num("oy", "Geser jendela ke atas (mm)", 0, 1, -50), _sel("d", "Baut", SCREWS, 3.4)], "build": _lcd1602},
    "jendela-baut": {"label": "Jendela + 4 baut (layar kustom)", "note": "Isi dari datasheet layar / modul Anda.",
                     "params": [_num("w", "Lebar jendela (mm)", 70, 1), _num("h", "Tinggi jendela (mm)", 25, 1),
                                _num("sx", "Jarak baut horizontal (mm)", 75, 1), _num("sy", "Jarak baut vertikal (mm)", 31, 1),
                                _sel("d", "Baut", SCREWS, 3.4)], "build": _window},
    "soket-2-baut": {"label": "Soket kotak + 2 baut (kustom)", "note": "Contoh: inlet IEC, saklar. Nilai awal hanya contoh: ISI DARI DATASHEET komponen Anda.",
                     "params": [_num("w", "Lebar bukaan (mm)", 28, 0.5), _num("h", "Tinggi bukaan (mm)", 20, 0.5),
                                _num("sp", "Jarak 2 baut (mm)", 40, 0.5), _sel("d", "Baut", SCREWS, 3.4)], "build": _inlet},
    "esp32-4827s043": {"label": "ESP32-4827S043 (layar 4,3 inci, PCB 123x74)",
                       "note": "PCB, kaca layar, jendela tampilan, 4 lubang D3,2 (3,5 dari tepi). PCB, lubang, dan kaca dari gambar teknis; "
                               "POSISI kaca dan UKURAN jendela belum pasti: cocokkan dengan modul asli, lalu ubah Geser kaca / Geser jendela / ukuran jendela.",
                       "params": [_num("w", "Lebar PCB (mm)", 123, 0.5), _num("h", "Tinggi PCB (mm)", 74, 0.5),
                                  _num("inset", "Lubang dari tepi (mm)", 3.5, 0.1), _num("d", "Diameter lubang (mm)", 3.2, 0.1),
                                  _num("gw", "Lebar kaca layar (mm)", 105.5, 0.1), _num("gh", "Tinggi kaca layar (mm)", 67.2, 0.1),
                                  _num("gy", "Geser kaca ke atas (mm)", 0, 0.5, -30),
                                  _num("ww", "Lebar jendela tampilan (mm)", 95, 0.5), _num("wh", "Tinggi jendela tampilan (mm)", 54, 0.5),
                                  _num("oy", "Geser jendela dari kaca (mm)", 0, 0.5, -30)], "build": _esp32},
    "usb-betina": {"label": "Port USB betina + cangkangnya (A / B / Micro / C)",
                   "note": "Cangkang logam digambar sebagai garis bantu; bukaan potong = cangkang + celah. Ukuran cangkang umum "
                           "(A 13,1x5,7; B 12x10,9; Micro 7,5x2,6; C 8,94x3,26): isi Lebar/Tinggi bila soket Anda berbeda (0 = ukuran jenis). "
                           "Jarak 2 baut 0 = tanpa baut (soket di PCB).",
                   "params": [_sel("type", "Jenis", [[v[0], k] for k, v in USB.items()], 4),
                              _num("w", "Lebar cangkang (mm, 0 = standar jenis)", 0, 0.1, 0), _num("h", "Tinggi cangkang (mm, 0 = standar)", 0, 0.1, 0),
                              _num("clear", "Celah bukaan (mm)", 0.4, 0.1, 0), _num("sp", "Jarak 2 baut (mm, 0 = tanpa)", 0, 0.5, 0),
                              _sel("d", "Baut", SCREWS, 3.4)], "build": _usb},
    "oled-096-spi": {"label": "OLED 0,96 inci SPI/I2C (SSD1306, modul 27,3x27,8)",
                     "note": "Angka dari lembar data vendor (hasil pencarian internet): modul 27,3x27,8 mm, area aktif 21,74x10,86 mm. "
                             "Beda antar vendor sampai >1 mm (Waveshare 21,7x11,2; modul 27x27; DFRobot 30x30). Jarak lubang baut (2 mm dari tepi, D2,2), "
                             "ukuran kaca 26,7x19,3 dan posisinya adalah PERKIRAAN: ukur modul Anda. Lubang baut 0 = tanpa baut.",
                     "params": [_num("w", "Lebar PCB (mm)", 27.3, 0.1), _num("h", "Tinggi PCB (mm)", 27.8, 0.1),
                                _num("inset", "Lubang dari tepi (mm)", 2.0, 0.1), _num("d", "Diameter lubang (mm, 0 = tanpa)", 2.2, 0.1, 0),
                                _num("gw", "Lebar kaca (mm)", 26.7, 0.1), _num("gh", "Tinggi kaca (mm)", 19.3, 0.1),
                                _num("gy", "Geser kaca ke atas (mm)", 3.0, 0.1, -20),
                                _num("aw", "Lebar area aktif (mm)", 21.74, 0.01), _num("ah", "Tinggi area aktif (mm)", 10.86, 0.01),
                                _num("ay", "Geser area aktif dari kaca (mm)", 0, 0.1, -10),
                                _num("m", "Tambahan jendela potong (mm)", 1.0, 0.1, 0)], "build": _oled},
    "ventilasi": {"label": "Ventilasi lubang bulat (heksagonal)", "note": "Lubang tersusun selang-seling dalam area persegi, dipusatkan.",
                  "params": [_num("w", "Lebar area (mm)", 60, 1, 5), _num("h", "Tinggi area (mm)", 40, 1, 5),
                             _num("d", "Diameter lubang (mm)", 6, 0.5), _num("pitch", "Jarak pusat ke pusat (mm)", 9, 0.5)],
                  "build": _vent},
}


def catalog():
    return [{"name": k, "label": v["label"], "note": v["note"], "params": v["params"]} for k, v in LIB.items()]


def _params(spec, given):
    out = {}
    for p in spec["params"]:
        v = given.get(p["key"], p["default"])
        try:
            v = float(v)
        except (TypeError, ValueError):
            raise ProjectError(f"parameter {p['label']}: angka tidak valid")
        if p["type"] == "number" and v < p.get("min", 0):
            raise ProjectError(f"parameter {p['label']}: minimal {p.get('min', 0):g}")
        out[p["key"]] = v
    return out


def build(name, params=None, at=(0, 0), rotate=0.0):
    """Bentuk (dict) komponen `name` berpusat di `at`, diputar `rotate` derajat."""
    spec = LIB.get(name)
    if spec is None:
        raise ProjectError(f"komponen '{name}' tidak ada (pilihan: {', '.join(LIB)})")
    shapes = spec["build"](_params(spec, params or {}))
    a = math.radians(rotate)
    ca, sa = math.cos(a), math.sin(a)
    out = []
    for s in shapes:
        dx, dy = s["center"]
        s = dict(s)
        s["center"] = [round(at[0] + dx * ca - dy * sa, 3), round(at[1] + dx * sa + dy * ca, 3)]
        if s["kind"] == "rect":
            s["angle"] = round((s.get("angle", 0) + rotate) % 180, 3)
        out.append(s)
    return out


def footprint(name, params=None, rotate=0.0):
    """Pratinjau untuk dialog: bentuk di sekitar (0,0) dan ukuran kotak pembatasnya."""
    from . import edits
    shapes = build(name, params, (0, 0), rotate)
    polys = [edits.shape_poly(s) for s in shapes]
    from shapely.ops import unary_union
    u = unary_union(polys)
    b = u.bounds
    return {"shapes": shapes, "bounds": [round(v, 2) for v in b],
            "size": [round(b[2] - b[0], 2), round(b[3] - b[1], 2)]}
