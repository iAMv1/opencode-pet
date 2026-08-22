# HANDOFF — opencode-pet

> Canonical resume-state. Update BEFORE reporting done. Last: 2026-08-22.

## Repo facts
- Path: `C:\Users\ItzP\projects\opencode-pet` · Remote: `github.com/iAMv1/opencode-pet`
- main == origin/main @ `cf5868b` (2026-08-22). Latest release **v0.6.1** (Aug 3).
- Python via `py -3.12` (`python` alias broken on this box — Store stub).
- Full validation: `py -3.12 tests/run_all.py` (~2–4 min) → 625 pytest + UI self-test + real-browser self-test.

## State after this session
- Fixed flaky `test_goal.py::test_goal_celebration_sets_cast_flash` (froze clock; cast flash = 1s, slow ticks expired it).
- Hardened `tests/make_real_selftest.py` cold-start race: waitFor 150→600 tries, virtual-time-budget 20s→40s. Was intermittently 52/72 with all `[n=0]`; now stable 72/72.
- README release badge v0.6.0 → v0.6.1.
- Deleted stray root `PRD.md`/`TRD.md` (belonged to unrelated "Workflow Orchestrator" project; user confirmed delete).

## Parked / open decisions
- **Parked branches (user decision, do not merge/delete without ask):**
  - `epic/project-completion-sprint` = fdeb9d1 "pet unlock system replaces evolution" (+8.2k/−13.8k, deletes ~15 test files, predates Aug 7 main HEAD → heavy conflicts if revived).
  - `feature/autonomous-cleanup-sprint` = same + stash commit 9d89325.
  - `chore/comprehensive-cleanup` ≈ main (no delta found).
- `origin/develop` dead (2 init commits only).
- BUG-7/BUG-8 in EMOTION_BUGS.md still need new LPC-cat sprite art.
- No `docs/HANDOFF.md` existed before today — keep this file updated.

## Next high-value steps
1. Cut v0.6.2 once next feature lands (tag triggers exe build workflow).
2. Decide epic-branch fate (revive as PR = big test-repair job).
3. LPC-cat sprite variety (BUG-7/8) — sprite pipeline lives in `tools/sprite_forge.py`.
