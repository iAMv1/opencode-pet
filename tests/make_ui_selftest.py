"""Generate a headless self-test page for the dashboard UI.

Builds tests/fixtures/ui-selftest.html = app-mock.html + an appended assertion
script that exercises the interactive behaviors (filter chips, expandable rows,
pets view, keyboard nav, rail actions) and writes PASS/FAIL lines into a
<pre id="selftest"> element. Run it with headless Chrome and grep the dump:

  python tests/make_ui_selftest.py
  chrome --headless=new --disable-gpu --virtual-time-budget=15000 --dump-dom \
         file:///.../tests/fixtures/ui-selftest.html | grep -A 40 'selftest'
"""

import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIXTURES = os.path.join(ROOT, "tests", "fixtures")
MOCK = os.path.join(FIXTURES, "app-mock.html")
OUT = os.path.join(FIXTURES, "ui-selftest.html")

SELFTEST = r"""<script>
/* --- UI self-test (injected; run inside headless Chrome) --- */
(function () {
  "use strict";
  var results = [];
  var pageErrors = [];
  window.addEventListener("error", function (e) {
    pageErrors.push((e.message || "?") + " @ " + (e.filename || ""));
  });
  window.addEventListener("unhandledrejection", function (e) {
    pageErrors.push("unhandled rejection: " + (e.reason && e.reason.message || e.reason));
  });
  function check(name, cond, extra) {
    results.push((cond ? "PASS" : "FAIL") + "  " + name + (extra ? "  [" + extra + "]" : ""));
  }
  function has(q) { return document.querySelectorAll(q).length; }
  function text(q) { var el = document.querySelector(q); return el ? el.textContent.trim() : ""; }
  function click(q) {
    var el = document.querySelector(q);
    if (!el) return false;
    el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true }));
    return true;
  }
  function done() {
    var pre = document.createElement("pre");
    pre.id = "selftest";
    pre.textContent = results.join("\n") + "\nTOTAL " +
      results.filter(function (r) { return r.indexOf("PASS") === 0; }).length +
      "/" + results.length;
    document.body.appendChild(pre);
    document.title = "SELFTEST-DONE";
  }

  var tries = 0;
  var iv = setInterval(function () {
    tries++;
    if ((has("#sessions .ses") === 5 && has("#wbHistory .wk-bar") >= 1) || tries > 100) {
      clearInterval(iv);
      run();
    }
  }, 50);

  function run() {
    // 1. stats + live count
    check("stats: working=1", text("#stBusy") === "1", text("#stBusy"));
    check("stats: thinking=1", text("#stThink") === "1", text("#stThink"));
    check("stats: sessions=5", text("#stTotal") === "5", text("#stTotal"));
    check("live badge 2 active", text("#liveCount").indexOf("2 active") === 0, text("#liveCount"));

    // 2. filter chips
    click('#filters .fbtn[aria-label^="Errors"]');
    check("filter Errors -> 1 row", has("#sessions .ses") === 1, String(has("#sessions .ses")));
    check("filter Errors -> Sprite pipeline",
      text("#sessions .ses-title").indexOf("Sprite pipeline") === 0,
      text("#sessions .ses-title"));
    click('#filters .fbtn[aria-label^="All"]');
    check("filter All -> 5 rows", has("#sessions .ses") === 5, String(has("#sessions .ses")));
    click('#filters .fbtn[aria-label^="Thinking"]');
    check("filter Thinking -> Debug watcher",
      text("#sessions .ses-title").indexOf("Debug watcher") === 0, text("#sessions .ses-title"));
    click('#filters .fbtn[aria-label^="All"]');

    // 3. expandable row
    var rows = document.querySelectorAll("#sessions .ses");
    var target = null;
    rows.forEach(function (r) {
      if (r.textContent.indexOf("Refactor engine") >= 0) target = r;
    });
    if (target) {
      target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      var detail = target.querySelector(".ses-detail");
      check("row expands", detail && detail.offsetParent !== null);
      check("detail shows msg/tool/id", detail && detail.textContent.indexOf("msg") >= 0 &&
        detail.textContent.indexOf("edit main.py") >= 0 && detail.textContent.indexOf("sess-1") >= 0,
        detail ? detail.textContent.slice(0, 60) : "");
      target.dispatchEvent(new MouseEvent("click", { bubbles: true }));
      check("row collapses", !target.classList.contains("expanded"));
    } else {
      check("row expands", false, "target row not found");
    }

    // 4. focus page: session control, chart, insights, comparison, wellbeing, activity
    click('.nav-item[data-view="focus"]');
    check("focus view visible", !document.getElementById("view-focus").hidden);
    check("focus session control", has("#focusSession .fsess") === 1, String(has("#focusSession .fsess")));
    check("focus start button", text("#focusSession #fsStart").indexOf("Start focus") >= 0, text("#focusSession #fsStart"));
    check("min chips 15/25/45", has("#focusSession .min-chip") === 5, String(has("#focusSession .min-chip")));
    click("#focusSession #fsStart");
    check("start_focus recorded", (window.__calls || []).indexOf("start_focus:25") >= 0,
      JSON.stringify(window.__calls));
    // the start click re-renders async (mock resolves a Promise); wait a tick
    // so the Stop button exists before we click it
    setTimeout(function () {
      var stop = document.querySelector("#focusSession #fsStop");
      check("stop button appears after start", !!stop, stop ? "" : "no #fsStop");
      if (stop) click("#focusSession #fsStop");
      check("stop_focus recorded", (window.__calls || []).indexOf("stop_focus") >= 0,
        JSON.stringify(window.__calls));
      continueFocusChecks();
    }, 50);
    return;
  }
  function continueFocusChecks() {
    check("history chart 7 bars", has("#wbHistory .wk-bar") === 7, String(has("#wbHistory .wk-bar")));
    check("history weekly total", text("#wbHistTotal").indexOf("this week") >= 0, text("#wbHistTotal"));
    check("history today highlighted", has("#wbHistory .wk-day.today") === 1);
    check("insights best day", text("#wbInsights").indexOf("Best day") >= 0, text("#wbInsights").slice(0, 90));
    check("insights top app", text("#wbInsights").indexOf("Most time in VS Code") >= 0, text("#wbInsights").slice(0, 90));
    check("compare card", text("#wbCompare").indexOf("This week") >= 0 && text("#wbCompare").indexOf("Last week") >= 0,
      text("#wbCompare").slice(0, 90));
    check("compare badge up", text("#wbCompare").indexOf("\u25b2 29%") >= 0, text("#wbCompare"));
    check("wellbeing total 3h 20m", text("#wbTotalVal") === "3h 20m", text("#wbTotalVal"));
    check("wellbeing 4 apps", has("#wellbeing .wb-row") === 4, String(has("#wellbeing .wb-row")));
    check("activity 9 rows", has("#activity .ses") === 9, String(has("#activity .ses")));

    // 5. wrapped page
    click('.nav-item[data-view="wrapped"]');
    check("wrapped view visible", !document.getElementById("view-wrapped").hidden);
    check("wrapped card 9h title", text("#wrappedCard .wrap-title").indexOf("9h") === 0,
      text("#wrappedCard .wrap-title"));
    check("wrapped 4 cells", has("#wrappedCard .wrap-cell") === 4, String(has("#wrappedCard .wrap-cell")));
    check("wrapped share button", has("#wrappedCard #wrapShare") === 1);
    check("sparkline 30 bars", has("#sparkline .spark i") === 30, String(has("#sparkline .spark i")));
    check("sparkline today highlight", has("#sparkline .spark i.today") === 1);
    check("week apps 3 rows", has("#weekApps .wa-row") === 3, String(has("#weekApps .wa-row")));
    click("#wrappedCard #wrapShare");
    // share uses navigator.clipboard (may reject headless) -> fallback path;
    // what matters is no uncaught exception surfaces in pageErrors
    check("share no uncaught error", pageErrors.length === 0, pageErrors.join(" | "));

    // 6. companion page
    click('.nav-item[data-view="companion"]');
    check("companion view visible", !document.getElementById("view-companion").hidden);
    check("profile level 7", text("#profileCard .lvl").indexOf("7") >= 0, text("#profileCard .lvl"));
    check("profile mood chip happy", text("#profileCard .mood-chip").indexOf("happy") >= 0,
      text("#profileCard .mood-chip"));
    check("profile xp bar", has("#profileCard .xpbar span") === 1);
    check("profile streak stat", text("#profileCard .prof-stats").indexOf("day streak") >= 0);
    check("companion stats card", text("#companionStats").indexOf("Streak") >= 0, text("#companionStats").slice(0, 60));
    check("companion today card", text("#companionToday").indexOf("Focus today") >= 0,
      text("#companionToday").slice(0, 60));
    check("milestones feed renders", has("#milestones .ses") >= 1, String(has("#milestones .ses")));
    check("heatmap 90 cells", has("#heatmap .hm .hm-cell") >= 90 && has("#heatmap .hm .hm-cell") <= 91, "cells=" + has("#heatmap .hm .hm-cell"));
    check("heatmap has colored cells", has("#heatmap .hm .hm-cell.l1") >= 1 || has("#heatmap .hm .hm-cell.l2") >= 1);
    // 7. focus page best-hours peaks
    click('.nav-item[data-view="focus"]');
    check("peaks card renders", has("#peaksCard .pk i") === 24, "bars=" + has("#peaksCard .pk i"));
    check("peaks best line", text("#peaksCard .pk-line").indexOf("focus best") >= 0,
      text("#peaksCard .pk-line"));
    check("peaks best highlighted", has("#peaksCard .pk i.best") === 1);
    click('.nav-item[data-view="dash"]');
    check("back on dashboard", !document.getElementById("view-dash").hidden);

    // 7. pets & behavior view
    click('.nav-item[data-view="pets"]');
    check("pets view visible", !document.getElementById("view-pets").hidden);
    check("7 pet cards", has(".pet-card") === 7, String(has(".pet-card")));
    var selected = document.querySelector('.pet-card[aria-checked="true"]');
    check("pet 2 selected (Charmander)", selected && selected.textContent.indexOf("Charmander") >= 0,
      selected ? selected.textContent : "");

    // 8. keyboard nav on pet cards
    var first = document.querySelector(".pet-card");
    if (first) {
      first.focus();
      var diag = "ae=" + (document.activeElement && document.activeElement.className) +
        " contains=" + document.getElementById("pets").contains(document.activeElement);
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true, cancelable: true }));
      var sel = document.querySelector('.pet-card[aria-checked="true"]');
      var idx = Array.prototype.indexOf.call(document.querySelectorAll(".pet-card"), sel);
      // mock config selects Charmander (idx 1), so ArrowRight must land on idx 2
      check("ArrowRight moves selection", sel === document.querySelectorAll(".pet-card")[2], "idx=" + idx + " " + diag);
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true, cancelable: true }));
      check("Home returns to first", document.querySelector('.pet-card[aria-checked="true"]') === first);
    }

    // 9. walk slider
    var rng = document.getElementById("walk");
    rng.value = "0";
    rng.dispatchEvent(new Event("input", { bubbles: true }));
    check("walk slider 0%", text("#walkVal") === "0%", text("#walkVal"));

    // 10. break reminder switch
    var brk = document.getElementById("brk");
    if (brk.getAttribute("aria-checked") !== "true") brk.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    check("break row appears", !document.getElementById("brkRow").hidden);

    // 11. dashboard rail actions
    click('.nav-item[data-view="dash"]');
    click("#nextPet");
    check("next_pet recorded", (window.__calls || []).indexOf("next_pet") >= 0,
      JSON.stringify(window.__calls));
    check("no page errors", pageErrors.length === 0, pageErrors.join(" | "));

    // 12. session search
    var searchEl = document.getElementById("search");
    if (searchEl) {
      searchEl.value = "sprite";
      searchEl.dispatchEvent(new Event("input", { bubbles: true }));
      check("search 'sprite' -> 1 row", has("#sessions .ses") === 1, String(has("#sessions .ses")));
      check("search finds Sprite pipeline", text("#sessions .ses-title").indexOf("Sprite pipeline") === 0,
        text("#sessions .ses-title"));
      searchEl.value = "";
      searchEl.dispatchEvent(new Event("input", { bubbles: true }));
      check("clear search -> 5 rows", has("#sessions .ses") === 5, String(has("#sessions .ses")));
    } else {
      check("search box present", false);
    }

    // 13. sort toggle
    if (document.getElementById("sortBtn")) {
      click("#sortBtn");
      check("oldest-first top row = Docs", text("#sessions .ses-title").indexOf("Docs") === 0,
        text("#sessions .ses-title"));
      click("#sortBtn");
      check("newest-first top row = UI polish", text("#sessions .ses-title").indexOf("UI polish") === 0,
        text("#sessions .ses-title"));
    } else {
      check("sort button present", false);
    }

    // 14. state distribution bar
    check("dist bar visible with 5 sessions", has("#dist .dist-bar") === 1);
    check("dist legend has working/thinking/errors", has("#dist .dist-legend span") >= 3,
      String(has("#dist .dist-legend span")));

    // 15. Escape inside the search box must NOT close the window
    var s2 = document.getElementById("search");
    if (s2) {
      s2.focus();
      s2.value = "docs";
      document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }));
      check("Escape in search keeps window open", (window.__calls || []).indexOf("hide_control") < 0,
        JSON.stringify(window.__calls));
      s2.value = "";
      s2.dispatchEvent(new Event("input", { bubbles: true }));
    } else {
      check("Escape in search keeps window open", false, "no search box");
    }

    done();
  }
})();
</script>
"""


def main():
    src = open(MOCK, encoding="utf-8").read()
    assert src.count("<script>") >= 2
    with open(OUT, "w", encoding="utf-8") as fh:
        fh.write(src + SELFTEST)
    print("wrote %s (%d bytes)" % (OUT, os.path.getsize(OUT)))


if __name__ == "__main__":
    main()
