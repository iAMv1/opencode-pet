# Task: Petdex ecosystem deep-dive + R4 architecture decision

## Goal
Produce the evidence base for Round 4 of opencode-pet: (a) adopt the Petdex/Codex
pet-pack format via a loader, and (b) settle the native-UI question with data
instead of taste. Deliverables feed docs/HANDOFF.md Round 4 queue.

## Milestones
1. M1 — Format spec verified: pet.json schema, v1/v2 atlas geometry, per-row
   frame counts, durationMs conventions, messageMap/state vocabulary, manifest
   API shape. Cross-checked against >=2 independent implementations.
2. M2 — Comparable-client stack survey: what OpenAnima / AgentPet / AgentCat /
   OpenPets / dengyie-OpenPet chose (PySide6/Tauri/Electron), packaging path,
   visible LOC, stated rationale; lessons transferable to our Python/GDI app.
3. M3 — Licensing & risk verdict: gallery asset license norms, runtime-import
   vs bundling, format-drift risk (v1 vs v2), frame-count variance handling.
4. M4 — Synthesis: pack-loader spec draft mapped onto desktop/sprites.py +
   stack decision matrix + recommendation.

## Success criteria
- >=12 findings in findings.jsonl, each with source URL(s) or file:line evidence
- Loader spec covers: discovery, validation, frame-grid parsing, state mapping,
  scale/preview reuse, failure modes
- Stack matrix scores 3 options on >=5 criteria with cited evidence
- Zero unresolved load-bearing claims (each either cited or marked OPEN)

## Constraints
- Zero interaction; ambiguity resolved + logged level=decision
- Fresh direction each iteration; directions recorded in directions_tried.json
- Validation between iterations: claims spot-checked, not batched
