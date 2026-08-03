"""Generate a browser-test fixture: desktop/app.html with a mock pywebview
bridge injected, so browser automation can exercise the REAL dashboard code
paths (sessions feed, filters, expandable rows, wellbeing) with realistic data.

Usage:  python tests/make_mock_page.py   ->  tests/fixtures/app-mock.html

The fixture is a build artifact of the real page and should be regenerated
whenever app.html changes (the validation loop does this before browser tests).
"""

import os
import re
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "desktop", "app.html")
OUT_DIR = os.path.join(ROOT, "tests", "fixtures")
OUT = os.path.join(OUT_DIR, "app-mock.html")

MOCK = r"""<script>
/* --- test-only mock pywebview bridge (injected by tests/make_mock_page.py) --- */
(function () {
  var now = Date.now();
  var SESSIONS = [
    { sessionID: "sess-1", state: "busy", title: "Refactor engine", toolLabel: "edit main.py (12 chars)", message: "Rewriting the state machine", direction: "right", cwd: "C:\\proj\\opencode-pet", updatedAt: now - 4000 },
    { sessionID: "sess-2", state: "thinking", title: "Debug watcher thread", toolLabel: "", message: "Thread is deadlocking on", direction: "left", cwd: "C:\\proj\\watcher", updatedAt: now - 12000 },
    { sessionID: "sess-3", state: "error", title: "Sprite pipeline", toolLabel: "bash", message: "Something went wrong", direction: "right", cwd: "C:\\proj\\sprites", updatedAt: now - 25000 },
    { sessionID: "sess-4", state: "celebrating", title: "UI polish", toolLabel: "", message: "Done!", direction: "left", cwd: "C:\\proj\\ui", updatedAt: now - 3000 },
    { sessionID: "sess-5", state: "idle", title: "Docs", toolLabel: "", message: "", direction: "left", cwd: "C:\\proj\\docs", updatedAt: now - 60000 }
  ];
  var ACTIVITY = [
    { t: (now / 1000) - 5, kind: "state", state: "busy" },
    { t: (now / 1000) - 20, kind: "tool", tool: "edit main.py" },
    { t: (now / 1000) - 40, kind: "state", state: "thinking" },
    { t: (now / 1000) - 90, kind: "active", app: "VS Code" },
    { t: (now / 1000) - 120, kind: "poke" },
    { t: (now / 1000) - 180, kind: "break", mins: 52 },
    { t: (now / 1000) - 300, kind: "levelUp", level: 7 },
    { t: (now / 1000) - 800, kind: "focusDone", minutes: 25 },
    { t: (now / 1000) - 2000, kind: "state", state: "success" }
  ];
  var WELLBEING = [
    { app: "VS Code", seconds: 7200 },
    { app: "Terminal", seconds: 3600 },
    { app: "Chrome", seconds: 900 },
    { app: "Explorer", seconds: 300 }
  ];
  window.pywebview = {
    api: {
      get_config: function () {
        return Promise.resolve({
          petIdx: 1, walk: 70, alwaysOnTop: true, petVisible: true, breakMin: 50,
          pets: ["Pikachu", "Charmander", "Doraemon", "Gardevoir", "Giratina", "LPC Cat"],
          petName: "Charmander", state: "busy"
        });
      },
      get_previews: function () {
        return Promise.resolve([
          { id: "capvolt", name: "Pikachu", strip: null, frames: 6, durationMs: 1100, frameW: 80, frameH: 80 },
          { id: "charmander", name: "Charmander", strip: null, frames: 6, durationMs: 1100, frameW: 80, frameH: 80 },
          { id: "doraemon", name: "Doraemon", strip: null, frames: 6, durationMs: 1100, frameW: 80, frameH: 80 },
          { id: "gardevoir", name: "Gardevoir", strip: null, frames: 6, durationMs: 1100, frameW: 80, frameH: 80 },
          { id: "giratina", name: "Giratina", strip: null, frames: 6, durationMs: 1100, frameW: 80, frameH: 80 },
          { id: "lpc-cat", name: "LPC Cat", strip: null, frames: 8, durationMs: 1100, frameW: 80, frameH: 80 }
        ]);
      },
      get_sessions: function () {
        window.__calls = window.__calls || [];
        window.__calls.push("get_sessions");
        return Promise.resolve(SESSIONS.slice());
      },
      get_logs: function () { return Promise.resolve(ACTIVITY.slice()); },
      get_wellbeing: function () { return Promise.resolve(WELLBEING.slice()); },
      get_wellbeing_history: function (days) {
        var today = new Date();
        function ld(d) {
          return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" +
            String(d.getDate()).padStart(2, "0");
        }
        var n = days || 7;
        var week = [7200, 5400, 3600, 8100, 0, 4500, 3600];
        var out = [];
        for (var i = n - 1; i >= 0; i--) {
          var secs = week[(n - 1 - i) % 7];
          if (n > 7) secs = (i * 137 + 900) % 7200; // synthetic 30-day trail
          var d = new Date(today.getTime() - i * 86400000);
          out.push({ date: ld(d), seconds: secs });
        }
        return Promise.resolve(out);
      },
      get_wellbeing_insights: function () {
        var today = new Date();
        function ld(d) {
          return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" +
            String(d.getDate()).padStart(2, "0");
        }
        return Promise.resolve({
          weekSeconds: 32400, prevWeekSeconds: 25200, deltaPct: 29,
          bestDay: { date: ld(new Date(today.getTime() - 3 * 86400000)), seconds: 8100 },
          todaySeconds: 3600, topApp: { app: "VS Code", seconds: 7200 }
        });
      },
      get_focus_state: function () {
        var fs = window.__focusState || { active: false, startedAt: 0, targetMin: 25, wilted: false, app: "", progress: 0 };
        if (fs.active) fs.progress = Math.min(1, (Date.now() - fs.startedAt) / (fs.targetMin * 60000));
        return Promise.resolve(JSON.parse(JSON.stringify(fs)));
      },
      start_focus: function (m) {
        window.__calls = window.__calls || [];
        window.__calls.push("start_focus:" + (m || 25));
        window.__focusState = { active: true, startedAt: Date.now(), targetMin: m || 25, wilted: false, app: "VS Code", progress: 0 };
        return Promise.resolve(true);
      },
      stop_focus: function () {
        window.__calls = window.__calls || [];
        window.__calls.push("stop_focus");
        window.__focusState = { active: false, startedAt: 0, targetMin: 25, wilted: false, app: "", progress: 0 };
        return Promise.resolve(true);
      },
      get_pet_profile: function () {
        return Promise.resolve({ level: 7, xp: 64, xpNext: 400, xpPct: 0.16, mood: "happy", streak: 4 });
      },
      get_weekly_wrapped: function () {
        return Promise.resolve({
          days: 7, weekSeconds: 32400, prevWeekSeconds: 25200,
          bestDay: { date: "2026-07-30", seconds: 8100 },
          topApp: { app: "VS Code", seconds: 11700 }, streak: 4, xp: 640,
          focusSessions: 9, level: 7
        });
      },
      get_week_apps: function () {
        return Promise.resolve([
          { app: "VS Code", seconds: 11700 },
          { app: "Terminal", seconds: 8100 },
          { app: "Chrome", seconds: 4500 }
        ]);
      },
      get_focus_peaks: function (days) {
        // hours: 24 buckets; 10 AM is the clear peak, 2 PM runner-up
        var hours = [];
        var vals = [0, 0, 0, 0, 0, 0, 0, 0, 0, 600, 5400, 4200, 1800, 0, 3600, 2400, 1200, 0, 0, 0, 0, 0, 0, 0];
        for (var h = 0; h < 24; h++) hours.push({ hour: h, seconds: vals[h] });
        return Promise.resolve({
          hours: hours,
          best: { hour: 10, label: "10 AM", pct: 27, seconds: 5400 },
          runnerUp: { hour: 11, label: "11 AM", pct: 21, seconds: 4200 },
          spanLabel: (days || 7) + " days"
        });
      },
      save_config: function (c) {
        window.__saved = c;
        window.__calls = window.__calls || [];
        window.__calls.push("save_config");
        return Promise.resolve(true);
      },
      hide_pet: function () { return Promise.resolve(true); },
      show_pet: function () { return Promise.resolve(true); },
      hide_control: function () {
        window.__calls = window.__calls || [];
        window.__calls.push("hide_control");
        return Promise.resolve(true);
      },
      quit: function () { return Promise.resolve(true); },
      next_pet: function () {
        window.__calls = window.__calls || [];
        window.__calls.push("next_pet");
        return Promise.resolve(true);
      },
      prev_pet: function () {
        window.__calls = window.__calls || [];
        window.__calls.push("prev_pet");
        return Promise.resolve(true);
      }
    }
  };
})();
</script>
"""


def main():
    src = open(SRC, encoding="utf-8").read()
    assert "window.pywebview" not in src.split("<script>")[0], "unexpected"
    # inject the mock right before the first inline <script> so it runs first
    marker = "<script>"
    idx = src.index(marker)
    fixture = src[:idx] + MOCK + src[idx:]
    os.makedirs(OUT_DIR, exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(fixture)
    print("wrote %s (%d bytes, from %s @ %s)"
          % (OUT, os.path.getsize(OUT), os.path.basename(SRC),
             time.strftime("%H:%M:%S")))


if __name__ == "__main__":
    main()
