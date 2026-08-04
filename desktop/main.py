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
import math
import datetime
import struct
import base64
import threading
import ctypes
from ctypes import wintypes
import pystray
from PIL import Image, ImageDraw, ImageFont

import contextlib
import msvcrt

# ---------------------------------------------------------------- constants
PET_DIR = os.path.join(os.path.expanduser("~"), ".opencode", "pet")
CONFIG_FILE = os.path.join(PET_DIR, "config.json")
ACTIVITY_LOG = os.path.join(PET_DIR, "activity.jsonl")
WELLBEING_FILE = os.path.join(PET_DIR, "wellbeing.json")
FOCUS_FILE = os.path.join(PET_DIR, "focus.json")
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


class LASTINPUTINFO(ctypes.Structure):
    """ctypes.wintypes doesn't provide this on all Python versions (3.13
    slimmed it down), and a missing attribute inside the old try/except
    silently disabled the whole OS-activity layer. Define it locally."""
    _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]


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

# --- remaining interop hardening: every call that returns or accepts a HANDLE
# --- needs explicit argtypes/restype, otherwise ctypes truncates 64-bit handles
# --- to 32-bit c_int on 64-bit Windows (silent corruption of window/app state).
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetTickCount.restype = wintypes.DWORD
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL
kernel32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                 wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
kernel32.CreateFileW.restype = wintypes.HANDLE
kernel32.ReadDirectoryChangesW.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD,
                                           wintypes.BOOL, wintypes.DWORD,
                                           ctypes.POINTER(wintypes.DWORD),
                                           ctypes.c_void_p, ctypes.c_void_p]  # lpOverlapped always NULL
kernel32.ReadDirectoryChangesW.restype = wintypes.BOOL
kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
kernel32.CreateMutexW.restype = wintypes.HANDLE
user32.GetForegroundWindow.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.FindWindowW.restype = wintypes.HWND
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT]
user32.SystemParametersInfoW.restype = wintypes.BOOL
user32.GetLastInputInfo.argtypes = [ctypes.POINTER(LASTINPUTINFO)]
user32.GetLastInputInfo.restype = wintypes.BOOL

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
    {"id": "walking", "row": 7, "frames": 6, "durationMs": 820},
    {"id": "review", "row": 8, "frames": 6, "durationMs": 1030},
]
DEFAULT_MAP = {
    "idle": "idle", "busy": "walking", "thinking": "review",
    "error": "failed", "success": "jumping",
    "waiting": "waiting",
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
     {"id": "emberkit", "name": "Emberkit", "file": "pet-emberkit.webp", "frameW": 192, "frameH": 208, "scale": 1, "map": DEFAULT_MAP},
 ]


def pet_states(pet):
    return pet.get("states") or PET_STATES


# ---------------------------------------------------------------- config
def load_config():
    default = {"petIdx": 0, "alwaysOnTop": True, "walk": 100, "breakMin": 50}
    # A concurrent locked save in the other process briefly blocks reads of
    # the locked byte (ERROR_LOCK_VIOLATION); retry a couple of times rather
    # than falling back to defaults for a transient microsecond window.
    for _ in range(3):
        try:
            with open(CONFIG_FILE, encoding="utf-8") as fh:
                c = json.load(fh)
            if isinstance(c, dict):
                default.update(c)
            return default
        except OSError:
            time.sleep(0.01)
        except Exception:
            return default
    return default


_CONFIG_THREAD_LOCK = threading.Lock()


@contextlib.contextmanager
def _config_lock():
    """Serialize config.json access across BOTH processes and threads.

    The pet and control processes both read-modify-write config.json; without
    a lock an interleaved read/read/write/write silently loses keys (TOCTOU
    race). The msvcrt byte-range lock serializes across processes on Windows;
    the module-level threading.Lock serializes within this process, because
    Windows byte-range locks conflict even between two handles of the same
    process. If the file lock is unavailable we degrade to the thread lock
    alone rather than blocking forever.
    """
def _lock_with_retry(fd, tries=50, wait_ms=20):
    """Acquire the byte-range lock without the ~10s stall LK_LOCK can block
    for (that would freeze the watcher thread on contention). LK_NBLCK fails
    immediately; writers hold the lock for microseconds, so a short retry
    almost always succeeds, then we give up and rely on the thread lock."""
    for _ in range(tries):
        try:
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            time.sleep(wait_ms / 1000.0)
    return False


@contextlib.contextmanager
def _config_lock():
    """Serialize config.json access across BOTH processes and threads.

    The pet and control processes both read-modify-write config.json; without
    a lock an interleaved read/read/write/write silently loses keys (TOCTOU
    race). The msvcrt byte-range lock serializes across processes on Windows;
    the module-level threading.Lock serializes within this process, because
    Windows byte-range locks conflict even between two handles of the same
    process. If the file lock is unavailable we degrade to the thread lock
    alone rather than blocking forever.
    """
    _CONFIG_THREAD_LOCK.acquire()
    fd = None
    yielded = False
    try:
        os.makedirs(PET_DIR, exist_ok=True)
        fd = os.open(CONFIG_FILE, os.O_RDWR | os.O_CREAT)
        _lock_with_retry(fd)
        yielded = True
        yield fd
    except OSError:
        if yielded:
            raise  # exception from the consumer body — never swallow it
        yield None  # only for failures BEFORE the yield (open/lock)
    finally:
        if fd is not None:
            try:
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            os.close(fd)
        _CONFIG_THREAD_LOCK.release()


def _read_locked_fd(fd):
    """Read config through the lock-holding fd.

    Windows byte-range locks block READS of the locked region from any OTHER
    handle (ERROR_LOCK_VIOLATION — unlike POSIX advisory locks), so a plain
    open() inside the lock fails and the merge silently sees an empty file.
    Seeking and reading the lock-owning handle is the only correct path.
    """
    os.lseek(fd, 0, os.SEEK_SET)
    try:
        raw = os.read(fd, 1 << 20)
        return json.loads(raw.decode("utf-8"))
    except Exception:
        return {}


def _write_locked_fd(fd, data):
    """Write `data` through a lock-held fd. Windows refuses writes into a
    byte-range-locked region from a DIFFERENT handle (ERROR_LOCK_VIOLATION), so
    a separate open() in "w" mode would silently fail and leave the file
    truncated. Seeking/truncating/writing the lock-holding fd is the only
    correct path."""
    os.lseek(fd, 0, os.SEEK_SET)
    os.ftruncate(fd, 0)
    payload = json.dumps(data).encode("utf-8")
    while payload:
        n = os.write(fd, payload)
        payload = payload[n:]
    os.fsync(fd)


def streak_from_history(history):
    """Consecutive days ending today or yesterday with >= 30min focus.

    Shared by the pet process (PetEngine._streak_days) and the control/web
    process (ControlApi.get_pet_profile) so the rule lives in one place.
    Today with < 30min doesn't break the chain — the day isn't over yet.
    """
    today = datetime.date.today()
    streak = 0
    for back in range(0, 400):
        day = (today - datetime.timedelta(days=back)).isoformat()
        if int(history.get(day, 0)) >= 30 * 60:
            streak += 1
        elif back == 0:
            continue  # today may still be building; check yesterday
        else:
            break
    return streak


def evolution_stage(level):
    """Level -> evolution stage: name + emoji + aura colour + sprite suffix.

    Launch ships PROGRAMMATIC evolution (a coloured aura glow + label baked
    from the SAME sprite sheet — no new art needed). When real per-stage
    sprite sheets are added later, drop them in desktop/sprites as
    ``pet-<id>-stageN.webp`` (N = 1/2/3) and _load_sheet prefers them; the
    rest of the app (stage name, badge, aura) needs no changes.
    """
    level = int(level or 1)
    if level >= 10:
        return {"id": "stage3", "name": "Evolved", "emoji": "\u2728",
                "aura": (226, 162, 60, 40), "suffix": "stage3"}
    if level >= 5:
        return {"id": "stage2", "name": "Growing", "emoji": "\ud83c\udf31",
                "aura": (93, 215, 155, 34), "suffix": "stage2"}
    return {"id": "stage1", "name": "Baby", "emoji": "\ud83d\udc0a",
            "aura": (93, 185, 216, 26), "suffix": "stage1"}


def save_config(conf):
    """Persist config, merging with whatever is already on disk.

    The pet process and the control process both write config.json (the pet
    writes its own resolved config + petVisible; the control writes user
    settings + one-shot commands). A bare write would clobber the other
    process's keys, so the whole read-merge-write happens under a
    cross-process file lock (see _config_lock) and writes go through the
    lock-holding handle.
    """
    try:
        with _config_lock() as fd:
            if fd is None:
                return
            existing = _read_locked_fd(fd)
            merged = dict(existing) if isinstance(existing, dict) else {}
            merged.update(conf)
            _write_locked_fd(fd, merged)
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
        self._click_timer = None
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
                # Pin the pet vertically so _phys() doesn't snap it back to the
                # floor on the next tick — this lets the user place the pet
                # anywhere in the window, not just on the bottom axis.
                self.engine.phys["pinned_y"] = True
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
                    # Unpin — physics can resume normal floor snapping after
                    # the user releases the pet.
                    self.engine.phys.pop("pinned_y", None)
                    # Clamp into the workspace so the pet never drifts off-screen
                    # after a drag-and-drop near an edge.
                    l, t, r, b = self.engine.area
                    w = self.engine.pet["frameW"] * self.engine.pet["scale"]
                    h = self.engine.pet["frameH"] * self.engine.pet["scale"]
                    px = max(l, min(int(self.engine.phys["x"]), r - w))
                    py = max(t, min(int(self.engine.phys["y"]), b - h))
                    self.engine.phys["x"] = px
                    self.engine.phys["y"] = py
                    self.engine._last_pos = (px, py)
                    self.move(px, py)
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
            # Double-click detected — cancel pending poke and fire jump
            self._last_click = None
            if self._click_timer:
                self._click_timer.cancel()
                self._click_timer = None
            eng.jump()
        else:
            self._last_click = (now, pt.x, pt.y)
            # Delay poke() until we're sure this isn't the first click of a double-click
            if self._click_timer:
                self._click_timer.cancel()
            self._click_timer = threading.Timer(
                dbl, self._fire_poke, args=(eng,))
            self._click_timer.start()

    def _fire_poke(self, eng):
        self._click_timer = None
        if self._last_click is not None:
            self._last_click = None
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
        li = LASTINPUTINFO()
        li.cbSize = ctypes.sizeof(li)
        if not user32.GetLastInputInfo(ctypes.byref(li)):
            return 0
        # Mask to the 32-bit DWORD range: GetTickCount wraps every 49.7 days
        # of uptime, and an unwrapped subtraction can go negative — which
        # would make os_active permanently True (the pet never rests).
        return (kernel32.GetTickCount() - li.dwTime) & 0xFFFFFFFF
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
    except OSError:
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


def current_app_session():
    """Expose active desktop work when no tool-specific status file exists."""
    app = foreground_app()
    if not app or app in ("Explorer", "Program Manager") or last_input_ms() >= ACTIVE_MS:
        return None
    now_ms = int(time.time() * 1000)
    return {
        "sessionID": "desktop-activity",
        "state": "busy",
        "title": app + " activity",
        "toolLabel": app,
        "message": "Active desktop work",
        "updatedAt": now_ms,
        "direction": "right",
    }


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
        self._stale_emotion = None   # BUG-3: preserve last emotion across stale boundary
        self.break_min = int(self.cfg.get("breakMin", 50))
        self.focus_start = None
        self._break_shown = False
        self._last_break = 0.0
        self.attention_until = 0.0
        self.cast = None  # focus-completion cast flash (small independent event)
        self._wb = {}
        self._wb_date = time.strftime("%Y-%m-%d")
        self._wb_app = ""
        self._wb_t = time.time()
        self._last_wb_save = 0.0
        self._history = {}   # date "YYYY-MM-DD" -> total focused seconds (past days)
        self._app_history = {}  # date "YYYY-MM-DD" -> {app: seconds} (per-day breakdown)
        self._hour_today = {}   # today's {hour: seconds} — folded into _hour_history at rollover
        self._hour_history = {}  # date "YYYY-MM-DD" -> {hour: seconds} (per-day, per-hour)
        self._font = None  # lazy font cache (truetype() is ~5ms — load once)
        # focus sessions (inverse-Tamagotchi)
        self.focus_active = False
        self.focus_started = 0.0
        self.focus_target_min = int(self.cfg.get("focusMin", 25))
        self.focus_wilted = False
        self._focus_app = ""
        # pet growth (XP / level / mood)
        self.xp = int(self.cfg.get("xp", 0))
        self.level = int(self.cfg.get("level", 1))
        self.mood = "neutral"
        self._last_tool_earn = ""
        self._last_break_log = 0.0
        self._load_wellbeing()
        self._load_focus_state()
        self._build_frame_cache()
        self._shutdown = False
        self._watch_failures = 0  # consecutive read_dir_changes failures -> fallback to polling

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
            if isinstance(d.get("history"), dict):
                self._history = dict(d["history"])
            if isinstance(d.get("appHistory"), dict):
                self._app_history = dict(d["appHistory"])
            self._hour_history = {
                day: {int(h): v for h, v in day_map.items()
                      if isinstance(v, (int, float))
                      and (isinstance(h, int) or h.isdigit())}
                for day, day_map in d["hourHistory"].items()
                if isinstance(day_map, dict)} if isinstance(d.get("hourHistory"), dict) else {}
            hour_today_raw = {
                int(k): v for k, v in d["hourToday"].items()
                if isinstance(v, (int, float))
                and (isinstance(k, int) or k.isdigit())
            } if isinstance(d.get("hourToday"), dict) else {}
            self._hour_today = {}
            # Drop non-numeric app values: a corrupt file must never let a
            # TypeError reach _track_app_time/_rollover_wellbeing and kill the
            # render loop (there is no try/except on that thread path).
            apps = {k: v for k, v in d.get("apps", {}).items()
                    if isinstance(v, (int, float))}
            if d.get("date") == self._wb_date:
                self._wb = apps
                self._hour_today = hour_today_raw
            elif d.get("date"):
                # The file holds a PREVIOUS day (pet was off / older build):
                # keep its date so the first _track_app_time folds that day
                # into history instead of silently dropping it.
                self._wb_date = d["date"]
                self._wb = apps
                # Preserve the previous day's hour-of-day distribution too,
                # or the peaks analysis silently loses that day's shape.
                if hour_today_raw:
                    day_hours = dict(self._hour_history.get(self._wb_date, {}))
                    for hour, secs in hour_today_raw.items():
                        day_hours[hour] = day_hours.get(hour, 0) + secs
                    self._hour_history[self._wb_date] = day_hours
        except Exception:
            pass

    def _save_wellbeing(self):
        try:
            os.makedirs(PET_DIR, exist_ok=True)
            json.dump({"date": self._wb_date, "apps": self._wb,
                       "history": getattr(self, "_history", {}),
                       "appHistory": getattr(self, "_app_history", {}),
                       "hourToday": getattr(self, "_hour_today", {}),
                       "hourHistory": getattr(self, "_hour_history", {})},
                      open(WELLBEING_FILE, "w", encoding="utf-8"))
        except Exception:
            pass

    # --------------------------------------------------------- focus sessions
    def _load_focus_state(self):
        try:
            with open(FOCUS_FILE, encoding="utf-8") as fh:
                d = json.load(fh)
            self.focus_active = bool(d.get("active"))
            self.focus_started = float(d.get("startedAt", 0))
            self.focus_target_min = int(d.get("targetMin", self.focus_target_min))
            self.focus_wilted = bool(d.get("wilted"))
            self._focus_app = d.get("app", "")
        except Exception:
            pass

    def _save_focus_state(self):
        try:
            os.makedirs(PET_DIR, exist_ok=True)
            json.dump({"active": self.focus_active, "startedAt": self.focus_started,
                       "targetMin": self.focus_target_min, "wilted": self.focus_wilted,
                       "app": self._focus_app, "progress": self._focus_progress()},
                      open(FOCUS_FILE, "w", encoding="utf-8"))
        except Exception:
            pass

    def _focus_progress(self):
        if not self.focus_active:
            return 0.0
        el = time.time() - self.focus_started
        return max(0.0, min(1.0, el / max(1, self.focus_target_min * 60)))

    def start_focus(self, minutes=None):
        """Begin a focus session. The sprout grows while the user stays in one
        app; leaving wilts it. Completing awards XP."""
        if minutes:
            self.focus_target_min = max(1, min(int(minutes), 180))
        self.focus_active = True
        self.focus_started = time.time()
        self.focus_wilted = False
        self._focus_app = self.os_app or "Desktop"
        self._log("focusStart", targetMin=self.focus_target_min, app=self._focus_app)
        self._save_focus_state()
        return True

    def stop_focus(self, completed=False):
        if not self.focus_active and not completed:
            return False
        self.focus_active = False
        self._save_focus_state()
        return True

    def _focus_tick(self):
        """Runs at ~2Hz while a session is live: grow, wilt on app-switch or
        idle, complete at the target."""
        if not self.focus_active:
            return
        now = time.time()
        if now - self.focus_started >= self.focus_target_min * 60:
            self.focus_active = False
            self.focus_wilted = False
            self._log("focusDone", minutes=self.focus_target_min)
            self._award_xp(50, "focus")
            self.mood = "happy"
            self._save_focus_state()
            # celebration reaction
            self.bubble_text = "Focus complete! +50 XP \u2728"
            self.bubble_until = now + 4
            self.attention_until = now + 3
            self.cast = {"until": now + 1.0, "started": now}  # completion -> cast flash
            return
        # wilt when the user leaves the session app or goes idle > 45s
        if self.os_active and self.os_app and self.os_app != self._focus_app:
            if not self.focus_wilted:
                self.focus_wilted = True
                self._log("focusWilt", app=self.os_app, fromApp=self._focus_app)
                self.bubble_text = "Hey, you left! My sprout is sad \ud83c\udf31"
                self.bubble_until = now + 4
                self._save_focus_state()
        elif not self.os_active and now - self._wb_t > 45:
            if not self.focus_wilted:
                self.focus_wilted = True
                self._log("focusWilt", reason="idle")
                self.bubble_text = "Zzz\u2026 sprout needs you awake \ud83c\udf31"
                self.bubble_until = now + 4
                self._save_focus_state()

    # ------------------------------------------------------------ XP / growth
    @staticmethod
    def _xp_needed(level):
        return 100 + (level - 1) * 50

    def _award_xp(self, amount, reason):
        self.xp += amount
        leveled = False
        while self.xp >= self._xp_needed(self.level):
            self.xp -= self._xp_needed(self.level)
            self.level += 1
            leveled = True
            self._log("levelUp", level=self.level)
        if leveled:
            self.mood = "happy"
            self.bubble_text = "Level %d! \ud83c\udf89" % self.level
            self.bubble_until = time.time() + 4
            self.attention_until = time.time() + 3
        self._save_growth()

    def _save_growth(self):
        try:
            c = load_config()
            c["xp"] = self.xp
            c["level"] = self.level
            c["mood"] = self.mood
            c["focusMin"] = self.focus_target_min
            save_config(c)
        except Exception:
            pass

    def _mood_tick(self):
        """Recalculate mood from recent state when nothing else changed it."""
        if self.mood in ("happy",):
            return  # keep celebration mood until something else happens
        if self.os_active and time.time() - self._last_break_log > 3600 \
                and self._focus_tick is not None:
            # long-work tiredness: reuse the break-nudge signal
            if self.break_min > 0 and self.focus_start \
                    and time.time() - self.focus_start >= self.break_min * 60 * 2:
                self.mood = "tired"

    def _earn_tool_xp(self, tool):
        """Small XP for completing tool calls (once per tool id)."""
        if tool and tool != self._last_tool_earn:
            self._last_tool_earn = tool
            self._award_xp(2, "tool")

    def _streak_days(self):
        """Consecutive days (ending today or yesterday) with >= 30min focus."""
        return streak_from_history(self._history)

    def _rollover_wellbeing(self):
        """The day changed: fold the finished day's total into history and
        persist immediately, then prune to a bounded window so the file never
        grows without bound."""
        total = int(sum(v for v in self._wb.values()
                        if isinstance(v, (int, float)))) if self._wb else 0
        if total > 0:
            self._history[self._wb_date] = self._history.get(self._wb_date, 0) + total
        # fold per-app breakdown too (top-app / weekly-app charts); guard the
        # attribute so a bare/legacy engine state can never crash the render loop
        if self._wb and getattr(self, "_app_history", None) is not None:
            day_apps = dict(self._app_history.get(self._wb_date, {}))
            for app, secs in self._wb.items():
                if isinstance(secs, (int, float)):
                    day_apps[app] = day_apps.get(app, 0) + int(secs)
            self._app_history[self._wb_date] = day_apps
        # fold the finished day's per-hour buckets for the best-time analysis
        # (getattr guards keep bare/legacy engine states off the crash path)
        if getattr(self, "_hour_today", None) and getattr(self, "_hour_history", None) is not None:
            day_hours = dict(self._hour_history.get(self._wb_date, {}))
            for hour, secs in self._hour_today.items():
                if isinstance(secs, (int, float)):
                    day_hours[hour] = day_hours.get(hour, 0) + int(secs)
            self._hour_history[self._wb_date] = day_hours
        if getattr(self, "_hour_today", None) is not None:
            self._hour_today = {}  # new day starts clean
        # streak bonus: a full day of >=30min focus extends the chain
        if total >= 30 * 60:
            s = self._streak_days()
            if s and s % 5 == 0:
                self._award_xp(25, "streak")
        # Calendar arithmetic (not seconds-based): around DST the naive
        # now - N*86400 form can skip/duplicate a calendar day.
        cutoff = (datetime.date.today() - datetime.timedelta(days=29)).isoformat()
        self._history = {k: v for k, v in self._history.items() if k >= cutoff}
        if getattr(self, "_app_history", None) is not None:
            self._app_history = {k: v for k, v in self._app_history.items() if k >= cutoff}
        if getattr(self, "_hour_history", None) is not None:
            self._hour_history = {k: v for k, v in self._hour_history.items() if k >= cutoff}
        self._save_wellbeing()

    def _track_app_time(self):
        """Digital-wellbeing: attribute elapsed time to the active app."""
        now = time.time()
        date = time.strftime("%Y-%m-%d")
        if date != self._wb_date:
            self._rollover_wellbeing()
            self._wb_date = date
            self._wb = {}
        dt = now - self._wb_t
        self._wb_t = now
        if dt <= 0:
            return
        # Laptop sleep / lock screen can pause the process for hours; a giant
        # delta is a gap, not usage — crediting it would inflate one app's
        # wellbeing total and poison the daily stats.
        if dt > 60:
            return
        if not self.os_active:
            app = "Idle"
        else:
            app = self.os_app or "Desktop"
            if app in ("Explorer", "Program Manager"):
                app = "Desktop"
        self._wb[app] = self._wb.get(app, 0) + dt
        # hour-of-day bucket (used by the "best focus time" analysis)
        if getattr(self, "_hour_today", None) is not None:
            hour = time.localtime(now).tm_hour
            self._hour_today[hour] = self._hour_today.get(hour, 0) + dt
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
        # mirror _state(): a fresh session with null/unknown state logs as idle
        our = (st.get("state") or "idle") if fresh else ("busy" if self.os_active else "waiting")
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
        # Prefer a real per-stage sprite sheet when it exists (future art):
        # pet-<id>-stageN.webp beside the base sheet. Falls back to the base
        # sheet so launch ships with the programmatic aura only.
        p = _res(self.pet["file"])
        # _load_sheet can run before the growth attrs are set during __init__
        staged = evolution_stage(getattr(self, "level", 1))["suffix"]
        base, ext = os.path.splitext(self.pet["file"])
        staged_file = base + "-" + staged + ext
        sp = _res(staged_file)
        if os.path.exists(sp):
            p = sp
        try:
            im = Image.open(p)
            im.load()
            self.sheet = im.convert("RGBA")
        except Exception:
            self.sheet = None

    STATE_COLORS = {
        "idle": (96, 96, 116), "busy": (246, 179, 92), "thinking": (127, 200, 232),
        "error": (255, 123, 132), "success": (95, 221, 157), "celebrating": (255, 210, 125),
        "waiting": (112, 112, 122), "retry": (127, 200, 232), "stale": (112, 112, 122),
    }

    def _state_aura(self):
        """Small status dot in the top-right corner: colour = what your AI
        tools / terminal are doing. Soft pulse, no big background circle."""
        try:
            st = self._state()
            col = self.STATE_COLORS.get(st, (96, 96, 116))
            r = 6
            w = r * 2 + 4
            h = r * 2 + 4
            if getattr(self, "_sa_cache", None) is None:
                self._sa_cache = {}
            key = (col[0], col[1], col[2], w, h)
            glow = self._sa_cache.get(key)
            if glow is None:
                glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                dr = ImageDraw.Draw(glow)
                for rr in range(r, 0, -2):
                    a = int(160 * (1 - rr / r) ** 2)
                    if a > 0:
                        dr.ellipse((2 + r - rr, 2 + r - rr, 2 + r + rr, 2 + r + rr),
                                   fill=(col[0], col[1], col[2], a))
                self._sa_cache[key] = glow
            now = time.time()
            live = st in ("busy", "thinking", "retry")
            alarm = st in ("error", "celebrating")
            if live:
                p = 0.5 + 0.5 * math.sin(now * 3.2)
            elif alarm:
                p = 0.5 + 0.5 * math.sin(now * 5.5)
            else:
                p = 0.5 + 0.5 * math.sin(now * 1.1)
            out = glow.copy()
            dr = ImageDraw.Draw(out)
            ra = min(255, int((110 if alarm else 70) + (80 if alarm else 55) * p))
            dr.ellipse((2, 2, 2 + r * 2, 2 + r * 2),
                       outline=(col[0], col[1], col[2], ra), width=2)
            return out
        except Exception:
            return None

    def _stage_aura(self):
        """Cached soft radial glow for the current evolution stage."""
        try:
            st = evolution_stage(self.level)
            if getattr(self, "_aura_cache", None) is None:
                self._aura_cache = {}
            key = st["id"]
            if key not in self._aura_cache:
                w = max(8, int(self.pet["frameW"] * self.pet["scale"]))
                h = max(8, int(self.pet["frameH"] * self.pet["scale"]))
                glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                dr = ImageDraw.Draw(glow)
                cx, cy = w // 2, int(h * 0.52)
                r = max(6, int(min(w, h) * 0.42))
                for rr in range(r, 0, -2):
                    a = int(st["aura"][3] * (1 - rr / r) ** 2)
                    if a <= 0:
                        continue
                    dr.ellipse((cx - rr, cy - rr, cx + rr, cy + rr),
                               fill=(st["aura"][0], st["aura"][1], st["aura"][2], a))
                self._aura_cache[key] = glow
            return self._aura_cache[key]
        except Exception:
            return None

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

    def _raw_state(self):
        st = self.sessions[0] if self.sessions else None
        if st and not st.get("stale"):
            return st.get("state")   # may be None
        return None

    def _state(self):
        raw = self._raw_state()
        if raw is not None:
            return raw
        st = self.sessions[0] if self.sessions else None
        if st and not st.get("stale"):
            # Fresh session with null/unknown state: treat as idle rather than
            # falling through to busy/waiting (BUG-9).
            return "idle"
        # BUG-3: use preserved stale emotion before falling back to busy/idle.
        # When nothing is driving the pet (no active session, OS idle), it
        # settles into a calm IDLE rest instead of the restless "waiting" gait —
        # so "screen idle => pet idle", matching how a companion should behave.
        return self._stale_emotion or ("busy" if self.os_active else "idle")

    def _anim_id(self):
        our = self._state()
        m = self.pet.get("map") or DEFAULT_MAP
        if not self.phys["grounded"]:
            if any(s["id"] == "jumping" for s in pet_states(self.pet)):
                return "jumping"
            # fall through to map lookup instead
        if time.time() < self.attention_until and any(s["id"] == "waving" for s in pet_states(self.pet)):
            return "waving"
        if self.phys["mode"] == "walk" and self.phys["vx"] != 0:
            if self.phys["vx"] < 0 and any(s["id"] == "running-left" for s in pet_states(self.pet)):
                return "running-left"
            if any(s["id"] == "running-right" for s in pet_states(self.pet)):
                return "running-right"
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
            # Only snap to floor if not drag-pinned. A drag drop should stay
            # where the user placed it (free vertical positioning).
            if not p.get("pinned_y"):
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
            # Only a pet that is actively engaged (working/thinking, or any
            # foreground activity) prowls around. When the screen has been idle
            # the pet stays put — no random roaming while it is resting.
            working = self._state() in ("busy", "thinking") or self.os_active
            chance = (0.45 if working else 0.0) * self.walk_factor
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
        # status dot: small glanceable indicator in the top-right corner.
        # Colour = what your AI tools / terminal are doing.
        saura = self._state_aura()
        if saura:
            canvas.alpha_composite(saura, (w - saura.width, 0))
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
        # focus-completion cast flash (independent event; self-expiring)
        if self.cast:
            if time.time() < self.cast["until"]:
                canvas = self._draw_cast(canvas, min(1.0, (time.time() - self.cast["started"]) / 0.9))
            else:
                self.cast = None
        # bubble above the pet's head
        if self.bubble_text and time.time() < self.bubble_until:
            canvas = self._draw_bubble(canvas, self.bubble_text)
        return canvas

    def _draw_cast(self, canvas, t):
        """Brief, celebratory energy burst behind the pet on focus completion.
        Pure additive overlay; the caller clears the event once it expires."""
        import math as _m
        w, h = canvas.size
        cx, cy = w * 0.5, h * 0.56
        ring = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        d = ImageDraw.Draw(ring)
        a = int((1 - t) * 165)
        lw = max(2, int((1 - t) * 7))
        for i, col in enumerate([(246, 179, 92, a), (255, 122, 106, max(0, a - 70))]):
            rr = int((8 + t * (w * 0.55)) + i * 6)
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=col, width=lw)
        for k in range(6):
            ang = k * (2 * _m.pi / 6) + t * 1.6
            rr = int((8 + t * (w * 0.55)) * (0.8 + 0.25 * t))
            ex = int(cx + _m.cos(ang) * rr * 1.1)
            ey = int(cy - (h * 0.18) * t - _m.sin(ang) * rr * 0.35)
            ea = max(0, 215 - int(t * 200))
            d.ellipse([ex - 2, ey - 2, ex + 2, ey + 2], fill=(255, 209, 137, ea))
        canvas.alpha_composite(ring)
        return canvas

    def _font_cache(self):
        """truetype() is the single most expensive call in _draw_bubble; load once."""
        if getattr(self, "_font", None) is None:
            try:
                self._font = ImageFont.truetype("segoeui.ttf", 14)
            except Exception:
                self._font = ImageFont.load_default()
        return self._font

    @staticmethod
    def _fit_text(text, font, avail):
        """Truncate a label with an ellipsis so it fits `avail` pixels.

        Binary search on the visible length: font.getlength() costs ~50us, so
        the naive linear walk is O(n) calls and dominates _draw_bubble on long
        labels (measured ~15ms/frame with a 200-char label). Binary search
        cuts that to O(log n) calls (~8).
        """
        if not text:
            return ""
        if font.getlength(text) <= avail:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if font.getlength(text[:mid] + "\u2026") <= avail:
                lo = mid
            else:
                hi = mid - 1
        return (text[:lo] + "\u2026") if lo else text[:1]

    def _draw_bubble(self, canvas, text):
        w = canvas.width
        pad = 8
        font = self._font_cache()
        # truncate with ellipsis so the label never overflows the canvas
        avail = max(16, w - 8 - pad * 2)
        text = self._fit_text(text, font, avail)
        tw = font.getlength(text)
        bw = min(tw + pad * 2, w - 8)
        bh = 22
        bx = max(0, (w - bw) // 2)
        by = max(0, 4)
        d = ImageDraw.Draw(canvas)
        d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=10, fill=(255, 255, 255, 245))
        d.polygon([(bx + bw // 2 - 5, by + bh), (bx + bw // 2 + 5, by + bh),
                   (bx + bw // 2, by + bh + 6)], fill=(255, 255, 255, 245))
        d.text((bx + pad, by + 3), text, font=font, fill=(30, 30, 46, 255))
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

    # personality reactions keyed on state transitions (error -> empathy,
    # completion after work -> cheer). Local only; keeps the pet alive.
    REACTIONS = {
        "error": [
            "Ouch — that one stung. Want me to watch the retry? 👁",
            "Exit %d — rough. I'll stay by your side. 💙",
            "Bounced hard. I'm right here.",
            "That one blipped — I've got you.",
        ],
        "success": [
            "Nice! Done. ✨",
            "Look at you go — nailed it! 🎉",
            "Clean exit. That's how it's done.",
            "Smooth. Another win.",
        ],
    }

    # Personality bubbles keyed on state — richer than REACTIONS because they
    # run on every transition (not just first-seen), with a 6s decay window
    # so the same line doesn't re-fire every tick while the state persists.
    BUBBLES = {
        "thinking": [
            "Hmm… thinking about it 🤔",
            "Processing… patience ✨",
            "Reasoning through this…",
            "Connecting the dots 🔮",
            "Almost there…",
            "Pondering…",
        ],
        "busy": [
            "On it 🔧",
            "Working the gears",
            "In the flow",
            "Making moves",
        ],
        "waiting": [
            "Waiting on you…",
            "Still here whenever you are",
            "Standing by 👀",
            "Whenever you're ready",
            "Not going anywhere",
        ],
        "error": [
            "That one hurt 😣",
            "Oof — rough exit",
            "Hang on, retry? 💪",
            "Tough one. I'm still here.",
        ],
        "success": [
            "Nice — done! 🎉",
            "Crisp. Nailed it ✨",
            "Another one in the bag",
            "Smooth. Another win.",
            "Look at that — clean.",
        ],
        "idle": [
            "Just vibing 😌",
            "Chilling for now",
            "All quiet on my end",
            "Ready when you are",
        ],
        "failed": [
            "That one hurt 😣",
            "Oof — rough exit",
            "Hang on, retry? 💪",
        ],
    }

    def update_sessions(self, sessions):
        # BUG-3: preserve the last-known emotion whenever the top (most recent)
        # session goes stale or disappears, so a timed-out session keeps showing
        # its real emotion (failed/thinking/...) instead of collapsing to
        # busy/waiting. A new fresh session clears the preserved emotion.
        prev_top = self.sessions[0] if self.sessions else None
        new_top = sessions[0] if sessions else None
        prev_fresh = prev_top is not None and not prev_top.get("stale")
        new_fresh = new_top is not None and not new_top.get("stale")
        if prev_fresh and not new_fresh:
            self._stale_emotion = prev_top.get("state")
        elif new_fresh:
            self._stale_emotion = None
        self.sessions = sessions
        # personality + growth on real transitions of the top session
        if new_top and new_fresh:
            st = new_top.get("state")
            tool = new_top.get("toolLabel") or ""
            if st == "error" and (not prev_top or prev_top.get("state") != "error"):
                import random as _r
                line = _r.choice(self.REACTIONS["error"])
                self.bubble_text = line
                self.bubble_until = time.time() + 5
            elif st == "success" and prev_top and prev_top.get("state") == "busy":
                import random as _r
                self.bubble_text = _r.choice(self.REACTIONS["success"])
                self.bubble_until = time.time() + 4
                self._award_xp(5, "complete")
            elif st == "busy" and tool:
                self._earn_tool_xp(tool)

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
        if c.get("focusStart") is not None:
            mins = int(c["focusStart"]) if isinstance(c["focusStart"], (int, float)) else None
            try:
                self.start_focus(mins)
            finally:
                # clear even on failure so a bad command can't retrigger
                # every poll cycle
                self._clear_command("focusStart")
        if c.get("focusStop"):
            try:
                self.stop_focus()
            finally:
                self._clear_command("focusStop")
        if changed:
            save_config(self.cfg)

    @staticmethod
    def _clear_command(key):
        try:
            with _config_lock() as fd:
                if fd is None:
                    return
                c = _read_locked_fd(fd)
                if not isinstance(c, dict):
                    return
                c.pop(key, None)
                _write_locked_fd(fd, c)
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
        state = st.get("state") if fresh else None
        tool = (st.get("toolLabel") or "").strip() if (fresh and state == "busy") else ""

        # Helper: pick a personality line with decay suppression so we don't
        # re-fire the same line every tick while a state persists.
        def _personality(state_key, ttl=6):
            last = getattr(self, "_last_bubble_state", None)
            last_at = getattr(self, "_last_bubble_state_at", 0)
            if state_key == last and now - last_at < ttl:
                return None
            import random as _r
            lines = self.BUBBLES.get(state_key) or []
            if not lines:
                return None
            line = _r.choice(lines)
            self._last_bubble_state = state_key
            self._last_bubble_state_at = now
            return line

        # 1. Tool-use line (busy + tool): the most useful real-time cue.
        if tool:
            friendly = {
                "bash": "Running a shell command",
                "grep": "Searching the codebase",
                "glob": "Finding files",
                "read": "Reading a file",
                "write": "Writing a file",
                "edit": "Editing a file",
            }
            base = tool.split(" ")[0].lower()
            label = friendly.get(base, tool)
            if base in friendly and len(tool.split(" ")) <= 1:
                self.bubble_text = label
            else:
                self.bubble_text = tool
            self.bubble_until = now + 3.5
        # 2. Personality lines keyed on state transitions.
        elif state in self.BUBBLES:
            line = _personality(state)
            if line:
                self.bubble_text = line
                self.bubble_until = now + 4
        # 3. No active sessions, OS is active → show foreground app.
        elif not fresh and self.os_active and self.os_app and self.os_app not in ("Explorer", "Program Manager", ""):
            self.bubble_text = "In " + self.os_app
            self.bubble_until = now + 3
        # 4. Nothing to say.
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
                self.mood = "tired"
        else:
            self.focus_start = None
            self._break_shown = False
            self.bubble_text = ""
            self.bubble_until = 0

        # focus session lifecycle (grow / wilt / complete) + mood + tool XP
        self._focus_tick()
        if self.os_active:
            self._mood_tick()
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
        c["state"] = (sess[0].get("state") or "idle") if sess and not sess[0].get("stale") else ("busy" if current_app_session() else "idle")
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
        if not out:
            activity = current_app_session()
            if activity:
                out.append(activity)
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

    def get_wellbeing_history(self, days=7):
        """Per-day total focus for the last N days, ascending, ending today.

        Returns [{date: "YYYY-MM-DD", seconds: int}, ...] with zero-second
        days included so the dashboard can draw a contiguous week. The live
        running total for today is folded in from the apps map. The day window
        uses calendar arithmetic so DST transitions can't skip/duplicate a day.
        """
        d = None
        for _ in range(3):  # wellbeing.json is rewritten non-atomically every 20s
            try:
                with open(WELLBEING_FILE, encoding="utf-8") as fh:
                    d = json.load(fh)
                break
            except OSError:
                time.sleep(0.01)
            except Exception:
                break
        # A missing file is treated as an empty window, NOT a short list: the
        # dashboard contract is a contiguous N-day series (zero-filled days
        # included) so the chart always draws the same shape. The UI shows its
        # empty state from the totals, not from list length.
        history = d.get("history") if (d and isinstance(d.get("history"), dict)) else {}
        today = datetime.date.today().isoformat()
        if d and d.get("date") == today and isinstance(d.get("apps"), dict):
            running = int(sum(v for v in d["apps"].values() if isinstance(v, (int, float))))
            if running > 0:
                history = dict(history)
                history[today] = history.get(today, 0) + running
        days = int(days) if days is not None else 7  # 0 => 1 via the clamp below
        # 90-day window is used by the focus-calendar heatmap; 30 would
        # silently truncate it. The list itself stays bounded.
        days = max(1, min(days, 90))
        out = []
        for i in range(days - 1, -1, -1):
            day = (datetime.date.today() - datetime.timedelta(days=i)).isoformat()
            out.append({"date": day, "seconds": int(history.get(day, 0))})
        return out

    def get_wellbeing_insights(self):
        """Automated focus insights for the dashboard.

        Returns a dict:
          weekSeconds / prevWeekSeconds : totals for the last 7 days and the
              seven before that (today's running total folded into the week)
          deltaPct                      : rounded % change, None if no baseline
          bestDay                       : {date, seconds} or None (ties -> first)
          todaySeconds                  : seconds accrued today so far
          topApp                        : {app, seconds} or None (today, >= 30s)
        """
        d = None
        for _ in range(3):
            try:
                with open(WELLBEING_FILE, encoding="utf-8") as fh:
                    d = json.load(fh)
                break
            except OSError:
                time.sleep(0.01)
            except Exception:
                break
        if d is None:
            return {"weekSeconds": 0, "prevWeekSeconds": 0, "deltaPct": None,
                    "bestDay": None, "todaySeconds": 0, "topApp": None}
        history = d.get("history") if isinstance(d.get("history"), dict) else {}
        today = datetime.date.today()
        week = {}
        prev = {}
        for i in range(14):
            day = (today - datetime.timedelta(days=i)).isoformat()
            secs = int(history.get(day, 0))
            (week if i < 7 else prev)[day] = secs
        running = 0
        if d.get("date") == today.isoformat() and isinstance(d.get("apps"), dict):
            running = int(sum(v for v in d["apps"].values() if isinstance(v, (int, float))))
            if running > 0:
                week[today.isoformat()] = week.get(today.isoformat(), 0) + running
        week_secs = sum(week.values())
        prev_secs = sum(prev.values())
        delta = None
        if prev_secs > 0:
            delta = int(round((week_secs - prev_secs) / prev_secs * 100))
        best_day = None
        if week_secs > 0:
            best = max(week, key=week.get)
            best_day = {"date": best, "seconds": week[best]}
        top_app = None
        if d.get("date") == today.isoformat() and isinstance(d.get("apps"), dict):
            apps = [(a, int(s)) for a, s in d["apps"].items()
                    if isinstance(s, (int, float)) and s >= 30]
            if apps:
                apps.sort(key=lambda x: -x[1])
                top_app = {"app": apps[0][0], "seconds": apps[0][1]}
        return {
            "weekSeconds": week_secs,
            "prevWeekSeconds": prev_secs,
            "deltaPct": delta,
            "bestDay": best_day,
            "todaySeconds": running,
            "topApp": top_app,
        }

    @staticmethod
    def _hour_label(hour):
        """24h -> '9 AM' / '12 PM' style label (tie-in with the peaks UI)."""
        hour = int(hour) % 24
        if hour == 0:
            return "12 AM"
        if hour < 12:
            return "%d AM" % hour
        if hour == 12:
            return "12 PM"
        return "%d PM" % (hour - 12)

    def get_focus_peaks(self, days=7):
        """Best time-of-day for deep work over the last N days.

        Reuses the exact selection pattern from get_wellbeing_insights (window
        arithmetic, today's live total folded in, ties -> first found) but over
        24 hour-of-day buckets instead of 7 calendar days, so the two analyses
        stay consistent by construction.

        Returns:
          days            : the clamped window actually analysed
          totalSeconds    : sum over the window
          hours           : [{hour, seconds}, ...] for all 24, ascending
          best            : {hour, label, seconds, pct} of the busiest hour
                            (ties -> earliest hour), or None
          runnerUp        : second-busiest hour (or None) — shows the spread
          spanLabel       : "mornings" / "afternoons" / "evenings" / "nights"
                            for the best hour, for a friendlier UI line
        """
        days = int(days) if days is not None else 7  # 0 => 1 via the clamp below
        days = max(1, min(days, 30))
        d = None
        for _ in range(3):
            try:
                with open(WELLBEING_FILE, encoding="utf-8") as fh:
                    d = json.load(fh)
                break
            except OSError:
                time.sleep(0.01)
            except Exception:
                break
        today = datetime.date.today()
        buckets = [0] * 24
        if d:
            hour_hist = d.get("hourHistory") if isinstance(d.get("hourHistory"), dict) else {}
            for i in range(days):
                day = (today - datetime.timedelta(days=i)).isoformat()
                day_map = hour_hist.get(day)
                if isinstance(day_map, dict):
                    for h, s in day_map.items():
                        if isinstance(s, (int, float)):
                            try:
                                buckets[int(h) % 24] += int(s)
                            except (TypeError, ValueError):
                                pass
            # today's live running total, attributed to its hour bucket
            if d.get("date") == today.isoformat() and isinstance(d.get("hourToday"), dict):
                for h, s in d["hourToday"].items():
                    if isinstance(s, (int, float)):
                        try:
                            buckets[int(h) % 24] += int(s)
                        except (TypeError, ValueError):
                            pass
        total = sum(buckets)
        hours = [{"hour": h, "seconds": buckets[h]} for h in range(24)]
        best = runner = None
        if total > 0:
            # ties -> earliest hour (stable argmax over ascending order)
            ranked = sorted(((buckets[h], -h) for h in range(24)), reverse=True)
            best_hour = -ranked[0][1]
            best = {"hour": best_hour,
                    "label": self._hour_label(best_hour),
                    "seconds": buckets[best_hour],
                    "pct": int(round(buckets[best_hour] * 100.0 / total))}
            if ranked[1][0] > 0:
                runner_hour = -ranked[1][1]
                runner = {"hour": runner_hour,
                          "label": self._hour_label(runner_hour),
                          "seconds": buckets[runner_hour],
                          "pct": int(round(buckets[runner_hour] * 100.0 / total))}
        span = {0: "overnight", 1: "overnight", 2: "overnight", 3: "overnight", 4: "overnight",
                5: "mornings", 6: "mornings", 7: "mornings", 8: "mornings", 9: "mornings",
                10: "mornings", 11: "mornings", 12: "afternoons", 13: "afternoons",
                14: "afternoons", 15: "afternoons", 16: "afternoons", 17: "afternoons",
                18: "evenings", 19: "evenings", 20: "evenings", 21: "evenings",
                22: "nights", 23: "nights"}
        return {"days": days, "totalSeconds": total, "hours": hours,
                "best": best, "runnerUp": runner,
                "spanLabel": span.get(best["hour"], "") if best else ""}

    # ------------------------------------------------------ focus + growth API
    def get_focus_state(self):
        """Live focus-session state for the dashboard (sprout progress).

        Progress is recomputed from startedAt/targetMin rather than trusting
        the file snapshot (which is only written on start/wilt/stop/complete),
        so the dashboard ring actually grows during a session."""
        try:
            with open(FOCUS_FILE, encoding="utf-8") as fh:
                d = json.load(fh)
            if isinstance(d, dict) and d.get("active"):
                el = time.time() - float(d.get("startedAt", 0))
                target = max(1, float(d.get("targetMin", 25))) * 60
                d["progress"] = max(0.0, min(1.0, el / target))
            else:
                d = {"active": False, "startedAt": 0, "targetMin": 25,
                     "wilted": False, "app": "", "progress": 0.0}
            return d
        except Exception:
            return {"active": False, "startedAt": 0, "targetMin": 25,
                    "wilted": False, "app": "", "progress": 0.0}

    def start_focus(self, minutes=None):
        """Write the one-shot command; the pet process owns the session."""
        self._cmd("focusStart", int(minutes) if minutes else 25)
        return True

    def stop_focus(self):
        self._cmd("focusStop")
        return True

    def get_pet_profile(self):
        """Level / XP / mood / streak for the pet profile card."""
        c = load_config()
        xp = int(c.get("xp", 0))
        level = int(c.get("level", 1))
        needed = PetEngine._xp_needed(level)
        streak = 0
        try:
            with open(WELLBEING_FILE, encoding="utf-8") as fh:
                d = json.load(fh)
            hist = d.get("history") if isinstance(d.get("history"), dict) else {}
            # fold today's live running total so a fresh 30+ min of focus
            # extends the streak immediately (matches get_wellbeing_history)
            if d.get("date") == datetime.date.today().isoformat() and isinstance(d.get("apps"), dict):
                running = int(sum(v for v in d["apps"].values()
                                  if isinstance(v, (int, float))))
                if running > 0:
                    hist = dict(hist)
                    hist[datetime.date.today().isoformat()] = hist.get(
                        datetime.date.today().isoformat(), 0) + running
            streak = streak_from_history(hist)
        except Exception:
            pass
        stage = evolution_stage(level)
        return {"level": level, "xp": xp, "xpNext": needed, "xpPct": min(1.0, xp / needed),
                "mood": c.get("mood", "neutral"), "streak": streak,
                "stage": {"id": stage["id"], "name": stage["name"],
                           "emoji": stage["emoji"]}}

    def get_weekly_wrapped(self):
        """'Your Week in Focus' summary: totals, best day, top app, streak,
        XP earned — rendered client-side; copy-to-clipboard share text."""
        out = {"days": 7, "weekSeconds": 0, "bestDay": None, "topApp": None,
               "streak": 0, "xp": 0, "focusSessions": 0, "prevWeekSeconds": 0}
        d = None
        for _ in range(3):
            try:
                with open(WELLBEING_FILE, encoding="utf-8") as fh:
                    d = json.load(fh)
                break
            except Exception:
                break
        today = datetime.date.today()
        history = {}
        app_hist = {}
        if d:
            history = d.get("history") if isinstance(d.get("history"), dict) else {}
            app_hist = d.get("appHistory") if isinstance(d.get("appHistory"), dict) else {}
            if d.get("date") == today.isoformat() and isinstance(d.get("apps"), dict):
                running = int(sum(v for v in d["apps"].values()
                                  if isinstance(v, (int, float))))
                if running > 0:
                    history = dict(history)
                    history[today.isoformat()] = history.get(today.isoformat(), 0) + running
        week = {}
        prev = {}
        for i in range(14):
            day = (today - datetime.timedelta(days=i)).isoformat()
            (week if i < 7 else prev)[day] = int(history.get(day, 0))
        out["weekSeconds"] = sum(week.values())
        out["prevWeekSeconds"] = sum(prev.values())
        if out["weekSeconds"] > 0:
            best = max(week, key=week.get)
            out["bestDay"] = {"date": best, "seconds": week[best]}
        app_tot = {}
        for i in range(7):
            day = (today - datetime.timedelta(days=i)).isoformat()
            day_map = app_hist.get(day)
            if isinstance(day_map, dict):
                for app, secs in day_map.items():
                    if isinstance(secs, (int, float)):
                        app_tot[app] = app_tot.get(app, 0) + int(secs)
        if d and d.get("date") == today.isoformat():
            for app, secs in (d.get("apps") or {}).items():
                if isinstance(secs, (int, float)):
                    app_tot[app] = app_tot.get(app, 0) + int(secs)
        if app_tot:
            top = max(app_tot, key=app_tot.get)
            out["topApp"] = {"app": top, "seconds": app_tot[top]}
        # streak + XP + session count
        c = load_config()
        out["xp"] = int(c.get("xp", 0))
        out["level"] = int(c.get("level", 1))
        profile = self.get_pet_profile()
        out["streak"] = profile["streak"]
        # count focus sessions in the activity log this week
        try:
            pet_id = PETS[c.get("petIdx", 0) % len(PETS)]["id"]
            with open(os.path.join(PET_DIR, "activity-%s.jsonl" % pet_id),
                      encoding="utf-8") as fh:
                for line in fh:
                    try:
                        e = json.loads(line)
                    except Exception:
                        continue
                    if e.get("kind") == "focusDone" and \
                            time.time() - (e.get("t") or 0) < 7 * 86400:
                        out["focusSessions"] += 1
        except Exception:
            pass
        return out

    def get_week_apps(self, days=7):
        """Per-app totals for the last N days (ascending; today folded in)."""
        days = max(1, min(int(days) if days else 7, 30))
        out = {}
        d = None
        for _ in range(3):
            try:
                with open(WELLBEING_FILE, encoding="utf-8") as fh:
                    d = json.load(fh)
                break
            except Exception:
                break
        today = datetime.date.today()
        app_hist = d.get("appHistory") if (d and isinstance(d.get("appHistory"), dict)) else {}
        for i in range(days):
            day = (today - datetime.timedelta(days=i)).isoformat()
            day_map = app_hist.get(day)
            if isinstance(day_map, dict):
                for app, secs in day_map.items():
                    if isinstance(secs, (int, float)):
                        out[app] = out.get(app, 0) + int(secs)
        if d and d.get("date") == today.isoformat() and isinstance(d.get("apps"), dict):
            for app, secs in d["apps"].items():
                if isinstance(secs, (int, float)):
                    out[app] = out.get(app, 0) + int(secs)
        rows = [{"app": a, "seconds": s} for a, s in out.items() if s >= 60]
        rows.sort(key=lambda x: -x["seconds"])
        return rows[:8]

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
        """Write a one-shot command, merging under the cross-process lock so a
        concurrent settings save from the pet process can't be clobbered."""
        try:
            with _config_lock() as fd:
                if fd is None:
                    return
                c = _read_locked_fd(fd)
                if not isinstance(c, dict):
                    c = {}
                c[key] = val
                _write_locked_fd(fd, c)
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
        """Graceful shutdown: signal threads, save state, then exit."""
        self._shutdown = True
        self._cmd("quit")
        # Give daemon threads a moment to finish their current tick and save state.
        # render_loop and watcher will exit on their next loop iteration.
        try:
            time.sleep(0.6)
        except Exception:
            pass
        # Final save of wellbeing + focus state so nothing is lost on restart.
        try:
            self._save_wellbeing()
            self._save_focus_state()
        except Exception:
            pass
        sys.exit(0)


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


# ---------------------------------------------------------------- web mode
# `python desktop/main.py --web [--pet-dir DIR] [--port N]`
#
# Serves the REAL app.html over localhost HTTP with a fetch-based bridge that
# maps window.pywebview.api.* onto the REAL ControlApi. This is both a feature
# (view the dashboard in any browser, e.g. Ctrl+Shift+D with pywebview
# unavailable) and the real end-to-end path the test suite drives: same UI,
# same backend, same data files — no mock anywhere.

_WEB_METHODS = [
    "get_config", "get_previews", "get_sessions", "get_logs",
    "get_wellbeing", "get_wellbeing_history", "get_wellbeing_insights",
    "get_focus_state", "start_focus", "stop_focus", "get_pet_profile",
    "get_weekly_wrapped", "get_week_apps", "get_focus_peaks",
    "save_config", "next_pet", "prev_pet", "hide_pet", "show_pet",
    "hide_control", "quit",
]
# Methods that make no sense from a browser tab: there is no control window
# to hide (the tab IS the UI), so hide_control is a no-op. quit is NOT a
# no-op: the dashboard's Quit button means "quit the pet app", and the real
# pet process reads the quit one-shot command from config.json — so we write
# the command (like ControlApi.quit does) but never os._exit(0) the SERVER.
_WEB_NOP = frozenset(["hide_control"])

_WEB_SHIM = """<script>
/* --- real fetch bridge for window.pywebview.api (injected by --web mode) --- */
(function () {
  var METHODS = %(methods)s;
  function rpc(method) {
    return function () {
      var args = Array.prototype.slice.call(arguments);
      return fetch("/rpc", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ method: method, args: args })
      }).then(function (r) { return r.json(); }).then(function (resp) {
        if (resp && resp.ok) return resp.result;
        throw new Error(resp && resp.error || ("rpc " + method + " failed"));
      });
    };
  }
  var api = {};
  METHODS.forEach(function (m) { api[m] = rpc(m); });
  window.pywebview = { api: api };
})();
</script>
""" % {"methods": json.dumps(_WEB_METHODS)}


def _apply_pet_dir(path):
    """Point all data-file globals at `path` (used by --web --pet-dir so a
    browser session can run against a throwaway or portable data dir)."""
    global PET_DIR, CONFIG_FILE, ACTIVITY_LOG, WELLBEING_FILE, FOCUS_FILE
    PET_DIR = os.path.abspath(path)
    CONFIG_FILE = os.path.join(PET_DIR, "config.json")
    ACTIVITY_LOG = os.path.join(PET_DIR, "activity.jsonl")
    WELLBEING_FILE = os.path.join(PET_DIR, "wellbeing.json")
    FOCUS_FILE = os.path.join(PET_DIR, "focus.json")
    os.makedirs(PET_DIR, exist_ok=True)


def run_web(host="127.0.0.1", port=0, pet_dir=None, extra_tail=None):
    """Serve the real dashboard over HTTP. Blocks forever (Ctrl+C to stop).

    extra_tail: optional HTML/script string appended before </body> — used by
    the test suite to attach the UI self-test harness to the REAL page.
    """
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import urllib.parse

    if pet_dir:
        _apply_pet_dir(pet_dir)
    api = ControlApi()
    html = load_control_html()
    if not html or html == _FALLBACK_HTML:
        raise RuntimeError("app.html not found next to main.py — cannot run --web")
    marker = "<script>"
    idx = html.find(marker)
    if idx < 0:
        raise RuntimeError("app.html has no <script> to bridge into")
    page = html[:idx] + _WEB_SHIM + html[idx:]
    if extra_tail and "</body>" in page:
        page = page.replace("</body>", extra_tail + "</body>", 1)

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass  # keep the console clean (the port line is the contract)

        def _json(self, code, obj):
            body = json.dumps(obj).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urllib.parse.urlparse(self.path).path in ("/", "/index.html"):
                body = page.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json(404, {"ok": False, "error": "not found"})

        def do_POST(self):
            if urllib.parse.urlparse(self.path).path != "/rpc":
                self._json(404, {"ok": False, "error": "not found"})
                return
            # Explicit CSRF + DNS-rebinding guards: only same-origin JSON-RPC
            # is accepted. A cross-site page can't set Content-Type
            # application/json (browser forbids it without CORS preflight,
            # which we never answer), and a text/plain form POST is rejected
            # instead of being parsed by accident. The Host check blocks
            # DNS rebinding: an attacker-controlled domain resolving to
            # 127.0.0.1 still sends its own Host header.
            ctype = self.headers.get("Content-Type", "")
            host = self.headers.get("Host", "") or ""
            ok_host = host.startswith("127.0.0.1:") or host.startswith("localhost:")
            if not ctype.startswith("application/json") or not ok_host:
                self._json(415, {"ok": False, "error": "unsupported request"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > 1 << 20:  # 1 MB cap — a local process must not OOM the server
                    self._json(413, {"ok": False, "error": "body too large"})
                    return
                req = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                method = req.get("method")
                args = req.get("args") or []
                if method not in _WEB_METHODS:
                    self._json(400, {"ok": False, "error": "unknown method %r" % method})
                    return
                if method in _WEB_NOP:
                    result = True
                elif method == "quit":
                    # Real quit semantics minus process death: write the one-shot
                    # command the pet process reads, keep the tab/server alive.
                    api._cmd("quit")
                    result = True
                else:
                    fn = getattr(api, method)
                    result = fn(*args)
                self._json(200, {"ok": True, "result": result})
            except Exception as exc:  # noqa: BLE001 — surface to the browser
                self._json(500, {"ok": False, "error": str(exc)})

    try:
        server = ThreadingHTTPServer((host, port), Handler)
    except OSError:
        raise SystemExit("--web: cannot bind %s:%d (port in use?)" % (host, port))
    actual = server.server_address[1]
    print("OPENCODE_PET_WEB_PORT=%d" % actual, flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


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


# ---------------------------------------------------------------- main
def main():
    if "--control" in sys.argv:
        run_control()
        return
    if "--web" in sys.argv:
        args = sys.argv[sys.argv.index("--web") + 1:]
        port = 0
        pet_dir = None
        tail = None
        i = 0
        while i < len(args):
            if args[i] == "--port":
                if i + 1 >= len(args):
                    print("--web: --port needs a value"); return
                try:
                    port = int(args[i + 1])
                except ValueError:
                    print("--web: invalid --port %r (must be an integer)" % args[i + 1]); return
                i += 2
            elif args[i] == "--pet-dir":
                if i + 1 >= len(args):
                    print("--web: --pet-dir needs a value"); return
                pet_dir = args[i + 1]; i += 2
            elif args[i] == "--selftest-tail":
                if i + 1 >= len(args):
                    print("--web: --selftest-tail needs a value"); return
                try:
                    with open(args[i + 1], encoding="utf-8") as fh:
                        tail = fh.read()
                except Exception:
                    tail = None
                i += 2
            else:
                i += 1
        run_web(port=port, pet_dir=pet_dir, extra_tail=tail)
        return

    mutex = kernel32.CreateMutexW(None, False, "OpenCodePet_SingleInstance")
    if kernel32.GetLastError() == 183:
        # Refuse to start ONLY when the owning instance's pet window is actually
        # alive. A leaked mutex handle held by a crashed/orphaned child (e.g. a
        # --control WebView2 subprocess) must not block a fresh launch.
        try:
            alive_win = bool(user32.FindWindowW("OpenCodePetLayer", None))
        except Exception:
            alive_win = True
        if alive_win:
            print("OpenCode Pet is already running.", file=sys.stderr)
            sys.exit(0)
        # zombie mutex (no live window): take over by continuing to boot
    os.makedirs(PET_DIR, exist_ok=True)
    engine = PetEngine()
    engine.area = workarea()
    engine.win.show()
    engine._prune_status()  # clear stale session files from previous runs

    # Load sessions that were already running BEFORE the app started. The
    # watcher below only fires on file CHANGES, so pre-existing status files
    # would otherwise never reach the engine.
    engine.update_sessions(read_status())

    create_tray(engine)

    # Launching the app should open the control window too, not just the pet.
    # It runs as its own process so the pet never hosts a browser.
    try:
        spawn_control()
    except Exception:
        pass

    # watcher thread -> push session changes + config/commands to engine.
    # Falls back to polling every 2s if ReadDirectoryChangesW fails permanently
    # (e.g., antivirus lock, network redirect, or missing permissions).
    def watcher():
        last_prune = 0.0
        poll_interval = 2.0  # fallback when file watch is broken
        last_poll = 0.0
        while not engine._shutdown:
            try:
                engine._watch_failures = 0
                for _ in read_dir_changes(PET_DIR):
                    if engine._shutdown:
                        return
                    time.sleep(0.15)
                    engine.update_sessions(read_status())
                    engine.config_watch()
                    if time.time() - last_prune >= 30:
                        last_prune = time.time()
                        engine._prune_status()
                    last_poll = time.time()
            except Exception:
                engine._watch_failures += 1
                if engine._watch_failures == 1:
                    import traceback
                    traceback.print_exc()
            # Periodic refresh so sessions that appear (or stale) without a
            # directory-change event still reach the engine.
            if time.time() - last_poll >= poll_interval:
                engine.update_sessions(read_status())
                engine.config_watch()
                if time.time() - last_prune >= 30:
                    last_prune = time.time()
                    engine._prune_status()
                last_poll = time.time()
            time.sleep(poll_interval)
            if engine._shutdown:
                return

    threading.Thread(target=watcher, daemon=True).start()

    def render_loop():
        next_t = time.time()
        while not engine._shutdown:
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
