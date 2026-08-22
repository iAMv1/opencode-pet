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
# use_last_error=True makes ctypes save/restore the thread's Windows error
# code around EVERY call through this dll, so ctypes.get_last_error() right
# after CreateMutexW (single-instance guard) is trustworthy — the plain
# windll form let internal ctypes calls clobber it intermittently.
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

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
WM_KEYDOWN = 0x0100
WM_DISPLAYCHANGE = 0x0126
HTCAPTION = 2
HTCLIENT = 1
GW_HINSTANCE = -6
HOTKEY_TOGGLE_PET = 1   # Ctrl+Shift+P
HOTKEY_OPEN_DASH = 2    # Ctrl+Alt+D
HOTKEY_MOD = 0x0002 | 0x0004  # MOD_CONTROL | MOD_ALT
HOTKEY_VK_TOGGLE_PET = 0x50   # P
HOTKEY_VK_OPEN_DASH = 0x44    # D
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27

SPI_GETWORKAREA = 0x0030
# SPI_GETWORKAREA is primary-monitor-only; per-monitor bounds come from
# EnumDisplayMonitors + GetMonitorInfoW instead (see monitor_workarea_for).

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


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", RECT),
                ("rcWork", RECT), ("dwFlags", wintypes.DWORD)]


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

MONITORENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HDC, ctypes.POINTER(RECT),
                                     wintypes.HMONITOR, wintypes.LPARAM)

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
user32.SetFocus.argtypes = [wintypes.HWND]
user32.SetFocus.restype = wintypes.HWND
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
user32.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.POINTER(RECT), MONITORENUMPROC, wintypes.LPARAM]
user32.EnumDisplayMonitors.restype = wintypes.BOOL
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.GetMonitorInfoW.restype = wintypes.BOOL
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
        if msg == WM_KEYDOWN:
            return self._on_key_down(wp)
        if msg == WM_DISPLAYCHANGE:
            return self._on_display_change()
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
            self.engine.drag_start()
            # Grab keyboard focus ONLY when arrows are enabled — stealing
            # focus from the user's active app on every pet click is hostile
            # (their typing would be dropped by the pet window).
            try:
                if self.engine.cfg.get("arrows", True):
                    user32.SetFocus(hwnd)
            except Exception:
                pass
        user32.SetCapture(hwnd)
        return 0

    def _on_key_down(self, wp):
        """Arrow-key control (config 'arrows', default on): VK_LEFT/VK_RIGHT
        walk the pet, VK_UP jumps. Ignored when arrows is False; every path
        is guarded so a bad key or engine state never kills the pump."""
        if not self.engine:
            return 0
        try:
            if not self.engine.cfg.get("arrows", True):
                return 0
            if wp == VK_LEFT:
                self.engine.walk_toward("left")
            elif wp == VK_RIGHT:
                self.engine.walk_toward("right")
            elif wp == VK_UP:
                self.engine.walk_toward("up")
        except Exception:
            pass
        return 0

    def _on_mouse_move(self):
        if self._drag and self.engine:
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            cx, cy, wx, wy = self._drag
            nx = wx + (pt.x - cx)
            ny = wy + (pt.y - cy)
            self.engine.drag_to(nx, ny)
            self.move(nx, ny)
        return 0

    def _on_display_change(self):
        """Dock/undock or resolution change invalidates the cached bounds:
        re-read the monitor under the pet (primary fallback) and pull it
        inside immediately, or a removed secondary strands it off-screen
        until restart. Engine-side, so physics clamps use the fresh area."""
        eng = self.engine
        if eng:
            try:
                eng.refresh_area(monitor_workarea_for(int(eng.phys["x"]), int(eng.phys["y"])))
            except Exception:
                eng.refresh_area(workarea())
        return 0

    def _on_lbutton_up(self, hwnd):
        if self._drag:
            self._drag = None
            if self.engine:
                # Unpin + clamp into the monitor the pet is ON, in one locked
                # step so the render tick can never interleave with release.
                self.engine.drag_end()
                self.move(int(self.engine.phys["x"]), int(self.engine.phys["y"]))
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


def _monitor_info(hmon):
    """Workarea tuple for one monitor handle, or None if info is unavailable."""
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return None
    rc = mi.rcWork
    return (int(rc.left), int(rc.top), int(rc.right), int(rc.bottom))


def monitor_workarea_for(x, y):
    """Workarea (l, t, r, b) of the monitor containing screen point (x, y).

    SPI_GETWORKAREA only describes the PRIMARY monitor: clamping against it
    snapped a pet released on any other display back to primary and made
    left-placed negative-coordinate monitors unreachable. Enumerate every
    monitor instead and use the one holding the point; when enumeration fails
    or no monitor contains the point (e.g. its display was just unplugged),
    fall back to the primary workarea so callers always get usable bounds."""
    found = []

    def _on_mon(_hdc, _rect, hmon, _data):
        info = _monitor_info(hmon)
        if info:
            found.append(info)
        return True

    try:
        if user32.EnumDisplayMonitors(None, None, MONITORENUMPROC(_on_mon), 0):
            for l, t, r, b in found:
                if l <= x < r and t <= y < b:
                    return l, t, r, b
    except Exception:
        pass
    return workarea()


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


def cursor_pos():
    """Current cursor position in screen coords, or None when unreadable."""
    try:
        pt = POINT()
        if not user32.GetCursorPos(ctypes.byref(pt)):
            return None
        return (pt.x, pt.y)
    except Exception:
        return None


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
