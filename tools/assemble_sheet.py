# assemble_sheet.py - Gemini full-sheet PNG -> OpenCode Pet sheet.
# Input: one 1024x1024 (or NxM) 9-row grid on PURE BLACK bg, 8 cols per row.
# Pipeline: black-key -> uniform-grid slice -> bbox-fit each cell in 192x208
# -> compose exact 1536x1872 webp -> derive stage1/2/3 variants.
#
# Usage:
#   python tools/assemble_sheet.py <gemini.png> -o desktop/sprites/pet-<id>.webp --id <id>
import argparse
import os

from collections import deque

from PIL import Image

FRAME_W, FRAME_H = 192, 208
COLS, ROWS = 8, 9
SHEET_W, SHEET_H = FRAME_W * COLS, FRAME_H * ROWS
BLACK_TOL = 42


def black_key(im, tol=BLACK_TOL):
    """Remove only border-connected black background; preserve black outlines."""
    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    queue = deque()
    seen = set()

    def is_background(x, y):
        r, g, b, a = px[x, y]
        return a and r < tol and g < tol and b < tol

    for x in range(w):
        for y in (0, h - 1):
            if is_background(x, y):
                queue.append((x, y))
    for y in range(h):
        for x in (0, w - 1):
            if is_background(x, y):
                queue.append((x, y))

    while queue:
        x, y = queue.popleft()
        if (x, y) in seen or not is_background(x, y):
            continue
        seen.add((x, y))
        px[x, y] = (0, 0, 0, 0)
        for nx, ny in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in seen:
                queue.append((nx, ny))
    return rgba


def fit_cell(cell, tw=FRAME_W, th=FRAME_H, pad=10, bottom=8):
    out = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    bbox = cell.getchannel("A").getbbox()
    if bbox is None:
        return out
    cropped = cell.crop(bbox)
    bw, bh = cropped.size
    scale = min((tw - 2 * pad) / bw, (th - 2 * pad - bottom) / bh)
    nw, nh = max(1, int(bw * scale)), max(1, int(bh * scale))
    resized = cropped.resize((nw, nh), Image.NEAREST)
    out.paste(resized, ((tw - nw) // 2, th - nh - bottom), resized)
    return out


def slice_grid(im, cols=COLS, rows=ROWS):
    """Return cells[row][col] from a uniform grid."""
    w, h = im.size
    cw, ch = w // cols, h // rows
    grid = [[None] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            cell = im.crop((c * cw, r * ch, (c + 1) * cw, (r + 1) * ch))
            grid[r][c] = cell
    return grid


def bounds(grid):
    """Detect actual content bounds so a 1024 image is sliced right even if
    Gemini leaves margins or draws rows at slightly different heights."""
    w, h = 1024, 1024
    cw, ch = w // 8, h // 9
    xmin = xmax = None
    for r in range(9):
        for c in range(8):
            b = grid[r][c].getchannel("A").getbbox()
            if not b:
                continue
            cell_x = c * cw
            cell_y = r * ch
            if xmin is None or cell_x + b[0] < xmin:
                xmin = cell_x + b[0]
            if xmax is None or cell_x + b[2] > xmax:
                xmax = cell_x + b[2]
    return xmin or 0, xmax or w


def main():
    ap = argparse.ArgumentParser(description="Compose an 8x9 OpenCode Pet sheet from a Gemini grid.")
    ap.add_argument("src")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--id", required=True, help="pet id (writes pet-<id>-stageN.webp too)")
    ap.add_argument("--no-stages", action="store_true")
    ap.add_argument("--grid-h", type=int, default=9, help="rows in the source image")
    args = ap.parse_args()

    outdir = os.path.dirname(os.path.abspath(args.out)) or "."
    os.makedirs(outdir, exist_ok=True)

    im = black_key(Image.open(args.src))
    w, h = im.size
    cols = 8
    cw, ch = w // cols, h // args.grid_h

    sheet = Image.new("RGBA", (SHEET_W, SHEET_H), (0, 0, 0, 0))
    for r in range(args.grid_h):
        for c in range(cols):
            cell = im.crop((c * cw, r * ch, (c + 1) * cw, (r + 1) * ch))
            fitted = fit_cell(cell)
            sheet.paste(fitted, (c * FRAME_W, r * FRAME_H), fitted)
    sheet.save(args.out, "WEBP", lossless=True)
    print("base:", args.out, sheet.size)

    if not args.no_stages:
        for sfx, name, sc in (("stage1", "baby", 0.62),
                              ("stage2", "growing", 0.84),
                              ("stage3", "evolved", 1.05)):
            s = sheet.resize((int(SHEET_W * sc), int(SHEET_H * sc)), resample=Image.NEAREST)
            cv = Image.new("RGBA", (SHEET_W, SHEET_H), (0, 0, 0, 0))
            cv.paste(s, ((SHEET_W - s.size[0]) // 2, (SHEET_H - s.size[1]) // 2), s)
            p = os.path.join(outdir, f"pet-{args.id}-{sfx}.webp")
            cv.save(p, "WEBP", lossless=True)
            print("stage:", p, "(scale %.2f)" % sc)


if __name__ == "__main__":
    main()
