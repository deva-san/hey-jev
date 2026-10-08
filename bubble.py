"""A small black pill at the bottom middle of the screen, Siri style, that shows what she's doing:

listening    the Siri wave, moving with your voice
window       the few seconds after she answers, when you can carry on without her name: a dimmer wave, and a red
             line counting them down
dictating    the wave, as for listening
thinking     glowing dots that merge, scatter and gather
looking      the dots, bluer, while she looks at the screen (the popup is left out of what she sees)
doing        the dots, warmer, while the steps run
speaking     the wave, moving with her voice, and what she's saying
It fades in and out, and never takes focus, so typing and pasting still go where your cursor is.

The two animations are the GLSL shaders of the SiriWave React component (its "wave" and "fluid-dots" variants),
worked out here with numpy for a small image each frame, since this window is Tk, not a web page.
"""
import math
import re
import sys
import time
import tkinter as tk
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


# --------------------------------------------------------------------------- the window
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


class Bubble:
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

    def _loudness(self, source):
        """How loud the voice moving the wave is now, 0 to 1, eased so it swells and settles."""
        siri = sys.modules.get("siri")  # siri may still be loading
        levels = list(getattr(siri, "MIC_LEVELS" if source == "mic" else "SPEAK_LEVELS", ()))[-3:] if source else []
        target = min(1.0, math.sqrt(max(levels) / GAIN[source])) if levels else 0.0
        self.level += (target - self.level) * (0.35 if target > self.level else 0.12)
        return self.level

    def _frame(self):
        kind, source, tint, _ = LOOKS.get(self.state, LOOKS["listening"])
        t = time.time() - self.t0
        if kind == "dots":
            col = dots(t, self.iw, self.h)[..., None] * np.array(tint, np.float32)
        else:
            amp = 0.12 + 0.88 * self._loudness(source) if source else 0.25
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
