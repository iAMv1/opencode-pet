"""Sprite registry and rendering: pet sheets, per-frame caches, previews."""

import base64
import io
import os
import sys
import threading

from PIL import Image

# Same 9-state petdex layout; rows = state rows in the sheet.
PET_STATES = [
    {"id": "idle", "row": 0, "frames": 6, "durationMs": 1100},
    {"id": "running-right", "row": 1, "frames": 8, "durationMs": 1060},
    {"id": "running-left", "row": 2, "frames": 8, "durationMs": 1060},
    {"id": "waving", "row": 3, "frames": 4, "durationMs": 700},
    {"id": "jumping", "row": 4, "frames": 5, "durationMs": 840},
    {"id": "failed", "row": 5, "frames": 8, "durationMs": 1220},
    {"id": "waiting", "row": 6, "frames": 6, "durationMs": 1010},
    {"id": "walking", "row": 7, "frames": 6, "durationMs": 820},
    {"id": "review", "row": 8, "frames": 6, "durationMs": 1030},
]
DEFAULT_MAP = {
    "idle": "idle", "busy": "walking", "thinking": "review",
    "error": "failed", "success": "jumping",
    "waiting": "waiting",
}


def sprites_dir():
    if getattr(sys, "_MEIPASS", None):
        return os.path.join(sys._MEIPASS, "sprites")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "sprites")


def sprite_path(name):
    p = os.path.join(sprites_dir(), name)
    if os.path.exists(p):
        return p
    # fallback: source-tree sprites (dev runs)
    alt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "desktop", "sprites", name)
    return alt if os.path.exists(alt) else p


PETS = [
    {"id": "capvolt", "name": "Pikachu", "file": "pet-capvolt.webp", "frameW": 192, "frameH": 208, "scale": 1, "map": DEFAULT_MAP},
    {"id": "charmander", "name": "Charmander", "file": "pet-charmander.webp", "frameW": 192, "frameH": 208, "scale": 1, "map": DEFAULT_MAP},
    {"id": "doraemon", "name": "Doraemon", "file": "pet-doraemon.webp", "frameW": 192, "frameH": 208, "scale": 1, "map": DEFAULT_MAP},
    {"id": "gardevoir", "name": "Gardevoir", "file": "pet-gardevoir.webp", "frameW": 192, "frameH": 208, "scale": 1, "map": DEFAULT_MAP},
    {"id": "giratina", "name": "Giratina", "file": "pet-giratina.webp", "frameW": 192, "frameH": 208, "scale": 1, "map": DEFAULT_MAP},
     {"id": "lpc-cat", "name": "LPC Cat", "file": "pet-lpc-cat.png", "frameW": 64, "frameH": 64, "scale": 3,
      "states": [
          {"id": "idle", "row": 0, "frames": 8, "durationMs": 1100},
          {"id": "running-right", "row": 1, "frames": 8, "durationMs": 900},
          {"id": "running-left", "row": 2, "frames": 8, "durationMs": 900},
          {"id": "waiting", "row": 0, "frames": 8, "durationMs": 1500},
      ],
      "map": {"idle": "idle", "busy": "running-right", "thinking": "idle", "error": "idle",
              "success": "idle", "celebrating": "idle", "stale": "waiting", "waiting": "waiting"}},
     {"id": "emberkit", "name": "Emberkit", "file": "pet-emberkit.webp", "frameW": 192, "frameH": 208, "scale": 1, "map": DEFAULT_MAP},
 ]


def pet_states(pet):
    return pet.get("states") or PET_STATES


# ---------------------------------------------------------------- previews
PREVIEW_H = 80

_PREVIEW_CACHE = None
_PREVIEW_LOCK = threading.Lock()


def _preview_strip(pet):
    """Tiles the idle row into one horizontal strip, returned as a data URI."""
    p = sprite_path(pet["file"])
    try:
        sheet = Image.open(p).convert("RGBA")
    except Exception:
        return None
    st = pet_states(pet)[0]
    fw, fh = pet["frameW"], pet["frameH"]
    nw = max(1, int(fw * PREVIEW_H / fh))
    strip = Image.new("RGBA", (nw * st["frames"], PREVIEW_H), (0, 0, 0, 0))
    for i in range(st["frames"]):
        try:
            frame = sheet.crop((i * fw, st["row"] * fh, (i + 1) * fw, (st["row"] + 1) * fh))
            frame = frame.resize((nw, PREVIEW_H), Image.NEAREST)
            strip.alpha_composite(frame, (i * nw, 0))
        except Exception:
            continue
    buf = io.BytesIO()
    strip.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def build_previews():
    """All pet preview strips, generated once and cached for the process."""
    global _PREVIEW_CACHE
    with _PREVIEW_LOCK:
        if _PREVIEW_CACHE is not None:
            return _PREVIEW_CACHE
        out = []
        for pet in PETS:
            st = pet_states(pet)[0]
            out.append({
                "id": pet["id"],
                "name": pet["name"],
                "strip": _preview_strip(pet),
                "frames": st["frames"],
                "durationMs": st["durationMs"],
                "frameW": max(1, int(pet["frameW"] * PREVIEW_H / pet["frameH"])),
                "frameH": PREVIEW_H,
            })
        _PREVIEW_CACHE = out
        return _PREVIEW_CACHE
