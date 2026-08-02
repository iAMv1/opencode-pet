"""Benchmark frame cache build time per pet and _compose() time."""
import sys, time, os
sys.path.insert(0, r'C:\Users\ItzP\projects\opencode-pet')

from PIL import Image
from desktop.main import PETS, PET_STATES, _sprites_dir

print('=== Frame cache build times ===')
for pet in PETS:
    p = os.path.join(_sprites_dir(), pet['file'])
    t0 = time.perf_counter()
    im = Image.open(p)
    im.load()
    sheet = im.convert('RGBA')
    t_load = (time.perf_counter() - t0) * 1000

    w = pet['frameW'] * pet['scale']
    h = pet['frameH'] * pet['scale']
    states = pet.get('states') or PET_STATES
    total_frames = sum(s['frames'] for s in states)

    t0 = time.perf_counter()
    cache = {}
    for st in states:
        for i in range(st['frames']):
            sx = i * pet['frameW']
            sy = st['row'] * pet['frameH']
            f = sheet.crop((sx, sy, sx + pet['frameW'], sy + pet['frameH']))
            cache[(st['id'], i)] = f.resize((w, h), Image.NEAREST)
    t_build = (time.perf_counter() - t0) * 1000

    fw = w; fh = h
    bytes_per_frame = fw * fh * 4
    cache_kb = total_frames * bytes_per_frame / 1024
    sheet_kb = os.path.getsize(p) / 1024
    print(f'  {pet["id"]:15s}: sheet={sheet_kb:6.0f}KB  load={t_load:6.1f}ms  '
          f'crop+resize={t_build:6.1f}ms  {total_frames} frames  cache={cache_kb:.0f}KB')

