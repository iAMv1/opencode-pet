# R4 Research Synthesis — Petdex loader + native stack (2026-08-23)

Evidence: research/petdex-r4/state/findings.jsonl (19 findings, 3 independent
agents: format spec / stack survey / adversarial refutation with live fetches
and pixel alpha-scans).

## Decision 1 — Build the Petdex pack loader? YES, but ship it right

The ecosystem is real and large: **4,579 packs** on the manifest, byte-compatible
with our atlas (same 9 rows, same 192x208 cells, same timing constants). But the
refutation round proved naive parsing WILL break on live packs:

Loader spec (non-negotiables):
1. **Infer geometry from the image**, never from pet.json/manifest: rows ∈ {9,11}
   by height divisibility; cell = W/8 × H/rows; accept clean integer scales.
2. **Alpha-scan each row** at load → frame_count = contiguous painted cells from
   col 0; animate min(canonical, scanned); log drift. (sayaka idle = 7 frames
   already breaks Petdex's own clients.)
3. **Alias shim**: canon("walking"/"walk"/"run")→"running" before any name
   lookup; store row indices internally.
4. Parse only the observed 4-5 pet.json fields; tolerate extras; strict UTF-8,
   sanitize display strings (manifest has mojibake).
5. Fetch only on explicit user action; descriptive UA; respect manifest
   Cache-Control 300s; one retry on 5xx. Never bundle/mirror gallery pets.

## Decision 2 — Native UI: PySide6 incremental, control.html first

Stack matrix favors **B. Incremental PySide6 panels** (keep GDI pet window):
- OpenAnima is the existence proof (solo dev, PySide6+Pillow+PyInstaller,
  MS Store distribution, zero HTML, same overlay primitives we already use).
- Tauri/Electron would force a Python↔webview IPC bridge whose cost these repos
  document in detail (4 ADRs for a Node-Node sidecar; per-OS forks; petdex
  literally deleted its Tauri Windows client).
- Only real regression: installer size (+100–150MB est). Solo-maintainability
  and engine/test reuse both improve.
- Sequencing: port `control.html` first (highest surface), resolve the dual
  event loop once (~1 day budgeted), keep app.html on pywebview until the port
  earns trust.

## ⚠ Escalation — bundled-sprite exposure (user decision required)

R1 inverted our licensing assumption AND found a worse pre-existing issue:
the exe bundles Pikachu / Charmander / Doraemon / Gardevoir / Giratina sprites —
direct distribution of likely-infringing fan art. Gallery pets carry NO license
metadata at all, so per-pack checks are impossible; galleries survive as
conduits, redistributors don't. Options:
a) Replace bundled roster with original/CC0 pets (sprite_forge pipeline can
   generate), keep Pokemon as local-only imports users add themselves;
b) Accept risk as a hobby project (documented);
c) Ask Petdex-style galleries how they position it.
This gates v0.6.2/v0.7 releases more than any code question.

## Iteration 2 — the ACTUAL buzz: Grok Companions (user correction)

The user meant the **Grok Companion wave (Jul 2025)** — Ani / Bad Rudy /
Valentine — not pixel-sheet galleries. Decoded:

- **What it is**: 3D avatars animated on-device in real time; engineers noted
  xAI does NOT drive them with preset Live2D/VRM clips — language output maps
  directly to motion ("Any2Any"). The moat is generative rigging, NOT a
  reusable asset library. Nothing to adopt from it directly.
- **Usable expressive-2D stacks for us**:
  | Stack | License | Fit |
  |---|---|---|
  | Live2D Cubism models + `pixi-live2d-display` (1.5k★) | runtime MIT; editor/models proprietary, publishing needs SDK license | fastest to "wow", licensing friction |
  | Inochi2D + nijigenerate + inox2d | BSD-2-Clause, fully open pipeline | rig our own pet freely; more authoring work |
  | More sprite emotion states (current format) | none needed | cheap win now |
- **Twitter tooling note**: twitter-cli broken (X ClientTransaction change),
  OpenCLI profile offline — findings sourced via Exa-indexed coverage +
  GitHub probing instead. OPEN: raw tweet-vertex sentiment.

## OPEN items
- stateDurations semantics (agent-pet extension) — read its state_machine.rs if we adopt the field.
- v2 rows 9-10 canonical purpose (look-directions vs reserved) — irrelevant to loader (ignore them).
- Manifest rate limits — none documented; empirically none hit at our scale.
