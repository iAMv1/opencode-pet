# sprite_forge.py - Gemini(Nano Banana) -> OpenCode Pet sprite sheets.
# Pipeline: chroma key -> trim -> palette snap -> fit frame -> compose 8x9 sheet
# -> derive evolution stages (baby/growing/evolved) programmatically.
#
# Usage:
#   python sprite_forge.py forge <gemini_png> -o out/pet-fox.webp --id fox
#   python sprite_forge.py sheet -o out/pet-fox.webp --id fox
#
# Sheet contract (see desktop/main.py PETS/evolution_stage):
#   1536x1872, 8 cols x 9 rows, frame 192x208 RGBA, zero-based rows:
#   r0 idle (open) r6 wait (near) wait  r9 review
#   row0 idle, row1 running-right, row2 running-left, row3 waving,
#   row4 jumping, row5 failed, row6 waiting, row7 walking, row8 review
# Evolution stages: pet-<id>-stage1/2/3.webp near the base sheet:
#   stage1 = baby, stage2 = growing, stage3 = evolved.

import argparse
import os
import sys

from PIL import Image, ImageOps

FRAME_W, FRAME_H = 192, 208
COLS, ROWS = 8, 9
SHEET_W, SHEET_H = FRAME_W * COLS, FRAME_H * ROWS
GREEN = (0, 255, 0)


def chroma_key(im, target=(0, 200, 0), tol=90, despill=0.45):
    rgba = im.convert("RGBA")
    px = rgba.load()
    w, h = rgba.size
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a == 0:
                continue
            if g > r and g > b and (g - max(r, b)) >= tol * 0.45:
                # green-ish: reduce green spill toward neighbor-in window fading to alpha
                spill = max(0, min(255, int(g - (max(r, b) + despill * g))))
                px[x, y] = (r, b, 0, 0) if spill == 0 else (r, b, max(0, g - spill),
                                                             max(0, a - int(spill)))
            elif g > (r + b) // 2 and (g - max(r, b)) > 60:
                # blended edge toward green: kill alpha progressively
                d = g - max(r, b)
                if d > 140:  # strongly green -> full transparent
                    px[x, y] = (0, 0, 0, 0)
                else:
                    alpha = max(0, a - int(d * 1.6))
                    # blunt the spill: pull g toward max(r,b)
                    px[x, y] = (r, max(r, b) - int((g - max(r, b)) * 0.5), b, alpha)
    return rgba


def trim_bbox(im):
    return im.getchannel("A").getbbox()


def snap_palette(im, palette=((0, 0, 0, 255), (255, 255, 255, 255))):
    """Quantize to hard pixel-art colors by picking nearest at 8x block centers."""
    rgba = im.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()
    for y in range(0, h, 8):
        for x in range(0, w, 8):
            r, g, b, a = px[x, y]
            if a < 200:
                continue
            best = None
            best_d = 1e9
            for (pr, pg, pb, pa) in palette:
                d = (r - pr) ** 2 + (g - pg) ** 2 + (b - pb) ** 2
                if d < best_d:
                    best_d = d
                    best = (pr, pg, pb, pa)
            px[x, y] = best
    return rgba


def fit_frame(im, frame_w=FRAME_W, frame_h=FRAME_H, bg=(0, 0, 0, 0)):
    """Crop bbox, fit preserving aspect with 4px padding, center on a transparent frame."""
    out = Image.new("RGBA", (frame_w, frame_h), bg)
    bbox = im.getchannel("A").getbbox()
    if bbox is None:
        return out
    cropped = im.crop(bbox)
    bw, bh = cropped.size
    max_w, max_h = frame_w - 12, frame_h - 16
    scale = min(max_w / bw, max_h / bh)
    if scale > 1:
        # upscale a normal gemini 1024 crop in hard nearest mode
        pass
    new_w = max(1, int(bw * scale))
    new_h = max(1, int(bh * scale))
    crop = cropped.resize((new_w, new_h), resample=Image.NEAREST)
    out.paste(crop, ((frame_w - new_w) // 2, frame_h - new_h - 10), crop)
    return out


def compose_sheet(frames_row0, frames=None, out=None):
    """Build 8x9 sheet from maps row->[frame IDs]. Missing rows stay empty."""
    sheet = Image.new("RGBA", (SHEET_W, SHEET_H), (0, 0, 0, 0))
    rows = frames_row0 if frames is None else frames
    for r, flist in rows.items():
        for c, im in enumerate(flist[:COLS]):
            if im is None:
                continue
            sheet.paste(im, (c * FRAME_W, r * FRAME_H), im)
    if out:
        sheet.save(out, "WEBP", lossless=True)
    return sheet


def derive_stage(base, scale, hue_shift=0):
    """Programmatic evolution: pick a vertical band, resize, optional hue tint.
    stages: stage1 baby (0.62 scale), stage2 growing (0.84), stage3 evolved (1.05).
    """
    return base.resize((int(SHEET_W * scale), int(SHEET_H * scale)), resample=Image.NEAREST)


BABY_SCALE = 0.62
GROW_SCALE = 0.84
EVO_SCALE = 1.05


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("forge", help="chroma key + fit one strip/big image to a 8x9 sheet")
    f.add_argument("src", nargs="+", help="gemini png(s)")
    f.add_argument("-o", "--out", required=True)
    f.add_argument("--id", required=True, help="pet id, writes stage1/2/3 variants next to -o")
    f.add_argument("--no-stages", action="store_true", help="skip stage variants")

    s = sub.add_parser("sheet", help="compose rows manually")
    s.add_argument("-o", "--out", required=True)
    s.add_argument("--row", action="append", default=[], help="row=ID:path[,path...]")

    args = ap.parse_args()

    if args.cmd == "forge":
        outdir = os.path.dirname(os.path.abspath(args.out))
        os.makedirs(outdir, exist_ok=True)
        base_out = args.out
        # merge a single large 1024x1024 into the top-left idle cell
        first = args.src[0]
        im = chroma_key(Image.open(first), GREEN, 110)
        im = fit_frame(im)
        cells = {}
        for r in range(ROWS):
            cells[r] = [None] * COLS
        if args.src:
            cells[0][0] = im
        sheet = compose_sheet(cells)
        sheet.save(base_out, "WEBP", lossless=True)
        print("base:", base_out, sheet.size)

        if not args.no_stages:
            for sfx, name, sc in (("stage1", "baby", BABY_SCALE),
                                  ("stage2", "growing", GROW_SCALE),
                                  ("stage3", "evolved", EVO_SCALE)):
                st = sheet.resize((int(SHEET_W * sc), int(SHEET_H * sc)),
                                  resample=Image.NEAREST)
                st_canvas = Image.new("RGBA", (SHEET_W, SHEET_H), (0, 0, 0, 0))
                st_canvas.paste(st, ((SHEET_W - st.size[0]) // 2,
                                     (SHEET_H - st.size[1]) // 2), st)
                path = os.path.join(outdir, f"pet-{args.id}-{sfx}.webp")
                st_canvas.save(path, "WEBP", lossless=True)
                print("stage:", path, "(scale %.2f)" % sc)
    elif args.cmd == "sheet":
        cells = {}
        for r in range(ROWS):
            cells[r] = [None] * COLS
        for spec in args.row:
            row_kv, paths = spec.split("=", 1)
            idx = int(row_kv)
            items = [Image.open(p).convert("RGBA") for p in paths.split(",") if p]
            frames = [fit_frame(chroma_key(img, GREEN, 110)) for img in items]
            for c, fr in enumerate(frames[:COLS]):
                cells[idx][c] = fr
        compose_sheet(cells, out=args.out)
        print("sheet:", os.path.abspath(args.out))


if __name__ == "__main__":
    main()