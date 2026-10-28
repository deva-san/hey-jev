"""The popup that shows what she's doing, as an iPhone's Dynamic Island: a black capsule at the top middle of the
screen that springs open into a rounded card to show what you're saying and what she's saying, and shrinks away
when she's done.

listening    the Siri wave, moving with your voice, your words as you say them, and an orange dot (the mic is on,
             as on an iPhone)
window       the few seconds after she answers, when you can carry on without her name: a ring running down
dictating    the wave, your words, and a red dot
thinking     glowing dots that merge, scatter and gather, over what she heard you say
looking      the dots, bluer, while she looks at the screen (the popup is left out of what she sees)
doing        the dots, warmer, while the steps run
speaking     the wave, moving with her voice, what she's saying, and what you asked above it
It never takes focus, so typing and pasting still go where your cursor is, and clicks go through it.

The two animations are the GLSL shaders of the SiriWave React component (its "wave" and "fluid-dots" variants),
worked out here with numpy for a small image each frame. The island is drawn the same way, a few hundred thousand
pixels with smooth edges and a soft shadow, and handed to Windows as a layered window (UpdateLayeredWindow), with
the words drawn by Windows' own text renderer. Settings popup_style "pill" brings back the old Siri pill at the
bottom of the screen, which is also used if Windows won't draw the island.
"""
import ctypes
import math
import re
import sys
import time
import tkinter as tk
from ctypes import wintypes as wt
from tkinter import font as tkfont

import numpy as np

import winplatform as win

HEIGHT, WAVE_W, MAX_TEXT = 44, 124, 400  # logical px: the pill's height, the animation's width, the longest text
KEY = "#ff00fe"  # see-through colour, so only the rounded pill shows. Never drawn with.
KEY_RGB = np.array([255, 0, 254], np.uint8)
PILL = "#0a0a0c"
PILL_RGB = np.array([10, 10, 12], np.float32)
TEXT, DIM_TEXT, ERROR_TEXT, RED = "#f5f5f7", "#a1a1aa", "#fca5a5", "#ef4444"
LOOKS = {  # state: (animation, what moves it, tint, words when there are none)
    "listening": ("wave", "mic", (1.0, 1.0, 1.0), "Listening\u2026"),
    "window": ("wave", "mic", (0.6, 0.6, 0.6), "Still listening"),
    "dictating": ("wave", "mic", (1.0, 1.0, 1.0), "Dictating\u2026"),
    "speaking": ("wave", "voice", (1.0, 1.0, 1.0), ""),
    "thinking": ("dots", None, (0.88, 0.84, 1.0), "Thinking\u2026"),
    "looking": ("dots", None, (0.62, 0.92, 1.0), "Looking at the screen\u2026"),
    "doing": ("dots", None, (1.0, 0.84, 0.66), "On it\u2026"),
    "finishing": ("dots", None, (0.72, 0.86, 1.0), "Writing it up\u2026"),
    "error": ("wave", None, (1.0, 0.3, 0.3), "Something went wrong"),
    "phone": ("wave", None, (0.45, 0.75, 1.0), "Phone"),  # pairing news, a calm blue line
    "read": ("wave", "mic", (1.0, 1.0, 1.0), "Read this out loud"),  # learning your voice: the sentence to read
    "again": ("wave", "mic", (1.0, 0.6, 0.6), "Once more"),  # that one didn't count, read it again
    "note": ("wave", None, (0.6, 0.6, 0.6), ""),  # why she let it go: "That didn't sound like you"
}
GAIN = {"mic": 0.06, "voice": 0.2}  # loudness that fills the wave: a voice into the mic, and her own voice


# --------------------------------------------------------------------------- the two shaders, in numpy
def _smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def wave(t, w, h, amp):
    """The Siri wave at t seconds, as (h, w, 3) floats from 0 up: four coloured lines a phase apart with the band
    between them lit, a white line through the middle, fading out at the ends. amp: 0 a calm line, 1 talking."""
    x = ((np.arange(w, dtype=np.float32) + 0.5) * 2 / w - 1)  # -1 to 1 across
    y = ((np.arange(h, dtype=np.float32) + 0.5) * 2 / h - 1)[:, None]  # -1 to 1 down
    px, py = x * 2.3, y / 1.4  # the square shader's look, stretched along a pill: about one hump across
    low = min(max(0.45 + 0.45 * math.sin(t * 0.8) * math.sin(t * 0.37 + 1.0), 0.0), 1.0)
    mid = min(max(0.40 + 0.40 * math.sin(t * 1.7 + 2.0) * math.sin(t * 0.53), 0.0), 1.0)
    high = min(max(0.30 + 0.30 * math.sin(t * 2.9 + 4.0) * math.sin(t * 0.71 + 2.0), 0.0), 1.0)
    drift = (t % (20 * math.pi)) * 2.4
    xn = x * 1.1
    env = np.cos(math.pi * 0.5 * np.minimum(np.abs(0.9 * xn), 1.0)) ** 2
    a1 = (0.32 + 0.06 * low) * amp
    a2 = a1 + (0.05 * mid + 0.06 * high) * amp
    ab = 2.6 + 0.8 * mid + 0.5 * high
    th, soft = 0.045, 0.01 * (2.5 + 0.4 * mid) * 1.5  # 1.5 times the shader's, at this small size
    inten = 0.01 * (2.0 + 1.5 * low)
    y_main = a1 * env * np.sin(px * 1.1 + drift)
    lit = []  # each line and its band, red, yellow, green and cyan
    for s in range(4):
        y_line = a2 * env * np.sin(px + drift - ab + 2 * ab * s / 3)
        d = py - y_line
        line = inten / (np.sqrt(d * d + soft * soft) + th)
        lo, hi = np.minimum(y_main, y_line), np.maximum(y_main, y_line)
        band = 3 * inten / (np.maximum(np.maximum(py - hi, lo - py), 0.0) + 0.08)
        lit.append(line + band)
    d = py - y_main
    white = 0.5 * inten / (np.sqrt(d * d + soft * soft) + th)
    col = np.stack([(lit[0] + lit[1]) / 2, (lit[1] + lit[2] + lit[3]) / 3, lit[3]], axis=-1) + white[..., None]
    col = col * np.sqrt(col)  # pow 1.5
    e = np.clip((1 - np.abs(y)) / 0.4, 0.0, 1.0)
    ends = np.clip((1 - np.abs(x)) / 0.2, 0.0, 1.0)  # all the way to black at the ends, the pill is small
    fade = (e * e * (3 - 2 * e)) * np.exp(-(xn * 1.7) ** 2) * ends
    return col * fade[..., None]


def _hash(n):
    return (math.sin(n * 127.1 + 311.7) * 43758.5453) % 1.0


def _settle(tau, w=4.6, l=3.2):
    return 0.0 if tau <= 0 else 1 - math.exp(-l * tau) * math.cos(w * tau)


def _settle_crit(tau, l):
    return 0.0 if tau <= 0 else 1 - math.exp(-l * tau) * (1 + l * tau)


def _dot_r(i, seed, t):
    return 0.036 + 0.010 * math.sin(t * 1.3 + seed * math.tau) + 0.005 * math.sin(t * 2.4 + i * 1.3)


def dots(t, w, h, zoom=0.42):
    """Six glowing dots at t seconds, as (h, w) floats 0 to 1: pairs pass through each other, they scatter, and
    every 12 seconds they gather into one and burst out again. One colour, since the shader's colour fringes are
    under a pixel at this size."""
    m = min(w, h)
    breathe = 1 + 0.03 * math.sin(t)
    x = ((np.arange(w, dtype=np.float32) + 0.5) * 2 - w) / m * zoom / breathe
    y = (((np.arange(h, dtype=np.float32) + 0.5) * 2 - h) / m * zoom / breathe)[:, None]
    k, te, tg = math.floor(t / 6), (t / 6 % 1) * 6, t % 12
    g = _settle_crit((tg - 9.2) * 1.8, 7.5) - _settle(tg - 10.0, 6.5, 4.0)
    gc = min(max(g, 0.0), 1.0)
    tb = tg - 10.0
    charge = (0.0 if tb < -0.3 else 1.0 if tb >= 0 else (lambda u: u * u * (3 - 2 * u))((tb + 0.3) / 0.3)) * gc
    flash = math.exp(-tb * 7) if tb > 0 else 0.0
    glow = (1 - 0.15 * gc) * (1 + 0.35 * charge + 1.2 * flash)
    total = None
    for i in range(6):
        seed = _hash(i)
        ang = i / 6 * math.tau + t * 0.35
        dx, dy = math.cos(ang), math.sin(ang)
        orbit = 0.17 + 0.010 * math.sin(t) + 0.007 * math.sin(t * 1.3 + seed * math.tau)
        pair = i % 3
        low = (k + pair) % 2
        mover = float(low < 0.5) if i < 3 else float(low >= 0.5)
        go, back = pair * 0.33, 0.99 + pair * 0.33
        move = (_settle(te - go) - _settle(te - back)) * mover
        recoil = (_settle(te - go - 0.11) - _settle(te - back - 0.11)) * (1 - mover)
        r = (_dot_r(i, seed, t) * (1 - gc) + 0.036 * gc) * (1 - 0.18 * charge)
        j = (i + 3) % 6
        deep = -(orbit + 0.035) - 0.12 * _dot_r(j, _hash(j), t)
        radial = orbit + (deep - orbit) * move + 0.035 * recoil
        radial += (0.008 - radial) * g
        ox, oy = x - (radial + 0.0025) * dx, y - (radial + 0.0025) * dy
        squash = 0.075 * (0.5 + 0.5 * math.sin(t * 0.9 + i * 2.0)) * (1 - gc)
        ca, sa = math.cos(t * 0.35 + i), math.sin(t * 0.35 + i)
        sd = np.hypot((ca * ox + sa * oy) * (1 + squash), (ca * oy - sa * ox) * (1 - squash)) - r
        if total is None:
            total = sd
        else:  # the smooth minimum: dots that touch melt into one shape
            hk = np.maximum(0.08 - np.abs(total - sd), 0.0) / 0.08
            total = np.minimum(total, sd) - hk * hk * 0.02
    sd = np.maximum(total, 0.0) + 1e-4
    col = np.clip(0.0025 / sd ** 1.35, 0.0, 1.0) * (1 - _smoothstep(0.02, 0.56, sd)) * glow
    col = np.minimum((col * (1 + 0.05 * math.sin(t + 1))) ** (1 / 1.2), 1.0)
    e = np.clip((1 - np.abs(np.linspace(-1, 1, h, dtype=np.float32))) / 0.3, 0.0, 1.0)[:, None]
    return col * (e * e * (3 - 2 * e))


def loudness(source, level):
    """How loud the voice moving the wave is now, 0 to 1, eased from level so it swells and settles."""
    siri = sys.modules.get("siri")  # siri may still be loading
    levels = list(getattr(siri, "MIC_LEVELS" if source == "mic" else "SPEAK_LEVELS", ()))[-3:] if source else []
    target = min(1.0, math.sqrt(max(levels) / GAIN[source])) if levels else 0.0
    return level + (target - level) * (0.35 if target > level else 0.12)


# --------------------------------------------------------------------------- the old Siri pill, at the bottom
class Caption:
    """A line above the pill with what she heard you say ("You: open Notepad"), after she's put right the words she
    knows speech-to-text gets wrong, so you can see she has them right before she acts (asked for on 8 October). It
    goes with the pill, and after 15 s at most. Never takes the focus and isn't in her screenshots, as the pill."""

    def __init__(self, root, s):
        self.root, self.s, self.job, self.visible = root, s, None, False
        families = set(tkfont.families(root))
        self.font = tkfont.Font(root=root, family="Segoe UI" if "Segoe UI" in families else "TkDefaultFont", size=10)
        self.h = round(30 * s)
        self.top = tk.Toplevel(root, bg=KEY)
        self.top.withdraw()
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.attributes("-transparentcolor", KEY)
        self.top.attributes("-alpha", 0.92)
        self.canvas = tk.Canvas(self.top, width=10, height=self.h, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        self.top.geometry(f"10x{self.h}+-20000+-20000")
        self.top.deiconify()
        self.top.update_idletasks()
        self.hwnd = win.root_hwnd(self.top.winfo_id())
        win.make_overlay(self.hwnd)
        win.NO_CAPTURE.append(self.hwnd)
        win.hide_window(self.hwnd)

    def show(self, text, above):
        """"You: text", centred, above the bottom of the work area by above px and a gap."""
        text = " ".join(str(text or "").split())
        if not text:
            return self.hide()
        text, limit = "You: " + text, round(MAX_TEXT * self.s)
        if self.font.measure(text) > limit:
            while text and self.font.measure(text + "\u2026") > limit:
                text = text[:-1]
            text = text.rstrip() + "\u2026"
        w = self.font.measure(text) + round(28 * self.s)
        c, h, r = self.canvas, self.h, self.h / 2
        c.configure(width=w)
        c.delete("all")
        c.create_oval(0, 0, h, h, fill=PILL, outline=PILL)
        c.create_oval(w - h, 0, w, h, fill=PILL, outline=PILL)
        c.create_rectangle(r, 0, w - r, h, fill=PILL, outline=PILL)
        c.create_text(w / 2, r, text=text, fill=DIM_TEXT, font=self.font)
        left, top, right, bottom = win.work_area()
        win.show_no_activate(self.hwnd, left + (right - left - w) // 2, bottom - above - h - round(6 * self.s), w, h)
        self.visible = True
        if self.job:
            self.root.after_cancel(self.job)
        self.job = self.root.after(15000, self.hide)  # never left up: the pill going takes it sooner

    def hide(self):
        if self.job:
            self.root.after_cancel(self.job)
            self.job = None
        if self.visible:
            win.hide_window(self.hwnd)
            self.visible = False


class Pill:
    """The popup before the Dynamic Island: a small black pill at the bottom middle of the screen, Siri style."""

    def __init__(self, root):
        self.root = root
        self.s = root.winfo_fpixels("1i") / 96  # Windows display scaling
        self.h = round(HEIGHT * self.s)
        families = set(tkfont.families(root))
        family = next((f for f in ("Segoe UI Variable Display Semib", "Segoe UI Semibold") if f in families), "Segoe UI")
        self.font = tkfont.Font(root=root, family=family, size=11)
        self.top = tk.Toplevel(root, bg=KEY)
        self.top.withdraw()
        self.top.overrideredirect(True)
        self.top.attributes("-topmost", True)
        self.top.attributes("-transparentcolor", KEY)
        self.top.attributes("-alpha", 0.0)
        self.x0, self.iw = round(6 * self.s), round(WAVE_W * self.s)  # where the animation sits, and how wide
        self.photo = tk.PhotoImage(master=root, width=self.iw, height=self.h)
        self.w = self._width("")
        self.canvas = tk.Canvas(self.top, width=self.w, height=self.h, bg=KEY, highlightthickness=0, bd=0)
        self.canvas.pack()
        # map it once off screen so Tk draws into it, then Windows shows and hides it without ever giving it focus,
        # or the dictation would paste into the bubble instead of where your cursor was
        self.top.geometry(f"{self.w}x{self.h}+-20000+-20000")
        self.top.deiconify()
        self.top.update_idletasks()
        self.hwnd = win.root_hwnd(self.top.winfo_id())
        win.make_overlay(self.hwnd)
        win.NO_CAPTURE.append(self.hwnd)  # not in the screenshots she looks at
        win.hide_window(self.hwnd)
        self.visible, self.state, self.text, self.alpha, self.fade = False, None, "", 0.0, 0
        self.level, self.since, self.t0, self.job, self.hide_job = 0.0, 0.0, time.time(), None, None
        self.outside = self._outside()
        self.heard = Caption(root, self.s)  # what she heard you say, on a line above

    # ------------------------------------------------------------------ what the app calls
    def show(self, state, text=None):
        """Show the pill in this state (see LOOKS), with text, or the state's own words if text is None or empty."""
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None
        text = re.sub(r"\[[^\]]*\]\s*", "", " ".join(str(text or "").split()))  # her [cheerful] tags aren't words
        if state != self.state:
            self.since = time.time()
        self.state, self.text = state, self._fit(text or LOOKS.get(state, LOOKS["listening"])[3])
        w = self._width(self.text)
        if not self.visible or w != self.w:
            self.w = w
            self.outside = self._outside()
            self.canvas.configure(width=w)
            left, top, right, bottom = win.work_area()
            win.show_no_activate(self.hwnd, left + (right - left - w) // 2, bottom - self.h - round(28 * self.s), w, self.h)
            self.visible = True
        self.fade = 1
        if not self.job:
            self._tick()

    def caption(self, text):
        """What she heard you say, on a line above the pill while she's on it: you can see she got the words."""
        self.heard.show(text, self.h + round(28 * self.s))

    def hide(self, delay=0):
        """Fade out, after delay ms. Showing it again in the meantime keeps it up."""
        if delay:
            if self.visible and not self.hide_job:
                self.hide_job = self.root.after(delay, self.hide)
            elif not self.visible:
                self.heard.hide()
            return
        self.hide_job = None
        if self.visible:
            self.fade = -1
        else:
            self.heard.hide()

    def close(self):
        """Gone straight away, for quitting."""
        for job in (self.job, self.hide_job):
            if job:
                self.root.after_cancel(job)
        self.job = self.hide_job = None
        self.heard.hide()
        if self.visible:
            win.hide_window(self.hwnd)
            self.visible = False

    # ------------------------------------------------------------------ drawing
    def _width(self, text):
        words = (round(6 * self.s) + min(self.font.measure(text), round(MAX_TEXT * self.s))) if text else 0
        return self.x0 + self.iw + words + round(20 * self.s if text else self.x0)

    def _fit(self, text):
        limit = round(MAX_TEXT * self.s)
        if self.font.measure(text) <= limit:
            return text
        while text and self.font.measure(text + "\u2026") > limit:
            text = text[:-1]
        return text.rstrip() + "\u2026"

    def _outside(self):
        """The animation's pixels outside the pill's rounded ends, left see-through."""
        r = self.h / 2
        cx = self.x0 + np.arange(self.iw) + 0.5
        cy = (np.arange(self.h) + 0.5)[:, None]
        left = (cx < r) & ((cx - r) ** 2 + (cy - r) ** 2 > (r + 0.5) ** 2)
        right = (cx > self.w - r) & ((cx - self.w + r) ** 2 + (cy - r) ** 2 > (r + 0.5) ** 2)
        return left | right

    def _frame(self):
        kind, source, tint, _ = LOOKS.get(self.state, LOOKS["listening"])
        t = time.time() - self.t0
        if kind == "dots":
            col = dots(t, self.iw, self.h)[..., None] * np.array(tint, np.float32)
        else:
            self.level = loudness(source, self.level)
            amp = 0.12 + 0.88 * self.level if source else 0.25
            col = wave(t, self.iw, self.h, amp) * np.array(tint, np.float32)
        rgb = np.clip(col * 255 + PILL_RGB, 0, 255).astype(np.uint8)  # her light on the black pill
        rgb[self.outside] = KEY_RGB
        self.photo.configure(data=b"P6 %d %d 255 " % (self.iw, self.h) + rgb.tobytes(), format="ppm")

    def _tick(self):
        self.alpha = min(0.96, self.alpha + 0.2) if self.fade > 0 else max(0.0, self.alpha - 0.15)
        try:  # a drawing error must never take the app down
            self.top.attributes("-alpha", self.alpha)
            self._frame()
            self._draw()
        except Exception as exc:
            print(f"  bubble draw failed: {exc}")
        if self.fade < 0 and self.alpha <= 0:
            win.hide_window(self.hwnd)
            self.heard.hide()  # the turn it was for is over
            self.visible, self.job, self.state = False, None, None
            return
        self.job = self.root.after(33, self._tick)

    def _draw(self):
        c, w, h, s = self.canvas, self.w, self.h, self.s
        c.delete("all")
        r = h / 2
        c.create_oval(0, 0, h, h, fill=PILL, outline=PILL)
        c.create_oval(w - h, 0, w, h, fill=PILL, outline=PILL)
        c.create_rectangle(r, 0, w - r, h, fill=PILL, outline=PILL)
        c.create_image(self.x0, 0, image=self.photo, anchor="nw")
        if self.text:
            colour = {"window": DIM_TEXT, "note": DIM_TEXT, "error": ERROR_TEXT}.get(self.state, TEXT)
            c.create_text(self.x0 + self.iw + 6 * s, r, text=self.text, fill=colour, font=self.font, anchor="w")
        if self.state == "window":  # the follow-up window running down
            total = float(getattr(sys.modules.get("siri"), "FOLLOW_UP", 12.0))
            left = max(0.0, 1 - (time.time() - self.since) / total)
            if left > 0:
                c.create_line(r, h - 3 * s, r + (w - 2 * r) * left, h - 3 * s, fill=RED, width=max(1, round(2 * s)))


# --------------------------------------------------------------------------- the Dynamic Island, at the top
_user32 = ctypes.WinDLL("user32", use_last_error=True)  # its own handles: winplatform's keep their own signatures
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


class _BLEND(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte), ("SourceConstantAlpha", ctypes.c_ubyte),
                ("AlphaFormat", ctypes.c_ubyte)]


class _BMIH(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG), ("biClrUsed", wt.DWORD),
                ("biClrImportant", wt.DWORD)]


class _BMI(ctypes.Structure):
    _fields_ = [("bmiHeader", _BMIH), ("bmiColors", wt.DWORD * 3)]


def _api(fn, args, res):
    fn.argtypes, fn.restype = args, res
    return fn


_ULW = _api(_user32.UpdateLayeredWindow, [wt.HWND, wt.HDC, ctypes.POINTER(wt.POINT), ctypes.POINTER(wt.SIZE), wt.HDC,
                                          ctypes.POINTER(wt.POINT), wt.DWORD, ctypes.POINTER(_BLEND), wt.DWORD], wt.BOOL)
_new_dc = _api(_gdi32.CreateCompatibleDC, [wt.HDC], wt.HDC)
_new_dib = _api(_gdi32.CreateDIBSection, [wt.HDC, ctypes.POINTER(_BMI), wt.UINT, ctypes.POINTER(ctypes.c_void_p),
                                          wt.HANDLE, wt.DWORD], wt.HBITMAP)
_select = _api(_gdi32.SelectObject, [wt.HDC, wt.HGDIOBJ], wt.HGDIOBJ)
_delete = _api(_gdi32.DeleteObject, [wt.HGDIOBJ], wt.BOOL)
_delete_dc = _api(_gdi32.DeleteDC, [wt.HDC], wt.BOOL)
_new_font = _api(_gdi32.CreateFontW, [ctypes.c_int] * 5 + [wt.DWORD] * 8 + [wt.LPCWSTR], wt.HFONT)
_text_colour = _api(_gdi32.SetTextColor, [wt.HDC, wt.DWORD], wt.DWORD)
_bk_mode = _api(_gdi32.SetBkMode, [wt.HDC, ctypes.c_int], ctypes.c_int)
_text_out = _api(_gdi32.TextOutW, [wt.HDC, ctypes.c_int, ctypes.c_int, wt.LPCWSTR, ctypes.c_int], wt.BOOL)
_extent = _api(_gdi32.GetTextExtentPoint32W, [wt.HDC, wt.LPCWSTR, ctypes.c_int, ctypes.POINTER(wt.SIZE)], wt.BOOL)
_face = _api(_gdi32.GetTextFaceW, [wt.HDC, ctypes.c_int, wt.LPWSTR], ctypes.c_int)
_flush = _api(_gdi32.GdiFlush, [], wt.BOOL)

# iOS's own colours, for the parts that mean the same as on an iPhone
WHITE = np.array([1.0, 1.0, 1.0], np.float32) * 0.97
GREY = np.array([152, 152, 157], np.float32) / 255  # secondary text
ORANGE = np.array([255, 159, 10], np.float32) / 255  # the mic is on
SIGNAL_RED = np.array([255, 69, 58], np.float32) / 255
BLUE = np.array([10, 132, 255], np.float32) / 255
RING_BACK = np.array([0.28, 0.28, 0.3], np.float32)
# the small mark on the right: (shape, colour, pulses)
MARKS = {"listening": ("dot", ORANGE, True), "read": ("dot", ORANGE, True), "again": ("dot", ORANGE, True),
         "dictating": ("dot", SIGNAL_RED, True), "window": ("ring", ORANGE, False), "error": ("dot", SIGNAL_RED, False),
         "phone": ("dot", BLUE, False)}


def _units(text):
    """How long text is to Windows, which counts UTF-16 units: an emoji is two, where Python counts one."""
    return len(text.encode("utf-16-le")) // 2


def _dib(dc, w, h):
    """A 32-bit picture Windows can draw from, top row first, and a numpy view of its pixels (blue, green, red,
    alpha)."""
    bmi = _BMI()
    bmi.bmiHeader.biSize = ctypes.sizeof(_BMIH)
    bmi.bmiHeader.biWidth, bmi.bmiHeader.biHeight = w, -h
    bmi.bmiHeader.biPlanes, bmi.bmiHeader.biBitCount = 1, 32
    bits = ctypes.c_void_p()
    bitmap = _new_dib(dc, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
    if not bitmap or not bits.value:
        raise OSError(ctypes.get_last_error(), "CreateDIBSection failed")
    pixels = np.ctypeslib.as_array((ctypes.c_ubyte * (w * h * 4)).from_address(bits.value)).reshape(h, w, 4)
    return bitmap, pixels


class Text:
    """Words drawn by Windows itself (GDI, grey antialiasing) into an array of how much each pixel is covered, so
    they can go on the island in any colour. One font, size and weight each; what it draws is kept for next time."""
    FACES = ("Segoe UI Variable Display", "Segoe UI")  # Windows 11's own, the nearest it has to an iPhone's

    def __init__(self, px, weight=600):
        self.dc = _new_dc(None)
        self.font, self.cache = None, {}
        for face in self.FACES:
            font = _new_font(-px, 0, 0, 0, weight, 0, 0, 0, 1, 0, 0, 4, 0, face)  # 4: ANTIALIASED_QUALITY
            _select(self.dc, font)
            got = ctypes.create_unicode_buffer(64)
            _face(self.dc, 64, got)
            if self.font:
                _delete(self.font)
            self.font = font
            if got.value.lower().startswith(face.lower()):
                break  # else Windows gave something else for a font this PC doesn't have: try the next
        size = wt.SIZE()
        _extent(self.dc, "Ag", 2, ctypes.byref(size))
        self.line = size.cy

    def measure(self, text):
        if not text:
            return 0
        size = wt.SIZE()
        _extent(self.dc, text, _units(text), ctypes.byref(size))
        return size.cx

    def fit(self, text, width):
        """text, cut short with an ellipsis if it's wider than width px."""
        if self.measure(text) <= width:
            return text
        lo, hi = 0, len(text)
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if self.measure(text[:mid].rstrip() + "\u2026") <= width:
                lo = mid
            else:
                hi = mid - 1
        return text[:lo].rstrip() + "\u2026"

    def wrap(self, text, width, lines, newest=False, tidy=True):
        """text in at most lines rows of width px. newest: the end of it, for words still coming in, so what you've
        just said is what shows; else the start, with an ellipsis if it doesn't all fit. tidy: no word left alone on
        the last row ("21."), one more comes down with it; not for words still coming in, which would jump about."""
        words = text.split()
        if not words:
            return []
        if newest:
            plain = self.wrap(text, width, lines, tidy=False)
            if len(plain) <= lines and not plain[-1].endswith("\u2026"):
                return plain  # it all fits: rows filled from the start, so they read evenly

            rows, i = [], len(words)
            while i > 0 and len(rows) < lines:
                row = [words[i - 1]]
                i -= 1
                while i > 0 and self.measure(" ".join([words[i - 1]] + row)) <= width:
                    row.insert(0, words[i - 1])
                    i -= 1
                rows.insert(0, " ".join(row))
            if i > 0:  # more came before it: an ellipsis in front, and the oldest of what's left goes for room
                first = rows[0].split()
                while len(first) > 1 and self.measure("\u2026" + " ".join(first)) > width:
                    first.pop(0)
                rows[0] = "\u2026" + " ".join(first)
            return [self.fit(r, width) for r in rows]
        rows, row = [], ""
        for i, word in enumerate(words):
            trial = f"{row} {word}" if row else word
            if self.measure(trial) <= width:
                row = trial
                continue
            if row:
                rows.append(row)
            if len(rows) == lines:  # no room for the rest
                rows[-1] = self.fit(rows[-1] + " " + " ".join(words[i:]), width)
                return rows
            row = word if self.measure(word) <= width else self.fit(word, width)
        if row:
            rows.append(row)
        if tidy and len(rows) >= 2 and " " not in rows[-1]:
            before = rows[-2].split()
            if len(before) >= 3 and self.measure(f"{before[-1]} {rows[-1]}") <= width:
                rows[-2], rows[-1] = " ".join(before[:-1]), f"{before[-1]} {rows[-1]}"
        return rows

    def render(self, text):
        """text as an (h, w) array, 0 to 1."""
        hit = self.cache.get(text)
        if hit is not None:
            return hit
        w, h = self.measure(text) + 4, self.line + 2
        bitmap, pixels = _dib(self.dc, w, h)
        old = _select(self.dc, bitmap)
        try:
            _bk_mode(self.dc, 1)  # TRANSPARENT
            _text_colour(self.dc, 0xFFFFFF)
            _text_out(self.dc, 2, 1, text, _units(text))
            _flush()
            cover = pixels[..., 1].astype(np.float32) * (1 / 255)
        finally:
            _select(self.dc, old)
            _delete(bitmap)
        if len(self.cache) > 120:
            self.cache.clear()
        self.cache[text] = cover
        return cover

    def close(self):
        if self.font:
            _delete(self.font)
        _delete_dc(self.dc)


class Spring:
    """A value that springs to where it's sent, the way the Dynamic Island grows and shrinks: response, about how
    long it takes; damping under 1 overshoots a little and settles."""

    def __init__(self, x, response=0.42, damping=0.8):
        self.x = self.target = float(x)
        self.v = 0.0
        omega = 2 * math.pi / response
        self.k, self.c = omega * omega, 2 * damping * omega

    def go(self, target):
        self.target = float(target)

    def jump(self, x):
        self.x = self.target = float(x)
        self.v = 0.0

    def step(self, dt):
        n = max(1, math.ceil(dt / 0.004))  # small steps, so a slow frame doesn't throw it
        h = dt / n
        for _ in range(n):
            self.v += (-self.k * (self.x - self.target) - self.c * self.v) * h
            self.x += self.v * h

    def resting(self, near=0.3):
        return abs(self.x - self.target) < near and abs(self.v) < near * 20


def _box(dx, dy, hw, hh, r):
    """How far each point is outside a rounded rectangle centred on 0, 0 (less than 0 inside), in px."""
    qx, qy = np.abs(dx) - (hw - r), np.abs(dy) - (hh - r)
    return np.hypot(np.maximum(qx, 0.0), np.maximum(qy, 0.0)) + np.minimum(np.maximum(qx, qy), 0.0) - r


def _same(a, b):
    norm = lambda t: re.sub(r"[^a-z0-9]+", "", str(t).lower())  # noqa: E731
    a, b = norm(a), norm(b)
    return bool(a) and bool(b) and (a == b or a in b or b in a)


class Layout:
    """What the island holds in one state: its size, its words already drawn, where the animation and the mark go."""
    __slots__ = ("state", "w", "h", "card", "texts", "anim", "mark", "key")


class Island:
    """The popup as the Dynamic Island. The same calls as the pill: show(state, text), caption(text), hide(delay),
    close(), visible."""
    TOP, MARGIN = 8, 18  # logical px: the gap above it, and room round it for the shadow and smooth edges
    COMPACT_H, CARD_MIN_H, PAD_Y = 36, 64, 13
    MIN_W, CARD_MIN_W, MAX_W = 160, 340, 540
    RADIUS, PAD, GAP = 30, 16, 10
    GROW = (112, 32)  # the small capsule it grows out of and shrinks back into, like the iPhone's camera cut-out

    def __init__(self, root):
        self.root = root
        s = self.s = root.winfo_fpixels("1i") / 96  # Windows display scaling
        self.compact = Text(round(14 * s), 600)
        self.label = Text(round(12.5 * s), 600)
        self.main = Text(round(15 * s), 600)
        self.m = round(self.MARGIN * s)
        max_h = 2 * self.PAD_Y * s + self.label.line + 2 * s + 3 * self.main.line
        self.cw = int(math.ceil(self.MAX_W * s)) + 2 * self.m
        self.ch = int(math.ceil(max(max_h, self.CARD_MIN_H * s))) + 2 * self.m
        self.xs = np.arange(self.cw, dtype=np.float32) + 0.5
        self.ys = np.arange(self.ch, dtype=np.float32) + 0.5
        # Tk's window, made a layered one that Windows draws from our picture: clicks go through, never focused,
        # not in the taskbar or Alt+Tab, and not in the screenshots she looks at
        self.top = tk.Toplevel(root)
        self.top.withdraw()
        self.top.overrideredirect(True)
        self.top.geometry("1x1+-20000+-20000")
        self.top.deiconify()
        self.top.update_idletasks()
        self.hwnd = win.root_hwnd(self.top.winfo_id())
        win.make_overlay(self.hwnd)
        win.NO_CAPTURE.append(self.hwnd)
        self.dc = _new_dc(None)
        self.bitmap, self.buf = _dib(self.dc, self.cw, self.ch)
        self.old_bitmap = _select(self.dc, self.bitmap)
        self.buf[:] = 0
        self.origin = wt.POINT(-20000, -20000)
        # Windows refuses (invalid parameter) a picture for this window while it's hidden, so the first one goes in
        # while it's still shown off screen, and every later one only while it's up: see show and _tick
        if not self._push():  # Windows won't take our pictures for this window: the pill instead
            raise OSError(ctypes.get_last_error(), "UpdateLayeredWindow failed")
        win.hide_window(self.hwnd)
        self.W, self.H = Spring(self.GROW[0] * s, 0.46, 0.72), Spring(self.GROW[1] * s, 0.4, 0.8)
        self.alpha, self.fade = 0.0, 0  # how much it shows, and which way it's going
        self.layout, self.prev = None, None  # what it holds, and what it held, fading out
        self.content, self.prev_alpha, self.changed = 0.0, 0.0, 0.0
        self.visible, self.state, self.text, self.you = False, None, "", ""
        self.level, self.since, self.t0, self.job, self.hide_job, self.last = 0.0, 0.0, time.time(), None, None, 0.0
        self.geo = None  # the shape's pixels while it's still, so a still island isn't worked out every frame
        self.frame_ms = 0.0  # what a frame took, for the log

    # ------------------------------------------------------------------ what the app calls
    def show(self, state, text=None):
        """Show it in this state (see LOOKS), with text, or the state's own words if text is None or empty."""
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None
        text = re.sub(r"\[[^\]]*\]\s*", "", " ".join(str(text or "").split()))  # her [cheerful] tags aren't words
        if state != self.state:
            self.since = time.time()
        self.state, self.text = state, text
        if not self.visible:
            self._place()
            self.W.jump(self.GROW[0] * self.s)
            self.H.jump(self.GROW[1] * self.s)
            self.alpha, self.layout, self.prev = 0.0, None, None
            self.buf[:] = 0
            # shown first, holding the see-through picture it was hidden with, then given the new one: see __init__
            win.show_no_activate(self.hwnd, self.origin.x, self.origin.y, self.cw, self.ch)
            self._push()
            self.visible = True
        self.fade = 1
        self._relayout()
        if not self.job:
            self.last = time.time()
            self._tick()

    def caption(self, text):
        """What she heard you say, put right: it shows over what she's doing and above what she says back."""
        self.you = " ".join(str(text or "").split())
        if self.visible and self.fade > 0:
            self._relayout()

    def hide(self, delay=0):
        """Fold up and go, after delay ms. Showing it again in the meantime keeps it up."""
        if delay:
            if self.visible and not self.hide_job:
                self.hide_job = self.root.after(delay, self.hide)
            elif not self.visible:
                self.you = ""
            return
        self.hide_job = None
        if not self.visible:
            self.you = ""
            return
        if self.fade > 0:  # what it holds goes first, then it shrinks back into the capsule and fades
            if self.layout is not None:
                self.prev, self.prev_alpha, self.layout, self.content = self.layout, self.content, None, 0.0
            self.W.go(self.GROW[0] * self.s)
            self.H.go(self.GROW[1] * self.s)
        self.fade = -1

    def close(self):
        """Gone straight away, for quitting."""
        for job in (self.job, self.hide_job):
            if job:
                self.root.after_cancel(job)
        self.job = self.hide_job = None
        if self.visible:
            win.hide_window(self.hwnd)
            self.visible = False

    # ------------------------------------------------------------------ what it says
    def _words(self):
        """(label, main text, newest words first, most rows) for the state: the label is the small grey line."""
        state, you = self.state or "listening", self.you
        own = LOOKS.get(state, LOOKS["listening"])[3]
        plain = own.rstrip("\u2026").strip()
        text = self.text.rstrip(" \u2026").strip() if self.text else ""
        if text == plain:
            text = ""
        if state in ("listening", "dictating"):
            return plain, text, True, 2
        if state in ("thinking", "looking", "doing", "finishing"):
            if you and text and not _same(text, you):
                return text, you, False, 2  # what she's doing, over what you said
            return plain, you or text, False, 2
        if state == "speaking":
            return (f"You: {you}" if you else "Jev"), text, False, 3
        if state == "window":
            return plain, "", False, 1
        if state == "note":
            return text or plain, "", False, 1
        return plain, text, False, 2

    def _make_layout(self):
        s, state = self.s, self.state or "listening"
        label, main, newest, rows = self._words()
        mark = MARKS.get(state)
        pad, gap = self.PAD * s, self.GAP * s
        trail = (gap + 12 * s) if mark else 0.0
        lay = Layout()
        lay.state, lay.key = state, (state, label, main)
        if not main:  # compact: the animation, a word or two, and the mark
            h = self.COMPACT_H * s
            aw = round(60 * s)
            tx = pad * 0.45 + aw + gap * 0.5
            text = self.compact.fit(label, self.MAX_W * s - tx - pad - trail)
            colour = SIGNAL_RED if state == "error" else GREY if state in ("note", "window") else WHITE
            lay.w = max(self.MIN_W * s, tx + self.compact.measure(text) + trail + pad)
            lay.h, lay.card = h, False
            lay.texts = [(self.compact.render(text), tx, (h - self.compact.line) / 2 - 1, colour)] if text else []
            lay.anim = (round(pad * 0.4), 0, aw, round(h))
            lay.mark = (mark[0], mark[1], mark[2], pad + 6 * s, h / 2) if mark else None
            return lay
        # a card: the animation on the left, the grey label, and the words under it
        aw, ah = round(64 * s), round(44 * s)
        tx = pad * 0.6 + aw + gap
        avail = self.MAX_W * s - tx - pad - trail
        label = self.label.fit(label, avail) if label else ""
        lines = self.main.wrap(main, avail, rows, newest)
        widest = max([self.label.measure(label)] + [self.main.measure(r) for r in lines])
        lay.w = min(self.MAX_W * s, max(self.CARD_MIN_W * s, tx + widest + trail + pad))
        lh, mh = self.label.line, self.main.line
        tall = (lh + 2 * s if label else 0) + mh * len(lines)
        lay.h = max(self.CARD_MIN_H * s, tall + 2 * self.PAD_Y * s)
        lay.card = True
        y = (lay.h - tall) / 2
        lay.texts = []
        if label:
            lay.texts.append((self.label.render(label), tx, y, SIGNAL_RED if state == "error" else GREY))
            y += lh + 2 * s
        for row in lines:
            lay.texts.append((self.main.render(row), tx, y, GREY if state == "note" else WHITE))
            y += mh
        lay.anim = (round(pad * 0.6), round((lay.h - ah) / 2), aw, ah)
        lay.mark = (mark[0], mark[1], mark[2], pad + 6 * s, (lay.h - tall) / 2 + lh / 2) if mark else None
        return lay

    def _relayout(self):
        new = self._make_layout()
        old = self.layout
        if old is not None and new.key == old.key:
            return
        if old is None:  # first words since it opened: they fade in as it grows
            self.layout, self.content, self.changed = new, 0.0, time.time()
        elif new.card == old.card and new.state == old.state:  # more of the same, as words come in: straight away
            self.layout = new
        else:  # something else: what's there fades out quickly, then the new words fade in as it reshapes
            if self.prev is None or self.content > self.prev_alpha:
                self.prev, self.prev_alpha = old, self.content
            self.layout, self.content, self.changed = new, 0.0, time.time()
        self.W.go(new.w)
        self.H.go(new.h)

    # ------------------------------------------------------------------ drawing
    def _place(self):
        """Top middle of the screen you're working on, under the edge like the iPhone's."""
        left, top, right, bottom = win.work_area()
        cx = (left + right) // 2
        self.origin = wt.POINT(cx - self.cw // 2, top + round(self.TOP * self.s) - self.m)

    def _push(self):
        _flush()
        size, src = wt.SIZE(self.cw, self.ch), wt.POINT(0, 0)
        blend = _BLEND(0, 0, 255, 1)  # AC_SRC_OVER, with our own alpha, premultiplied
        return bool(_ULW(self.hwnd, None, ctypes.byref(self.origin), ctypes.byref(size), self.dc, ctypes.byref(src), 0,
                         ctypes.byref(blend), 2))  # ULW_ALPHA

    def _tick(self):
        now = time.time()
        dt = min(0.05, max(0.0, now - self.last))
        self.last = now
        self.alpha = min(1.0, self.alpha + dt / 0.14) if self.fade > 0 else max(0.0, self.alpha - dt / 0.24)
        if self.prev is not None:
            self.prev_alpha -= dt / 0.09
            if self.prev_alpha <= 0:
                self.prev = None
        elif self.layout is not None and now - self.changed > 0.07:
            self.content = min(1.0, self.content + dt / 0.2)
        self.W.step(dt)
        self.H.step(dt)
        try:  # a drawing error must never take the app down
            t = time.perf_counter()
            self._draw(now)
            self._push()
            self.frame_ms = (time.perf_counter() - t) * 1000
        except Exception as exc:
            print(f"  island draw failed: {exc!r}")
        if self.fade < 0 and self.alpha <= 0:
            win.hide_window(self.hwnd)
            self.visible, self.job, self.state, self.you = False, None, None, ""
            self.layout = self.prev = None
            return
        moving = not (self.W.resting() and self.H.resting()) or self.prev is not None or self.content < 1 or \
            0 < self.alpha < 1
        self.job = self.root.after(16 if moving else 33, self._tick)

    def _shape(self, W, H):
        """The island's pixels and its shadow at this size: (patch bounds, how covered, alpha with the shadow)."""
        key = (round(W * 2), round(H * 2))
        if self.geo and self.geo[0] == key:
            return self.geo[1:]
        s, m, cx = self.s, self.m, self.cw / 2
        x0, x1 = max(0, int(cx - W / 2 - m)), min(self.cw, int(math.ceil(cx + W / 2 + m)))
        y1 = min(self.ch, int(math.ceil(m + H + m)))
        dx = self.xs[x0:x1][None, :] - cx
        dy = self.ys[:y1][:, None] - (m + H / 2)
        r = min(H / 2, self.RADIUS * s)
        cover = np.clip(0.5 - _box(dx, dy, W / 2, H / 2, r), 0.0, 1.0)
        far = _box(dx, dy - 3 * s, W / 2, H / 2, r)  # a soft shadow a little below, so it lifts off a white page
        shadow = 0.3 * np.clip(0.5 - far / (11 * s), 0.0, 1.0) ** 2
        alpha = cover + shadow * (1 - cover)
        self.geo = (key, (x0, x1, y1), cover, alpha)
        return self.geo[1:]

    def _draw(self, now):
        self.buf[:] = 0
        if self.alpha <= 0:
            return
        s = self.s
        W, H = max(self.W.x, 8 * s), max(self.H.x, 8 * s)
        (x0, x1, y1), cover, alpha = self._shape(W, H)
        col = np.zeros(cover.shape + (3,), np.float32)
        ox, oy = self.cw / 2 - W / 2 - x0, self.m  # the island's top left in the patch
        frames = {}
        for lay, a in ((self.prev, self.prev_alpha), (self.layout, self.content)):
            if lay is not None and a > 0.01:
                self._content(col, lay, ox, oy, W, min(a, 1.0), now, frames)
        np.minimum(col, 1.0, out=col)
        g = 255 * self.alpha
        k = cover * g
        out = self.buf[:y1, x0:x1]
        out[..., 0] = col[..., 2] * k + 0.5  # premultiplied: the island is black, so its colour is just what's on it
        out[..., 1] = col[..., 1] * k + 0.5
        out[..., 2] = col[..., 0] * k + 0.5
        out[..., 3] = alpha * g + 0.5

    def _content(self, col, lay, ox, oy, W, a, now, frames):
        kind, source, tint, _ = LOOKS.get(lay.state, LOOKS["listening"])
        ax, ay, aw, ah = lay.anim
        key = (lay.state, aw, ah)
        img = frames.get(key)
        if img is None:  # the same frame for what's fading out and coming in
            t = now - self.t0
            if kind == "dots":
                img = dots(t, aw, ah)[..., None] * np.array(tint, np.float32)
            else:
                self.level = loudness(source, self.level)
                img = wave(t, aw, ah, 0.12 + 0.88 * self.level if source else 0.25) * np.array(tint, np.float32)
            frames[key] = img
        _add(col, img * a, ox + ax, oy + ay)
        for cover, x, y, colour in lay.texts:
            _blend(col, cover, ox + x, oy + y, colour, a)
        if lay.mark:
            shape, colour, pulse, from_right, my = lay.mark
            mx, my = ox + W - from_right, oy + my
            if shape == "ring":
                total = float(getattr(sys.modules.get("siri"), "FOLLOW_UP", 8.0))
                left = max(0.0, 1 - (now - self.since) / total)
                _ring(col, mx, my, 6.5 * self.s, 2.2 * self.s, left, colour, a)
            else:
                beat = 0.62 + 0.38 * (0.5 + 0.5 * math.sin((now - self.t0) * 5.2)) if pulse else 1.0
                _dot(col, mx, my, 4.2 * self.s, colour, a * beat)


def _patch(col, x, y, w, h):
    """The part of col a w x h picture at x, y lands on, and which part of the picture that is."""
    x, y = int(round(x)), int(round(y))
    X0, Y0 = max(0, x), max(0, y)
    X1, Y1 = min(col.shape[1], x + w), min(col.shape[0], y + h)
    if X1 <= X0 or Y1 <= Y0:
        return None
    return (slice(Y0, Y1), slice(X0, X1)), (slice(Y0 - y, Y1 - y), slice(X0 - x, X1 - x))


def _add(col, img, x, y):
    """Light added on: the animations glow on the black."""
    p = _patch(col, x, y, img.shape[1], img.shape[0])
    if p:
        col[p[0]] += img[p[1]]


def _blend(col, cover, x, y, colour, a):
    """Words, or a mark, in colour over what's there."""
    p = _patch(col, x, y, cover.shape[1], cover.shape[0])
    if p:
        m = (cover[p[1]] * a)[..., None]
        col[p[0]] = col[p[0]] * (1 - m) + colour * m


def _dot(col, x, y, r, colour, a):
    n = int(math.ceil(r + 2))
    yy, xx = np.mgrid[-n:n + 1, -n:n + 1].astype(np.float32)
    fx, fy = x - round(x), y - round(y)
    cover = np.clip(0.5 - (np.hypot(xx + 0.5 - fx, yy + 0.5 - fy) - r), 0.0, 1.0)
    _blend(col, cover, round(x) - n, round(y) - n, colour, a)


def _ring(col, x, y, r, width, left, colour, a):
    """A ring running down from the top, clockwise, like a timer on an iPhone: left, how much is still to go."""
    n = int(math.ceil(r + width + 2))
    yy, xx = np.mgrid[-n:n + 1, -n:n + 1].astype(np.float32)
    dx, dy = xx + 0.5 - (x - round(x)), yy + 0.5 - (y - round(y))
    ring = np.clip(0.5 - (np.abs(np.hypot(dx, dy) - r) - width / 2), 0.0, 1.0)
    turn = (np.arctan2(dx, -dy) % math.tau) / math.tau  # 0 at the top, going round clockwise
    _blend(col, ring, round(x) - n, round(y) - n, RING_BACK, a)
    _blend(col, ring * (turn <= left), round(x) - n, round(y) - n, colour, a)


# --------------------------------------------------------------------------- which one
def Bubble(root):
    """The popup: her island at the top of the screen with her eyes and its plugins (island.py), or with Settings
    popup_style "card" the iPhone Dynamic Island card here (Island), or "pill" the Siri pill at the bottom. Each
    falls back to the next if Windows won't draw it."""
    try:
        import settings
        style = settings.get("popup_style")
    except Exception:
        style = "island"
    if style not in ("pill", "card"):
        try:
            import island
            return island.DynamicIsland(root)
        except Exception as exc:
            print(f"  her island didn't start ({exc!r}), using the card")
    if style != "pill":
        try:
            return Island(root)
        except Exception as exc:
            print(f"  dynamic island didn't start ({exc!r}), using the pill")
    return Pill(root)
