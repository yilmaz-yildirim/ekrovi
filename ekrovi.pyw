# -*- coding: utf-8 -*-
"""
Ekrovi: send what is on your screen to your Claude session with one key.

  PrtScr          screen under the mouse
  Alt+PrtScr      active window
  Shift+PrtScr    pick an area (single click = window under the mouse)
  Ctrl+PrtScr     short recording (press PrtScr again to stop early), key frames are sent

Every capture is saved in kayitlar/<date>/. The Claude window is brought to the front and
the image(s) plus a short context line are pasted into its message box. With auto_send on
it also presses Enter (only when the message box was empty).

If an instance is already running, a second start forwards its argument to it:
  pythonw ekrovi.pyw [screen|window|area|record|show|quit]
"""
import ctypes
import ctypes.wintypes as wt
import datetime
import io
import json
import os
import queue
import socket
import subprocess
import sys
import threading
import time
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "ekrovi.log"
CONFIG = HERE / "config.json"
UDP_PORT = 47819
COMMANDS = ("screen", "window", "area", "record", "show", "quit")


def log(*parts):
    try:
        if LOG.exists() and LOG.stat().st_size > 1_000_000:
            LOG.replace(HERE / "ekrovi.old.log")
        with LOG.open("a", encoding="utf-8") as f:
            f.write(time.strftime("%Y-%m-%d %H:%M:%S ") + " ".join(str(p) for p in parts) + "\n")
    except Exception:
        pass


# Physical pixels everywhere (mss, Tk, cursor, window rects).
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

# --------------------------------------------------------------------------- config

DEFAULTS = {
    "key": "print screen",
    "record_seconds": 5,
    "record_fps": 5,
    "max_images": 4,
    "auto_send": False,
    "mark_cursor": True,
    "show_button": True,
    "button_pos": None,
    "exclude_from_capture": True,
    "max_edge": 1568,
    "target_exe": "claude.exe",
    "save_dir": "captures",
    "prompt_screen": "",
    "prompt_record": "",
    "language": "auto",
}


def load_cfg():
    c = dict(DEFAULTS)
    try:
        c.update(json.loads(CONFIG.read_text(encoding="utf-8")))
    except FileNotFoundError:
        pass
    except Exception as e:
        log("config read error:", e)
    return c


cfg = load_cfg()


def save_cfg():
    try:
        CONFIG.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        log("config write error:", e)


# --------------------------------------------------------------------------- language

STRINGS = {
    "en": {
        "prompt_screen": "Look at this screen: what is wrong, and where does it come from?",
        "prompt_record": "Look at this recording: what happens, and where is the problem?",
        "head_screen": "📸 Screen", "head_window": "🪟 Window", "head_area": "✂️ Selected area",
        "head_rec": "🎬 {dur:.1f} s recording · {n} frames ({times} s)",
        "head_rec_static": "🎬 {dur:.1f} s recording · the screen barely changed, last frame",
        "note_cursor": "red ring = mouse pointer", "note_file": "file: {path}",
        "note_crop": "first frame full screen, the others zoom in on the changing area",
        "note_frames": "all {n} frames: {folder}",
        "badge": "{t:.1f} s", "badge_full": "{t:.1f} s · full screen", "badge_close": "{t:.1f} s · close-up",
        "label_shot": "Screenshot", "label_img": "Image", "label_rec": "Recording",
        "fb_saved": "{label} saved and copied to the clipboard. {reason} Paste it with Ctrl+V.",
        "fb_no_claude": "Claude window not found.", "fb_no_front": "Could not bring Claude to the front.",
        "fb_no_box": "Message box not found.", "fb_changed": "The window changed, stopped.",
        "rec_empty": "The recording was empty.", "error": "Something went wrong, see ekrovi.log.",
        "key_fail": "Could not set up the shortcut {key}. The button and the tray menu still work.",
        "ready": "Ready. PrtScr: screen · Shift: area · Ctrl: record · Alt: window",
        "tip_screen": "Send screen · PrtScr", "tip_area": "Pick area · Shift+PrtScr",
        "tip_record": "{s} s recording · Ctrl+PrtScr", "tip_stop": "Stop recording · PrtScr",
        "m_auto": "Send automatically (Enter)", "m_cursor": "Mark the mouse pointer",
        "m_folder": "Open captures folder", "m_hide": "Hide button (bring it back from the tray)",
        "m_quit": "Quit", "m_button": "Floating button",
        "t_screen": "Send screen   (PrtScr)", "t_area": "Pick area   (Shift+PrtScr)",
        "t_record": "{s} s recording   (Ctrl+PrtScr)", "tray_title": "Ekrovi · PrtScr sends your screen to Claude",
        "rec": "Recording  {e:.1f} / {t:.0f} s", "rec_stop": "   PrtScr: stop",
        "hint": "Drag: pick area   ·   Click: window   ·   Esc: cancel",
        "click": "{name}  ·  click", "window": "Window",
        "app_explorer": "File Explorer", "app_notepad": "Notepad",
    },
    "tr": {
        "prompt_screen": "Bu ekrana bak: sorun ne, kaynağı nerede?",
        "prompt_record": "Bu kayda bak: ne oluyor, sorun nerede?",
        "head_screen": "📸 Ekran", "head_window": "🪟 Pencere", "head_area": "✂️ Seçili alan",
        "head_rec": "🎬 {dur:.1f} sn kayıt · {n} kare ({times} sn)",
        "head_rec_static": "🎬 {dur:.1f} sn kayıt · ekran neredeyse hiç değişmedi, son kare",
        "note_cursor": "kırmızı halka = fare imleci", "note_file": "dosya: {path}",
        "note_crop": "ilk kare tam ekran, diğerleri değişen bölgeye yakın",
        "note_frames": "tüm {n} kare: {folder}",
        "badge": "{t:.1f} sn", "badge_full": "{t:.1f} sn · tam ekran", "badge_close": "{t:.1f} sn · yakın",
        "label_shot": "Ekran görüntüsü", "label_img": "Görüntü", "label_rec": "Kayıt",
        "fb_saved": "{label} kaydedildi ve panoya kopyalandı. {reason} Ctrl+V ile yapıştır.",
        "fb_no_claude": "Claude penceresi bulunamadı.", "fb_no_front": "Claude öne gelemedi.",
        "fb_no_box": "Mesaj kutusu bulunamadı.", "fb_changed": "Pencere değişti, durdum.",
        "rec_empty": "Kayıt boş kaldı.", "error": "Bir hata oldu, ayrıntı ekrovi.log dosyasında.",
        "key_fail": "Kısayol kurulamadı: {key}. Buton ve tepsi menüsü çalışır.",
        "ready": "Hazır. PrtScr: ekran · Shift: alan · Ctrl: kayıt · Alt: pencere",
        "tip_screen": "Ekranı gönder · PrtScr", "tip_area": "Alan seç · Shift+PrtScr",
        "tip_record": "{s} sn kayıt · Ctrl+PrtScr", "tip_stop": "Kaydı durdur · PrtScr",
        "m_auto": "Otomatik gönder (Enter)", "m_cursor": "Fare imlecini işaretle",
        "m_folder": "Kayıtlar klasörünü aç", "m_hide": "Butonu gizle (tepsiden geri aç)",
        "m_quit": "Kapat", "m_button": "Yüzen buton",
        "t_screen": "Ekranı gönder   (PrtScr)", "t_area": "Alan seç   (Shift+PrtScr)",
        "t_record": "{s} sn kayıt   (Ctrl+PrtScr)", "tray_title": "Ekrovi · PrtScr ile ekranı Claude'a gönder",
        "rec": "Kayıt  {e:.1f} / {t:.0f} sn", "rec_stop": "   PrtScr: durdur",
        "hint": "Sürükle: alan seç   ·   Tıkla: pencere   ·   Esc: iptal",
        "click": "{name}  ·  tıkla", "window": "Pencere",
        "app_explorer": "Dosya Gezgini", "app_notepad": "Not Defteri",
    },
}


def ui_language():
    lang = str(cfg.get("language", "auto")).lower()
    if lang in STRINGS:
        return lang
    try:  # follow the Windows display language
        return "tr" if (ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF) == 0x1F else "en"
    except Exception:
        return "en"


LANG = ui_language()


def T(name, /, **kw):  # positional-only, so a string may use {name}/{key} placeholders
    text = STRINGS[LANG].get(name) or STRINGS["en"][name]
    return text.format(**kw) if kw else text


def prompt(kind):
    return cfg.get(f"prompt_{kind}") or T(f"prompt_{kind}")


# --------------------------------------------------------------------------- win32

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

HWND = wt.HWND
WNDENUMPROC = ctypes.WINFUNCTYPE(wt.BOOL, HWND, wt.LPARAM)

user32.GetForegroundWindow.restype = HWND
user32.SetForegroundWindow.argtypes = [HWND]
user32.BringWindowToTop.argtypes = [HWND]
user32.SwitchToThisWindow.argtypes = [HWND, wt.BOOL]
user32.ShowWindow.argtypes = [HWND, ctypes.c_int]
user32.IsIconic.argtypes = [HWND]
user32.IsWindowVisible.argtypes = [HWND]
user32.GetWindowTextLengthW.argtypes = [HWND]
user32.GetWindowTextW.argtypes = [HWND, wt.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [HWND, ctypes.POINTER(wt.DWORD)]
user32.GetWindowThreadProcessId.restype = wt.DWORD
user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
user32.GetAncestor.argtypes = [HWND, wt.UINT]
user32.GetAncestor.restype = HWND
user32.GetWindowRect.argtypes = [HWND, ctypes.POINTER(wt.RECT)]
user32.SetWindowDisplayAffinity.argtypes = [HWND, wt.DWORD]
user32.GetWindowLongPtrW.argtypes = [HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.OpenClipboard.argtypes = [HWND]
user32.SetClipboardData.argtypes = [wt.UINT, wt.HANDLE]
user32.SetClipboardData.restype = wt.HANDLE
user32.RegisterClipboardFormatW.argtypes = [wt.LPCWSTR]
user32.RegisterClipboardFormatW.restype = wt.UINT
user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = ctypes.c_short
user32.keybd_event.argtypes = [wt.BYTE, wt.BYTE, wt.DWORD, ctypes.c_size_t]
user32.GetCursorPos.argtypes = [ctypes.POINTER(wt.POINT)]
user32.EnumWindows.argtypes = [WNDENUMPROC, wt.LPARAM]
user32.MessageBoxW.argtypes = [HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
kernel32.GlobalAlloc.argtypes = [wt.UINT, ctypes.c_size_t]
kernel32.GlobalAlloc.restype = wt.HANDLE
kernel32.GlobalLock.argtypes = [wt.HANDLE]
kernel32.GlobalLock.restype = ctypes.c_void_p
kernel32.GlobalUnlock.argtypes = [wt.HANDLE]
kernel32.GlobalFree.argtypes = [wt.HANDLE]
kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel32.OpenProcess.restype = wt.HANDLE
kernel32.QueryFullProcessImageNameW.argtypes = [wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.LPCWSTR]
kernel32.CreateMutexW.restype = wt.HANDLE
dwmapi.DwmGetWindowAttribute.argtypes = [HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]
dwmapi.DwmSetWindowAttribute.argtypes = [HWND, wt.DWORD, ctypes.c_void_p, wt.DWORD]


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("rcMonitor", wt.RECT), ("rcWork", wt.RECT), ("dwFlags", wt.DWORD)]


user32.MonitorFromPoint.argtypes = [wt.POINT, wt.DWORD]
user32.MonitorFromPoint.restype = wt.HANDLE
user32.GetMonitorInfoW.argtypes = [wt.HANDLE, ctypes.POINTER(MONITORINFO)]

VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN = 0x10, 0x11, 0x12, 0x5B, 0x5C
VK_RETURN, VK_END, VK_V = 0x0D, 0x23, 0x56
EXTENDED_KEYS = {VK_END}
OWN_PID = os.getpid()


def key_down(vk):
    return bool(user32.GetAsyncKeyState(vk) & 0x8000)


def mods_down():
    return any(key_down(k) for k in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN))


def wait_mods_released(timeout=3.0):
    end = time.time() + timeout
    while time.time() < end:
        if not mods_down():
            return True
        time.sleep(0.03)
    return False


def tap(*vks):
    seq = [(vk, 1 if vk in EXTENDED_KEYS else 0) for vk in vks]
    for vk, ext in seq:
        user32.keybd_event(vk, 0, ext, 0)
    for vk, ext in reversed(seq):
        user32.keybd_event(vk, 0, ext | 2, 0)
    time.sleep(0.04)


def cursor():
    p = wt.POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def win_pid(h):
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(h, ctypes.byref(pid))
    return pid.value


def win_title(h):
    n = user32.GetWindowTextLengthW(h)
    if n <= 0:
        return ""
    b = ctypes.create_unicode_buffer(n + 1)
    user32.GetWindowTextW(h, b, n + 1)
    return b.value


def win_exe(h):
    hp = kernel32.OpenProcess(0x1000, False, win_pid(h))
    if not hp:
        return ""
    try:
        b = ctypes.create_unicode_buffer(1024)
        n = wt.DWORD(1024)
        return b.value if kernel32.QueryFullProcessImageNameW(hp, 0, b, ctypes.byref(n)) else ""
    finally:
        kernel32.CloseHandle(hp)


def win_rect(h):
    r = wt.RECT()
    if dwmapi.DwmGetWindowAttribute(h, 9, ctypes.byref(r), ctypes.sizeof(r)) != 0:
        user32.GetWindowRect(h, ctypes.byref(r))
    return r.left, r.top, r.right, r.bottom


def clip_to_work_area(l, t, r, b):
    """Keep a window rect inside its monitor's work area, so the taskbar never ends up in a window shot."""
    mon = user32.MonitorFromPoint(wt.POINT((l + r) // 2, (t + b) // 2), 2)  # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if not mon or not user32.GetMonitorInfoW(mon, ctypes.byref(mi)):
        return l, t, r, b
    w = mi.rcWork
    nl, nt, nr, nb = max(l, w.left), max(t, w.top), min(r, w.right), min(b, w.bottom)
    return (nl, nt, nr, nb) if nr - nl > 20 and nb - nt > 20 else (l, t, r, b)


def is_cloaked(h):
    v = wt.DWORD()
    dwmapi.DwmGetWindowAttribute(h, 14, ctypes.byref(v), 4)
    return v.value != 0


APP_NAMES = {
    "chrome": "Chrome", "msedge": "Edge", "firefox": "Firefox", "code": "VS Code",
    "explorer": T("app_explorer"), "claude": "Claude", "unrealeditor": "UEFN",
    "windowsterminal": "Terminal", "powershell": "PowerShell", "pwsh": "PowerShell",
    "notepad": T("app_notepad"), "blender": "Blender", "photoshop": "Photoshop",
    "obs64": "OBS", "excel": "Excel", "winword": "Word", "robloxstudiobeta": "Roblox Studio",
}


def app_info(h):
    if not h:
        return {}
    exe = Path(win_exe(h)).stem
    return {"hwnd": h, "exe": exe, "app": APP_NAMES.get(exe.lower(), exe), "title": win_title(h)}


def list_windows():
    """Visible top-level windows of other processes, in z-order (top first)."""
    out = []

    @WNDENUMPROC
    def cb(h, _):
        try:
            if not user32.IsWindowVisible(h) or user32.IsIconic(h) or is_cloaked(h):
                return True
            if win_pid(h) == OWN_PID or not win_title(h):
                return True
            r = clip_to_work_area(*win_rect(h))
            if r[2] - r[0] >= 40 and r[3] - r[1] >= 40:
                out.append((h, r))
        except Exception:
            pass
        return True

    user32.EnumWindows(cb, 0)
    return out


def find_claude():
    target = "\\" + cfg["target_exe"].lower()
    found = []

    @WNDENUMPROC
    def cb(h, _):
        try:
            if user32.IsWindowVisible(h) and win_title(h) and win_exe(h).lower().endswith(target):
                l, t, r, b = win_rect(h)
                if user32.IsIconic(h) or (r - l > 300 and b - t > 300):
                    found.append(h)
                    return False
        except Exception:
            pass
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else None


def force_foreground(h):
    if user32.IsIconic(h):
        user32.ShowWindow(h, 9)  # SW_RESTORE
    if user32.GetForegroundWindow() == h:
        return True
    fg = user32.GetForegroundWindow()
    me = kernel32.GetCurrentThreadId()
    t_fg = user32.GetWindowThreadProcessId(fg, None) if fg else 0
    attached = bool(t_fg and t_fg != me and user32.AttachThreadInput(me, t_fg, True))
    try:
        user32.BringWindowToTop(h)
        user32.SetForegroundWindow(h)
    finally:
        if attached:
            user32.AttachThreadInput(me, t_fg, False)
    for attempt in range(3):
        for _ in range(15):
            if user32.GetForegroundWindow() == h:
                return True
            time.sleep(0.02)
        if attempt == 0:
            user32.SwitchToThisWindow(h, True)
        elif attempt == 1 and not mods_down():
            user32.keybd_event(VK_MENU, 0, 0, 0)
            user32.keybd_event(VK_MENU, 0, 2, 0)
            user32.SetForegroundWindow(h)
    return user32.GetForegroundWindow() == h


# --------------------------------------------------------------------------- clipboard

CF_DIB, CF_UNICODETEXT = 8, 13
CF_PNG = user32.RegisterClipboardFormatW("PNG")


def _clip_open():
    for _ in range(40):
        if user32.OpenClipboard(None):
            return
        time.sleep(0.025)
    raise RuntimeError("clipboard busy")


def _clip_put(fmt, data):
    h = kernel32.GlobalAlloc(0x0002, len(data))
    p = kernel32.GlobalLock(h)
    ctypes.memmove(p, data, len(data))
    kernel32.GlobalUnlock(h)
    if not user32.SetClipboardData(fmt, h):
        kernel32.GlobalFree(h)


def clip_image(img):
    b = io.BytesIO()
    img.convert("RGB").save(b, "BMP")
    dib = b.getvalue()[14:]
    p = io.BytesIO()
    img.save(p, "PNG")
    _clip_open()
    try:
        user32.EmptyClipboard()
        _clip_put(CF_DIB, dib)
        _clip_put(CF_PNG, p.getvalue())
    finally:
        user32.CloseClipboard()


def clip_text(s):
    _clip_open()
    try:
        user32.EmptyClipboard()
        _clip_put(CF_UNICODETEXT, (s + "\0").encode("utf-16-le"))
    finally:
        user32.CloseClipboard()


# --------------------------------------------------------------------------- images

import mss  # noqa: E402

MSS = getattr(mss, "MSS", None) or mss.mss  # mss 10 renamed the class
from PIL import Image, ImageDraw, ImageEnhance, ImageFont  # noqa: E402

FONT_UI = r"C:\Windows\Fonts\seguisb.ttf"


def font(size):
    try:
        return ImageFont.truetype(FONT_UI, size)
    except Exception:
        return ImageFont.load_default()


def grab(sct, region):
    s = sct.grab({k: int(region[k]) for k in ("left", "top", "width", "height")})
    return Image.frombytes("RGB", s.size, s.bgra, "raw", "BGRX")


def monitor_at(sct, x, y):
    for m in sct.monitors[1:]:
        if m["left"] <= x < m["left"] + m["width"] and m["top"] <= y < m["top"] + m["height"]:
            return m
    return sct.monitors[1]


def clip_to_virtual(sct, l, t, r, b):
    v = sct.monitors[0]
    l, t = max(l, v["left"]), max(t, v["top"])
    r, b = min(r, v["left"] + v["width"]), min(b, v["top"] + v["height"])
    return {"left": l, "top": t, "width": max(1, r - l), "height": max(1, b - t)}


def draw_cursor(img, x, y):
    """Hollow ring around the mouse position; the centre stays visible."""
    if not (-40 <= x < img.width + 40 and -40 <= y < img.height + 40):
        return
    d = ImageDraw.Draw(img)
    r = 19
    d.ellipse((x - r - 2, y - r - 2, x + r + 2, y + r + 2), outline=(255, 255, 255), width=2)
    d.ellipse((x - r, y - r, x + r, y + r), outline=(255, 59, 48), width=3)


def badge(img, text):
    d = ImageDraw.Draw(img, "RGBA")
    f = font(max(14, img.width // 72))
    l, t, r, b = d.textbbox((0, 0), text, font=f)
    pad, x, y = 7, 10, 10
    d.rounded_rectangle((x, y, x + r - l + 2 * pad, y + b - t + 2 * pad), radius=7, fill=(12, 12, 14, 185))
    d.text((x + pad - l, y + pad - t), text, font=f, fill=(255, 255, 255, 255))


def fit(img):
    w, h = img.size
    s = cfg["max_edge"] / max(w, h)
    return img.resize((round(w * s), round(h * s)), Image.LANCZOS) if s < 1 else img


def out_dir():
    d = HERE / cfg["save_dir"] / datetime.date.today().isoformat()
    d.mkdir(parents=True, exist_ok=True)
    return d


def stamp():
    return time.strftime("%H%M%S")


def context(info):
    if not info or not info.get("app") or info.get("exe", "").lower() == "claude":
        return ""
    s = f" · {info['app']}"
    title = (info.get("title") or "").strip()
    if title and title != info["app"]:
        s += f" — “{title[:90]}”"
    return s


def message(head, info, prompt, notes):
    return "\n".join([f"{head} · {time.strftime('%H:%M')}{context(info)}", prompt, "(" + " · ".join(notes) + ")"])


def analyse(frames, max_n):
    """Pick key frames where the change happens, and a crop box if the change is local."""
    import numpy as np

    SW, SH = 240, 135
    W, H = frames[0][1].size
    sm = [np.asarray(f[1].convert("L").resize((SW, SH), Image.BILINEAR), dtype=np.int16) for f in frames]
    n = len(sm)
    diffs = np.zeros(n)
    mask = np.zeros((SH, SW), dtype=bool)
    for i in range(1, n):
        d = np.abs(sm[i] - sm[i - 1])
        diffs[i] = d.mean()
        mask |= d > 18
        (x0, y0), (x1, y1) = frames[i - 1][2], frames[i][2]
        moved = ((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5
        if moved > 3:
            diffs[i] += 4.0 * moved / W
    total = float(diffs.sum())
    if n == 1 or total < 0.25:
        return [n - 1], None
    m = max(2, min(max_n, n))
    cum = np.cumsum(diffs)
    keys = [0]
    for k in range(1, m - 1):
        i = int(np.searchsorted(cum, total * k / (m - 1)))
        keys.append(min(max(i, keys[-1] + 1), n - 1))
    keys.append(n - 1)
    keys = sorted(set(keys))

    ys, xs = np.nonzero(mask)
    if len(xs) < 3:
        return keys, None
    sx, sy = W / SW, H / SH
    x0, x1 = np.percentile(xs, [1, 99])
    y0, y1 = np.percentile(ys, [1, 99])
    bx0, bx1, by0, by1 = x0 * sx, (x1 + 1) * sx, y0 * sy, (y1 + 1) * sy
    if (bx1 - bx0) * (by1 - by0) >= 0.35 * W * H:
        return keys, None
    pad = 60
    bx0, by0, bx1, by1 = bx0 - pad, by0 - pad, bx1 + pad, by1 + pad
    minw, minh = min(W, 720), min(H, 405)
    if bx1 - bx0 < minw:
        c = (bx0 + bx1) / 2
        bx0, bx1 = c - minw / 2, c + minw / 2
    if by1 - by0 < minh:
        c = (by0 + by1) / 2
        by0, by1 = c - minh / 2, c + minh / 2
    if bx0 < 0:
        bx1, bx0 = bx1 - bx0, 0
    if by0 < 0:
        by1, by0 = by1 - by0, 0
    if bx1 > W:
        bx0, bx1 = bx0 - (bx1 - W), W
    if by1 > H:
        by0, by1 = by0 - (by1 - H), H
    return keys, (int(max(0, bx0)), int(max(0, by0)), int(min(W, bx1)), int(min(H, by1)))


# --------------------------------------------------------------------------- delivery (worker thread)

def uia_client():
    from uiautomation.uiautomation import _AutomationClient
    return _AutomationClient.instance().IUIAutomation


def is_editor(c):
    # The message box is an Edit with class "tiptap ProseMirror"; its wrapper div also
    # mentions ProseMirror in its (Tailwind) class list, so the control type matters.
    return c is not None and c.ControlTypeName == "EditControl" and "ProseMirror" in (c.ClassName or "")


def find_editor(auto, h):
    f = auto.GetFocusedControl()
    if is_editor(f):
        return f
    ia = uia_client()
    root = ia.ElementFromHandle(h)
    cond = ia.CreateAndCondition(ia.CreatePropertyCondition(30003, 50004),  # ControlType = Edit
                                 ia.CreatePropertyConditionEx(30012, "ProseMirror", 2))  # class contains
    for _ in range(14):  # Chromium builds its accessibility tree on first request
        el = root.FindFirst(4, cond)
        if el:
            return auto.Control.CreateControlFromElement(el)
        time.sleep(0.25)
    return None


def editor_focused(auto):
    return is_editor(auto.GetFocusedControl())


def focus_editor(auto, ed):
    try:
        ed.SetFocus()
    except Exception:
        pass
    time.sleep(0.08)
    if editor_focused(auto):
        return True
    try:
        if ed.BoundingRectangle.width() > 0:
            ed.Click(simulateMove=False, waitTime=0.1)
    except Exception:
        pass
    return editor_focused(auto)


def editor_empty(auto, ed):
    # An empty tiptap editor holds one paragraph with class "is-empty is-editor-empty".
    try:
        for c, _ in auto.WalkControl(ed, includeTop=False, maxDepth=2):
            if "is-editor-empty" in (c.ClassName or ""):
                return True
        return False
    except Exception:
        return False


def deliver(app, auto, images, text, label):
    def fallback(reason):
        clip_image(images[0])
        app.notify(T("fb_saved", label=label, reason=reason))
        log("fallback:", reason)
        return False

    h = find_claude()
    if not h:
        return fallback(T("fb_no_claude"))
    wait_mods_released()
    if not force_foreground(h):
        return fallback(T("fb_no_front"))
    ed = find_editor(auto, h)
    if ed is None or not focus_editor(auto, ed):
        return fallback(T("fb_no_box"))
    empty = editor_empty(auto, ed)
    tap(VK_CONTROL, VK_END)
    for img in images:
        if user32.GetForegroundWindow() != h:
            return fallback(T("fb_changed"))
        clip_image(img)
        tap(VK_CONTROL, VK_V)
        time.sleep(0.45)
    if user32.GetForegroundWindow() != h:
        return fallback(T("fb_changed"))
    clip_text(text if empty else "\n" + text)
    tap(VK_CONTROL, VK_V)
    if cfg["auto_send"] and empty:
        time.sleep(1.0)
        if user32.GetForegroundWindow() == h and editor_focused(auto):
            tap(VK_RETURN)
    log("delivered", label, len(images), "image(s)", "sent" if cfg["auto_send"] and empty else "pasted")
    return True


def job_screen(app, auto, info, point, mark, kind, hwnd=None):
    with MSS() as sct:
        if kind == "window" and hwnd:
            region = clip_to_virtual(sct, *clip_to_work_area(*win_rect(hwnd)))
        else:
            region = monitor_at(sct, *point)
        cx, cy = cursor()
        img = grab(sct, region)
    notes = []
    if mark:
        draw_cursor(img, cx - region["left"], cy - region["top"])
        notes.append(T("note_cursor"))
    path = out_dir() / f"{stamp()}_{'window' if kind == 'window' else 'screen'}.png"
    img.save(path)
    notes.append(T("note_file", path=path))
    head = T("head_window") if kind == "window" else T("head_screen")
    deliver(app, auto, [fit(img)], message(head, info, prompt("screen"), notes), T("label_shot"))


def job_area(app, auto, img, info, kind):
    path = out_dir() / f"{stamp()}_{'window' if kind == 'window' else 'area'}.png"
    img.save(path)
    head = T("head_window") if kind == "window" else T("head_area")
    deliver(app, auto, [fit(img)], message(head, info, prompt("screen"), [T("note_file", path=path)]), T("label_img"))


def job_record(app, auto, rec):
    frames = rec.frames
    if not frames:
        app.notify(T("rec_empty"))
        return
    folder = out_dir() / f"{stamp()}_recording"
    folder.mkdir(parents=True, exist_ok=True)
    keys, crop = analyse(frames, max(1, int(cfg["max_images"])))
    left, top = rec.mon["left"], rec.mon["top"]
    out = []
    for j, i in enumerate(keys):
        t, img, (cx, cy) = frames[i]
        im = img.copy()
        if rec.mark:
            draw_cursor(im, cx - left, cy - top)
        if crop and j > 0:
            im = im.crop(crop)
            label = T("badge_close", t=t)
        else:
            label = T("badge_full", t=t) if crop else T("badge", t=t)
        im = fit(im)
        badge(im, label)
        out.append((t, im))
    dur = frames[-1][0]
    times = " / ".join(f"{t:.1f}" for t, _ in out)
    if len(out) == 1 and len(frames) > 1:
        head = T("head_rec_static", dur=dur)
    else:
        head = T("head_rec", dur=dur, n=len(out), times=times)
    notes = []
    if rec.mark:
        notes.append(T("note_cursor"))
    if crop:
        notes.append(T("note_crop"))
    notes.append(T("note_frames", n=len(frames), folder=folder))
    deliver(app, auto, [im for _, im in out], message(head, rec.info, prompt("record"), notes), T("label_rec"))
    for i, (t, img, _) in enumerate(frames):
        img.save(folder / f"{i:02d}_{t:04.1f}s.jpg", quality=85)
    for j, (t, im) in enumerate(out, 1):
        im.save(folder / f"sent_{j}_{t:.1f}s.png")


def worker(app):
    import uiautomation as auto

    with auto.UIAutomationInitializerInThread():
        while True:
            job = app.job_q.get()
            try:
                kind = job[0]
                if kind == "screen":
                    job_screen(app, auto, *job[1:])
                elif kind == "area":
                    job_area(app, auto, *job[1:])
                elif kind == "record":
                    job_record(app, auto, job[1])
            except Exception:
                log(traceback.format_exc())
                app.notify(T("error"))
            finally:
                app.ui_q.put(("job_done",))


# --------------------------------------------------------------------------- recorder

class Recorder(threading.Thread):
    def __init__(self, app, mon, info, mark):
        super().__init__(daemon=True)
        self.app, self.mon, self.info, self.mark = app, mon, info, mark
        self.seconds = float(cfg["record_seconds"])
        self.fps = max(1.0, float(cfg["record_fps"]))
        self.stop_ev = threading.Event()
        self.frames = []
        self.t0 = time.perf_counter()

    def elapsed(self):
        return time.perf_counter() - self.t0

    def run(self):
        try:
            with MSS() as sct:
                self.t0 = time.perf_counter()
                nxt = self.t0
                while not self.stop_ev.is_set():
                    t = self.elapsed()
                    if t > self.seconds:
                        break
                    c = cursor()
                    self.frames.append((t, grab(sct, self.mon), c))
                    nxt += 1.0 / self.fps
                    wait = nxt - time.perf_counter()
                    if wait > 0:
                        self.stop_ev.wait(wait)
        except Exception:
            log(traceback.format_exc())
        finally:
            self.app.ui_q.put(("rec_stopped",))
            self.app.job_q.put(("record", self))


# --------------------------------------------------------------------------- Tk UI

import tkinter as tk  # noqa: E402

from PIL import ImageTk  # noqa: E402

BG, HOVER, FG, DIM, RED = "#1b1b1f", "#2d2d34", "#ececf1", "#5c5c66", "#ff453a"
ICON_FONT = ("Segoe Fluent Icons", 13)
G_SCREEN, G_AREA, G_RECORD, G_STOP = "\ue7f4", "\uef20", "\ue7c8", "\ue71a"


def style_popup(win, rounded=True):
    """Tool window that never takes focus, is left out of screen captures, with rounded corners."""
    win.update_idletasks()
    h = user32.GetAncestor(win.winfo_id(), 2) or win.winfo_id()
    ex = user32.GetWindowLongPtrW(h, -20)
    user32.SetWindowLongPtrW(h, -20, ex | 0x80 | 0x08000000)  # TOOLWINDOW | NOACTIVATE
    if rounded:
        v = ctypes.c_int(2)
        dwmapi.DwmSetWindowAttribute(h, 33, ctypes.byref(v), 4)
        col = wt.DWORD(0x003C3434)
        dwmapi.DwmSetWindowAttribute(h, 34, ctypes.byref(col), 4)
    if cfg["exclude_from_capture"]:
        user32.SetWindowDisplayAffinity(h, 0x11)  # WDA_EXCLUDEFROMCAPTURE
    return h


def round_rect(cv, x0, y0, x1, y1, r, **kw):
    pts = [x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1,
           x0 + r, y1, x0, y1, x0, y1 - r, x0, y0 + r, x0, y0]
    return cv.create_polygon(pts, smooth=True, splinesteps=12, **kw)


class Tooltip:
    def __init__(self, root):
        self.top = tk.Toplevel(root)
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.configure(bg=BG)
        self.lbl = tk.Label(self.top, bg=BG, fg=FG, font=("Segoe UI", 9), padx=9, pady=4)
        self.lbl.pack()
        self.top.withdraw()
        style_popup(self.top)

    def show(self, text, cx, y_above):
        self.lbl.configure(text=text)
        self.top.update_idletasks()
        w, h = self.top.winfo_reqwidth(), self.top.winfo_reqheight()
        self.top.geometry(f"+{int(cx - w / 2)}+{int(y_above - h - 6)}")
        self.top.deiconify()
        self.top.lift()

    def hide(self):
        self.top.withdraw()


class FloatingButton:
    L, BW, GAP, H = 20, 38, 2, 42

    def __init__(self, app):
        self.app = app
        self.items = [
            ("screen", G_SCREEN, T("tip_screen")),
            ("area", G_AREA, T("tip_area")),
            ("record", G_RECORD, T("tip_record", s=int(cfg["record_seconds"]))),
        ]
        self.W = self.L + 3 * self.BW + 2 * self.GAP + 6
        t = self.top = tk.Toplevel(app.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=BG)
        cv = self.cv = tk.Canvas(t, width=self.W, height=self.H, bg=BG, highlightthickness=0, bd=0)
        cv.pack()
        for row in range(3):
            for col in range(2):
                x, y = 8 + col * 5, 14 + row * 6
                cv.create_oval(x, y, x + 2.4, y + 2.4, fill=DIM, outline="")
        self.hover_ids, self.icon_ids = [], []
        for i, (mode, glyph, _) in enumerate(self.items):
            x0 = self.L + i * (self.BW + self.GAP)
            self.hover_ids.append(round_rect(cv, x0, 5, x0 + self.BW, self.H - 5, 8, fill=BG, outline=""))
            color = RED if mode == "record" else FG
            self.icon_ids.append(cv.create_text(x0 + self.BW / 2, self.H / 2, text=glyph, font=ICON_FONT, fill=color))
        self.tip = Tooltip(app.root)
        self.hover = None
        self.tip_job = None
        self.press = None
        self.dragging = False
        cv.bind("<Motion>", self.on_motion)
        cv.bind("<Leave>", self.on_leave)
        cv.bind("<ButtonPress-1>", self.on_press)
        cv.bind("<B1-Motion>", self.on_drag)
        cv.bind("<ButtonRelease-1>", self.on_release)
        cv.bind("<ButtonPress-3>", self.on_menu)
        pos = cfg.get("button_pos")
        if not pos:
            sw, sh = t.winfo_screenwidth(), t.winfo_screenheight()
            pos = [sw - self.W - 24, sh - self.H - 72]
        t.geometry(f"{self.W}x{self.H}+{int(pos[0])}+{int(pos[1])}")
        style_popup(t)
        self.menu = None

    def hit(self, x):
        for i in range(3):
            x0 = self.L + i * (self.BW + self.GAP)
            if x0 <= x < x0 + self.BW:
                return i
        return None

    def set_hover(self, i):
        if i == self.hover:
            return
        if self.hover is not None:
            self.cv.itemconfigure(self.hover_ids[self.hover], fill=BG)
        self.hover = i
        if self.tip_job:
            self.cv.after_cancel(self.tip_job)
            self.tip_job = None
        self.tip.hide()
        if i is not None:
            self.cv.itemconfigure(self.hover_ids[i], fill=HOVER)
            self.tip_job = self.cv.after(450, lambda: self.show_tip(i))

    def show_tip(self, i):
        self.tip_job = None
        if self.hover != i or self.dragging:
            return
        x0 = self.top.winfo_rootx() + self.L + i * (self.BW + self.GAP) + self.BW / 2
        text = T("tip_stop") if (i == 2 and self.app.recorder) else self.items[i][2]
        self.tip.show(text, x0, self.top.winfo_rooty())

    def on_motion(self, e):
        if not self.dragging:
            self.set_hover(self.hit(e.x))

    def on_leave(self, _):
        if not self.dragging:
            self.set_hover(None)

    def on_press(self, e):
        self.press = (e.x_root, e.y_root, self.top.winfo_x(), self.top.winfo_y())
        self.dragging = False

    def on_drag(self, e):
        if not self.press:
            return
        dx, dy = e.x_root - self.press[0], e.y_root - self.press[1]
        if not self.dragging and abs(dx) + abs(dy) > 4:
            self.dragging = True
            self.set_hover(None)
        if self.dragging:
            self.top.geometry(f"+{self.press[2] + dx}+{self.press[3] + dy}")

    def on_release(self, e):
        if self.dragging:
            self.dragging = False
            cfg["button_pos"] = [self.top.winfo_x(), self.top.winfo_y()]
            save_cfg()
        else:
            i = self.hit(e.x)
            if i is not None:
                self.tip.hide()
                self.app.handle(("capture", self.items[i][0], "button"))
        self.press = None

    def on_menu(self, e):
        self.tip.hide()
        m = tk.Menu(self.top, tearoff=0, font=("Segoe UI", 10))
        self.v_auto = tk.BooleanVar(value=cfg["auto_send"])
        self.v_cur = tk.BooleanVar(value=cfg["mark_cursor"])
        m.add_checkbutton(label=T("m_auto"), variable=self.v_auto,
                          command=lambda: self.app.handle(("toggle", "auto_send")))
        m.add_checkbutton(label=T("m_cursor"), variable=self.v_cur,
                          command=lambda: self.app.handle(("toggle", "mark_cursor")))
        m.add_command(label=T("m_folder"), command=lambda: self.app.handle(("open_dir",)))
        m.add_separator()
        m.add_command(label=T("m_hide"), command=lambda: self.app.handle(("toggle", "show_button")))
        m.add_command(label=T("m_quit"), command=lambda: self.app.handle(("quit",)))
        m.tk_popup(e.x_root, e.y_root)

    def set_recording(self, on):
        self.cv.itemconfigure(self.icon_ids[2], text=G_STOP if on else G_RECORD)

    def show(self, on):
        if on:
            self.top.deiconify()
            self.top.lift()
        else:
            self.tip.hide()
            self.top.withdraw()


class RecIndicator:
    def __init__(self, app, mon):
        t = self.top = tk.Toplevel(app.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.configure(bg=BG)
        f = tk.Frame(t, bg=BG, padx=14, pady=7)
        f.pack()
        dot = tk.Canvas(f, width=12, height=12, bg=BG, highlightthickness=0)
        dot.create_oval(1, 1, 11, 11, fill=RED, outline="")
        dot.pack(side="left", padx=(0, 9))
        self.lbl = tk.Label(f, text=T("rec", e=0, t=float(cfg["record_seconds"])), bg=BG, fg=FG, font=("Segoe UI Semibold", 10))
        self.lbl.pack(side="left")
        tk.Label(f, text=T("rec_stop"), bg=BG, fg="#9a9aa5", font=("Segoe UI", 9)).pack(side="left")
        t.update_idletasks()
        w = t.winfo_reqwidth()
        t.geometry(f"+{int(mon['left'] + (mon['width'] - w) / 2)}+{int(mon['top'] + 14)}")
        style_popup(t)

    def update(self, elapsed, total):
        self.lbl.configure(text=T("rec", e=min(elapsed, total), t=total))

    def close(self):
        self.top.destroy()


class AreaPicker:
    def __init__(self, app, on_done, on_cancel):
        self.app, self.on_done, self.on_cancel = app, on_done, on_cancel
        with MSS() as sct:
            self.v = sct.monitors[0]
            self.full = grab(sct, self.v)
        self.windows = list_windows()
        vl, vt, W, H = self.v["left"], self.v["top"], self.v["width"], self.v["height"]
        self.W, self.H = W, H
        t = self.top = tk.Toplevel(app.root)
        t.overrideredirect(True)
        t.attributes("-topmost", True)
        t.geometry(f"{W}x{H}+{vl}+{vt}")
        cv = self.cv = tk.Canvas(t, width=W, height=H, highlightthickness=0, bd=0, cursor="crosshair", bg="black")
        cv.pack()
        self.ph_dim = ImageTk.PhotoImage(ImageEnhance.Brightness(self.full).enhance(0.45), master=t)
        self.ph_full = ImageTk.PhotoImage(self.full, master=t)
        cv.create_image(0, 0, image=self.ph_dim, anchor="nw")
        self.sel = tk.PhotoImage(master=t)
        self.sel_item = cv.create_image(0, 0, image=self.sel, anchor="nw", state="hidden")
        self.rect = cv.create_rectangle(0, 0, 0, 0, outline="#ffffff", width=2, state="hidden")
        self.lbl_bg = cv.create_rectangle(0, 0, 0, 0, fill="#141417", outline="", state="hidden")
        self.lbl = cv.create_text(0, 0, text="", fill="#ffffff", font=("Segoe UI Semibold", 10), anchor="nw", state="hidden")
        cx, cy = cursor()
        with MSS() as sct:
            m = monitor_at(sct, cx, cy)
        hx = m["left"] - vl + m["width"] / 2
        hint = cv.create_text(hx, m["top"] - vt + 34, text=T("hint"),
                              fill="#ffffff", font=("Segoe UI Semibold", 11))
        b = cv.bbox(hint)
        bg = round_rect(cv, b[0] - 16, b[1] - 9, b[2] + 16, b[3] + 9, 12, fill="#141417", outline="")
        cv.tag_raise(hint, bg)
        self.start = None
        self.hover = None
        self.mode = None
        cv.bind("<Motion>", self.on_motion)
        cv.bind("<ButtonPress-1>", self.on_press)
        cv.bind("<B1-Motion>", self.on_drag)
        cv.bind("<ButtonRelease-1>", self.on_release)
        cv.bind("<ButtonPress-3>", lambda e: self.cancel())
        t.bind("<Escape>", lambda e: self.cancel())
        self.esc = None
        try:
            import keyboard
            self.esc = keyboard.add_hotkey("esc", lambda: app.ui_q.put(("area_cancel",)), suppress=True)
        except Exception:
            pass
        t.focus_force()
        self.on_motion(None)

    def show_region(self, x0, y0, x1, y1, label):
        x0, x1 = sorted((int(x0), int(x1)))
        y0, y1 = sorted((int(y0), int(y1)))
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(self.W, x1), min(self.H, y1)
        if x1 - x0 < 2 or y1 - y0 < 2:
            for it in (self.sel_item, self.rect, self.lbl, self.lbl_bg):
                self.cv.itemconfigure(it, state="hidden")
            return
        self.top.tk.call(str(self.sel), "copy", str(self.ph_full), "-from", x0, y0, x1, y1, "-shrink")
        self.cv.coords(self.sel_item, x0, y0)
        self.cv.coords(self.rect, x0 + 1, y0 + 1, x1 - 1, y1 - 1)
        self.cv.itemconfigure(self.lbl, text=label, state="normal")  # bbox() is None while hidden
        ly = y1 + 8 if y1 + 34 < self.H else y0 - 30
        self.cv.coords(self.lbl, x0 + 8, max(4, ly + 4))
        b = self.cv.bbox(self.lbl)
        self.cv.coords(self.lbl_bg, b[0] - 8, b[1] - 4, b[2] + 8, b[3] + 4)
        for it in (self.sel_item, self.rect, self.lbl_bg, self.lbl):
            self.cv.itemconfigure(it, state="normal")
            self.cv.tag_raise(it)

    def window_at(self, ax, ay):
        for h, r in self.windows:
            if r[0] <= ax < r[2] and r[1] <= ay < r[3]:
                return h, r
        return None

    def on_motion(self, e):
        if self.start:
            return
        ax, ay = cursor() if e is None else (e.x + self.v["left"], e.y + self.v["top"])
        w = self.window_at(ax, ay)
        if w and (not self.hover or w[0] != self.hover[0]):
            self.hover = w
            l, t, r, b = w[1]
            name = app_info(w[0]).get("app") or T("window")
            self.show_region(l - self.v["left"], t - self.v["top"], r - self.v["left"], b - self.v["top"],
                             T("click", name=name))
        elif not w and self.hover:
            self.hover = None
            self.show_region(0, 0, 0, 0, "")

    def on_press(self, e):
        self.start = (e.x, e.y)

    def on_drag(self, e):
        if not self.start:
            return
        x0, y0 = self.start
        if abs(e.x - x0) + abs(e.y - y0) > 5:
            self.show_region(x0, y0, e.x, e.y, f"{abs(e.x - x0)} × {abs(e.y - y0)}")

    def on_release(self, e):
        vl, vt = self.v["left"], self.v["top"]
        if self.start and abs(e.x - self.start[0]) > 5 and abs(e.y - self.start[1]) > 5:
            x0, x1 = sorted((self.start[0], e.x))
            y0, y1 = sorted((self.start[1], e.y))
            x0, y0, x1, y1 = max(0, x0), max(0, y0), min(self.W, x1), min(self.H, y1)
            w = self.window_at((x0 + x1) // 2 + vl, (y0 + y1) // 2 + vt)
            info = app_info(w[0]) if w else {}
            kind = "area"
        elif self.hover:
            l, t, r, b = self.hover[1]
            x0, y0, x1, y1 = max(0, l - vl), max(0, t - vt), min(self.W, r - vl), min(self.H, b - vt)
            info = app_info(self.hover[0])
            kind = "window"
        else:
            self.cancel()
            return
        crop = self.full.crop((x0, y0, x1, y1))
        self.close()
        self.on_done(crop, info, kind)

    def close(self):
        if self.esc is not None:
            try:
                import keyboard
                keyboard.remove_hotkey(self.esc)
            except Exception:
                pass
            self.esc = None
        try:
            self.top.destroy()
        except Exception:
            pass

    def cancel(self):
        self.close()
        self.on_cancel()


def tray_image():
    S = 256
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((8, 8, S - 8, S - 8), radius=58, fill=(27, 27, 31, 255))
    c, w, L, m = (236, 236, 241, 255), 18, 58, 54
    for x, y, sx, sy in [(m, m, 1, 1), (S - m, m, -1, 1), (m, S - m, 1, -1), (S - m, S - m, -1, -1)]:
        d.line((x - sx * w / 2, y, x + sx * L, y), fill=c, width=w)
        d.line((x, y - sy * w / 2, x, y + sy * L), fill=c, width=w)
    d.ellipse((S / 2 - 30, S / 2 - 30, S / 2 + 30, S / 2 + 30), fill=(255, 69, 58, 255))
    return im.resize((64, 64), Image.LANCZOS)


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.report_callback_exception = lambda *a: log("".join(traceback.format_exception(*a)))
        self.ui_q, self.job_q = queue.Queue(), queue.Queue()
        self.busy_since = None
        self.recorder = None
        self.indicator = None
        self.picker = None
        self.last_fg = None
        self.key_held = False
        self.tray = None
        self.button = FloatingButton(self)
        if not cfg["show_button"]:
            self.button.show(False)
        threading.Thread(target=worker, args=(self,), daemon=True).start()
        threading.Thread(target=self.udp_server, daemon=True).start()
        self.start_tray()
        self.install_key()
        self.root.after(30, self.poll)

    # -- outside threads talk to Tk only through ui_q
    def notify(self, text):
        self.ui_q.put(("notify", text))

    def install_key(self):
        import keyboard

        def cb(e):
            if e.event_type == "down":
                if not self.key_held:
                    self.key_held = True
                    if key_down(VK_SHIFT):
                        mode = "area"
                    elif key_down(VK_CONTROL):
                        mode = "record"
                    elif key_down(VK_MENU):
                        mode = "window"
                    else:
                        mode = "screen"
                    self.ui_q.put(("capture", mode, "key"))
            else:
                self.key_held = False
            return False  # swallow the key so Snipping Tool does not open

        try:
            keyboard.hook_key(cfg["key"], cb, suppress=True)
        except Exception:
            log(traceback.format_exc())
            self.notify(T("key_fail", key=cfg["key"]))

    def udp_server(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("127.0.0.1", UDP_PORT))
        except OSError as e:
            log("udp bind failed:", e)
            return
        while True:
            data, _ = s.recvfrom(256)
            cmd = data.decode("utf-8", "ignore").strip().lower()
            if cmd in ("screen", "window", "area", "record"):
                self.ui_q.put(("capture", cmd, "ipc"))
            elif cmd == "show":
                self.ui_q.put(("set", "show_button", True))
            elif cmd == "quit":
                self.ui_q.put(("quit",))

    def start_tray(self):
        try:
            import pystray
        except Exception:
            log("pystray missing")
            return

        def cmd(*msg):
            return lambda icon, item: self.ui_q.put(msg)

        menu = pystray.Menu(
            pystray.MenuItem(T("t_screen"), cmd("capture", "screen", "tray"), default=True),
            pystray.MenuItem(T("t_area"), cmd("capture", "area", "tray")),
            pystray.MenuItem(T("t_record", s=int(cfg["record_seconds"])), cmd("capture", "record", "tray")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(T("m_button"), cmd("toggle", "show_button"), checked=lambda i: cfg["show_button"]),
            pystray.MenuItem(T("m_auto"), cmd("toggle", "auto_send"), checked=lambda i: cfg["auto_send"]),
            pystray.MenuItem(T("m_cursor"), cmd("toggle", "mark_cursor"), checked=lambda i: cfg["mark_cursor"]),
            pystray.MenuItem(T("m_folder"), cmd("open_dir")),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(T("m_quit"), cmd("quit")),
        )
        self.tray = pystray.Icon("Ekrovi", tray_image(), T("tray_title"), menu)
        threading.Thread(target=self.tray.run, daemon=True).start()

    @property
    def busy(self):
        if self.busy_since and time.time() - self.busy_since > 40:
            log("busy flag reset after timeout")
            self.busy_since = None
        return self.busy_since is not None

    def poll(self):
        try:
            while True:
                self.handle(self.ui_q.get_nowait())
        except queue.Empty:
            pass
        except Exception:
            log(traceback.format_exc())
        fg = user32.GetForegroundWindow()
        if fg and win_pid(fg) != OWN_PID:
            self.last_fg = fg
        if self.recorder and self.indicator:
            self.indicator.update(self.recorder.elapsed(), self.recorder.seconds)
        self.root.after(40, self.poll)

    def handle(self, msg):
        kind = msg[0]
        if kind == "capture":
            self.capture(msg[1], msg[2])
        elif kind == "job_done":
            self.busy_since = None
        elif kind == "rec_stopped":
            if self.indicator:
                self.indicator.close()
            self.indicator = None
            self.recorder = None
            self.button.set_recording(False)
        elif kind == "area_cancel":
            if self.picker:
                self.picker.cancel()
        elif kind == "notify":
            log("notify:", msg[1])
            if self.tray:
                try:
                    self.tray.notify(msg[1], "Ekrovi")
                except Exception:
                    pass
        elif kind == "toggle":
            self.set_option(msg[1], not cfg[msg[1]])
        elif kind == "set":
            self.set_option(msg[1], msg[2])
        elif kind == "open_dir":
            d = HERE / cfg["save_dir"]
            d.mkdir(parents=True, exist_ok=True)
            os.startfile(d)
        elif kind == "quit":
            self.quit()

    def set_option(self, key, value):
        cfg[key] = value
        save_cfg()
        if key == "show_button":
            self.button.show(value)
        if self.tray:
            try:
                self.tray.update_menu()
            except Exception:
                pass

    def capture(self, mode, source):
        if self.recorder:  # any capture key while recording = stop
            self.recorder.stop_ev.set()
            return
        if self.picker or self.busy:
            return
        info = app_info(self.last_fg)
        mark = cfg["mark_cursor"] and source in ("key", "ipc")
        if source == "tray":  # let the tray menu close first
            self.root.after(350, lambda: self.capture(mode, "tray_late"))
            return
        self.busy_since = time.time()
        if mode in ("screen", "window"):
            hwnd = self.last_fg if mode == "window" else None
            if mode == "window" and not hwnd:
                mode = "screen"
            self.job_q.put(("screen", info, cursor(), mark, mode, hwnd))
        elif mode == "area":
            self.busy_since = None

            def done(img, inf, kind):
                self.picker = None
                self.busy_since = time.time()
                self.job_q.put(("area", img, inf or info, kind))

            def cancelled():
                self.picker = None

            try:
                self.picker = AreaPicker(self, done, cancelled)
            except Exception:
                self.picker = None
                log(traceback.format_exc())
        elif mode == "record":
            with MSS() as sct:
                mon = dict(monitor_at(sct, *cursor()))
            self.recorder = Recorder(self, mon, info, mark)
            self.indicator = RecIndicator(self, mon)
            self.button.set_recording(True)
            self.recorder.start()

    def quit(self):
        try:
            if self.tray:
                self.tray.stop()
        except Exception:
            pass
        try:
            import keyboard
            keyboard.unhook_all()
        except Exception:
            pass
        self.root.quit()

    def run(self):
        self.root.after(1500, lambda: self.notify(T("ready")))
        self.root.mainloop()


def send_udp(cmd):
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.sendto(cmd.encode(), ("127.0.0.1", UDP_PORT))
        s.close()
    except OSError:
        pass


def main():
    sys.excepthook = lambda *a: log("".join(traceback.format_exception(*a)))
    threading.excepthook = lambda a: log("".join(traceback.format_exception(a.exc_type, a.exc_value, a.exc_traceback)))
    args = [a.lower() for a in sys.argv[1:]]
    cmd = args[0] if args and args[0] in COMMANDS else None
    kernel32.CreateMutexW(None, False, "Local\\Ekrovi-Claude-Ekran")
    if ctypes.get_last_error() == 183:  # already running
        send_udp(cmd or "show")
        return
    log("start", sys.executable)
    try:  # toasts and the taskbar show "Ekrovi" instead of "Python"
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Ekrovi")
    except Exception:
        pass
    app = App()
    if cmd in ("screen", "window", "area", "record"):
        app.root.after(900, lambda: app.ui_q.put(("capture", cmd, "ipc")))
    app.run()
    log("exit")


if __name__ == "__main__":
    main()
