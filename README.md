# OpenCode Pet

Native desktop pet for OpenCode. Pixel-art animated pets (petdex-style sprite sheets) that react to live agent events in a transparent always-on-top frameless window. No web server — the exe polls session status files directly.

## Features

- **Pixel Art Pets** - Real sprite-sheet frame animation. Bundled: Pikachu, Charmander, Doraemon, Gardevoir, Giratina (petdex-format 192×208) + **LPC Cat** (CC-BY, 64×64). More can be added — renderer is data-driven per pet (frame size, state rows, state map).
- **Event-Driven Updates** - No polling. `ReadDirectoryChangesW` file watcher pushes status to JS the instant a session event lands (3s safety-net poll only). OS activity (foreground app + input idle) checked at 1s.
- **Interactive** - Click pet → jump burst, double-click → wave, hover shows name + ◀ ▶ ✕ controls, drag anywhere to move.
- **Completion Celebration** - session idle after busy → celebrating state (wave/jump) fires once, not just "Done".
- **Transparent Window** - No background. Just the pet, floating over your desktop.
- **Frame Animation** - Canvas-rendered sprite sheets: idle, run L/R, wave, jump, fail, wait, run, review. States map to real agent activity (busy → running, thinking → review, error → failed, success → jump).
- **Standalone Desktop App** - Single exe, zero setup. Reads `status-<sessionID>.json` via native bridge, 2s poll. No web server.
- **Works With ANY App** - Not just opencode. OS-level activity layer: foreground-window detection + global input timer (Win32). Any terminal, editor, browser, or app drives the pet — typing → running, app switch → reacts, idle 30s+ → waiting. opencode events (tool names, exact states) enhance it when opencode is running.
- **Tool Tracking** - Speech bubble shows tool label (opencode) or foreground app name (any app); typing indicator while working.
- **Killswitch** - Drop `~/.opencode/pet/disabled` to disable the plugin.

## Installation

```bash
opencode plugin C:\Users\ItzP\projects\opencode-pet -g
```

## Usage

### Desktop Pet
Run `/pet.open` in any opencode session, or launch `dist\OpenCodePet.exe` directly.

- Frameless transparent window, always on top, drag anywhere to move
- **Close**: hover pet → ✕ button, or press `Esc`, or right-click, or tray icon → Quit
- **Switch pet**: hover pet → ◀ ▶ buttons (choice persists)
- Hover shows pet name + controls
- Animates from real session events (busy/thinking/error/success)

### Commands
- `/pet.open` - open the native desktop pet window

## How it works

- `dist/server.js` - opencode plugin: writes `status-<sessionID>.json` to `~/.opencode/pet/` on every event + 10s heartbeat.
- `desktop/sprites/*.webp` - pixel-art sprite sheets (petdex format, 1536×1872, 192×208 frames, 8 cols × 9 state rows).
- `desktop/control.html` - control window UI: pet picker with live animated sprite previews, behavior settings, hide/show/quit. Rendered in a pywebview window.
- `desktop/main.py` - native app: GDI layered window for the pet (PIL sprite renderer, state machine, physics, speech bubble) + pywebview control window + system tray. Exposes `get_config()`, `get_previews()`, `save_config()`, `hide_pet()`/`show_pet()`, `hide_control()`, `quit()` to the UI.
- `dist/tui.js` - TUI sidebar pet + `/pet.open` command.

## Development

```bash
npm install
pip install -r desktop/requirements.txt
python desktop/main.py
# rebuild the exe:
desktop\build.bat
```

## Adding pets

1. Download sprite.webp from petdex assets (`https://assets.petdex.dev/pets/<slug>/sprite.webp`, 1536×1872)
2. Drop into `desktop/sprites/pet-<name>.webp`
3. Add entry in `desktop/gen_index.py` PET_DEFS
4. `python desktop/gen_index.py` + rebuild exe

## License note

Bundled pixel art sources: petdex fan art (Pikachu/Charmander/Doraemon/Gardevoir/Giratina — personal use only, remove before distributing) + **LPC Cat** by bluecarrot16 (CC-BY 3.0 / GPL, https://opengameart.org/content/lpc-cats-and-dogs). LPC sprites are shippable with attribution.

## vs petdex.dev

| Feature | petdex.dev | This plugin |
|---------|-----------|-------------|
| Desktop window | Tauri (Windows) | pywebview + WebView2 (Windows 11 native) |
| Multi-session | One stream at a time | Tab bar, all sessions live |
| Event reactivity | tool hooks + idle | 7 bus events + tool hooks + SSE |
| Tool bubble | Formatted names | Formatted names + raw args + typing indicator |
| Animations | Sprite sheets | SVG + CSS + JS frame cycling |
| Auto-start | No | Spawns hub + desktop app on demand |
| Killswitch | Yes | Yes (`disabled` file) |
| TUI sidebar | No | Yes |
| Setup | Desktop app + hooks install | `opencode plugin -g` |
