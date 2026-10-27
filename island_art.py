"""Pictures for the island, as premultiplied RGBA floats (h, w, 4) from 0 to 1: an app's own icon, a round badge
with the app's first letter when it has no icon to give (an app on your phone, through Phone Link), and a song's
cover art. Windows' own GDI and GDI+ do the drawing and decoding, so there's no image library to install.
"""
import ctypes
import os
import re
import threading
from ctypes import wintypes as wt
from functools import lru_cache

import numpy as np

import bubble
import island_face as face

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdiplus = ctypes.WinDLL("gdiplus")
_shlwapi = ctypes.WinDLL("shlwapi")
_user32.PrivateExtractIconsW.argtypes = [wt.LPCWSTR, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                         ctypes.POINTER(wt.HICON), ctypes.POINTER(wt.UINT), wt.UINT, wt.UINT]
_user32.PrivateExtractIconsW.restype = wt.UINT
_user32.DrawIconEx.argtypes = [wt.HDC, ctypes.c_int, ctypes.c_int, wt.HICON, ctypes.c_int, ctypes.c_int, wt.UINT,
                               wt.HBRUSH, wt.UINT]
_user32.DestroyIcon.argtypes = [wt.HICON]
_user32.SendMessageTimeoutW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
                                        ctypes.POINTER(ctypes.c_size_t)]
_user32.SendMessageTimeoutW.restype = wt.LPARAM
_user32.GetClassLongPtrW.argtypes = [wt.HWND, ctypes.c_int]
_user32.GetClassLongPtrW.restype = ctypes.c_size_t
_shlwapi.SHCreateMemStream.argtypes = [ctypes.c_void_p, wt.UINT]
_shlwapi.SHCreateMemStream.restype = ctypes.c_void_p

# the colours apps are known by, for a badge with their letter
BRANDS = {"whatsapp": (0.15, 0.83, 0.4), "telegram": (0.13, 0.62, 0.85), "discord": (0.35, 0.4, 0.95),
          "teams": (0.38, 0.39, 0.65), "outlook": (0.0, 0.47, 0.83), "gmail": (0.92, 0.26, 0.21),
          "slack": (0.29, 0.08, 0.29), "signal": (0.23, 0.46, 0.94), "instagram": (0.88, 0.19, 0.42),
          "messenger": (0.0, 0.52, 1.0), "messages": (0.1, 0.45, 0.91), "phone link": (0.0, 0.47, 0.83),
          "chrome": (0.26, 0.52, 0.96), "google chrome": (0.26, 0.52, 0.96), "spotify": (0.11, 0.73, 0.33),
          "youtube": (1.0, 0.0, 0.0), "kiro": (0.49, 0.36, 1.0), "claude": (0.85, 0.47, 0.34),
          "microsoft edge": (0.0, 0.47, 0.83), "msedge": (0.0, 0.47, 0.83), "vlc": (1.0, 0.53, 0.0),
          "hey jev": (0.06, 0.46, 0.43)}


def brand(name):
    """The colour an app is known by, or one picked from its name, always the same for the same name."""
    key = str(name or "").lower().strip()
    for known, colour in BRANDS.items():
        if known == key or re.search(rf"\b{re.escape(known)}\b", key):
            return colour
    h = (sum(ord(c) * (i + 7) for i, c in enumerate(key)) % 360) / 360.0
    import colorsys
    return colorsys.hsv_to_rgb(h, 0.55, 0.85)


_draw_lock = threading.Lock()


def _from_icon(hicon, size):
    """An icon drawn at size px, its alpha worked out from drawing it on black and on white, so old masked icons
    and new ones with their own alpha both come out right."""
    with _draw_lock:
        dc = bubble._new_dc(None)
        try:
            bitmap, pixels = bubble._dib(dc, size, size)
            old = bubble._select(dc, bitmap)
            try:
                shots = []
                for back in (0, 255):
                    pixels[:] = back
                    if not _user32.DrawIconEx(dc, 0, 0, hicon, size, size, 0, None, 3):  # DI_NORMAL
                        return None
                    bubble._flush()
                    shots.append(pixels[..., :3].astype(np.float32) / 255)
            finally:
                bubble._select(dc, old)
                bubble._delete(bitmap)
        finally:
            bubble._delete_dc(dc)
    black, white = shots
    alpha = np.clip(1 - (white - black).mean(axis=2, keepdims=True), 0.0, 1.0)
    if alpha.max() < 0.05:
        return None
    rgb = black[..., ::-1]  # blue, green, red in the picture
    return np.concatenate([np.minimum(rgb, alpha), alpha], axis=2).astype(np.float32)


@lru_cache(maxsize=64)
def exe_icon(path, size):
    """The icon of a program file (or an .ico) at size px, or None."""
    if not path or not os.path.exists(path):
        return None
    icon, got = wt.HICON(), wt.UINT()
    try:
        n = _user32.PrivateExtractIconsW(path, 0, size, size, ctypes.byref(icon), ctypes.byref(got), 1, 0)
    except OSError:
        return None
    if not n or not icon.value or n == 0xFFFFFFFF:
        return None
    try:
        return _from_icon(icon, size)
    finally:
        _user32.DestroyIcon(icon)


def window_icon(hwnd, size):
    """The icon a window shows in its title bar, for apps whose program file can't be read (Store apps)."""
    out = ctypes.c_size_t()
    for which in (1, 2, 0):  # ICON_BIG, ICON_SMALL2, ICON_SMALL
        if _user32.SendMessageTimeoutW(hwnd, 0x7F, which, 0, 0x2, 60, ctypes.byref(out)) and out.value:
            got = _from_icon(wt.HICON(out.value), size)
            if got is not None:
                return got
    for index in (-14, -34):  # GCLP_HICON, GCLP_HICONSM
        h = _user32.GetClassLongPtrW(hwnd, index)
        if h:
            got = _from_icon(wt.HICON(h), size)
            if got is not None:
                return got
    return None


_badges = {}


def badge(name, size, text_maker):
    """A round badge in the app's colour with its first letter: text_maker(px) gives a bubble.Text."""
    key = (str(name or "?")[:1].upper(), round(size), brand(name))
    hit = _badges.get(key)
    if hit is not None:
        return hit
    letter = key[0] if key[0].isalnum() else "\u2022"
    n = int(round(size))
    col = np.zeros((n, n, 3), np.float32)
    cv = face.Canvas(col)
    xs = np.arange(n, dtype=np.float32) + 0.5
    ys = (np.arange(n, dtype=np.float32) + 0.5)[:, None]
    cover = np.clip(0.5 - face.circle(xs, ys, n / 2, n / 2, n / 2 - 0.5), 0.0, 1.0)
    col[:] = np.asarray(key[2], np.float32)
    t = text_maker(max(8, round(n * 0.52)))
    glyph = t.render(letter)
    cv.text(glyph, (n - glyph.shape[1]) / 2 + 0.5, (n - glyph.shape[0]) / 2, (1.0, 1.0, 1.0))
    out = np.concatenate([col * cover[..., None], cover[..., None]], axis=2).astype(np.float32)
    if len(_badges) > 64:
        _badges.clear()
    _badges[key] = out
    return out


def rounded(rgba, radius):
    """A picture with its corners rounded off."""
    h, w = rgba.shape[:2]
    xs = np.arange(w, dtype=np.float32) + 0.5
    ys = (np.arange(h, dtype=np.float32) + 0.5)[:, None]
    m = np.clip(0.5 - face.rbox(xs, ys, w / 2, h / 2, w / 2, h / 2, radius), 0.0, 1.0)[..., None]
    return (rgba * m).astype(np.float32)


# --------------------------------------------------------------------------- cover art, decoded by GDI+
class _StartupInput(ctypes.Structure):
    _fields_ = [("GdiplusVersion", ctypes.c_uint32), ("DebugEventCallback", ctypes.c_void_p),
                ("SuppressBackgroundThread", wt.BOOL), ("SuppressExternalCodecs", wt.BOOL)]


class _BitmapData(ctypes.Structure):
    _fields_ = [("Width", ctypes.c_uint), ("Height", ctypes.c_uint), ("Stride", ctypes.c_int),
                ("PixelFormat", ctypes.c_int), ("Scan0", ctypes.c_void_p), ("Reserved", ctypes.c_size_t)]


class _Rect(ctypes.Structure):
    _fields_ = [("X", ctypes.c_int), ("Y", ctypes.c_int), ("Width", ctypes.c_int), ("Height", ctypes.c_int)]


_token = ctypes.c_size_t()
_gdip_lock = threading.Lock()
PARGB = 0x000E200B  # PixelFormat32bppPARGB: blue, green, red, alpha, premultiplied


def _release(com_ptr):
    """IUnknown::Release on a raw COM pointer."""
    vtbl = ctypes.cast(ctypes.c_void_p.from_address(com_ptr).value, ctypes.POINTER(ctypes.c_void_p))
    ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)(vtbl[2])(com_ptr)


def decode(data, size, radius=0.0):
    """A JPEG or PNG (bytes) as a size x size picture, the middle of it if it isn't square, or None."""
    if not data:
        return None
    with _gdip_lock:
        if not _token.value:
            inp = _StartupInput(1, None, False, False)
            if _gdiplus.GdiplusStartup(ctypes.byref(_token), ctypes.byref(inp), None) != 0:
                return None
        raw = ctypes.create_string_buffer(bytes(data), len(data))
        stream = _shlwapi.SHCreateMemStream(raw, len(data))
        if not stream:
            return None
        image, thumb = ctypes.c_void_p(), ctypes.c_void_p()
        try:
            if _gdiplus.GdipCreateBitmapFromStream(ctypes.c_void_p(stream), ctypes.byref(image)) != 0:
                return None
            w, h = ctypes.c_uint(), ctypes.c_uint()
            _gdiplus.GdipGetImageWidth(image, ctypes.byref(w))
            _gdiplus.GdipGetImageHeight(image, ctypes.byref(h))
            if not w.value or not h.value:
                return None
            k = size / min(w.value, h.value)
            tw, th = max(size, round(w.value * k)), max(size, round(h.value * k))
            if _gdiplus.GdipGetImageThumbnail(image, tw, th, ctypes.byref(thumb), None, None) != 0:
                return None
            rect, bits = _Rect(0, 0, tw, th), _BitmapData()
            if _gdiplus.GdipBitmapLockBits(thumb, ctypes.byref(rect), 1, PARGB, ctypes.byref(bits)) != 0:
                return None
            stride = abs(bits.Stride)
            try:
                start = bits.Scan0 if bits.Stride > 0 else bits.Scan0 + bits.Stride * (th - 1)
                buf = ctypes.string_at(start, stride * th)
            finally:
                _gdiplus.GdipBitmapUnlockBits(thumb, ctypes.byref(bits))
        finally:
            for img in (thumb, image):
                if img.value:
                    _gdiplus.GdipDisposeImage(img)
            _release(stream)
    px = np.frombuffer(buf, np.uint8).reshape(th, stride // 4, 4)[:, :tw]
    if bits.Stride < 0:  # stored bottom row first
        px = px[::-1]
    y0, x0 = (th - size) // 2, (tw - size) // 2
    px = px[y0:y0 + size, x0:x0 + size]
    out = np.concatenate([px[..., 2::-1], px[..., 3:4]], axis=2).astype(np.float32) / 255
    return rounded(out, radius) if radius else out
