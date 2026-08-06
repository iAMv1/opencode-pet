/* ============================================================
   FOCUS RITUAL — additive enhancement (accepted via consensus).
   Reads the existing focus card's DOM (zero edits to app.js):
   - sprout maturity phase bar (Seed/Sprout/Leaf/Bloom/Wilt)
   - cross-app "Focusing in <app>" chip (any app counts)
   - type-move break ritual on completion (bolt -> cursor ash -> Break!)
   App-agnostic: uses fs.app from the OS-level foreground detector.
   ============================================================ */
(function () {
  "use strict";
  var RING_R = 33.5, RING_C = 2 * Math.PI * RING_R;
  var fired = false;   // break ritual fired during this session
  var lastSig = "";

  var TYPES = [
    { m: /pika/i, move: "Thunderbolt", g: "⚡" },
    { m: /charm/i, move: "Ember", g: "🔥" },
    { m: /dora/i, move: "Air Cannon", g: "💨" },
    { m: /gardev/i, move: "Confusion", g: "✨" },
    { m: /girat/i, move: "Shadow Claw", g: "🌑" },
    { m: /cat/i, move: "Scratch", g: "🐾" }
  ];
  function moveFor(pet) {
    for (var i = 0; i < TYPES.length; i++) {
      if (TYPES[i].m.test(pet || "")) return TYPES[i];
    }
    return { move: "Focus Burst", g: "✦" };
  }
  function phase(pct, wilted) {
    if (wilted) return { k: "wilt", label: "Wilted", e: "🥀", c: 0 };
    if (pct >= 100) return { k: "bloom", label: "Bloom", e: "🌸", c: 100 };
    if (pct >= 67) return { k: "leaf", label: "Leafing", e: "🍃", c: 67 };
    if (pct >= 34) return { k: "sprout", label: "Sprouting", e: "🌱", c: 34 };
    return { k: "seed", label: "Seed", e: "🌰", c: 0 };
  }
  function esc(s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }
  function appFrom(statusText) {
    var m = /Focusing in (.+?) \u00b7/.exec(statusText || "");
    return m ? m[1] : "";
  }

  function build() {
    var el = document.getElementById("focusSession");
    if (!el) return;
    var active = !!document.getElementById("fsStop");
    if (!active) { fired = false; removeRitual(el); return; }

    var ring = el.querySelector(".ring-fg");
    var sub = el.querySelector(".fsess-sub");
    var statusText = sub ? sub.textContent : "";
    var wilted = !!el.querySelector(".ring.wilted");
    var offset = ring ? parseFloat(ring.getAttribute("stroke-dashoffset")) : RING_C;
    if (isNaN(offset)) offset = RING_C;
    var pct = Math.max(0, Math.min(100, Math.round((1 - offset / RING_C) * 100)));

    if (!wilted && pct >= 100) fired = true;

    var pet = ((document.getElementById("railName") || {}).textContent || "").trim() || "Pet";
    var mv = moveFor(pet);
    var ph = phase(pct, wilted);
    var app = appFrom(statusText) || "your app";
    var showRitual = fired && !wilted;

    var sig = [active, wilted, ph.k, showRitual, app].join("|");
    if (sig === lastSig) return;
    lastSig = sig;
    removeRitual(el);

    var r = document.createElement("div");
    r.className = "focus-ritual" + (wilted ? " wilt" : (showRitual ? " fire" : ""));
    var body = "";
    if (showRitual) {
      body =
        '<div class="fr-ritual" role="img" aria-label="' + esc(mv.move) + ' \u2014 time to break">' +
          '<div class="fr-bolt">' + mv.g + "</div>" +
          '<svg class="fr-arc" viewBox="0 0 120 60" aria-hidden="true"><path d="M6 50 C 40 8, 80 8, 114 44"/></svg>' +
          '<div class="fr-cursor" aria-hidden="true">\ud83d\uddb1</div>' +
          '<div class="fr-ash" aria-hidden="true"><span>&bull;</span><span>&bull;</span><span>&bull;</span></div>' +
        "</div>" +
        '<div class="fr-break">Break! <b>' + esc(mv.move) + "</b> &middot; <span>rest your eyes</span></div>";
    } else if (wilted) {
      body = '<div class="fr-wilt">Switch back soon to save the sprout</div>';
    } else {
      body = '<div class="fr-move">' + mv.g + ' <b>' + esc(mv.move) + "</b> ready for your next break</div>";
    }

    r.innerHTML =
      '<div class="fr-top">' +
        '<span class="fr-appchip" title="Focus is app-agnostic \u2014 any app counts">' +
          '<span class="fr-appdot"></span> Focusing in <b>' + esc(app) + "</b></span>" +
        '<span class="fr-phase ' + ph.k + '">' + ph.e + " " + ph.label + "</span>" +
      "</div>" +
      '<div class="fr-phasebar" aria-hidden="true"><span style="width:' + ph.c + '%"></span></div>' +
      body;
    el.appendChild(r);
  }

  function removeRitual() {
    var el = document.getElementById("focusSession");
    if (!el) return;
    var old = el.querySelector(".focus-ritual");
    if (old) old.remove();
  }

  // Smooth live progress ring — fixes the "sluggish" stepped clock. A rAF loop
  // drives the ring + remaining time from wall-clock between polls (from the
  // data-started/data-target we stamped on the .fsess root), so it never waits
  // on a poll and never re-renders the card.
  var _raf = null;
  function _drive() {
    var fs = document.querySelector("#focusSession .fsess");
    var v = document.getElementById("view-focus");
    var active = !!fs && fs.getAttribute("data-active") === "1" && v && !v.hidden;
    if (!fs || !active) { _raf = null; return; }
    var fg = fs.querySelector(".ring-fg");
    var remain = fs.querySelector(".fs-remain");
    if (fg) {
      var started = parseFloat(fs.getAttribute("data-started")) || Date.now();
      var targetSec = parseFloat(fs.getAttribute("data-target")) || 0;
      var C = parseFloat(fg.getAttribute("stroke-dasharray")) || (2 * Math.PI * RING_R);
      var elapsed = (Date.now() - started) / 1000;
      var prog = targetSec > 0 ? Math.min(1, Math.max(0, elapsed / targetSec)) : 0;
      fg.style.transition = "none";           // direct, frame-accurate updates
      fg.setAttribute("stroke-dashoffset", (C * (1 - prog)).toFixed(1));
      if (remain) {
        var left = Math.max(0, targetSec - elapsed);
        remain.textContent = "\u00b7 " + Math.ceil(left / 60) + "m left";
      }
    }
    _raf = requestAnimationFrame(_drive);
  }
  function _kick() {
    // reduced-motion: keep the ring poll-driven (900ms), skip the rAF loop
    if (_raf == null && !(window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches))
      _raf = requestAnimationFrame(_drive);
  }

  // keep in sync while the Focus view is visible
  setInterval(function () {
    var v = document.getElementById("view-focus");
    if (!v || v.hidden) return;
    build();
    _kick();
  }, 900);
})();
