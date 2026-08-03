"""Standalone frontend checker (no pytest needed).

Extracts every inline <script> from the HTML frontends and runs
`node --check` on it, then reports HTML tag-balance issues.

Usage:  python tests/check_frontend.py
"""

import html.parser
import os
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML_TARGETS = ["desktop/app.html", "desktop/control.html"]
JS_TARGETS = ["dist/server.js", "dist/tui.js"]


class _Balancer(html.parser.HTMLParser):
    VOID = {"br", "hr", "img", "input", "meta", "link", "source", "col"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.errors = []

    def handle_starttag(self, tag, attrs):
        if tag not in self.VOID:
            self.stack.append(tag)

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if not self.stack:
            self.errors.append("unexpected </%s>" % tag)
        elif self.stack[-1] != tag:
            self.errors.append("mismatch </%s> vs <%s>" % (tag, self.stack[-1]))
        else:
            self.stack.pop()


def main():
    node = shutil.which("node")
    if not node:
        print("SKIP: node not installed (JS syntax check disabled)")
        node = None
    failed = False
    for rel in HTML_TARGETS:
        path = os.path.join(ROOT, rel)
        src = open(path, encoding="utf-8").read()
        print("== %s" % rel)
        scripts = re.findall(r"<script>(.*?)</script>", src, re.S)
        if node:
            for i, js in enumerate(scripts):
                with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                                 encoding="utf-8") as fh:
                    fh.write(js)
                    tmp = fh.name
                try:
                    r = subprocess.run([node, "--check", tmp],
                                       capture_output=True, text=True)
                    ok = r.returncode == 0
                    print("   script[%d]: %s" % (i, "OK" if ok else "FAIL"))
                    if not ok:
                        failed = True
                        print("     " + r.stderr.strip().replace("\n", "\n     "))
                finally:
                    os.unlink(tmp)
        else:
            print("   %d script block(s) present (skipped check)" % len(scripts))
        bal = _Balancer()
        bal.feed(src)
        if bal.errors or bal.stack:
            failed = True
            print("   HTML structure errors: %s" % (bal.errors + bal.stack))
        else:
            print("   HTML structure: OK")
    for rel in JS_TARGETS:
        path = os.path.join(ROOT, rel)
        print("== %s" % rel)
        if node:
            r = subprocess.run([node, "--check", path], capture_output=True, text=True)
            ok = r.returncode == 0
            print("   %s" % ("OK" if ok else "FAIL"))
            if not ok:
                failed = True
                print("     " + r.stderr.strip().replace("\n", "\n     "))
        else:
            print("   (skipped check)")
    print()
    print("RESULT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
