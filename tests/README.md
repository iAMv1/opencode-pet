# OpenCode Pet — Validation Suite

Zero-new-dependency tests that continuously validate the whole system under
realistic production conditions: the pet engine, config/status files, the
plugin → status-file contract, the frontend, and load/stress behavior.

## Run everything (one command)

```bash
python tests/run_all.py
```

This runs, in order:

| Step | Tool | What it covers |
|------|------|----------------|
| `pytest tests/` | pytest (stdlib `unittest`-style) | Engine state machine, config/status/wellbeing, ControlApi, spec contracts, focus/XP/level/mood/streak/wrapped, hour-of-day peaks, evolution stages, load/stress |
| `python tests/check_frontend.py` | node `--check` | Inline JS syntax + HTML structure of both frontends |
| `tests/make_ui_selftest.py` + headless Chrome | Chrome | 67 interactive UI checks (Dashboard/Focus/Wrapped/Companion page nav, filters, search/sort, expandable rows, keyboard nav, wellbeing, 7-day chart + weekly compare + insights, focus-session control, wrapped card + share, sparkline, week-app bars, pet profile + stage, milestones, 90-day heatmap, best-hours peaks) |
| `tests/make_real_selftest.py` + headless Chrome | Chrome | 65 REAL-bridge UI checks — the same UI driven through the actual `--web` server (real ControlApi + real files, zero mocks) |
| `node tests/test_server_plugin.mjs` | Node | 21 plugin→status-file contract tests (states, celebration, tool→busy, throttle, killswitch) |

`tests/fixtures/` is generated on each run and gitignored.

## Run pieces individually

```bash
python -m pytest tests/ -q                      # Python suite (187 tests)
node tests/test_server_plugin.mjs               # plugin contract (uses throwaway HOME)
python tests/check_frontend.py                  # frontend JS/HTML syntax
python tests/make_mock_page.py                  # regenerate the browser-test fixture
python tests/make_real_selftest.py              # REAL-bridge browser self-test
```

## What the suite guards against

- **Emotion system** (`test_state_machine.py`): state→animation mapping,
  stale-session emotion preservation (BUG-3), per-pet animation guards
  (LPC cat has no jumping row), null-state → idle.
- **Config integrity** (`test_config_status.py`): merge semantics of
  `save_config` (two processes share config.json), corruption resilience,
  one-shot command keys surviving setting saves.
- **Sprite/data integrity** (`test_engine_integration.py`): every declared
  animation row exists in the sprite sheet, no dead/unreachable animation
  ids, frame cache completeness, font caching (5ms/frame perf guard).
- **Production hardening** (`test_hardening.py`): Win32 interop shape (every
  HANDLE-returning call declares a 64-bit restype; GetLastInputInfo wiring),
  GetTickCount 49.7-day rollover mask, cross-process config write locking
  (concurrent writers never lose keys), wellbeing sleep-gap clamp,
  read_status permission resilience, bubble-text truncation equivalence
  (binary search == old linear result) and relative perf guard.
- **Frontend contract** (`test_spec_contract.py`): every `api.*` call the
  HTML makes exists on `ControlApi`; user data is always HTML-escaped;
  inline JS parses with `node --check`; tags balance.
- **Focus insights** (`test_config_status.py`): 7-day history window shape,
  day rollover folding, old-format compat, days clamp, weekly comparison
  (week vs prev week, delta %, no-baseline → None, flat week → 0), best-day
  and top-app selection, corrupt-value resilience.
- **Companion layer** (`test_config_status.py` + `test_web_bridge.py`):
  focus sessions (start/clamp, wilt on app-switch, completion XP), the
  linear XP curve and level-up persistence, mood transitions, consecutive-
  day streak counting, weekly-wrapped summary (best day, top app, session
  count, prev-week delta), per-app week aggregation, and the live
  focus.json contract — all against real files over the real `--web` server.
- **Plugin contract** (`test_server_plugin.mjs`): states land in status
  files, filenames are sanitized, messages truncated, celebration fires on
  completion (and not after errors), tool execution flips an idle session
  to busy, write throttle is a 400ms rate limiter, killswitch works.
- **Load/stress** (`test_stress.py`): 300-file directories with corrupt
  files, 5000-line logs, rapid config churn, 100k-char messages — no crash,
  correct results, sane timing.
