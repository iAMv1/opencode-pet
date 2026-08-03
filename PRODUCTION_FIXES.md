# Production Readiness Fixes — 2024

## Issues Fixed

### 🔴 Blocker 1: Dead Code Removed
- **Removed**: `dist/server.js` (9 KB) and `dist/tui.js` (6 KB)
- **Reason**: These files from a previous Node.js architecture were never loaded by the Python runtime. `desktop/main.py` has zero references to them.
- **Impact**: Eliminates 15 KB of dead code and prevents confusion about runtime dependencies.

### 🔴 Blocker 2: Architecture Documentation Corrected
- **Fixed**: `ARCHITECTURE_MAP.html`
- **Removed**: Nodes for `dist/server.js`, `dist/tui.js`, and `package.json`
- **Removed**: Edges claiming "plugin" and "tui" connections
- **Removed**: False edge "server-js → main-py (writes status files)" — Python writes these itself
- **Impact**: Graph now accurately reflects the actual runtime path: pet process → main.py → GDI/sprites/HTML

### 🟡 Blocker 3: Watcher Thread Error Recovery
- **Added**: `_watch_failures` counter and `_shutdown` flag to `PetEngine`
- **Added**: Fallback polling every 2s when `ReadDirectoryChangesW` fails permanently
- **Added**: Shutdown checks in both watcher and render_loop threads
- **Impact**: If antivirus locks the PET_DIR or file watching fails, the pet continues updating sessions/config via polling instead of appearing frozen.

### 🟡 Blocker 4: Graceful Shutdown
- **Changed**: `quit()` now sets `_shutdown = True` and waits for threads to exit
- **Added**: Final save of wellbeing + focus state before exit
- **Changed**: Uses `sys.exit(0)` instead of `os._exit(0)` to allow cleanup
- **Impact**: No orphaned control processes, no lost state on quit.

## Verification

```bash
# Syntax check
python -m py_compile desktop/main.py  # ✓ OK

# Dead code removed
Get-ChildItem -Recurse -File | Where-Object { $_.Name -match 'server\.js$|tui\.js$' }
# (no results)

# Architecture graph cleaned
Select-String -Path ARCHITECTURE_MAP.html -Pattern 'server-js|tui-js|package-json'
# Count: 0
```

## Files Modified

1. `desktop/main.py` — Added shutdown flag, watch failure recovery, graceful quit
2. `ARCHITECTURE_MAP.html` — Removed dead nodes/edges, corrected y-coordinates
3. `dist/server.js` — **DELETED**
4. `dist/tui.js` — **DELETED**

## Runtime Path (Simplified)

```
User launches OpenCodePet.exe
    ↓
main.py: PetEngine.__init__()
    ↓
    ├─ Load config, sprites, wellbeing, focus state
    ├─ Create GDI layered window (PetWindow)
    ├─ Start watcher thread (file watch + polling fallback)
    ├─ Start render loop thread (30 FPS)
    ├─ Spawn control process (pywebview dashboard)
    └─ Enter message pump (main thread)
        ↓
    Continuous: update_activity() → loop() → render frame
    Periodic:  watcher checks sessions/config/prune
    On event:  focus sessions, XP, bubbles, tray icons
    On quit:   graceful shutdown → save state → exit
```

**No Node.js runtime. No server.js. No tui.js. Pure Python + GDI + pywebview.**