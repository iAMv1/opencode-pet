# build_strip_sheet.py - proper per-state strip pipeline.
# For each state: Gemini strip PNG -> gap-detect frames -> key bg -> fit 192x208
# -> compose 1536x1872 with empty cells, same contract as Pikachu.
import os
import re
import sys
from PIL import Image

FRAME_W, FRAME_H = 192, 208
COLS, ROWS = 8, 9
SHEET_W, SHEET_H = FRAME_W * COLS, FRAME_H * ROWS

# state: (row, expected frames, source strip paths in order)
STATES = {
    "idle": (0, 6, []),
    "running-right": (1, 8, []),
    "running-left": (2, 8, []),
    "waving": (3, 4, []),
    "jumping": (4, 5, []),
    "failed": (5, 8, []),
    "waiting": (6, 6, []),
    "walking": (7, 6, []),
    "review": (8, 6, []),
}

BG_TOL = 40


def key_bg(im, tol=BG_TOL):
    """Remove near-black background -> alpha. Keeps dark sprite pixels by only
    removing pixels whose neighbours are also dark (avoids eating black outlines)."""
    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            lum = (r + g + b) // 3
            if lum < tol:
                # require the surrounding 3x3 to also be dark to call it bg
                dark = 0
                for dy in (-1, 0, 1):
                    for dx in (-1, 0, 1):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < w and 0 <= ny < h:
                            nr, ng, nb, _ = px[nx, ny]
                            if (nr + ng + nb) // 3 < tol + 20:
                                dark += 1
                if dark >= 5:
                    px[x, y] = (0, 0, 0, 0)
    return rgba


def gap_frames(im, expected, gap_px=6):
    """Split strip into frames by detecting dark vertical gaps."""
    rgba = key_bg(im)
    w, h = rgba.size
    px = rgba.load()
    col_empty = []
    for x in range(w):
        op = 0
        for y in range(0, h, 4):
            if px[x, y][3] > 40:
                op += 1
        col_empty.append(op)
    # find vertical bands with low opacity
    frames = []
    in_frame = False
    start = 0
    for x in range(w):
        is_gap = col_empty[x] <= 1
        if not in_frame and not is_gap:
            in_frame = True
            start = x
        elif in_frame and is_gap and x - start > 8:
            frames.append((start, x))
            in_frame = False
    if in_frame:
        frames.append((start, w - 1))
    # if we found way more than expected, merge by picking widest expected count
    if len(frames) > expected:
        widths = [(e - s, s, e) for s, e in frames]
        widths.sort(reverse=True)
        frames = [(s, e) for _, s, e in sorted(widths[:expected], key=lambda t: t[1])]
    return frames[:expected]


def fit_cell(im, tw=FRAME_W, th=FRAME_H, pad=10, bottom=8):
    out = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    bbox = im.getchannel("A").getbbox()
    if bbox is None:
        return out
    cropped = im.crop(bbox)
    bw, bh = cropped.size
    scale = min((tw - 2 * pad) / bw, (th - 2 * pad - bottom) / bh)
    if scale > 1:
        scale = 1
    nw, nh = max(1, int(bw * scale)), max(1, int(bh * scale))
    resized = cropped.resize((nw, nh), resample=Image.NEAREST)
    out.paste(resized, ((tw - nw) // 2, th - nh - bottom), resized)
    return out


def main():
    sheets = []
    for arg in sys.argv[1:]:
        name, path = arg.split("=", 1)
        sheets.append((name, path))
    sheet = Image.new("RGBA", (SHEET_W, SHEET_H), (0, 0, 0, 0))
    used = set()
    for name, path in sheets:
        st = STATES[name]
        row, expected = st[0], st[1]
        im = Image.open(path)
        frames = gap_frames(im, expected)
        print(f"{name}: found {len(frames)} frames (expected {expected})")
        for c, (s, e) in enumerate(frames[:expected]):
            cell = im.crop((s, 0, e + 1, im.size[1]))
            fitted = fit_cell(key_bg(cell))
            sheet.paste(fitted, (c * FRAME_W, row * FRAME_H), fitted)
        used.add(name)
    for name, (row, expected, _) in STATES.items():
        if name not in used:
            print(f"WARNING: missing state {name} - row {row} left empty")
    out = r"desktop\sprites\pet-emberkit.webp"
    sheet.save(out, "WEBP", lossless=True)
    print("saved", out, sheet.size)


if __name__ == "__main__":
    main()
