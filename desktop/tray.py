"""System-tray icon and menu for the pet process."""

import os
import threading

import pystray
from PIL import Image, ImageDraw

from . import web


def create_tray(engine):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse([8, 8, 56, 56], fill="#6366f1", outline="#3b82f6", width=3)
    d.ellipse([20, 22, 30, 32], fill="white")
    d.ellipse([34, 22, 44, 32], fill="white")
    d.ellipse([24, 36, 40, 44], fill="white")

    def show(icon, item):
        engine.set_visible(True)

    def hide(icon, item):
        engine.set_visible(False)

    def settings(icon, item):
        web.spawn_control()

    def next_pet(icon, item):
        engine.set_pet(engine.cfg["petIdx"] + 1)

    def prev_pet(icon, item):
        engine.set_pet(engine.cfg["petIdx"] - 1)

    def start_focus(icon, item):
        engine.start_focus()

    def stop_focus(icon, item):
        engine.stop_focus()

    def quit_(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Show Pet", show),
        pystray.MenuItem("Hide Pet", hide),
        pystray.MenuItem("Focus 25 min", start_focus, checked=lambda item: engine.focus_active),
        pystray.MenuItem("Stop Focus", stop_focus, enabled=lambda item: engine.focus_active),
        pystray.MenuItem("Control App", settings),
        pystray.MenuItem("Next Pet", next_pet),
        pystray.MenuItem("Previous Pet", prev_pet),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_),
    )
    icon = pystray.Icon("opencode-pet", img, "OpenCode Pet", menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon
