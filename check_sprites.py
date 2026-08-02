from PIL import Image
import os

sprites_dir = r'C:\Users\ItzP\projects\opencode-pet\desktop\sprites'

PETS_DEF = [
    ('pet-capvolt.webp',    192, 208, 1),
    ('pet-charmander.webp', 192, 208, 1),
    ('pet-doraemon.webp',   192, 208, 1),
    ('pet-gardevoir.webp',  192, 208, 1),
    ('pet-giratina.webp',   192, 208, 1),
    ('pet-lpc-cat.png',     64,   64, 3),
]

PET_STATES_ROWS = [
    ('idle',          0, 6),
    ('running-right', 1, 8),
    ('running-left',  2, 8),
    ('waving',        3, 4),
    ('jumping',       4, 5),
    ('failed',        5, 8),
    ('waiting',       6, 6),
    ('running',       7, 6),
    ('review',        8, 6),
]

LPC_STATES = [
    ('idle',          0, 8),
    ('running-right', 1, 8),
    ('running-left',  2, 8),
    ('waiting',       0, 8),
]

issues  = []
warnings = []
ok_count = 0

for fname, fw, fh, scale in PETS_DEF:
    p = os.path.join(sprites_dir, fname)
    if not os.path.exists(p):
        issues.append('MISSING: ' + fname)
        continue
    im = Image.open(p)
    iw, ih = im.size
    cols = iw // fw
    rows = ih // fh
    out_w = fw * scale
    out_h = fh * scale
    is_lpc = (fname == 'pet-lpc-cat.png')
    states = LPC_STATES if is_lpc else PET_STATES_ROWS
    print(f'\n=== {fname} ===')
    print(f'  size={iw}x{ih}  grid={cols}x{rows} cells  rendered={out_w}x{out_h}')
    if iw % fw != 0:
        issues.append(f'{fname}: width {iw} not divisible by frameW={fw}')
    if ih % fh != 0:
        issues.append(f'{fname}: height {ih} not divisible by frameH={fh}')
    if is_lpc and rows != 3:
        warnings.append(f'{fname}: LPC uses rows 0-2 (3 rows=192px) but file has {rows} rows ({ih}px). Row 3 is unused. (main.py L211-219)')
    for sname, row, nframes in states:
        if row >= rows:
            issues.append(f'{fname} state "{sname}": row={row} out of range (sheet has {rows} rows)')
            continue
        if nframes > cols:
            issues.append(f'{fname} state "{sname}": needs {nframes} cols but sheet has {cols}')
            continue
        right_edge = nframes * fw
        if right_edge > iw:
            issues.append(f'{fname} state "{sname}": crop right={right_edge} > sheet width {iw}')
        else:
            ok_count += 1
            print(f'  OK  {sname}: row={row} crop=[0,{row*fh}..{nframes*fw},{(row+1)*fh}) {nframes} frames')

# Standard pets: rows 0-8 must be accessible
print('\n=== Standard pet row coverage ===')
for fname, fw, fh, scale in PETS_DEF:
    if fname == 'pet-lpc-cat.png':
        continue
    p = os.path.join(sprites_dir, fname)
    im = Image.open(p)
    actual_rows = ih = im.height // fh
    max_declared = max(r for _, r, _ in PET_STATES_ROWS)
    ok = actual_rows > max_declared
    print(f'  {fname}: sheet_rows={actual_rows} max_declared_row={max_declared} {"OK" if ok else "ERROR"}')
    if not ok:
        issues.append(f'{fname}: rows={actual_rows} insufficient for max declared row {max_declared}')

# LPC _anim_id resolution: is 'running' ever reachable?
print('\n=== LPC _anim_id resolution ===')
lpc_map = {'idle':'idle','busy':'running-right','thinking':'idle','error':'idle','success':'idle','celebrating':'idle','stale':'waiting','waiting':'waiting'}
lpc_ids = [s[0] for s in LPC_STATES]
for our_state in ['idle','busy','thinking','error','success','celebrating','stale','waiting','running']:
    aid = lpc_map.get(our_state, 'idle')
    hit = aid in lpc_ids
    print(f'  _state="{our_state}" -> anim_id="{aid}" in LPC states={hit}')
    if not hit:
        warnings.append(f'LPC: _anim_id would return "{aid}" for state "{our_state}" but no frame cache entry exists')

print(f'\n=== RESULTS ===')
print(f'Errors  : {len(issues)}')
for e in issues:  print(f'  ERROR: {e}')
print(f'Warnings: {len(warnings)}')
for w in warnings: print(f'  WARN : {w}')
print(f'Valid frame-cache entries: {ok_count}')
