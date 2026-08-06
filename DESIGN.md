# OpenCode Pet — Design System ("Ambient Work Companion")

> Design authority for the redesigned desktop UIs. This is the single source of truth
> for tokens, type, and craft. Both `desktop/app.html` and `desktop/control.html` must
> render from the SAME token set below. The visual world is **Ambient Work Companion**:
> a warm, confident dark "studio" canvas where the pixel-art pet is the hero and every
> panel recedes into soft, glassy depth.

## One-sentence POV
A deep, warm near-black workbench glowing with amber "energy"; the desktop pet is a
collectible object on a glass shelf, and your focus data reads like an instrument
panel — calm, precise, alive.

## World rules
- **Canvas is warm, never blue.** Near-black with a faint amber cast; glow lives in the
  corner, not behind text.
- **Glass over flat.** Panels are translucent, hairline-bordered, with a top inner
  highlight and a soft layered shadow — never floating squares.
- **Accent is one voice.** Amber→coral gradient = the pet's aliveness / focus energy.
  Indigo is retired (control.html previously used it — eliminated for cohesion).
- **Pets are heroes.** Every pet sits on a radial "shelf" glow; selected cards get a
  dew highlight and a soft ground shadow.
- **Motion is alive but calm.** Fast, billowy ease on micro-interactions; never bouncy.
  Respect `prefers-reduced-motion`.

## Shared tokens (paste this :root into BOTH files)
```css
:root {
  /* canvas */
  --bg0: #0b0b0f;            /* deep warm near-black */
  --bg1: #141319;            /* card */
  --bg2: #1c1b22;            /* raised / hover */
  --bg3: #24232c;            /* inset fills */
  --border: #23222b;
  --border2: #33313d;
  /* ink */
  --text: #f2f1ec;
  --text2: #aaa8b3;
  --text3: #6e6d7a;
  /* energy accent (amber→coral) */
  --accent: #f6b35c;
  --accent2: #ff7a6a;
  --accent-ink: #221505;
  /* semantics */
  --ok: #5fdd9d;
  --warn: #e8b96b;
  --danger: #ff7b84;
  --thinking: #7fc8e8;
  --idle: #8b8b98;
  /* geometry + motion */
  --r-lg: 16px;
  --r-md: 11px;
  --r-sm: 8px;
  --ease: cubic-bezier(0.22, 1, 0.36, 1);
  --glow: 0 14px 44px -20px rgba(0, 0, 0, 0.75);
}
```

## Typography
- Stack: `"Segoe UI Variable", "Segoe UI", system-ui, -apple-system, sans-serif`.
- Display (page titles): ~25–27px / 620 weight / letter-spacing −0.02em.
- Section labels: 11px / 650 / +0.08em uppercase, muted.
- Data numerals: `"Cascadia Mono", Consolas` + `font-variant-numeric: tabular-nums`.
- Values / stats: 600–650 weight, tabular, accent-tinted.

## Day-body aura (data-embodiment)
The pet's body IS the day's data: an aura overlay per embodied state, alpha
scaled by intensity. Tokens below match `store.EMBODY_AURA` (single source of
truth — engine and dashboard must never disagree).

| State   | Aura (rgba)      | Meaning                                    |
|---------|------------------|--------------------------------------------|
| fog     | `125 128 145 .18`| day mostly idle — pet droops               |
| bloom   | `255 205 110 .24`| daily goal met / deep focus flowing        |
| storm   | `226 84 84 .22`  | session errored or focus wilted            |
| ember   | `255 118 46 .22` | ≥4 saturated deep hours today              |
| quiet   | none             | day not started — resting                  |
| flow    | none             | steady progress — chrono gene glow only    |

## States
- **Loading**: skeleton shimmer bars (already present) — keep, tint to bg2→bg3.
- **Empty**: centered art tile (icon on a soft ring) + short line, muted accent hint.
- **Error**: `.errbanner` soft danger wash + hairline danger border.
- **Success/celebration**: amber → coral halo pulse on the live dot / celebrating chip.

## Motion
- Micro-interactions: 150–240ms, `--ease` (fast billow-out). No bouncy springs.
- Live pulse ~2.2s soft halo. Chart grows: width/height transition 0.5s `--ease`.
- `prefers-reduced-motion: reduce` → zero transitions/animations.

## Per-surface directives
- **app.html (dashboard)** — main fridge of the workbench. Glass rail cards + feed
  cards, premium sidebar nav (active pill), display titles, energy-live pill.
- **control.html (control window)** — the pet "menu": a compact glass sheet. Pet cards
  on radial shelves, refined sliders/toggles with amber fill, one-tap actions.

## Craft floor (non-negotiable)
- WCAG AA contrast on all text (see tokens — text3 is boosted for small text).
- Keyboard focus must be visible (accent ring). Reduced-motion respected.
- Never rename an element `id`, an `aria-*` contract, or a JS function — the pywebview
  bridge is the product's contract and is untouchable.
- Every class the markup/JS generates must remain styled; no dead rules that collide.
