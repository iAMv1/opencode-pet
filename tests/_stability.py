"""Run the full validation suite twice to shake out flakiness."""
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for i in range(1, 3):
    r = subprocess.run([sys.executable, os.path.join("tests", "run_all.py")],
                       capture_output=True, text=True, cwd=ROOT)
    out = (r.stdout + r.stderr)
    for line in out.splitlines():
        if ("passed" in line or "failed" in line or "self-test" in line
                or "ALL VALIDATION" in line or "VALIDATION FAILURES" in line
                or "FAILED" in line):
            print("run %d: %s" % (i, line.strip()))
