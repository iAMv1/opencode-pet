"""Run the full OpenCode Pet validation suite in one shot.

Usage:  python tests/run_all.py

Runs:
  1. pytest (engine state machine, config/status, ControlApi, spec contracts)
  2. frontend JS syntax + HTML structure check
  3. headless Chrome UI self-test of the dashboard (if Chrome is available)

Exit code 0 = everything passed.
"""

import os
import shutil
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")


def run(cmd, cwd=ROOT):
    print("\n$ " + " ".join(cmd))
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    out = (r.stdout + r.stderr).strip()
    if out:
        print(out[-3000:])
    if r.returncode != 0:
        print(">>> FAILED: %s (exit %d)" % (cmd[0], r.returncode))
    return r.returncode == 0


def main():
    ok = True

    ok &= run([sys.executable, "-m", "pytest", "tests/", "-q", "--no-header"])

    ok &= run(["python", "tests/check_frontend.py"])

    # Regenerate the mock UI fixture from the CURRENT app.html, then run the
    # headless Chrome self-test if a browser is available. make_mock_page.py
    # MUST run first: make_ui_selftest.py consumes app-mock.html, and a stale
    # fixture would silently test the previous frontend.
    if (run([sys.executable, "tests/make_mock_page.py"])
            and run([sys.executable, "tests/make_ui_selftest.py"])):
        chrome = None
        for p in (os.path.expanduser("~\\AppData\\Local\\Google\\Chrome\\Application\\chrome.exe"),
                  "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe",
                  "C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe"):
            if os.path.exists(p):
                chrome = p
                break
        if chrome:
            fixture = "file:///" + os.path.join(FIXTURES, "ui-selftest.html").replace("\\", "/")
            profile = os.path.join(FIXTURES, "_chrome_profile")
            r = subprocess.run(
                [chrome, "--headless=new", "--disable-gpu", "--no-first-run",
                 "--user-data-dir=" + profile,
                  "--virtual-time-budget=15000", "--dump-dom", fixture],
                 capture_output=True, text=True, encoding="utf-8", errors="replace")
            import re
            m = re.search(r"TOTAL (\d+)/(\d+)", r.stdout)
            if m:
                passed, total = int(m.group(1)), int(m.group(2))
                print("UI self-test: %d/%d checks passed" % (passed, total))
                ok &= (passed == total)
            else:
                print("UI self-test: no results in dump")
                ok = False
            shutil.rmtree(profile, ignore_errors=True)  # don't pollute the repo
        else:
            print("UI self-test: skipped (no Chrome found)")

    # REAL-bridge browser test: headless Chrome against the actual desktop
    # server (real app.html + real ControlApi + real data files, no mocks).
    ok &= run([sys.executable, "tests/make_real_selftest.py"])

    print("\n" + ("ALL VALIDATION PASSED" if ok else "VALIDATION FAILURES REMAIN"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
