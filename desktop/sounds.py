"""Native chimes via winsound (stdlib, Windows only).

Synchronous but short (80-120ms per tone) — never blocks the render loop
meaningfully. Every tone is guarded: headless runs, test patches, and audio
failures all degrade to silence instead of crashes.
"""

import winsound

# kind -> [(freq Hz, duration ms), ...]
CHIMES = {
    "start": [(523, 80), (784, 80)],      # 2 rising tones
    "complete": [(523, 80), (659, 80), (784, 120)],  # 3 rising tones
    "break": [(262, 120)],                # 1 low soft tone
    "stretch": [(440, 100)],              # 1 mid tone
}


def play(kind):
    for freq, ms in CHIMES.get(kind, []):
        try:
            winsound.Beep(freq, ms)
        except Exception:
            return
