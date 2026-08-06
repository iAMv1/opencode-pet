"""Web mode, control-app launcher, and the pywebview-independent HTTP bridge.

`python desktop/main.py --web [--pet-dir DIR] [--port N]` serves the REAL
app.html over localhost HTTP with a fetch-based bridge that maps
window.pywebview.api.* onto the REAL ControlApi. This is both a feature
(view the dashboard in any browser, e.g. Ctrl+Alt+D with pywebview
unavailable) and the real end-to-end path the test suite drives: same UI,
same backend, same data files — no mock anywhere.
"""

import json
import os
import subprocess
import sys
import threading
import urllib.parse

from . import api, sprites, store

_FALLBACK_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #16161f; color: #e6e6e6;
         padding: 18px; display: grid; place-items: center; height: 100vh; margin: 0; text-align: center; }
</style></head><body><p>OpenCode Pet — control UI missing.<br><small>Reinstall or rebuild the app.</small></p></body></html>"""

WEB_MAX_BODY = 1 << 20  # 1 MB RPC cap — a local process must not OOM the server

# Static assets _file may hand out (P10): anything else is rejected outright.
_FILE_EXT_WHITELIST = (".html", ".css", ".js", ".png", ".webp", ".json")


def _file(name):
    """Bundled non-sprite asset (app.html/control.html). MEIPASS first, then
    source tree.

    P10 hardening: path-traversal guard + extension whitelist. The name is
    URL-decoded (a raw %2e%2e would otherwise be a literal filename), then
    normalized and required to resolve INSIDE the served directory — ../,
    encoded dots, absolute and drive-relative paths are all rejected.
    """
    ext = os.path.splitext(str(name or ""))[1].lower()
    if ext not in _FILE_EXT_WHITELIST:
        return None
    try:
        name = urllib.parse.unquote(name)
    except Exception:
        return None
    if os.path.isabs(name):
        return None

    def inside(base, p):
        try:
            return os.path.commonpath([os.path.abspath(base), os.path.abspath(p)]) \
                == os.path.abspath(base)
        except (ValueError, OSError):
            return False

    if getattr(sys, "_MEIPASS", None):
        for sub in ("", "desktop/"):
            p = os.path.normpath(os.path.join(sys._MEIPASS, sub, name))
            if inside(sys._MEIPASS, p) and os.path.exists(p):
                return p
    base = os.path.dirname(os.path.abspath(__file__))
    p = os.path.normpath(os.path.join(base, name))
    if not inside(base, p):
        return None
    return p if os.path.exists(p) else None


def load_control_html():
    for name in ("app.html", "control.html"):
        p = _file(name)
        if p:
            try:
                with open(p, encoding="utf-8") as fh:
                    return fh.read()
            except Exception:
                pass
    return _FALLBACK_HTML


_WEB_SHIM = """<script>
/* --- real fetch bridge for window.pywebview.api (injected by --web mode) --- */
(function () {
  var METHODS = %(methods)s;
  function rpc(method) {
    return function () {
      var args = Array.prototype.slice.call(arguments);
      return fetch("/rpc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ method: method, args: args })
      }).then(function (r) { return r.json(); }).then(function (resp) {
        if (resp && resp.ok) return resp.result;
        throw new Error(resp && resp.error || ("rpc " + method + " failed"));
      });
    };
  }
  var api = {};
  METHODS.forEach(function (m) { api[m] = rpc(m); });
  window.pywebview = { api: api };
})();
</script>
""" % {"methods": json.dumps(api._WEB_METHODS)}


def _apply_pet_dir(path):
    """Point all data-file globals at `path` (used by --web --pet-dir so a
    browser session can run against a throwaway or portable data dir)."""
    store.PET_DIR = os.path.abspath(path)
    store.CONFIG_FILE = os.path.join(store.PET_DIR, "config.json")
    store.WELLBEING_FILE = os.path.join(store.PET_DIR, "wellbeing.json")
    store.FOCUS_FILE = os.path.join(store.PET_DIR, "focus.json")
    os.makedirs(store.PET_DIR, exist_ok=True)


def run_web(host="127.0.0.1", port=0, pet_dir=None, extra_tail=None):
    """Serve the real dashboard over HTTP. Blocks forever (Ctrl+C to stop).

    extra_tail: optional HTML/script string appended before </body> — used by
    the test suite to attach the UI self-test harness to the REAL page.
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import urllib.parse

    if pet_dir:
        _apply_pet_dir(pet_dir)
    api_ctl = api.ControlApi()
    html = load_control_html()
    if not html or html == _FALLBACK_HTML:
        raise RuntimeError("app.html not found next to main.py — cannot run --web")
    marker = "<script>"
    idx = html.find(marker)
    if idx < 0:
        raise RuntimeError("app.html has no <script> to bridge into")
    page = html[:idx] + _WEB_SHIM + html[idx:]
    if extra_tail and "</body>" in page:
        page = page.replace("</body>", extra_tail + "</body>", 1)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass  # keep the console clean (the port line is the contract)

        def _json(self, code, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urllib.parse.urlparse(self.path).path in ("/", "/index.html"):
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            if urllib.parse.urlparse(self.path).path != "/rpc":
                self._json(404, {"ok": False, "error": "not found"})
                return
            # Explicit CSRF + DNS-rebinding guards: only same-origin JSON-RPC
            # is accepted. A cross-site page can't set Content-Type
            # application/json (browser forbids it without CORS preflight,
            # which we never answer), and a text/plain form POST is rejected
            # instead of being parsed by accident. The Host check blocks
            # DNS rebinding: an attacker-controlled domain resolving to
            # 127.0.0.1 still sends its own Host header.
            ctype = self.headers.get("Content-Type", "")
            host = self.headers.get("Host", "") or ""
            ok_host = host.startswith("127.0.0.1:") or host.startswith("localhost:")
            if not ctype.startswith("application/json") or not ok_host:
                self._json(415, {"ok": False, "error": "unsupported request"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > WEB_MAX_BODY:
                    self._json(413, {"ok": False, "error": "body too large"})
                    return
                req = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                method = req.get("method")
                args = req.get("args") or []
                if method not in api._WEB_METHODS:
                    self._json(400, {"ok": False, "error": "unknown method %r" % method})
                    return
                if method in api._WEB_NOP:
                    result = True
                elif method == "quit":
                    # Real quit semantics minus process death: write the one-shot
                    # command the pet process reads, keep the tab/server alive.
                    api_ctl._cmd("quit")
                    result = True
                else:
                    fn = getattr(api_ctl, method)
                    result = fn(*args)
                self._json(200, {"ok": True, "result": result})
            except Exception as exc:  # noqa: BLE001 — surface to the browser
                self._json(500, {"ok": False, "error": str(exc)})

    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError:
        raise SystemExit("--web: cannot bind %s:%d (port in use?)" % (host, port))
    actual = server.server_address[1]
    print("OPENCODE_PET_WEB_PORT=%d" % actual, flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


def spawn_control():
    if getattr(sys, "frozen", False):
        subprocess.Popen([sys.executable, "--control"],
                         creationflags=0x00000008 | 0x00000200)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        subprocess.Popen([sys.executable, os.path.join(here, "main.py"), "--control"],
                         creationflags=0x00000008 | 0x00000200)


def run_control():
    """Control app in its own process — no pet, no GDI, no single-instance mutex."""
    import webview  # noqa: F401 — lazy; the pet process never imports a browser
    # Pre-warm sprite strips while WebView2 spins up (first call is ~0.8s).
    threading.Thread(target=sprites.build_previews, daemon=True).start()
    control_api = api.ControlApi()
    win = webview.create_window(
        "OpenCode Pet", html=load_control_html(),
        js_api=control_api, width=980, height=680, min_size=(860, 600),
        resizable=True, frameless=False)
    control_api.bind_window(win)
    webview.start(private_mode=False)
