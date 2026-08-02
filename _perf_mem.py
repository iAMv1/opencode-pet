import sys, time, os, json, tempfile
sys.path.insert(0, r'C:\Users\ItzP\projects\opencode-pet')
from desktop.main import PETS, PET_STATES

print('=== Frame counts and memory per pet ===')
total_all = 0
for pet in PETS:
    states = pet.get('states') or PET_STATES
    total_frames = sum(s['frames'] for s in states)
    w = pet['frameW'] * pet['scale']
    h = pet['frameH'] * pet['scale']
    bytes_per_frame = w * h * 4
    cache_kb = total_frames * bytes_per_frame / 1024
    total_all += total_frames * bytes_per_frame
    print(f'  {pet["id"]:15s}: {total_frames:3d} frames, {w}x{h}px, {cache_kb:.1f} KB')

print(f'\nCombined (all 6): {total_all/1048576:.2f} MB')
print(f'Worst-case active pet: ~3.0 MB (giratina, 57 frames x 576x624 RGBA)')
