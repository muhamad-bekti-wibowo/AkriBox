"""GUI lokal: server HTTP kecil (tanpa dependensi tambahan) + halaman three.js.

GUI dan CLI memakai file proyek yang sama. Bila file proyek diubah dari luar
(misalnya oleh LLM), GUI memuat ulang sendiri.
"""
from __future__ import annotations

import json
import mimetypes
import os
import socket
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from . import components, edits, generator, measure, trace
from .assembly import Assembly
from .export import export, panel_svg
from .project import Project, ProjectError
from .report import summarize

STATIC = os.path.join(os.path.dirname(__file__), "static")
mimetypes.add_type("text/javascript", ".js")
LOCK = threading.Lock()


HIST = {"undo": [], "redo": []}          # salinan teks file proyek, untuk urungkan / ulangi


def snapshot(path):
    with open(path, encoding="utf-8") as f:
        HIST["undo"].append(f.read())
    del HIST["undo"][:-80]
    HIST["redo"].clear()


def step_history(path, src, dst):
    if not HIST[src]:
        raise ProjectError("tidak ada yang bisa " + ("diurungkan" if src == "undo" else "diulangi"))
    with open(path, encoding="utf-8") as f:
        HIST[dst].append(f.read())
    with open(path, "w", encoding="utf-8") as f:
        f.write(HIST[src].pop())


_PC = {"key": None, "pr": None}


def cached_project(path):
    """Proyek hasil baca ulang hanya bila berkas berubah (magnet butuh geometri di tiap gerakan mouse)."""
    st = os.stat(path)
    key = (path, st.st_mtime_ns, st.st_size)
    if _PC["key"] != key:
        _PC["pr"], _PC["key"] = Project(path), key
    return _PC["pr"]


def panel_record(pr, p, asm=None):
    conf = pr.spec["panels"].get(p.id, {})
    return {"id": p.id, "name": p.name, "size": [round(v, 2) for v in p.size],
            "placed": pr.matrix(p.id) is not None, "placement": conf.get("placement"),
            "new": "new" in conf, "new_size": conf.get("new", {}).get("size"), "generated": p.generated,
            "bounds": [round(v, 3) for v in p.outline.bounds], "edges": conf.get("edges"), "outline_custom": bool(conf.get("outline")), "color": conf.get("color"),
            "eff_placement": conf.get("placement") or getattr(pr, "_gen_place", {}).get(p.id),
            "tabs": len(p.tabs), "cuts": len(p.cuts()),
            "svg": panel_svg(p, pr.thickness), "items": measure.panel_items(p, pr.thickness),
            "measure": measure.panel_measure(p)}


def build_state(path):
    pr = Project(path)
    asm = Assembly(pr)
    rep = asm.report()
    panels = [panel_record(pr, p) for p in pr.panels]
    cols = [{"v": np.round(m.vertices, 3).ravel().tolist(), "f": m.faces.ravel().tolist()}
            for m in asm.collision_meshes]
    return {"project": os.path.basename(pr.path), "source": pr.spec.get("source") or "(proyek baru, tanpa gambar sumber)",
            "generator": pr.spec.get("generator"), "removed": removed_list(pr),
            "thickness": pr.thickness, "kerf": pr.kerf, "mtime": os.path.getmtime(pr.path),
            "panels": panels, "scene": asm.scene(), "collisions": cols,
            "report": {"ok": rep["ok"], "errors": rep["errors"], "tight": rep["tight"],
                       "warnings": rep["warnings"], "size_body": rep.get("size_body"),
                       "size_with_tabs": rep.get("size_with_tabs")},
            "summary": summarize(pr, rep)}


def removed_list(pr):
    return [{"id": pid, "name": c.get("name", "")} for pid, c in pr.spec["panels"].items() if c.get("removed")]


def quick_state(path, extra=None):
    """Jawaban cepat setelah penyuntingan 2D: hanya data panel (rakitan 3D dihitung terpisah)."""
    pr = Project(path)
    out = {"panels": [panel_record(pr, p) for p in pr.panels], "mtime": os.path.getmtime(pr.path),
           "removed": removed_list(pr)}
    out.update(extra or {})
    return out


def apply_changes(path, body):
    pr = Project(path)
    if "thickness" in body:
        pr.spec["thickness"] = float(body["thickness"])
    if "kerf" in body:
        pr.spec["kerf"] = float(body["kerf"])
    for pid, ch in body.get("panels", {}).items():
        if pr.panel(pid) is None:
            raise ProjectError(f"panel tidak dikenal: {pid}")
        conf = pr.spec["panels"].setdefault(pid, {})
        if "name" in ch:
            conf["name"] = str(ch["name"])
        if "color" in ch:                       # warna panel di tampilan 3D (#rrggbb); None = warna bawaan
            c = ch["color"]
            if c is None:
                conf.pop("color", None)
            else:
                import re
                if not re.fullmatch(r"#[0-9a-fA-F]{6}", str(c)):
                    raise ProjectError("warna harus berbentuk #rrggbb, mis. #ff8800")
                conf["color"] = str(c).lower()
        if "placement" in ch:
            if ch["placement"] is None:
                conf.pop("placement", None)
            else:
                conf["placement"] = ch["placement"]
    for p in pr.panels:          # validasi sebelum disimpan
        pr.matrix(p.id)
    if pr.thickness <= 0 or pr.kerf < 0:
        raise ProjectError("tebal harus > 0 dan kerf >= 0")
    snapshot(path)
    pr.save()


class _Server(ThreadingHTTPServer):
    """Menolak port yang sudah dipakai proses lain. Di Windows SO_REUSEADDR membolehkan dua server
    memegang port yang sama sehingga permintaan bisa jatuh ke server lama yang berkode usang."""
    allow_reuse_address = False

    def server_bind(self):
        if os.name == "nt" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _code_stamp():
    """Penanda versi kode di disk; dibandingkan dengan yang dimuat server untuk mendeteksi server usang."""
    root = os.path.dirname(__file__)
    files = [os.path.join(root, f) for f in os.listdir(root) if f.endswith(".py")] + [os.path.join(STATIC, "index.html")]
    return max(os.path.getmtime(f) for f in files)


CODE_AT_START = _code_stamp()


class Handler(BaseHTTPRequestHandler):
    project_path = ""

    def log_message(self, *a):
        pass

    def _send(self, code, data, ctype="application/json"):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype + ("; charset=utf-8" if ctype.startswith(("text", "application/j")) else ""))
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _guard(self, fn):
        try:
            with LOCK:
                self._send(200, fn())
        except (ProjectError, ValueError, KeyError, json.JSONDecodeError) as e:
            self._send(400, {"error": str(e)})
        except Exception as e:      # tampilkan di GUI, jangan matikan server
            self._send(500, {"error": f"{type(e).__name__}: {e}"})

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if path == "/api/ping":
            return self._send(200, {"pid": os.getpid(), "stale": _code_stamp() > CODE_AT_START + 1,
                                    "project": os.path.basename(self.project_path)})
        if path == "/api/components":
            return self._send(200, components.catalog())
        if path == "/api/state":
            return self._guard(lambda: build_state(self.project_path))
        if path == "/api/mtime":
            return self._send(200, {"mtime": os.path.getmtime(self.project_path)})
        rel = "index.html" if path == "/" else path.lstrip("/").removeprefix("static/")
        full = os.path.normpath(os.path.join(STATIC, rel))
        if not full.startswith(STATIC) or not os.path.isfile(full):
            return self._send(404, {"error": "tidak ditemukan"})
        with open(full, "rb") as f:
            self._send(200, f.read(), mimetypes.guess_type(full)[0] or "application/octet-stream")

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b"{}"
        if self.path == "/api/spec":
            def run():
                apply_changes(self.project_path, json.loads(raw))
                return build_state(self.project_path)
            return self._guard(run)
        if self.path == "/api/edit":
            def run():
                body = json.loads(raw)
                pr = Project(self.project_path)
                snapshot(self.project_path)
                try:
                    res = edits.apply_ops(pr, body["ops"])
                    for p in pr.panels:
                        pr.matrix(p.id)
                    pr.save()
                except Exception:
                    HIST["undo"].pop()
                    raise
                return quick_state(self.project_path, {"results": res})
            return self._guard(run)
        if self.path in ("/api/undo", "/api/redo"):
            def run():
                a, b = ("undo", "redo") if self.path.endswith("undo") else ("redo", "undo")
                step_history(self.project_path, a, b)
                return build_state(self.project_path)
            return self._guard(run)
        if self.path == "/api/generator":
            def run():
                body = json.loads(raw)
                pr = Project(self.project_path)
                snapshot(self.project_path)
                try:
                    if body.get("remove"):
                        pr.spec.pop("generator", None)
                    else:
                        g = pr.spec.get("generator") or generator.default_generator()
                        inner = body.get("inner", g["inner"])
                        g["inner"] = [int(round(float(v))) for v in inner]
                        if "tab" in body:
                            g["tab"] = int(round(float(body["tab"])))
                        if "top" in body:
                            g["top"] = bool(body["top"])
                        if "joints" in body:
                            g["joints"] = body["joints"]
                        pr.spec["generator"] = g
                        if body.get("thickness"):
                            pr.spec["thickness"] = float(body["thickness"])
                    pr.reload()
                    pr.save()
                except Exception:
                    HIST["undo"].pop()
                    raise
                return build_state(self.project_path)
            return self._guard(run)
        if self.path == "/api/measure":            # murni hitungan: tanpa kunci agar tetap cepat saat proyek dihitung
            try:
                body = json.loads(raw)
                need = body.get("what") == "divide" or (body.get("magnet") and body.get("panel"))
                proj = cached_project(self.project_path) if need else None
                return self._send(200, measure.run(body, proj))
            except Exception as e:
                return self._send(400, {"error": str(e)})
        if self.path == "/api/trace":
            body = json.loads(raw)
            return self._guard(lambda: trace.trace(body["image"], body.get("params", {})))
        if self.path == "/api/trace/apply":
            def run():
                body = json.loads(raw)
                res = trace.trace(body["image"], body.get("params", {}))
                pr = Project(self.project_path)
                snapshot(self.project_path)
                try:
                    at = body.get("at")
                    out = trace.apply_trace(pr, res, body.get("mode", "cut"), body.get("target"),
                                            at, body.get("anchor", "center"), body.get("role", "cut"),
                                            bool(body.get("largest")), body.get("name", ""))
                    pr.save()
                except Exception:
                    HIST["undo"].pop()
                    raise
                return quick_state(self.project_path, {"applied": out, "warnings": res["warnings"]})
            return self._guard(run)
        if self.path == "/api/export":
            def run():
                pr = Project(self.project_path)
                out = os.path.join(pr.dir, "hasil")
                return {"files": export(pr, out), "dir": out}
            return self._guard(run)
        self._send(404, {"error": "tidak ditemukan"})


def start_background(project_path, port=0):
    """Jalankan server di thread latar (port bebas bila 0). Hasil: (server, url)."""
    Project(project_path)
    Handler.project_path = os.path.abspath(project_path)
    srv = _Server(("127.0.0.1", port), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/"


def serve(project_path, port=8765, open_browser=True):
    Project(project_path)                 # gagal lebih awal bila proyek rusak
    Handler.project_path = os.path.abspath(project_path)
    try:
        srv = _Server(("127.0.0.1", port), Handler)
    except OSError as e:
        raise ProjectError(f"port {port} sudah dipakai proses lain (mungkin server lama yang belum ditutup): {e}\n"
                           f"Tutup server itu (Ctrl+C di terminalnya) atau pakai port lain: box gui ... --port {port + 1}")
    url = f"http://127.0.0.1:{port}/"
    print(f"GUI berjalan di {url}  (Ctrl+C untuk berhenti)")
    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nberhenti")
