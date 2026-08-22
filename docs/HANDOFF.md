# HANDOFF — opencode-pet

> Canonical resume-state. Update BEFORE reporting done. Last: 2026-08-23 (gauntlet round 2).

## Repo facts
- Path: `C:\Users\ItzP\projects\opencode-pet` · Remote: `github.com/iAMv1/opencode-pet`
- main == origin/main @ `ba20689`. Latest release **v0.6.1**.
- Python via `py -3.12` (`python` alias broken — Store stub).
- Full gate: `py -3.12 tests/run_all.py` (~2–3 min) → **640 pytest + UI 78/78 + real 72/72**.

## Gauntlet log
- **Round 1** (`fd07ed0`): persistence integrity (.bak/.corrupt recovery, atomic writes, locked focus-tag RMW, honest save bools), bubble priority tiers, echo int-keys, wilt guard, barter expiry clock, delta persistence in config_watch/set_pet, web hardening, mutex use_last_error. +15 regression tests.
- **Round 2** (`ba20689`, −237 LOC): `_pet_aura` glow ×3→1, `_log_events` scanner ×4→1, `_persist_keys` dance ×11→1, api `_iter_activity_log` ×5→1, frontend drift fixed (Emberkit fallback, ember move sync, dup wbCompare removed, sig-guards, dead _focus-ritual.js deleted), quit paths flush state before os._exit.
- LESSON: never rewrite test files via PS Set-Content (UTF-8 mojibake once; reverted). Use edit tool only.

## Parked / open decisions (user-owned)
- Branches parked: epic/project-completion-sprint + feature/autonomous-cleanup-sprint ("pet unlock system", +8.2k/−13.8k, predates Aug-7 main, heavy conflicts if revived). chore/comprehensive-cleanup ≈ main. origin/develop dead.
- BUG-7/8 LPC-cat sprite variety needs new sprite art (tools/sprite_forge.py pipeline).

## User directives (standing)
- **LOC budget: 1–2k lines per e2e complete feature.**
- Not fond of HTML dashboards — wants desktop-native stack eventually. Options to propose at checkpoint: PySide6/Qt (stays Python, reuses engine/store) vs C#/WinUI rewrite vs TUI (@opentui/solid dep exists in package.json). Pet window itself already native GDI. Do NOT rip out working UI mid-loop; layer it.
- Long-term architecture only, no stopgaps; grow in layers; debt OK when documented (DEBT-OK sections in audits).

## Next high-value steps (round 3 queue)
1. Hidden-view polling waste (app.html intervals fire for hidden views — gate on state.view).
2. api.py get_logs raw-window note is now documented in code; consider a "parse-then-window" contract change if corrupt lines ever matter.
3. Multi-monitor: pet confined to primary workarea; WM_DISPLAYCHANGE unhandled → stranded pet on dock/undock (feature-sized, respect 1–2k LOC budget).
4. Threading: engine still mutated from ≥5 threads without locks (audit MED) — next architectural item; design an RLock discipline around xp/bubble/sessions before adding features.
5. Native-stack migration proposal (user ask): PySide6/Qt vs WinUI vs TUI. Needs agency-design-pipeline skill if it produces UI.
6. Cut v0.6.2 tag when next feature lands (tag triggers exe build workflow).
7. Parked user decisions: epic/cleanup branches (pet unlock system), BUG-7/8 LPC-cat sprites.
