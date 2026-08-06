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
CSS_TARGETS = ["desktop/_ambient.css"]  # + every inline <style> block
JS_TARGETS = []  # dist/server.js and dist/tui.js removed in v0.6.0 (dead code)


def check_css(text, name):
    """Report unterminated plain rule blocks and orphan declaration text.

    Recovers like a browser (pops the broken block) so each independent
    bug is reported once instead of cascading.
    """
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    stack = []  # ("plain"|"at", start_line)
    sel = ""
    errors = []
    for ln, line in enumerate(text.splitlines(), 1):
        i = 0
        while i < len(line):
            c = line[i]
            if c == "{":
                kind = "at" if sel.strip().startswith("@") else "plain"
                if stack and stack[-1][0] == "plain" and kind == "plain":
                    errors.append("%s:%d unterminated rule block" % (name, stack[-1][1]))
                    stack.pop()
                stack.append((kind, ln))
                sel = ""
            elif c == "}":
                if not stack:
                    errors.append("%s:%d stray close" % (name, ln))
                else:
                    stack.pop()
                sel = ""
            elif c == ";" and not stack:
                errors.append("%s:%d orphan declaration at top level" % (name, ln))
                sel = ""
            elif c not in " \t\r":
                sel += c
            i += 1
    for kind, ln in stack:
        errors.append("%s:%d unterminated block (%s)" % (name, ln, kind))
    return errors


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
        for i, css in enumerate(re.findall(r"<style>(.*?)</style>", src, re.S)):
            errs = check_css(css, "%s <style>[%d]" % (rel, i))
            if errs:
                failed = True
                for e in errs:
                    print("   " + e)
            else:
                print("   <style>[%d]: CSS brace balance OK" % i)
    for rel in CSS_TARGETS:
        path = os.path.join(ROOT, rel)
        print("== %s" % rel)
        errs = check_css(open(path, encoding="utf-8").read(), rel)
        if errs:
            failed = True
            for e in errs:
                print("   " + e)
        else:
            print("   CSS brace balance OK")
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
