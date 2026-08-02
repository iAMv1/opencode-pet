"""Benchmark _compose() per-frame cost and foreground_app overhead."""
import sys, time, os
sys.path.insert(0, r'C:\Users\ItzP\projects\opencode-pet')

from PIL import Image
from desktop.main import PETS, PET_STATES, _sprites_dir, foreground_app, last_input_ms

# --- _compose() timing ---
import desktop.main as dm
engine = dm.PetEngine.__new__(dm.PetEngine)
engine.pet = PETS[0]  # capvolt
p = os.path.join(_sprites_dir(), PETS[0]['file'])
engine.sheet = Image.open(p).convert('RGBA')
engine._build_frame_cache()
engine.anim = PET_STATES[0]
engine.frame_idx = 0
engine.acc = 0
engine.bubble_text = ''
engine.bubble_until = 0
engine._anim_id = lambda: 'idle'

# No bubble
times = []
for _ in range(2000):
    t0 = time.perf_counter()
    result = engine._compose()
    t1 = time.perf_counter()
    times.append((t1 - t0) * 1000)

avg = sum(times) / len(times)
print(f'_compose() no bubble:   avg={avg:.4f} ms  worst={max(times):.4f} ms  (2000 frames)')

# With bubble
engine.bubble_text = 'VS Code'
engine.bubble_until = time.time() + 10
times2 = []
for _ in range(1000):
    t0 = time.perf_counter()
    result = engine._compose()
    t1 = time.perf_counter()
    times2.append((t1 - t0) * 1000)

avg2 = sum(times2) / len(times2)
print(f'_compose() with bubble: avg={avg2:.4f} ms  worst={max(times2):.4f} ms  (1000 frames)')
print(f'  Bubble delta: +{(avg2-avg)*1000:.1f} us/frame')

# Image.new allocation cost
print()
print('=== Image.new RGBA allocation cost ===')
times3 = []
for _ in range(5000):
    t0 = time.perf_counter()
    img = Image.new('RGBA', (192, 208), (0, 0, 0, 0))
    t1 = time.perf_counter()
    times3.append((t1 - t0) * 1000)
    del img
avg3 = sum(times3) / len(times3)
print(f'  Image.new 192x208 RGBA: avg={avg3:.4f} ms  worst={max(times3):.4f} ms  (5000 iterations)')

# --- foreground_app() overhead ---
print()
print('=== foreground_app() call overhead ===')
times4 = []
for _ in range(50):
    t0 = time.perf_counter()
    app = foreground_app()
    t1 = time.perf_counter()
    times4.append((t1 - t0) * 1000)
avg4 = sum(times4) / len(times4)
print(f'  foreground_app(): avg={avg4:.2f} ms  worst={max(times4):.2f} ms  (50 calls)')
print(f'  At 2 Hz throttle: ~{avg4*2:.0f} ms/s CPU overhead')

# --- UpdateLayeredWindow timing (via render) ---
print()
print('=== win.render() / UpdateLayeredWindow ===')
import desktop.main as dm2
win = dm2.PetWindow.__new__(dm2.PetWindow)
win.hwnd = None  # skip GDI init, just measure the Python side

# Measure memmove + tobytes cost
img = Image.new('RGBA', (192, 208), (0, 0, 0, 0))
times5 = []
for _ in range(2000):
    t0 = time.perf_counter()
    raw = img.tobytes('raw', 'BGRA')
    t1 = time.perf_counter()
    times5.append((t1 - t0) * 1000)
avg5 = sum(times5) / len(times5)
print(f'  tobytes BGRA 192x208: avg={avg5:.4f} ms  worst={max(times5):.4f} ms')
print(f'  memmove 159KB into DIB: ~same as tobytes (included above)')
