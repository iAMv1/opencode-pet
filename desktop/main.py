"""OpenCode Pet — standalone desktop pet.

Architecture (why):
  - The PET is a GDI layered window (UpdateLayeredWindow): per-pixel alpha is
    guaranteed, the window is exactly sprite-sized, and dragging anywhere is
    native (WM_NCHITTEST -> HTCAPTION). WebView2's compositor ignores OS-level
    transparency, which is why the previous box/pink/white attempts failed.
  - The CONTROL app is a pywebview window in its own process: pet picker +
    behavior settings. It talks to the pet through config.json + one-shot
    commands, so the pet process never hosts a browser.
  - All data is LOCAL (config.json + status files in ~/.opencode/pet). Nothing
    leaves the machine.
"""

import os
import sys
import io
import json
import time
import struct
import base64
import threading
import ctypes
from ctypes import wintypes
import pystray
from PIL import Image, ImageDraw, ImageFont

# ---------------------------------------------------------------- constants
PET_DIR = os.path.join(os.path.expanduser("~"), ".opencode", "pet")
CONFIG_FILE = os.path.join(PET_DIR, "config.json")
ACTIVITY_LOG = os.path.join(PET_DIR, "activity.jsonl")
WELLBEING_FILE = os.path.join(PET_DIR, "wellbeing.json")
STALE_MS = 25000
ACTIVE_MS = 30000

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

# GDI / window constants
WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
AC_SRC_OVER = 0
AC_SRC_ALPHA = 1
ULW_ALPHA = 2
WM_NCHITTEST = 0x0084
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_MOVE = 0x0003
WM_DESTROY = 0x0002
WM_HOTKEY = 0x0312
HTCAPTION = 2
HTCLIENT = 1
GW_HINSTANCE = -6
HOTKEY_TOGGLE_PET = 1   # Ctrl+Shift+P
HOTKEY_OPEN_DASH = 2    # Ctrl+Shift+D

SPI_GETWORKAREA = 0x0030


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]


class MSG(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                ("time", wintypes.DWORD), ("pt", POINT)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_byte), ("BlendFlags", ctypes.c_byte),
                ("SourceConstantAlpha", ctypes.c_byte), ("AlphaFormat", ctypes.c_byte)]


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", ctypes.c_long),
        ("biYPelsPerMeter", ctypes.c_long), ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER)]


class WNDCLASS(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT), ("lpfnWndProc", ctypes.c_void_p), ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HANDLE), ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

# --- argtypes (prevents 64-bit pointer overflow on lParam/WPARAM) ---
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_ssize_t
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
user32.CreateWindowExW.restype = wintypes.HWND
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASS)]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.PostQuitMessage.argtypes = [ctypes.c_int]
user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongW.restype = ctypes.c_long
user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
user32.SetWindowLongW.restype = ctypes.c_long
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.UpdateLayeredWindow.argtypes = [wintypes.HWND, wintypes.HDC, ctypes.POINTER(POINT), ctypes.POINTER(SIZE),
                                       wintypes.HDC, ctypes.POINTER(POINT), wintypes.DWORD,
                                       ctypes.POINTER(BLENDFUNCTION), wintypes.DWORD]
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.CreateDIBSection.argtypes = [wintypes.HDC, ctypes.POINTER(BITMAPINFO), wintypes.UINT,
                                   ctypes.POINTER(ctypes.c_void_p), wintypes.HANDLE, wintypes.DWORD]
gdi32.CreateDIBSection.restype = ctypes.c_void_p
user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = ctypes.c_long
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = ctypes.c_long
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.SetCapture.argtypes = [wintypes.HWND]
user32.SetCapture.restype = wintypes.HWND
user32.ReleaseCapture.argtypes = []
user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
user32.RegisterHotKey.restype = wintypes.BOOL
user32.GetDoubleClickTime.restype = wintypes.UINT

# ---------------------------------------------------------------- sprite data
# Same 9-state petdex layout; rows = state rows in the sheet.
PET_STATES = [
    {"id": "idle", "row": 0, "frames": 6, "durationMs": 1100},
    {"id": "running-right", "row": 1, "frames": 8, "durationMs": 1060},
    {"id": "running-left", "row": 2, "frames": 8, "durationMs": 1060},
    {"id": "waving", "row": 3, "frames": 4, "durationMs": 700},
    {"id": "jumping", "row": 4, "frames": 5, "durationMs": 840},
    {"id": "failed", "row": 5, "frames": 8, "durationMs": 1220},
    {"id": "waiting", "row": 6, "frames": 6, "durationMs": 1010},
    {"id": "running", "row": 7, "frames": 6, "durationMs": 820},
    {"id": "review", "row": 8, "frames": 6, "durationMs": 1030},
]
DEFAULT_MAP = {
    "idle": "idle", "busy": "running", "thinking": "review",
    "error": "failed", "success": "jumping", "celebrating": "waving",
    "stale": "waiting", "waiting": "waiting",
}


def _sprites_dir():
    if getattr(sys, "_MEIPASS", None):
        return os.path.join(sys._MEIPASS, "sprites")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "sprites")


def _res(name):
    p = os.path.join(_sprites_dir(), name)
    if os.path.exists(p):
        return p
    # fallback: source-tree sprites (dev runs)
    alt = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "desktop", "sprites", name)
    return alt if os.path.exists(alt) else p


def _file(name):
    """Bundled non-sprite asset (app.html/control.html). MEIPASS first, then source tree."""
    if getattr(sys, "_MEIPASS", None):
        for sub in ("", "desktop/"):
            p = os.path.join(sys._MEIPASS, sub, name)
            if os.path.exists(p):
                return p
    p = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
    return p if os.path.exists(p) else None


PETS = [
    {"id": "capvolt", "name": "Pikachu", "file": "pet-capvolt.webp", "frameW": 192, "frameH": 208, "scale": 1, "map": DEFAULT_MAP},
    {"id": "charmander", "name": "Charmander", "file": "pet-charmander.webp", "frameW": 192, "frameH": 208, "scale": 1, "map": DEFAULT_MAP},
    {"id": "doraemon", "name": "Doraemon", "file": "pet-doraemon.webp", "frameW": 192, "frameH": 208, "scale": 1, "map": DEFAULT_MAP},
    {"id": "gardevoir", "name": "Gardevoir", "file": "pet-gardevoir.webp", "frameW": 192, "frameH": 208, "scale": 1, "map": DEFAULT_MAP},
    {"id": "giratina", "name": "Giratina", "file": "pet-giratina.webp", "frameW": 192, "frameH": 208, "scale": 1, "map": DEFAULT_MAP},
    {"id": "lpc-cat", "name": "LPC Cat", "file": "pet-lpc-cat.png", "frameW": 64, "frameH": 64, "scale": 3,
     "states": [
         {"id": "idle", "row": 0, "frames": 8, "durationMs": 1100},
         {"id": "running-right", "row": 1, "frames": 8, "durationMs": 900},
         {"id": "running-left", "row": 2, "frames": 8, "durationMs": 900},
         {"id": "waiting", "row": 0, "frames": 8, "durationMs": 1500},
     ],
     "map": {"idle": "idle", "busy": "running-right", "thinking": "idle", "error": "idle",
             "success": "idle", "celebrating": "idle", "stale": "waiting", "waiting": "waiting"}},
]


def pet_states(pet):
    return pet.get("states") or PET_STATES


# ---------------------------------------------------------------- config
def load_config():
    default = {"petIdx": 0, "alwaysOnTop": True, "walk": 100, "breakMin": 50}
    try:
        with open(CONFIG_FILE, encoding="utf-8") as fh:
            default.update(json.load(fh))
    except Exception:
        pass
    return default


def save_config(conf):
    try:
        os.makedirs(PET_DIR, exist_ok=True)
        with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
            json.dump(conf, fh)
    except Exception:
        pass


# ---------------------------------------------------------------- GDI layered window
class PetWindow:
    """A GDI layered always-on-top tool window that renders RGBA frames."""

    def __init__(self):
        self.hwnd = None
        self.w, self.h = 192, 208
        self._wc = None
        self._bits = ctypes.c_void_p()
        self._bmp = None
        self._memdc = None
        self._old_bmp = None
        self._wndproc = None
        self.engine = None
        self._drag = None
        self._down_pt = None
        self._down_t = 0.0
        self._last_click = None
        self._create()
        self._register_hotkeys()

    def _create(self):
        hinst = kernel32.GetModuleHandleW(None)
        cls = "OpenCodePetLayer"
        self._wndproc = WNDPROC(self._proc)
        wc = WNDCLASS()
        wc.style = 0
        wc.lpfnWndProc = ctypes.cast(self._wndproc, ctypes.c_void_p)
        wc.hInstance = hinst
        wc.lpszClassName = cls
        user32.RegisterClassW(ctypes.byref(wc))
        self._wc = wc
        hwnd = user32.CreateWindowExW(
            WS_EX_LAYERED | WS_EX_TOOLWINDOW | WS_EX_TOPMOST,
            cls, "", WS_POPUP,
            0, 0, self.w, self.h, None, None, hinst, None)
        self.hwnd = hwnd

    def _register_hotkeys(self):
        try:
            user32.RegisterHotKey(self.hwnd, HOTKEY_TOGGLE_PET, 0x0002 | 0x0004, 0x50)  # Ctrl+Shift+P
            user32.RegisterHotKey(self.hwnd, HOTKEY_OPEN_DASH, 0x0002 | 0x0004, 0x44)   # Ctrl+Shift+D
        except Exception:
            pass

    def _proc(self, hwnd, msg, wp, lp):
        if msg == WM_NCHITTEST:
            return HTCLIENT  # manual drag (see below) so physics stays in sync
        if msg == WM_HOTKEY:
            if wp == HOTKEY_TOGGLE_PET and self.engine:
                self.engine.set_visible(not self.engine.win.is_visible())
            elif wp == HOTKEY_OPEN_DASH and self.engine:
                try:
                    spawn_control()
                except Exception:
                    pass
            return 0
        if msg == WM_LBUTTONDOWN:
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            self._drag = (pt.x, pt.y, int(self.engine.phys["x"]) if self.engine else 0,
                          int(self.engine.phys["y"]) if self.engine else 0)
            self._down_pt = (pt.x, pt.y)
            self._down_t = time.monotonic()
            if self.engine:
                self.engine.dragging = True
            user32.SetCapture(hwnd)
            return 0
        if msg == WM_MOUSEMOVE:
            if self._drag and self.engine:
                pt = POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                cx, cy, wx, wy = self._drag
                nx = wx + (pt.x - cx)
                ny = wy + (pt.y - cy)
                self.engine.phys["x"] = nx
                self.engine.phys["y"] = ny
                self.engine._last_pos = (nx, ny)
                self.move(nx, ny)
            return 0
        if msg == WM_LBUTTONUP:
            if self._drag:
                self._drag = None
                if self.engine:
                    self.engine.dragging = False
                user32.ReleaseCapture()
            if self._down_pt is not None:
                pt = POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                dx, dy = pt.x - self._down_pt[0], pt.y - self._down_pt[1]
                self._down_pt = None
                moved = (dx * dx + dy * dy) ** 0.5
                if self.engine and moved < 6 and (time.monotonic() - self._down_t) < 0.8:
                    self._handle_click(pt)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _handle_click(self, pt):
        eng = self.engine
        now = time.monotonic()
        dbl = user32.GetDoubleClickTime() / 1000.0
        if self._last_click and now - self._last_click[0] < dbl \
                and abs(self._last_click[1] - pt.x) < 8 and abs(self._last_click[2] - pt.y) < 8:
            self._last_click = None
            eng.jump()
        else:
            self._last_click = (now, pt.x, pt.y)
            eng.poke()

    def _ensure_dib(self, w, h):
        if self._bmp is not None and self.w == w and self.h == h:
            return
        if self._bmp:
            gdi32.SelectObject(self._memdc, self._old_bmp)
            gdi32.DeleteObject(self._bmp)
        self.w, self.h = w, h
        bi = BITMAPINFO()
        bi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.bmiHeader.biWidth = w
        bi.bmiHeader.biHeight = -h
        bi.bmiHeader.biPlanes = 1
        bi.bmiHeader.biBitCount = 32
        self._bmp = gdi32.CreateDIBSection(None, ctypes.byref(bi), 0, ctypes.byref(self._bits), None, 0)
        if not self._memdc:
            self._memdc = gdi32.CreateCompatibleDC(None)
        self._old_bmp = gdi32.SelectObject(self._memdc, self._bmp)

    def render(self, img, x, y):
        """img: PIL RGBA of the pet+bubble composite; x,y = screen top-left."""
        w, h = img.size
        self._ensure_dib(w, h)
        raw = img.tobytes("raw", "BGRA")
        ctypes.memmove(self._bits, raw, len(raw))
        screendc = user32.GetDC(None)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(
            self.hwnd, screendc,
            ctypes.byref(POINT(int(x), int(y))),
            ctypes.byref(SIZE(w, h)),
            self._memdc, ctypes.byref(POINT(0, 0)), 0, ctypes.byref(blend), ULW_ALPHA)
        user32.ReleaseDC(None, screendc)

    def move(self, x, y):
        """Position-only move: SetWindowPos, far cheaper than UpdateLayeredWindow."""
        user32.SetWindowPos(self.hwnd, 0, int(x), int(y), 0, 0,
                            0x0001 | 0x0002 | 0x0010)  # NOSIZE | NOZORDER | NOACTIVATE

    def show(self):
        user32.ShowWindow(self.hwnd, 5)

    def hide(self):
        user32.ShowWindow(self.hwnd, 0)

    def is_visible(self):
        return bool(user32.IsWindowVisible(self.hwnd)) if self.hwnd else False

    def pump(self):
        """Message loop — REQUIRED for clicks/hit-test/drag to be processed.
        Runs on its own thread; blocks until WM_QUIT."""
        msg = MSG()
        while True:
            r = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if r == 0:
                break
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def set_topmost(self, on):
        flag = WS_EX_TOPMOST if on else 0
        style = user32.GetWindowLongW(self.hwnd, -20)
        if on:
            style |= WS_EX_TOPMOST
        else:
            style &= ~WS_EX_TOPMOST
        user32.SetWindowLongW(self.hwnd, -20, style)
        user32.SetWindowPos(self.hwnd, -1 if on else -2, 0, 0, 0, 0,
                            0x0001 | 0x0002 | 0x0020)

    def destroy(self):
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)


def workarea():
    r = RECT()
    user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(r), 0)
    return r.left, r.top, r.right, r.bottom


# ---------------------------------------------------------------- activity + status
def last_input_ms():
    try:
        li = wintypes.LASTINPUTINFO()
        li.cbSize = ctypes.sizeof(li)
        if not user32.GetLastInputInfo(ctypes.byref(li)):
            return 0
        return kernel32.GetTickCount() - li.dwTime
    except Exception:
        return 0


APP_LABELS = {
    "WindowsTerminal.exe": "Terminal", "cmd.exe": "Command Prompt",
    "powershell.exe": "PowerShell", "pwsh.exe": "PowerShell", "Code.exe": "VS Code",
    "opencode.exe": "OpenCode", "chrome.exe": "Chrome", "msedge.exe": "Edge",
    "firefox.exe": "Firefox", "brave.exe": "Brave", "explorer.exe": "Explorer",
}


def foreground_app():
    try:
        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return ""
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""
        handle = kernel32.OpenProcess(0x1000, False, pid.value)
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(520)
            size = ctypes.c_ulong(520)
            kernel32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size))
            name = os.path.basename(buf.value)
            return APP_LABELS.get(name, name.replace(".exe", ""))
        finally:
            kernel32.CloseHandle(handle)
    except Exception:
        return ""


def read_status():
    try:
        files = [f for f in os.listdir(PET_DIR) if f.startswith("status-") and f.endswith(".json")]
    except FileNotFoundError:
        return []
    now_ms = int(time.time() * 1000)
    out = []
    for fn in files:
        try:
            with open(os.path.join(PET_DIR, fn), encoding="utf-8") as fh:
                d = json.load(fh)
            d["stale"] = now_ms - (d.get("updatedAt") or 0) > STALE_MS
            out.append(d)
        except Exception:
            pass
    out.sort(key=lambda s: s.get("updatedAt") or 0, reverse=True)
    return out


def read_dir_changes(path):
    handle = kernel32.CreateFileW(
        path, 1, 1 | 2 | 4, None, 3, 0x02000000, None)
    if not handle or handle == -1:
        raise RuntimeError("watch handle failed")
    try:
        buf = ctypes.create_string_buffer(65536)
        ret = wintypes.DWORD()
        while True:
            ok = kernel32.ReadDirectoryChangesW(
                handle, buf, len(buf), False, 1 | 0x10, ctypes.byref(ret), None, None)
            if not ok:
                break
            yield True
    finally:
        kernel32.CloseHandle(handle)


# ---------------------------------------------------------------- pet engine
class PetEngine:
    """Physics + sprite slicing + state resolution, renders via PetWindow."""

    FPS = 30
    TICK = 1.0 / FPS

    def __init__(self):
        self.win = PetWindow()
        self.win.engine = self
        self.dragging = False
        self.cfg = load_config()
        self.pet = PETS[self.cfg["petIdx"] % len(PETS)]
        self.sheet = None
        self._load_sheet()
        self.phys = {"x": 80, "y": 0, "vx": 0, "vy": 0, "grounded": True,
                     "mode": "idle", "t": 0, "walkT": 0, "spawned": False}
        self.area = (0, 0, 1920, 1040)
        self.sessions = []
        self.os_app = ""
        self.os_active = False
        self.rest_min = 4000
        self.walk_factor = self.cfg["walk"] / 100.0
        self.anim = pet_states(self.pet)[0]
        self.frame_idx = 0
        self.acc = 0.0
        self.bubble_text = ""
        self.bubble_until = 0.0
        self.running = True
        self._frame_cache = {}
        self._last_act = 0.0
        self._last_content = None
        self._last_pos = None
        self._last_log = 0.0
        self._prev_state = "_start"
        self._prev_tool = ""
        self._last_active_min = 0.0
        self._last_poke_log = 0.0
        self.break_min = int(self.cfg.get("breakMin", 50))
        self.focus_start = None
        self._break_shown = False
        self._last_break = 0.0
        self.attention_until = 0.0
        self._wb = {}
        self._wb_date = time.strftime("%Y-%m-%d")
        self._wb_app = ""
        self._wb_t = time.time()
        self._last_wb_save = 0.0
        self._load_wellbeing()
        self._build_frame_cache()

    def _log(self, kind, **data):
        """Append one JSON line to THIS pet's activity log — one pet, one memory."""
        try:
            log_path = os.path.join(PET_DIR, "activity-%s.jsonl" % self.pet["id"])
            with open(log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": time.time(), "kind": kind, **data}) + "\n")
        except Exception:
            pass

    def _prune_status(self):
        """Dead session files accumulate forever; drop anything older than 5 min."""
        try:
            now_ms = time.time() * 1000
            for f in os.listdir(PET_DIR):
                if f.startswith("status-") and f.endswith(".json"):
                    p = os.path.join(PET_DIR, f)
                    if now_ms - os.path.getmtime(p) * 1000 > 300000:
                        try:
                            os.unlink(p)
                        except Exception:
                            pass
        except Exception:
            pass

    def _load_wellbeing(self):
        try:
            with open(WELLBEING_FILE, encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("date") == self._wb_date:
                self._wb = d.get("apps", {})
        except Exception:
            pass

    def _save_wellbeing(self):
        try:
            os.makedirs(PET_DIR, exist_ok=True)
            with open(WELLBEING_FILE, "w", encoding="utf-8") as fh:
                json.dump({"date": self._wb_date, "apps": self._wb}, fh)
        except Exception:
            pass

    def _track_app_time(self):
        """Digital-wellbeing: attribute elapsed time to the active app."""
        now = time.time()
        date = time.strftime("%Y-%m-%d")
        if date != self._wb_date:
            self._wb_date = date
            self._wb = {}
        dt = now - self._wb_t
        self._wb_t = now
        if dt <= 0:
            return
        if not self.os_active:
            app = "Idle"
        else:
            app = self.os_app or "Desktop"
            if app in ("Explorer", "Program Manager"):
                app = "Desktop"
        self._wb[app] = self._wb.get(app, 0) + dt
        if now - self._last_wb_save >= 20:
            self._last_wb_save = now
            self._save_wellbeing()

    def _log_activity(self):
        now = time.time()
        if now - self._last_log < 1.0:
            return
        self._last_log = now
        st = self.sessions[0] if self.sessions else None
        fresh = st and not st.get("stale")
        our = st.get("state") if fresh else ("busy" if self.os_active else "waiting")
        if our != self._prev_state:
            self._log("state", state=our, sessionID=(st.get("sessionID") if st else None))
            self._prev_state = our
        tool = st.get("toolLabel") if st else ""
        if tool and tool != self._prev_tool:
            self._log("tool", tool=tool, sessionID=(st.get("sessionID") if st else None))
            self._prev_tool = tool
        if self.os_active and now - self._last_active_min >= 60:
            self._last_active_min = now
            self._log("active", app=self.os_app)
        elif self.os_active:
            self._last_active_min = now

    def _build_frame_cache(self):
        """Pre-render every sprite frame once per pet: crop+resize is the
        expensive part; per-frame render becomes a cached paste.
        Built into a local dict and swapped in atomically so the render
        thread never sees an empty cache mid-rebuild."""
        cache = {}
        if self.sheet:
            w = self.pet["frameW"] * self.pet["scale"]
            h = self.pet["frameH"] * self.pet["scale"]
            for st in pet_states(self.pet):
                for i in range(st["frames"]):
                    sx = i * self.pet["frameW"]
                    sy = st["row"] * self.pet["frameH"]
                    try:
                        f = self.sheet.crop((sx, sy, sx + self.pet["frameW"], sy + self.pet["frameH"]))
                        cache[(st["id"], i)] = f.resize((w, h), Image.NEAREST)
                    except Exception:
                        pass
        self._frame_cache = cache

    def _load_sheet(self):
        p = _res(self.pet["file"])
        try:
            im = Image.open(p)
            im.load()
            self.sheet = im.convert("RGBA")
        except Exception:
            self.sheet = None

    def set_pet(self, idx):
        idx %= len(PETS)
        self.cfg["petIdx"] = idx
        save_config(self.cfg)
        self.pet = PETS[idx]
        self._load_sheet()
        self.anim = pet_states(self.pet)[0]
        self.frame_idx = 0
        self._build_frame_cache()

    def set_walk(self, pct):
        self.walk_factor = max(0.0, min(1.0, pct / 100.0))

    def poke(self):
        """Single click — a small surprised hop. Physics does the arc."""
        p = self.phys
        if p["grounded"] and not self.dragging:
            p["vy"] = -1.4
            p["grounded"] = False
        if time.time() - self._last_poke_log > 1.0:
            self._last_poke_log = time.time()
            self._log("poke")

    def jump(self):
        """Double click — a real leap."""
        if not self.dragging:
            self.phys["vy"] = -3.0
            self.phys["grounded"] = False
        self._log("jump")

    def set_topmost(self, on):
        self.win.set_topmost(on)

    def set_visible(self, vis):
        if vis:
            self.win.show()
        else:
            self.win.hide()
        try:
            c = load_config()
            c["petVisible"] = bool(vis)
            save_config(c)
        except Exception:
            pass

    def _state(self):
        st = self.sessions[0] if self.sessions else None
        fresh = st and not st.get("stale")
        if fresh:
            return st.get("state") or "idle"
        return "busy" if self.os_active else "waiting"

    def _anim_id(self):
        our = self._state()
        m = self.pet.get("map") or DEFAULT_MAP
        if not self.phys["grounded"]:
            return "jumping"
        if time.time() < self.attention_until and any(s["id"] == "waving" for s in pet_states(self.pet)):
            return "waving"
        if self.phys["mode"] == "walk" and self.phys["vx"] != 0:
            return "running-left" if self.phys["vx"] < 0 else "running-right"
        if our == "busy" and self.sessions:
            d = self.sessions[0].get("direction")
            if d == "left" and any(s["id"] == "running-left" for s in pet_states(self.pet)):
                return "running-left"
            if d == "right" and any(s["id"] == "running-right" for s in pet_states(self.pet)):
                return "running-right"
        return m.get(our) or "idle"

    def _phys(self, dtms):
        s = min(dtms, 50) / 16.7
        left, top, right, bottom = self.area
        w = self.pet["frameW"] * self.pet["scale"]
        h = self.pet["frameH"] * self.pet["scale"]
        floor = bottom - h
        p = self.phys
        if not p["grounded"]:
            p["vy"] += 0.35 * s
            p["y"] += p["vy"] * s
            if p["y"] >= floor:
                p["y"] = floor
                if p["vy"] > 3:
                    p["vy"] = -p["vy"] * 0.35
                else:
                    p["vy"] = 0
                    p["grounded"] = True
        else:
            p["y"] = floor
        if p["y"] < top:
            p["y"] = top
            if p["vy"] < 0:
                p["vy"] = 0
        if p["mode"] == "walk":
            p["x"] += p["vx"] * s
        if p["x"] <= left:
            p["x"] = left
            p["vx"] = abs(p["vx"])
            if p["grounded"]:
                p["vy"] = -2.6
                p["grounded"] = False
        if p["x"] >= right - w:
            p["x"] = right - w
            p["vx"] = -abs(p["vx"])
            if p["grounded"]:
                p["vy"] = -2.6
                p["grounded"] = False
        p["t"] += dtms
        if p["grounded"] and p["mode"] == "idle" and p["t"] > self.rest_min:
            p["t"] = 0
            working = self._state() in ("busy", "thinking")
            chance = (0.45 if working else 0.16) * self.walk_factor
            if random() < chance:
                p["mode"] = "walk"
                p["vx"] = (1 if random() < 0.5 else -1) * (0.7 + random() * 0.9)
                p["walkT"] = 0
                self.rest_min = 3500 + random() * 3500
            else:
                self.rest_min = 7000 + random() * 8000
        if p["mode"] == "walk":
            p["walkT"] += dtms
            if p["grounded"] and p["walkT"] > 1200 + random() * 1800:
                p["mode"] = "idle"
                p["vx"] = 0
                p["t"] = 0
                self.rest_min = 6000 + random() * 6000

    def _compose(self):
        w = self.pet["frameW"] * self.pet["scale"]
        h = self.pet["frameH"] * self.pet["scale"]
        canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        if self.sheet:
            st = pet_states(self.pet)
            anim = next((a for a in st if a["id"] == self._anim_id()), st[0])
            if anim["id"] != self.anim["id"]:
                self.anim = anim
                self.frame_idx = 0
                self.acc = 0
            frame = self._frame_cache.get((self.anim["id"], self.frame_idx))
            if frame:
                canvas.alpha_composite(frame)
        # bubble above the pet's head
        if self.bubble_text and time.time() < self.bubble_until:
            canvas = self._draw_bubble(canvas, self.bubble_text)
        return canvas

    def _draw_bubble(self, canvas, text):
        w = canvas.width
        pad = 8
        try:
            font = ImageFont.truetype("segoeui.ttf", 14)
        except Exception:
            font = ImageFont.load_default()
        tw = font.getbbox(text)[2] - font.getbbox(text)[0]
        bw = min(tw + pad * 2, w - 8)
        bh = 22
        bx = max(0, (w - bw) // 2)
        by = max(0, 4)
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=10, fill=(255, 255, 255, 245))
        d.polygon([(bx + bw // 2 - 5, by + bh), (bx + bw // 2 + 5, by + bh),
                   (bx + bw // 2, by + bh + 6)], fill=(255, 255, 255, 245))
        d.text((bx + pad, by + 3), text[:40], font=font, fill=(30, 30, 46, 255))
        return canvas

    def loop(self):
        if not self.phys["spawned"]:
            self.phys["spawned"] = True
            left, top, right, bottom = self.area
            w = self.pet["frameW"] * self.pet["scale"]
            self.phys["x"] = (left + right) / 2 - w / 2
            self.phys["y"] = bottom - self.pet["frameH"] * self.pet["scale"]
        dt = self.TICK * 1000
        if not self.dragging:
            self._phys(dt)
        self._log_activity()
        self.acc += dt
        per = self.anim["durationMs"] / max(1, self.anim["frames"])
        if per > 0:
            while self.acc >= per:
                self.acc -= per
                self.frame_idx = (self.frame_idx + 1) % max(1, self.anim["frames"])
        # dirty-flag: full UpdateLayeredWindow only when CONTENT changed;
        # position-only changes move the cheap SetWindowPos way.
        px, py = int(round(self.phys["x"])), int(round(self.phys["y"]))
        bubble_on = bool(self.bubble_text and time.time() < self.bubble_until)
        content = (self.anim["id"], self.frame_idx, bubble_on, self.bubble_text)
        if self.dragging:
            return  # manual drag owns the window position until release
        if content != self._last_content:
            self._last_content = content
            self._last_pos = (px, py)
            img = self._compose()
            self.win.render(img, px, py)
        elif (px, py) != self._last_pos:
            self._last_pos = (px, py)
            self.win.move(px, py)

    def update_sessions(self, sessions):
        self.sessions = sessions

    def config_watch(self):
        """Apply config + one-shot commands written by the control app (separate process)."""
        try:
            with open(CONFIG_FILE, encoding="utf-8") as fh:
                c = json.load(fh)
        except Exception:
            return
        if c.get("quit"):
            try:
                self._clear_command("quit")
            except Exception:
                pass
            os._exit(0)
        changed = False
        if isinstance(c.get("petIdx"), int) and c["petIdx"] % len(PETS) != self.cfg["petIdx"] % len(PETS):
            self.set_pet(c["petIdx"])
            changed = True
        if isinstance(c.get("walk"), int) and c["walk"] != self.cfg.get("walk"):
            self.set_walk(c["walk"])
            self.cfg["walk"] = c["walk"]
            changed = True
        if isinstance(c.get("breakMin"), int):
            self.break_min = max(0, int(c["breakMin"]))
            self.cfg["breakMin"] = self.break_min
        if c.get("alwaysOnTop") is not None and bool(c["alwaysOnTop"]) != bool(self.cfg.get("alwaysOnTop", True)):
            self.set_topmost(bool(c["alwaysOnTop"]))
            self.cfg["alwaysOnTop"] = bool(c["alwaysOnTop"])
            changed = True
        if c.get("hidePet"):
            self.set_visible(False)
            self._clear_command("hidePet")
        if c.get("showPet"):
            self.set_visible(True)
            self._clear_command("showPet")
        if changed:
            save_config(self.cfg)

    @staticmethod
    def _clear_command(key):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as fh:
                c = json.load(fh)
            c.pop(key, None)
            with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
                json.dump(c, fh)
        except Exception:
            pass

    def update_activity(self):
        now = time.time()
        if now - self._last_act < 0.5:
            return  # foreground_app() is expensive; throttle to 2 Hz
        self._last_act = now
        self.os_active = last_input_ms() < ACTIVE_MS
        self.os_app = foreground_app()
        if now >= self.bubble_until:
            self.bubble_text = ""
        st = self.sessions[0] if self.sessions else None
        fresh = st and not st.get("stale")
        tool = st.get("toolLabel") if (fresh and st.get("state") == "busy") else ""
        if tool:
            self.bubble_text = tool
            self.bubble_until = now + 4
        elif not fresh and self.os_active and self.os_app and self.os_app not in ("Explorer", "Program Manager", ""):
            self.bubble_text = "Working in " + self.os_app
            self.bubble_until = now + 4
        elif not self.os_active and not fresh:
            self.bubble_text = ""
            self.bubble_until = 0
        # focus streak -> break nudge (distraction tracker). Runs LAST so the
        # nudge wins over any tool/app bubble for its 5s.
        if self.os_active:
            if self.focus_start is None:
                self.focus_start = now
            elif self.break_min > 0 and not self._break_shown \
                    and now - self.focus_start >= self.break_min * 60 \
                    and now - self._last_break > 300:
                self._break_shown = True
                self._last_break = now
                mins = int((now - self.focus_start) / 60)
                self.bubble_text = "Deep in it for %d min \u2014 take 5?" % mins
                self.bubble_until = now + 5
                self.attention_until = now + 3
                self._log("break", mins=mins)
        else:
            self.focus_start = None
            self._break_shown = False
            self.bubble_text = ""
            self.bubble_until = 0
        self._track_app_time()


def random():
    import random as _r
    return _r.random()


# ---------------------------------------------------------------- tray + control app
_engine = None

_FALLBACK_HTML = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
  body { font-family: 'Segoe UI', system-ui, sans-serif; background: #16161f; color: #e6e6e6;
         padding: 18px; display: grid; place-items: center; height: 100vh; margin: 0; text-align: center; }
</style></head><body><p>OpenCode Pet — control UI missing.<br><small>Reinstall or rebuild the app.</small></p></body></html>"""


def load_control_html():
    for name in ("app.html", "control.html"):
        p = _file(name)
        if p:
            try:
                with open(p, encoding="utf-8") as fh:
                    return fh.read()
            except Exception:
                pass
    return _FALLBACK_HTML


PREVIEW_H = 80

_PREVIEW_CACHE = None
_PREVIEW_LOCK = threading.Lock()


def _preview_strip(pet):
    """Tiles the idle row into one horizontal strip, returned as a data URI."""
    p = _res(pet["file"])
    try:
        sheet = Image.open(p).convert("RGBA")
    except Exception:
        return None
    st = pet_states(pet)[0]
    fw, fh = pet["frameW"], pet["frameH"]
    nw = max(1, int(fw * PREVIEW_H / fh))
    strip = Image.new("RGBA", (nw * st["frames"], PREVIEW_H), (0, 0, 0, 0))
    for i in range(st["frames"]):
        try:
            frame = sheet.crop((i * fw, st["row"] * fh, (i + 1) * fw, (st["row"] + 1) * fh))
            frame = frame.resize((nw, PREVIEW_H), Image.NEAREST)
            strip.alpha_composite(frame, (i * nw, 0))
        except Exception:
            continue
    buf = io.BytesIO()
    strip.save(buf, "PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def build_previews():
    """All pet preview strips, generated once and cached for the process."""
    global _PREVIEW_CACHE
    with _PREVIEW_LOCK:
        if _PREVIEW_CACHE is not None:
            return _PREVIEW_CACHE
        out = []
        for pet in PETS:
            st = pet_states(pet)[0]
            out.append({
                "id": pet["id"],
                "name": pet["name"],
                "strip": _preview_strip(pet),
                "frames": st["frames"],
                "durationMs": st["durationMs"],
                "frameW": max(1, int(pet["frameW"] * PREVIEW_H / pet["frameH"])),
                "frameH": PREVIEW_H,
            })
        _PREVIEW_CACHE = out
        return _PREVIEW_CACHE


class ControlApi:
    """Runs in the SEPARATE control process. Talks to the pet via config.json
    + one-shot commands, so the pet process never hosts a browser."""

    def __init__(self):
        self._control = None

    def bind_window(self, win):
        self._control = win

    def get_config(self):
        c = load_config()
        c["pets"] = [p["name"] for p in PETS]
        c["petVisible"] = bool(c.get("petVisible", True))
        c["petName"] = PETS[c.get("petIdx", 0) % len(PETS)]["name"]
        sess = read_status()
        c["state"] = (sess[0].get("state") or "idle") if sess and not sess[0].get("stale") else "idle"
        return c

    def get_previews(self):
        return build_previews()

    def get_sessions(self):
        # ACTIVE sessions only — working/thinking/error/celebrating right now.
        # Idle/done sessions drop off the dashboard immediately; combined with
        # the server plugin no longer heartbeating idle sessions, stale files
        # are pruned from disk too.
        out = []
        for s in read_status():
            if s.get("stale"):
                continue
            if (s.get("state") or "idle") in ("busy", "thinking", "error", "retry", "celebrating"):
                out.append(s)
        return out

    def get_logs(self, limit=200):
        """Recent activity history for the CURRENT pet (one pet, one memory)."""
        pet_id = PETS[load_config().get("petIdx", 0) % len(PETS)]["id"]
        log_path = os.path.join(PET_DIR, "activity-%s.jsonl" % pet_id)
        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                lines = fh.readlines()
            out = []
            for line in lines[-int(limit):]:
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
            return out
        except Exception:
            return []

    def get_wellbeing(self):
        """Per-app time for today (digital wellbeing), top apps first."""
        try:
            with open(WELLBEING_FILE, encoding="utf-8") as fh:
                d = json.load(fh)
            if d.get("date") != time.strftime("%Y-%m-%d"):
                return []
            out = [{"app": a, "seconds": int(s)}
                   for a, s in d.get("apps", {}).items() if s >= 30]
            out.sort(key=lambda x: -x["seconds"])
            return out[:8]
        except Exception:
            return []

    def next_pet(self):
        c = load_config()
        c["petIdx"] = (int(c.get("petIdx", 0)) + 1) % len(PETS)
        save_config(c)
        return True

    def prev_pet(self):
        c = load_config()
        c["petIdx"] = (int(c.get("petIdx", 0)) - 1) % len(PETS)
        save_config(c)
        return True

    def save_config(self, conf):
        c = load_config()
        c.update(conf)  # merge — never drop petVisible or pending commands
        save_config(c)
        return True

    def _cmd(self, key, val=1):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as fh:
                c = json.load(fh)
        except Exception:
            c = {}
        c[key] = val
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as fh:
                json.dump(c, fh)
        except Exception:
            pass

    def hide_pet(self):
        self._cmd("hidePet")
        return True

    def show_pet(self):
        self._cmd("showPet")
        return True

    def hide_control(self):
        if self._control is not None:
            try:
                self._control.hide()
            except Exception:
                pass
        return True

    def quit(self):
        self._cmd("quit")
        try:
            time.sleep(0.4)
        except Exception:
            pass
        os._exit(0)


def run_control():
    """Control app in its own process — no pet, no GDI, no single-instance mutex."""
    import webview  # noqa: F401 — lazy; the pet process never imports a browser
    # Pre-warm sprite strips while WebView2 spins up (first call is ~0.8s).
    threading.Thread(target=build_previews, daemon=True).start()
    control_api = ControlApi()
    win = webview.create_window(
        "OpenCode Pet", html=load_control_html(),
        js_api=control_api, width=980, height=680, min_size=(860, 600),
        resizable=True, frameless=False)
    control_api.bind_window(win)
    webview.start(private_mode=False)


def spawn_control():
    import subprocess
    if getattr(sys, "frozen", False):
        subprocess.Popen([sys.executable, "--control"],
                         creationflags=0x00000008 | 0x00000200)
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        subprocess.Popen([sys.executable, os.path.join(here, "main.py"), "--control"],
                         creationflags=0x00000008 | 0x00000200)


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
        spawn_control()

    def next_pet(icon, item):
        engine.set_pet(engine.cfg["petIdx"] + 1)

    def prev_pet(icon, item):
        engine.set_pet(engine.cfg["petIdx"] - 1)

    def quit_(icon, item):
        icon.stop()
        os._exit(0)

    menu = pystray.Menu(
        pystray.MenuItem("Show Pet", show),
        pystray.MenuItem("Hide Pet", hide),
        pystray.MenuItem("Control App", settings),
        pystray.MenuItem("Next Pet", next_pet),
        pystray.MenuItem("Previous Pet", prev_pet),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Quit", quit_),
    )
    icon = pystray.Icon("opencode-pet", img, "OpenCode Pet", menu)
    threading.Thread(target=icon.run, daemon=True).start()
    return icon


# ---------------------------------------------------------------- main
def main():
    if "--control" in sys.argv:
        run_control()
        return

    mutex = kernel32.CreateMutexW(None, False, "OpenCodePet_SingleInstance")
    if kernel32.GetLastError() == 183:
        sys.exit(0)

    os.makedirs(PET_DIR, exist_ok=True)
    engine = PetEngine()
    engine.area = workarea()
    engine.win.show()
    engine._prune_status()  # clear stale session files from previous runs

    create_tray(engine)

    # Launching the app should open the control window too, not just the pet.
    # It runs as its own process so the pet never hosts a browser.
    try:
        spawn_control()
    except Exception:
        pass

    # watcher thread -> push session changes + config/commands to engine
    def watcher():
        last_prune = 0.0
        while True:
            try:
                for _ in read_dir_changes(PET_DIR):
                    time.sleep(0.15)
                    engine.update_sessions(read_status())
                    engine.config_watch()
                    if time.time() - last_prune >= 30:
                        last_prune = time.time()
                        engine._prune_status()
            except Exception:
                pass
            time.sleep(5)
            engine.update_sessions(read_status())
            engine.config_watch()
            if time.time() - last_prune >= 30:
                last_prune = time.time()
                engine._prune_status()

    threading.Thread(target=watcher, daemon=True).start()

    def render_loop():
        next_t = time.time()
        while True:
            engine.update_activity()
            engine.loop()
            now = time.time()
            next_t = max(next_t, now)          # resync: never busy-spin to catch up
            next_t += PetEngine.TICK
            time.sleep(max(0.002, next_t - now))

    threading.Thread(target=render_loop, daemon=True).start()

    # main thread hosts the pet window's message pump (clicks, drag, hit-test)
    engine.win.pump()


if __name__ == "__main__":
    main()
