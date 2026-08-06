"""Contract tests between the HTML frontends and the Python ControlApi.

These guard the integration seam: if a UI calls api.foo() but ControlApi has no
foo, or an inline script has a syntax error, the control window silently breaks.
"""

import html.parser
import os
import re
import shutil
import subprocess

import pytest

main = pytest.importorskip("desktop.main")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

ALL_METHODS = {
    "get_config", "get_previews", "get_sessions", "get_logs",    "get_wellbeing",
    "get_wellbeing_history", "get_wellbeing_insights",
    "get_focus_state", "start_focus", "stop_focus", "set_focus_tag", "get_pet_profile",
    "get_goal_state", "get_pomo_state", "get_weekly_wrapped", "get_week_apps",
    "get_focus_peaks", "get_memory_state",
    "next_pet", "prev_pet", "save_config", "hide_pet", "show_pet",
    "hide_control", "quit",
}


def inline_scripts(path):
    src = open(path, encoding="utf-8").read()
    return re.findall(r"<script>(.*?)</script>", src, re.S)


def api_calls(src):
    return set(re.findall(r"api\.([a-zA-Z_][a-zA-Z0-9_]*)", src))


class _TagBalancer(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []
        self.void = {"br", "hr", "img", "input", "meta", "link", "source", "col"}

    def handle_starttag(self, tag, attrs):
        if tag not in self.void:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.void:
            return
        if not self.stack:
            self.errors.append("unexpected </%s>" % tag)
            return
        if self.stack[-1] != tag:
            self.errors.append("mismatch </%s> vs <%s>" % (tag, self.stack[-1]))
            return
        self.stack.pop()


@pytest.mark.parametrize("rel", ["desktop/app.html", "desktop/control.html"])
def test_html_api_contract(rel):
    path = os.path.join(ROOT, rel)
    src = open(path, encoding="utf-8").read()
    calls = api_calls(src)
    unknown = calls - ALL_METHODS
    assert not unknown, "%s calls unknown ControlApi methods: %s" % (rel, sorted(unknown))


@pytest.mark.parametrize("rel", ["desktop/app.html", "desktop/control.html"])
def test_inline_js_parses_with_node(rel):
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    path = os.path.join(ROOT, rel)
    scripts = inline_scripts(path)
    assert scripts, "%s has no inline scripts" % rel
    for i, js in enumerate(scripts):
        p = os.path.join(ROOT, ".tmp-%s-%d.js" % (rel.replace("/", "_"), i))
        try:
            with open(p, "w", encoding="utf-8") as fh:
                fh.write(js)
            r = subprocess.run([node, "--check", p], capture_output=True, text=True)
            assert r.returncode == 0, "%s script %d: %s %s" % (rel, i, r.stdout, r.stderr)
        finally:
            if os.path.exists(p):
                os.unlink(p)


@pytest.mark.parametrize("rel", ["desktop/app.html", "desktop/control.html"])
def test_html_well_formed(rel):
    path = os.path.join(ROOT, rel)
    parser = _TagBalancer()
    parser.feed(open(path, encoding="utf-8").read())
    assert not parser.errors, "%s: %s" % (rel, parser.errors)
    assert not parser.stack, "%s: unclosed tags %s" % (rel, parser.stack)


def test_control_api_methods_exist():
    impl = {m for m in dir(main.ControlApi) if not m.startswith("_")}
    assert ALL_METHODS <= impl, "ControlApi missing: %s" % (ALL_METHODS - impl)


def test_web_bridge_method_list_in_sync():
    """The --web RPC bridge must expose exactly the same methods the desktop
    window exposes, so a browser session and the pywebview window are
    interchangeable — no drift between the two UIs."""
    web = set(main._WEB_METHODS)
    assert web == ALL_METHODS, (
        "web bridge %s != desktop API %s" % (sorted(web - ALL_METHODS),
                                             sorted(ALL_METHODS - web)))
    assert main._WEB_NOP <= ALL_METHODS
    # hide_control is a browser no-op; quit is handled specially (writes the
    # one-shot command but never exits the server) and must NOT be a bare no-op
    assert main._WEB_NOP == {"hide_control"}
    assert "quit" in main._WEB_METHODS and "quit" not in main._WEB_NOP


def test_html_escapes_user_content():
    """Any spot rendering session data must escape HTML (XSS guard).

    Catches raw `+ s.title +`-style interpolation in the JS template strings:
    every user-data var must be wrapped in esc() (i.e. not directly followed
    by a `+` inside a string concat). esc(s.title) contains `)` between the
    var and the closing `+`, so it can't false-positive.
    """
    path = os.path.join(ROOT, "desktop", "app.html")
    src = open(path, encoding="utf-8").read()
    vars_ = ("s.title", "s.cwd", "s.sessionID", "s.toolLabel", "s.toolArgs",
             "s.message", "e.tool", "e.app", "e.state", "w.app",
             "w.bestDay.date", "w.topApp.app", "fs.app", "p.mood")
    for var in vars_:
        # not preceded by ( (inside esc()) and not a longer identifier
        assert re.search(r"(?<![(\w])%s\s*\+" % re.escape(var), src) is None, (
            "user-data field %s interpolated into HTML without esc() in app.html" % var
        )
    # sanity: the escaping helper is actually used on session data
    assert "esc(s.toolLabel)" in src and "esc(title)" in src
