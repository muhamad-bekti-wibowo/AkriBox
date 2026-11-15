"""Kendalikan GUI lewat browser tanpa kepala: ambil tangkapan layar, klik, seret, ketik.

Dibuat supaya LLM (atau skrip) bisa "melihat" dan memakai GUI persis seperti pengguna.
Butuh Playwright (pip install playwright) dan Chrome atau Edge yang sudah terpasang;
tidak perlu mengunduh browser.

Skrip = daftar langkah JSON. Koordinat "dalam mm" memakai koordinat panel yang sedang
dibuka di tab Panel 2D ((0,0) = pojok kiri-bawah outline panel).

  {"do": "tab", "to": "2d" | "3d"}
  {"do": "select", "panel": "P7"}                      pilih panel
  {"do": "tool", "name": "select" | "circle" | "rect"} alat gambar 2D
  {"do": "drag", "from": [40, 40], "to": [47, 40]}     seret (mm); mode alat yang aktif berlaku
  {"do": "click", "at": [40, 40]}                      klik di titik panel (mm)
  {"do": "click", "selector": "#b-array"}              klik elemen
  {"do": "key", "key": "Delete"}                       tekan tombol (Control+z, Escape, ...)
  {"do": "fill", "selector": "#ar-d", "value": "6"}
  {"do": "select_option", "selector": "#tr-target", "value": "new_panel"}
  {"do": "check" | "uncheck", "selector": "#ar-av"}
  {"do": "upload", "selector": "#tr-file", "file": "foto.png"}
  {"do": "wait", "ms": 500}
  {"do": "settle"}                                     tunggu hitung ulang 3D selesai
  {"do": "shot", "path": "a.png", "selector": "#stage2d"}   selector opsional (potong elemen)
  {"do": "state"}                                      ringkasan: panel, item, laporan
  {"do": "eval", "js": "window.__app.state.report"}    jalankan JavaScript, cetak hasilnya
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import time

from .project import Project, ProjectError


def _playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        raise ProjectError("Playwright belum terpasang. Jalankan:  .venv\\Scripts\\pip install playwright\n"
                           "(memakai Chrome / Edge yang sudah ada; tidak ada browser yang diunduh)")


class Session:
    def __init__(self, project_path, size=(1500, 900), outdir="."):
        from .server import start_background
        self.outdir = outdir
        os.makedirs(outdir, exist_ok=True)
        self.srv, self.url = start_background(project_path)
        self.errors = []
        self._pw = _playwright()().start()
        last = None
        for ch in ("chrome", "msedge"):
            try:
                self.br = self._pw.chromium.launch(channel=ch, headless=True, args=[
                    "--enable-unsafe-swiftshader", "--use-angle=swiftshader", "--ignore-gpu-blocklist"])
                break
            except Exception as e:            # tidak ada channel ini
                last = e
        else:
            self._pw.stop()
            raise ProjectError(f"Chrome / Edge tidak ditemukan untuk Playwright: {last}")
        self.pg = self.br.new_page(viewport={"width": size[0], "height": size[1]})
        self.pg.on("pageerror", lambda e: self.errors.append(f"pageerror: {e}"))
        self.pg.on("console", lambda m: self.errors.append(f"console.error: {m.text}")
                   if m.type == "error" and "GL Driver" not in m.text and "ReadPixels" not in m.text else None)
        self.pg.goto(self.url)
        self.pg.wait_for_function("window.__app && window.__app.state", timeout=60000)
        self.settle()

    # ------------------------------------------------------------------
    def close(self):
        for f in (lambda: self.br.close(), lambda: self._pw.stop(), lambda: self.srv.shutdown()):
            try:
                f()
            except Exception:
                pass

    def settle(self):
        self.pg.wait_for_timeout(300)
        self.pg.wait_for_function("!document.getElementById('badge').classList.contains('stale')", timeout=60000)

    def _scr(self, x, y):
        r = self.pg.evaluate("""([x,y]) => { const s=document.querySelector('#stage2d svg');
            if(!s) return null; const d=s.dataset, p=s.createSVGPoint();
            p.x = x - +d.b0 + +d.m; p.y = +d.h - (y - +d.b1 + +d.m);
            const q=p.matrixTransform(s.getScreenCTM()); return [q.x, q.y]; }""", [x, y])
        if r is None:
            raise ProjectError("tab Panel 2D belum terbuka atau belum ada panel terpilih "
                               "(pakai langkah tab '2d' dan select)")
        return r

    def path(self, p):
        return p if os.path.isabs(p) else os.path.join(self.outdir, p)

    # ------------------------------------------------------------------
    def step(self, st):
        pg, do = self.pg, st.get("do")
        if do == "tab":
            pg.evaluate(f"window.__app.tab({str(st['to'].lower() == '3d').lower()})")
            pg.wait_for_timeout(700 if st["to"].lower() == "3d" else 200)
            return f"tab {st['to']}"
        if do == "select":
            pg.evaluate("(id) => window.__app.select(id)", st["panel"])
            pg.wait_for_timeout(200)
            return f"panel {st['panel']} dipilih"
        if do == "tool":
            pg.click(f"#tl-{st['name']}")
            return f"alat {st['name']}"
        if do == "drag":
            (x0, y0), (x1, y1) = self._scr(*st["from"]), self._scr(*st["to"])
            pg.mouse.move(x0, y0)
            pg.mouse.down()
            n = int(st.get("steps", 8))
            for i in range(1, n + 1):
                pg.mouse.move(x0 + (x1 - x0) * i / n, y0 + (y1 - y0) * i / n)
            pg.mouse.up()
            pg.wait_for_timeout(int(st.get("wait", 800)))
            return f"seret {st['from']} -> {st['to']}"
        if do == "click":
            if "at" in st:
                x, y = self._scr(*st["at"])
                pg.mouse.click(x, y)
                pg.wait_for_timeout(int(st.get("wait", 800)))
                return f"klik {st['at']}"
            pg.click(st["selector"], timeout=15000)
            pg.wait_for_timeout(int(st.get("wait", 300)))
            return f"klik {st['selector']}"
        if do == "key":
            pg.keyboard.press(st["key"])
            pg.wait_for_timeout(int(st.get("wait", 500)))
            return f"tombol {st['key']}"
        if do in ("fill", "select_option"):
            getattr(pg, do)(st["selector"], st["value"], timeout=15000)
            return f"{do} {st['selector']} = {st['value']}"
        if do in ("check", "uncheck"):
            getattr(pg, do)(st["selector"], timeout=15000)
            return f"{do} {st['selector']}"
        if do == "press":
            pg.press(st["selector"], st["key"])
            pg.wait_for_timeout(int(st.get("wait", 700)))
            return f"{st['key']} di {st['selector']}"
        if do == "upload":
            pg.set_input_files(st["selector"], os.path.abspath(st["file"]))
            return f"unggah {st['file']}"
        if do == "wait":
            pg.wait_for_timeout(int(st["ms"]))
            return f"tunggu {st['ms']} ms"
        if do == "settle":
            self.settle()
            return "hitung ulang selesai"
        if do == "shot":
            out = self.path(st.get("path", "layar.png"))
            if st.get("selector"):
                pg.locator(st["selector"]).screenshot(path=out)
            else:
                pg.screenshot(path=out, full_page=bool(st.get("full")))
            return f"tangkapan layar: {os.path.abspath(out)}"
        if do == "state":
            return json.dumps(pg.evaluate("""() => { const s = window.__app.state, p = s.panels.find(p => p.id === document.querySelector('#plist .row.sel')?.dataset.id);
              return {panel_terpilih: p ? {id: p.id, nama: p.name, ukuran: p.size, item: p.items.map(i => [i.id, i.kind, i.role, i.added ? 'tambahan' : 'bawaan', i.center, i.r ?? i.size ?? null])} : null,
                      laporan: s.report, tab: document.getElementById('view2d').style.display === 'grid' ? '2d' : '3d',
                      pesan: document.getElementById('err').textContent || null,
                      panel: s.panels.map(p => [p.id, p.name, p.size, p.placed])}; }"""), ensure_ascii=False)
        if do == "eval":
            return json.dumps(pg.evaluate(st["js"]), ensure_ascii=False, default=str)
        raise ProjectError(f"langkah tidak dikenal: {do}")

    def run(self, steps):
        for i, st in enumerate(steps, 1):
            try:
                print(f"{i:>2}. {self.step(st)}", flush=True)
            except Exception as e:
                fail = self.path("gagal.png")
                try:
                    self.pg.screenshot(path=fail)
                except Exception:
                    fail = "(gagal menyimpan)"
                print(f"{i:>2}. GAGAL {json.dumps(st, ensure_ascii=False)}\n    {str(e).splitlines()[0]}\n"
                      f"    layar saat gagal: {os.path.abspath(fail) if fail != '(gagal menyimpan)' else fail}")
                return False
        return True


def drive(project, steps, outdir=".", size=(1500, 900), apply=False):
    """Jalankan langkah. Tanpa apply=True, yang diubah hanyalah salinan sementara proyek."""
    project = os.path.abspath(project)
    work = project
    if not apply:
        work = os.path.join(os.path.dirname(project), f".drive-{os.getpid()}.box.json")
        shutil.copy(project, work)
    try:
        s = Session(work, size, outdir)
        try:
            ok = s.run(steps)
            if s.errors:
                print("galat di halaman:", *s.errors, sep="\n  ")
        finally:
            s.close()
    finally:
        if not apply and os.path.exists(work):
            os.remove(work)
    if not apply:
        print("(perubahan hanya di salinan sementara; tambahkan --apply untuk menyimpan ke proyek asli)")
    return ok and not s.errors
