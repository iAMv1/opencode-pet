"""Benchmark read_status with varying file counts."""
import time, os, json, tempfile

def bench_read_status(tmpdir, n_files, iterations=20):
    # Write files
    for i in range(n_files):
        p = os.path.join(tmpdir, f'status-{i:04d}.json')
        with open(p, 'w') as f:
            json.dump({'updatedAt': int(time.time()*1000) - i*1000, 'state': 'busy',
                       'sessionID': f'sess-{i}'}, f)

    def read_status():
        files = [f for f in os.listdir(tmpdir) if f.startswith('status-') and f.endswith('.json')]
        now_ms = int(time.time() * 1000)
        out = []
        for fn in files:
            try:
                with open(os.path.join(tmpdir, fn), encoding='utf-8') as fh:
                    d = json.load(fh)
                d['stale'] = now_ms - (d.get('updatedAt') or 0) > 25000
                out.append(d)
            except Exception:
                pass
        out.sort(key=lambda s: s.get('updatedAt') or 0, reverse=True)
        return out

    # Warmup
    for _ in range(3):
        read_status()

    times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        result = read_status()
        t1 = time.perf_counter()
        times.append((t1 - t0) * 1000)

    avg = sum(times) / len(times)
    worst = max(times)
    print(f'  {n_files:3d} files: avg={avg:.2f} ms/call  worst={worst:.2f} ms  ({iterations} iterations)')
    return avg

for n in [5, 10, 20, 50, 100]:
    d = tempfile.mkdtemp(prefix=f'pet_status_{n}_')
    bench_read_status(d, n)
