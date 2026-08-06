"""Win32 interop: ctypes bindings, the GDI layered pet window, OS activity.

Every call that returns or accepts a HANDLE has explicit argtypes/restype —
otherwise ctypes truncates 64-bit handles to 32-bit c_int on 64-bit Windows
(silent corruption of window/app state).
"""

import ctypes
import os
import threading
import time
from ctypes import wintypes

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
HOTKEY_MOD = 0x0002 | 0x0004  # MOD_CONTROL | MOD_ALT
HOTKEY_VK_TOGGLE_PET = 0x50   # P
HOTKEY_VK_OPEN_DASH = 0x44    # D

SPI_GETWORKAREA = 0x0030

# click/drag detection
CLICK_MOVE_MAX = 6      # px of movement tolerated before a click is a drag
CLICK_TIME_MAX = 0.8    # s between down/up for a click
DOUBLE_CLICK_DIST = 8   # px tolerance for double-click

WATCH_BUFFER = 65536    # ReadDirectoryChangesW buffer


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
            user32.RegisterHotKey(self.hwnd, HOTKEY_TOGGLE_PET, HOTKEY_MOD, HOTKEY_VK_TOGGLE_PET)
            user32.RegisterHotKey(self.hwnd, HOTKEY_OPEN_DASH, HOTKEY_MOD, HOTKEY_VK_OPEN_DASH)
        except Exception:
            pass

    def _proc(self, hwnd, msg, wp, lp):
        if msg == WM_NCHITTEST:
            return HTCLIENT  # manual drag (see below) so physics stays in sync
        if msg == WM_HOTKEY:
            return self._on_hotkey(wp)
        if msg == WM_LBUTTONDOWN:
            return self._on_lbutton_down(hwnd)
        if msg == WM_MOUSEMOVE:
            return self._on_mouse_move()
        if msg == WM_LBUTTONUP:
            return self._on_lbutton_up(hwnd)
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wp, lp)

    def _on_hotkey(self, wp):
        if wp == HOTKEY_TOGGLE_PET and self.engine:
            self.engine.set_visible(not self.engine.win.is_visible())
        elif wp == HOTKEY_OPEN_DASH and self.engine:
            from . import web  # deferred: web imports api/engine — breaks the import cycle
            try:
                web.spawn_control()
            except Exception:
                pass
        return 0

    def _on_lbutton_down(self, hwnd):
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

    def _on_mouse_move(self):
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

    def _on_lbutton_up(self, hwnd):
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
            if self.engine and moved < CLICK_MOVE_MAX and (time.monotonic() - self._down_t) < CLICK_TIME_MAX:
                self._handle_click(pt)
        return 0

    def _handle_click(self, pt):
        eng = self.engine
        now = time.monotonic()
        dbl = user32.GetDoubleClickTime() / 1000.0
        if self._last_click and now - self._last_click[0] < dbl \
                and abs(self._last_click[1] - pt.x) < DOUBLE_CLICK_DIST \
                and abs(self._last_click[2] - pt.y) < DOUBLE_CLICK_DIST:
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


def read_dir_changes(path):
    handle = kernel32.CreateFileW(
        path, 1, 1 | 2 | 4, None, 3, 0x02000000, None)
    if not handle or handle == -1:
        raise RuntimeError("watch handle failed")
    try:
        buf = ctypes.create_string_buffer(WATCH_BUFFER)
        ret = wintypes.DWORD()
        while True:
            ok = kernel32.ReadDirectoryChangesW(
                handle, buf, len(buf), False, 1 | 0x10, ctypes.byref(ret), None, None)
            if not ok:
                break
            yield True
    finally:
        kernel32.CloseHandle(handle)
