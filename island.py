"""Her island at the top of the screen, the way Nixi (heynixi.com) has it: a black island with her eyes that
blink, look about and react, the app you're in and dots that move with your voice while she listens, and what
you're saying in a bar underneath, with the fillers and the words you put right struck out as you dictate.

Its plugins (island_plugins.py, from MaterialYou Dynamic Island) use it when she isn't busy: what she's working on
stays live, step by step, and opens into a card with Stop and Deny when you point at it (or click it to
keep it open); a notification pops up from the apps you pick, what's playing shows with its cover and its controls
when you point at it, the battery when you plug in or it runs low, and a running timer counts down. Light, dark and
AMOLED (pure black) themes, its place, size and corners, and the plugins are all in the Island tab.

It's one layered window drawn with numpy, like bubble.Island: clicks go through it except while you point at its
buttons, it never takes the focus, and it's left out of her screenshots, so the model never sees its buttons. Between
blinks nothing is drawn, and a long job moves once a second.
"""
import ctypes
import math
import os
import re
import sys
import time
import tkinter as tk
from ctypes import wintypes as wt

import numpy as np

import bubble
import dictation
import island_art as art
import island_face as face
import island_plugins as plugins
import settings
import winplatform as win
from bubble import LOOKS, Spring, Text

BLUE, GREEN, ORANGE = (0.04, 0.52, 1.0), (0.19, 0.82, 0.35), (1.0, 0.62, 0.04)
VIOLET, CYAN, RED = (0.69, 0.42, 1.0), (0.39, 0.82, 1.0), (1.0, 0.27, 0.23)
THEMES = {  # body, the bar under it, words, quieter words, eyes, eyes glow, a border, its shadow
    "amoled": {"body": (0.0, 0.0, 0.0), "cap": (0.03, 0.03, 0.035), "text": (0.96, 0.96, 0.97),
               "muted": (0.56, 0.56, 0.59), "eyes": (0.97, 0.97, 0.98), "glow": True, "line": (0.24, 0.24, 0.26),
               "shadow": 0.32, "track": (0.25, 0.25, 0.27)},
    "dark": {"body": (0.1, 0.1, 0.11), "cap": (0.13, 0.13, 0.145), "text": (0.95, 0.95, 0.96),
             "muted": (0.6, 0.6, 0.63), "eyes": (0.96, 0.96, 0.97), "glow": True, "line": (0.3, 0.3, 0.32),
             "shadow": 0.3, "track": (0.3, 0.3, 0.32)},
    "light": {"body": (0.965, 0.965, 0.975), "cap": (1.0, 1.0, 1.0), "text": (0.07, 0.07, 0.08),
              "muted": (0.42, 0.42, 0.45), "eyes": (0.11, 0.11, 0.12), "glow": False, "line": (0.8, 0.8, 0.83),
              "shadow": 0.2, "track": (0.82, 0.82, 0.85)},
}
# Her own turns: (how her eyes look, the dots' colour, what the dots do, the bars by the words)
JEV = {
    "listening": ("open", BLUE, "voice", BLUE), "read": ("open", ORANGE, "voice", ORANGE),
    "again": ("side", ORANGE, "voice", ORANGE), "window": ("open", ORANGE, "ring", None),
    "dictating": ("open", GREEN, "voice", GREEN), "thinking": ("think", VIOLET, "busy", None),
    "looking": ("glasses", CYAN, "busy", None), "doing": ("focus", ORANGE, "busy", None),
    "finishing": ("focus", BLUE, "busy", None), "speaking": ("open", None, "her", None),
    "error": ("sad", RED, "still", None), "phone": ("open", BLUE, "still", None),
    "note": ("side", None, "still", None),
}
MIC_STATES = {"listening", "read", "again", "dictating"}
HINTS = ("Say \u201cstop", "Say \"stop", "Go ahead", "Let go")  # the window's hints, not words you said
CLICKABLE = ("media", "notification", "card")  # what takes clicks while you point at it: all else lets them through
REST = 0.5  # seconds the pointer rests on Approve before a click on it counts: an agent's click moves it there first


class _ULWINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("hdcDst", wt.HDC), ("pptDst", ctypes.POINTER(wt.POINT)),
                ("psize", ctypes.POINTER(wt.SIZE)), ("hdcSrc", wt.HDC), ("pptSrc", ctypes.POINTER(wt.POINT)),
                ("crKey", wt.DWORD), ("pblend", ctypes.POINTER(bubble._BLEND)), ("dwFlags", wt.DWORD),
                ("prcDirty", ctypes.POINTER(wt.RECT))]


# Only the part that changed goes to Windows: the whole window's picture every frame took 20 ms or more
_ULWI = bubble._api(bubble._user32.UpdateLayeredWindowIndirect, [wt.HWND, ctypes.POINTER(_ULWINFO)], wt.BOOL)


def _union(a, b):
    """Two boxes (x0, y0, x1, y1) as one that holds both; either may be None."""
    if a is None:
        return b
    if b is None:
        return a
    return min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3])


def _spread(part, i0, i1):
    """A patch worked out with its alike middle columns as the one at i0, back to its full width."""
    h, n = part.shape[0], part.shape[1] - 1 + (i1 - i0)
    out = np.empty((h, n), part.dtype)
    out[:, :i0] = part[:, :i0]
    out[:, i0:i1] = part[:, i0:i0 + 1]
    out[:, i1:] = part[:, i0 + 1:]
    return out


class Layout:
    """What the island holds in one scene: its size, how to draw it, the words under it, and where to click.
    eyes: her expression in it, if her eyes are in it; wander: they may look about. press: for a card, what each
    hot place does, (plugin, what, data, careful)."""
    __slots__ = ("key", "kind", "w", "h", "radius", "draw", "cap", "hot", "eyes", "animated", "rate", "wander",
                 "press")

    def __init__(self, key, kind, w, h, draw, radius=None, cap=None, hot=(), eyes=None, animated=False, rate=0,
                 wander=True, press=None):
        self.key, self.kind, self.w, self.h, self.draw, self.radius = key, kind, w, h, draw, radius
        self.cap, self.hot, self.eyes, self.animated, self.rate = cap, list(hot), eyes, animated, rate
        self.wander, self.press = wander, dict(press or {})


class Caption:
    """The bar under the island with the words in it. live: the part that moves (the bars that go with your
    voice), drawn again each frame over a kept picture of the rest; live_box: where that part is."""
    __slots__ = ("key", "w", "h", "draw", "animated", "live", "live_box")

    def __init__(self, key, w, h, draw, animated=False, live=None, live_box=None):
        self.key, self.w, self.h, self.draw, self.animated = key, w, h, draw, animated
        self.live, self.live_box = live, live_box


class DynamicIsland:
    """The popup: show(state, text), caption(text), hide(delay), close() and visible as bubble.Island has them,
    and react(mood) for her eyes, reload() after a setting changed, preview() for a look at a notification."""
    MARGIN, GAP = 20, 9  # logical px: room round it in the window for the shadow, and from it to the words
    FACE, WAVE, COMPACT_H = (118, 80), (176, 44), 34
    CARD_W, CAP_MAX_W, CAP_PAD_X, CAP_PAD_Y = 380, 700, 16, 11
    EYES, SMALL_EYES = 19, 13
    CARD_PAD, ROW_GAP, BUTTON_H = 14, 9, 22  # a card's rows: round them, between them, and their buttons' height

    def __init__(self, root):
        self.root = root
        self.closed = False
        self.s = root.winfo_fpixels("1i") / 96
        self.runner = plugins.Runner()
        self.light, self.busy, self.area = False, False, None
        self._read_settings()
        self._build()
        self.eyes = face.Eyes()
        self.jev, self.you, self.hide_job, self.since = None, "", None, 0.0
        self.popups, self.popup, self.lives = [], None, {}
        self.hover, self.hover_at, self.away_at, self.hover_job, self.look_at = False, 0.0, 0.0, None, None
        self.pinned = None  # the plugin whose card a click keeps open after the pointer's gone
        self.rest_pos, self.rest_at = None, 0.0  # where the pointer is, and since when it's been there
        self.alpha, self.fade, self.visible_window = 0.0, 0, False
        self.layout = self.prev = None
        self.content = self.prev_alpha = 0.0
        self.changed = 0.0
        self.cap_alpha = 0.0
        self.level, self.t0, self.last, self.job, self.dirty = 0.0, time.time(), time.time(), None, True
        self.job_due = 0.0
        self.icon, self.icon_for = None, None
        self.frame_ms, self.dt = 0.0, 0.016
        self.eye = ("open", 1.0, 0.0, 0.0, False)  # this frame's eyes (face.Eyes.update), the same for every layout
        self.texts = {}
        self.root.after(250, self._events)
        self.runner.start()
        self.root.after(400, self._wake)

    # ------------------------------------------------------------------ settings
    def _read_settings(self):
        g = settings.get
        self.face_style = g("island_face") if g("island_face") in ("eyes", "wave") else "eyes"
        self.theme_name = g("island_theme") if g("island_theme") in ("system", "light", "dark", "amoled") else "amoled"
        self.border = bool(g("island_border"))
        self.align = g("island_align") if g("island_align") in ("left", "center", "right") else "center"
        self.off_x, self.off_y = int(g("island_x") or 0), int(g("island_y") if g("island_y") is not None else 8)
        self.scale = max(70, min(150, int(g("island_scale") or 100))) / 100
        self.corner = max(6, min(40, int(g("island_radius") or 22)))
        self.always = bool(g("island_always"))
        self.hide_full = bool(g("island_hide_fullscreen"))
        self.auto_hide = max(1.5, min(30.0, float(g("island_auto_hide") or 5)))
        self.enabled = bool(g("popup"))  # Settings > Show the popup: off, only the turns the window still shows

    def theme(self):
        name = self.theme_name
        if name == "system":
            name = "light" if self.light else "dark"
        return THEMES[name]

    def reload(self):
        """After a setting changed in the Island tab: it shows the change straight away."""
        old_scale = self.scale
        self._read_settings()
        if self.scale != old_scale:
            was = self.visible_window
            self._teardown()
            self._build()
            self.visible_window = False
            if was:
                self.alpha = 0.0
        self.layout = self.prev = None
        self.shapes = {}  # the shadow and the border change with the theme
        self.dirty = True
        self._place()
        self._wake()

    def preview(self):
        """A notification for a look at how they come out."""
        self.popups.append(plugins.Activity("notifications", "notification", {
            "app": "Hey Jev", "app_id": "", "title": "This is how a notification looks",
            "text": "Pick which apps show here in the Island tab.", "phone": False}, mood="surprised"))
        self.dirty = True
        self._wake()

    # ------------------------------------------------------------------ the window
    def _build(self):
        s = self.k = self.s * self.scale
        self.f_compact = Text(round(13.5 * s), 600)
        self.f_label = Text(round(12 * s), 600)
        self.f_main = Text(round(15 * s), 500)
        self.f_title = Text(round(14.5 * s), 700)
        self.f_small = Text(round(11.5 * s), 600)
        self.m = round(self.MARGIN * s)
        cap_h = 2 * self.CAP_PAD_Y * s + self.f_label.line + 2 * s + 3 * self.f_main.line
        # tall enough for a card's rows (_card) from the start: building the window again each time you point at it
        # would flicker, and the taller picture costs memory only (271 px for 140: 0.4 MB more at 100%, 0.8 MB at
        # 150%, measured 27 October), never time: only what changed is sent (_push)
        self.island_max_h = max(140 * s, self._tallest_card())
        self.cw = int(math.ceil(max(self.CAP_MAX_W, self.CARD_W) * s)) + 2 * self.m
        self.ch = int(math.ceil(self.m + self.island_max_h + self.GAP * s + cap_h + self.m))
        self.top = tk.Toplevel(self.root)
        self.top.withdraw()
        self.top.overrideredirect(True)
        self.top.geometry(f"{self.cw}x{self.ch}+-20000+-20000")  # Tk's own window covers it all, for clicks
        self.top.deiconify()
        self.top.update_idletasks()
        self.hwnd = win.root_hwnd(self.top.winfo_id())
        win.make_overlay(self.hwnd)
        win.NO_CAPTURE.append(self.hwnd)
        self.dc = bubble._new_dc(None)
        self.bitmap, self.buf = bubble._dib(self.dc, self.cw, self.ch)
        self.old_bitmap = bubble._select(self.dc, self.bitmap)
        self.buf[:] = 0
        self.drawn, self.partial = None, True  # the box drawn last frame; whether Windows takes just a part
        self.cap_key = self.cap_picture = None  # the words' bar while it stands still (_draw)
        self.origin = wt.POINT(-20000, -20000)
        if not self._push():  # Windows won't take our pictures: bubble's pill instead (see bubble.Bubble)
            raise OSError("UpdateLayeredWindow failed")
        win.hide_window(self.hwnd)
        self.W, self.H = Spring(84 * s, 0.46, 0.74), Spring(self.COMPACT_H * s, 0.4, 0.8)
        self.CW, self.CH = Spring(0.0, 0.42, 0.82), Spring(0.0, 0.38, 0.84)
        self.top.bind("<ButtonRelease-1>", lambda e: self._click(False))
        self.top.bind("<ButtonRelease-3>", lambda e: self._click(True))
        self.shapes = {}

    def _teardown(self):
        for job in (self.job, self.hover_job):
            if job:
                self.root.after_cancel(job)
        self.job = self.hover_job = None
        win.hide_window(self.hwnd)
        if self.hwnd in win.NO_CAPTURE:
            win.NO_CAPTURE.remove(self.hwnd)
        bubble._select(self.dc, self.old_bitmap)
        bubble._delete(self.bitmap)
        bubble._delete_dc(self.dc)
        for t in (self.f_compact, self.f_label, self.f_main, self.f_title, self.f_small):
            t.close()
        self.top.destroy()

    def _place(self, area=None):
        left, top, right, bottom = area or self.area or win.work_area()
        k, m = self.k, self.m
        if self.align == "left":
            x = left + (16 + self.off_x) * k - m
        elif self.align == "right":
            x = right - (16 + self.off_x) * k - self.cw + m
        else:
            x = (left + right) / 2 + self.off_x * k - self.cw / 2
        self.origin = wt.POINT(int(round(x)), int(round(top + self.off_y * k - m)))
        if self.visible_window:
            win.show_no_activate(self.hwnd, self.origin.x, self.origin.y, self.cw, self.ch)

    def _push(self, dirty=None):
        """The picture to Windows: all of it, or only the box (x0, y0, x1, y1) that changed."""
        bubble._flush()
        size, src = wt.SIZE(self.cw, self.ch), wt.POINT(0, 0)
        blend = bubble._BLEND(0, 0, 255, 1)  # AC_SRC_OVER, with our own alpha, premultiplied
        if dirty is not None and self.partial:
            x0, y0, x1, y1 = (int(v) for v in dirty)
            if x1 <= x0 or y1 <= y0:
                return True
            rect = wt.RECT(x0, y0, x1, y1)
            info = _ULWINFO(ctypes.sizeof(_ULWINFO), None, ctypes.pointer(self.origin), ctypes.pointer(size), self.dc,
                            ctypes.pointer(src), 0, ctypes.pointer(blend), 2, ctypes.pointer(rect))
            if _ULWI(self.hwnd, ctypes.byref(info)):
                return True
            print(f"  island: Windows won't take part of the picture ({ctypes.get_last_error()}), all of it then")
            self.partial = False
        return bool(bubble._ULW(self.hwnd, None, ctypes.byref(self.origin), ctypes.byref(size), self.dc,
                                ctypes.byref(src), 0, ctypes.byref(blend), 2))

    def _island_x(self, W):
        if self.align == "left":
            return self.m
        if self.align == "right":
            return self.cw - self.m - W
        return self.cw / 2 - W / 2

    # ------------------------------------------------------------------ what the app calls
    def show(self, state, text=None):
        if self.hide_job:
            self.root.after_cancel(self.hide_job)
            self.hide_job = None
        text = re.sub(r"\[[^\]]*\]\s*", "", " ".join(str(text or "").split()))  # her [cheerful] tags aren't words
        if not self.jev or self.jev["state"] != state:
            self.since = time.time()
            if state in ("error", "note"):  # hearts from a moment ago don't go with something going wrong
                self.eyes.mood = None
        if not self.jev:
            self.icon_for = None  # the app you're in now, for the dots
            self._place(win.work_area())
        self.eyes.wake(time.time())
        self.jev = {"state": state, "text": text}
        self.dirty = True
        self._wake()

    def caption(self, text):
        self.you = " ".join(str(text or "").split())
        if self.jev:
            self.dirty = True
            self._wake()

    def hide(self, delay=0):
        if delay:
            if self.jev and not self.hide_job:
                self.hide_job = self.root.after(delay, self.hide)
            return
        self.hide_job = None
        if self.jev is None:
            return
        self.jev, self.you = None, ""
        self.dirty = True
        self._wake()

    def react(self, mood):
        self.eyes.react(str(mood or ""), time.time())
        self._wake()

    def close(self):
        self.closed = True
        self.runner.stop()
        for job in (self.job, self.hide_job, self.hover_job):
            if job:
                self.root.after_cancel(job)
        self.job = self.hide_job = self.hover_job = None
        win.hide_window(self.hwnd)
        self.visible_window = False

    def destroy(self):
        """Gone for good: the Island tab switched to the card or the pill."""
        self.close()
        try:
            self._teardown()
            for t in self.texts.values():
                t.close()
            self.texts = {}
        except Exception as exc:
            print(f"  island: couldn't tidy up ({exc!r})")

    @property
    def visible(self):
        """Her own popup is up (not just her eyes, or a plugin's)."""
        return self.jev is not None

    # ------------------------------------------------------------------ the plugins
    def _events(self):
        if self.closed:
            return
        changed = False
        for event in self.runner.take():
            kind = event[0]
            if kind == "show":
                self.popups.append(event[1])
                self.popups = self.popups[-6:]
            elif kind == "live":
                if event[2] is None:
                    self.lives.pop(event[1], None)
                    if self.pinned == event[1]:
                        self.pinned = None
                else:
                    self.lives[event[1]] = event[2]
                    if event[2].mood:  # it came up, or something in it did: something done, or waiting on you
                        self.eyes.react(event[2].mood, time.time())
            elif kind == "busy":
                self.busy = event[1]
            elif kind == "place":
                self.area = event[1]
                if self.jev is None:
                    self._place(self.area)
            elif kind == "light":
                self.light = event[1]
            changed = True
        if changed:
            self.dirty = True
            self._wake()
        self.root.after(200, self._events)

    def _scene(self, now):
        """What to show now: her turn, a popup, what stays while it lasts, her eyes, or nothing."""
        if self.jev:
            return ("jev",)
        if not self.enabled or (self.busy and self.hide_full):
            return None
        while self.popups:
            head = self.popups[0]
            if head.until is None:
                if now - head.at > 120:  # it waited behind her too long to be news
                    self.popups.pop(0)
                    continue
                head.until = now + (head.seconds or self.auto_hide)
                if head.mood:
                    self.eyes.react(head.mood, now)
            if now < head.until or (self.hover and self.popup is head):
                self.popup = head
                return ("popup", head)
            self.popups.pop(0)
        self.popup = None
        if self.lives:  # what stays while it lasts, the one that matters most (Plugin.priority): tasks, a timer, music
            return ("live", self.lives[max(self.lives, key=plugins.priority)])
        if self.always and self.face_style == "eyes":
            return ("idle",)
        return None

    # ------------------------------------------------------------------ layouts
    def _make(self, scene, now):
        if scene is None:
            return None
        if scene[0] == "jev":  # pointing at her face while her turn's own row can be stopped: its card, with Stop.
            act, turn = self._turn()  # only while you point: a card pinned earlier never covers her face for a turn
            if turn and turn.get("buttons") and self.hover:
                return self._card(act)
            return self._jev()
        if scene[0] == "idle":
            return self._idle()
        act = scene[1]
        if act.kind == "notification":
            return self._notification(act)
        if act.kind == "media":
            return self._media_card(act) if self.hover else self._media(act)
        if act.kind == "battery":
            return self._battery(act)
        if act.kind == "timer":
            return self._timer(act)
        if isinstance(act.data, dict) and (act.data.get("rows") or act.data.get("title")):  # any plugin's card
            return self._card(act) if self.hover or self.pinned == act.plugin else self._compact(act)
        return self._idle()

    def _front_icon(self, size):
        """The app you're in, for the dots while she listens: its icon, or a badge with its first letter."""
        hwnd = win.user32.GetForegroundWindow()
        if hwnd and hwnd != self.hwnd:
            try:
                exe = win.window_exe(hwnd)
            except Exception:
                exe = ""
            mine = exe and os.path.basename(exe).lower() in ("pythonw.exe", "python.exe")
            if exe and not mine:
                key = (exe.lower(), size)
                if key != self.icon_for:
                    pic = art.exe_icon(exe, size)
                    if pic is None:
                        pic = art.window_icon(hwnd, size)
                    if pic is None:
                        name = win.file_description(exe) or os.path.splitext(os.path.basename(exe))[0]
                        pic = art.badge(name, size, self._text)
                    self.icon, self.icon_for = pic, key
        return self.icon

    def _text(self, px, weight=700):
        key = (px, weight)
        if key not in self.texts:
            self.texts[key] = Text(px, weight)
        return self.texts[key]

    def _turn(self):
        """(the Tasks card, her turn's own row in it) while one runs (island_plugins.Tasks), else (None, None)."""
        act = self.lives.get("tasks")
        turn = act.data.get("turn") if act is not None and isinstance(act.data, dict) else None
        return (act, turn) if turn else (None, None)

    def _jev(self):
        k, th = self.k, self.theme()
        state, text = self.jev["state"], self.jev["text"]
        expr, colour, mode, bars = JEV.get(state, JEV["listening"])
        colour = colour or th["muted" if state == "note" else "text"]
        cap = self._caption(state, text, bars)
        badge = sum(int(a.data.get("badge") or 0) for a in self.lives.values() if isinstance(a.data, dict))
        turn = self._turn()[1]  # how far her turn's got (step 3/5, round 5/30), beside her dots
        key = ("jev", state, self.face_style, badge, turn and (turn.get("status"), turn.get("progress")))
        if self.face_style == "wave":
            W, H = self.WAVE[0] * k, self.WAVE[1] * k
            kind_, source, tint, _ = LOOKS.get(state, LOOKS["listening"])

            def draw(cv, ox, oy, Wn, Hn, a, now):
                aw, ah = int(Wn - 20 * k), int(Hn - 6 * k)
                if aw < 8 or ah < 8:
                    return
                t = now - self.t0
                if kind_ == "dots":
                    img = bubble.dots(t, aw, ah)[..., None] * np.array(tint, np.float32)
                else:
                    self.level = bubble.loudness(source, self.level)
                    img = bubble.wave(t, aw, ah, 0.12 + 0.88 * self.level if source else 0.25) * \
                        np.array(tint, np.float32)
                x0, y0 = int(round(ox + (Wn - aw) / 2)), int(round(oy + (Hn - ah) / 2))
                sl = cv.region(x0, y0, x0 + aw, y0 + ah)
                if sl:
                    cv.col[sl[0]] += cv._part(img, sl[0], x0, y0) * a
            return Layout(key, "jev", W, H, draw, cap=cap, animated=True)
        W, H = self.FACE[0] * k, self.FACE[1] * k
        size = self.EYES * k
        icon = self._front_icon(round(17 * k))
        n, step, r = 5, 8.6 * k, 2.4 * k
        gr = 5.5 * k  # the turn's ring, after a gap

        src = "mic" if state in MIC_STATES else "voice" if state == "speaking" else None

        def draw(cv, ox, oy, Wn, Hn, a, now):
            t = now - self.t0
            e, open_, lx, ly, _ = self.eye
            face.draw_eyes(cv, ox + Wn / 2, oy + Hn * 0.38, size, e, open_, (lx, ly), self.level if src else 0.0, t,
                           th["eyes"], th["glow"], a)
            row_y = oy + Hn * 0.77
            iw = icon.shape[1] if icon is not None else 0
            row_w = iw + (9 * k if iw else 0) + (n - 1) * step + 2 * r + (8 * k + 2 * gr if turn else 0)
            x = ox + Wn / 2 - row_w / 2
            if icon is not None:
                cv.image(icon, x, row_y - icon.shape[0] / 2, a)
                x += iw + 9 * k
            if mode == "ring":
                total = float(getattr(sys.modules.get("siri"), "FOLLOW_UP", 8.0))
                left = max(0.0, 1 - (now - self.since) / total)
                face.ring(cv, x + (n - 1) * step / 2 + r, row_y, 6.5 * k, 2.2 * k, left, ORANGE, th["track"], a)
            else:
                dots_mode = "voice" if mode in ("voice", "her") else "busy" if mode == "busy" else "still"
                face.dots_row(cv, x + r, row_y, n, step, r, colour, self.level if mode in ("voice", "her") else 0.0,
                              t, dots_mode if dots_mode != "still" else "voice", a * (0.75 if mode == "still" else 1))
            if turn:
                self._glyph(cv, x + (n - 1) * step + 2 * r + 8 * k + gr, row_y, gr, turn, now, a)
            if badge:  # how many go on meanwhile, her turn's row too, in the corner: point at her for the card
                self._badge(cv, ox + Wn - 13 * k, oy + 13 * k, badge, a)
        return Layout(key, "jev", W, H, draw, cap=cap, eyes=expr, animated=state not in ("error", "note", "phone"),
                      wander=False)

    def _badge(self, cv, cx, cy, n, a):
        """A small grey pill with n in it, centred on cx, cy."""
        th = self.theme()
        words = str(n) if n < 10 else "9+"
        cover = self.f_small.render(words)
        r = max(7.5 * self.k, cover.shape[1] / 2 + 3 * self.k)
        cv.shape(lambda xs, ys: face.rbox(xs, ys, cx, cy, r, 7.5 * self.k, 7.5 * self.k),
                 (cx - r - 1, cy - 7.5 * self.k - 1, cx + r + 1, cy + 7.5 * self.k + 1), th["track"], a)
        cv.text(cover, cx - cover.shape[1] / 2, cy - self.f_small.line / 2 - 0.5, th["text"], a)

    def _words(self, state, text):
        """(label, words, newest first, most rows, struck out) for the bar under the island."""
        own = LOOKS.get(state, LOOKS["listening"])[3].rstrip("\u2026").strip()
        text = text.rstrip(" \u2026").strip() if text else ""
        if text == own or text.startswith(HINTS):
            text = ""
        you = self.you
        if state == "dictating":
            return "", text, True, 3, True
        if state in ("listening", "read", "again"):
            return "", text, True, 2, False
        if state in ("thinking", "looking", "doing", "finishing"):
            if you and text and not bubble._same(text, you):
                return text, you, False, 2, False
            return "", you or text, False, 2, False
        if state == "speaking":
            return (f"You: {you}" if you else ""), text, False, 3, False
        if state == "window":
            return "", "", False, 1, False
        if state == "note":
            return "", text or own, False, 1, False
        if state == "error":
            return own, text, False, 2, False
        return "", text, False, 2, False

    def _caption(self, state, text, bars):
        label, words, newest, rows, struck = self._words(state, text)
        if not words and not label:
            return None
        k, th = self.k, self.theme()
        f = self.f_main
        bar_w = 20 * k if bars else 0
        avail = self.CAP_MAX_W * k - 2 * self.CAP_PAD_X * k - bar_w
        tokens = dictation.segments(words) if struck else [(w, True) for w in words.split()]
        lines = self._wrap(tokens, avail, rows, newest)
        label = self.f_label.fit(label, avail) if label else ""
        space = f.measure(" ") or 4
        widths = [sum(f.measure(" ".join(w for w, _ in run)) for run in self._runs(line)) +
                  space * (len(self._runs(line)) - 1) for line in lines]
        widest = max([self.f_label.measure(label)] + widths + [0])
        w = min(self.CAP_MAX_W * k, 2 * self.CAP_PAD_X * k + bar_w + widest + 4)
        lh, mh = self.f_label.line, f.line
        h = 2 * self.CAP_PAD_Y * k + (lh + 2 * k if label else 0) + mh * len(lines)
        quiet = state in ("note",)
        lab_colour = RED if state == "error" else th["muted"]

        def origin(ox, oy, Hn):
            return ox + self.CAP_PAD_X * k, oy + (Hn - (h - 2 * self.CAP_PAD_Y * k)) / 2

        def meter_at(ox, oy, Hn):
            x, y = origin(ox, oy, Hn)
            return x, x + 3 * k, y + (lh + 2 * k if label else 0) + mh / 2

        def live(cv, ox, oy, Wn, Hn, a, now):  # the bars, which move with your voice
            _, mx, my = meter_at(ox, oy, Hn)
            lvl = self.level if state in MIC_STATES else 0.0
            face.meter(cv, mx, my, 15 * k, bars, lvl, now - self.t0, a)

        def live_box(ox, oy, Wn, Hn):  # all the bars can reach, and short of where the words start
            x, _, my = meter_at(ox, oy, Hn)
            return x - 2, my - 7.5 * k - 3, x + bar_w - 2, my + 7.5 * k + 3

        def draw(cv, ox, oy, Wn, Hn, a, now):
            x, y = origin(ox, oy, Hn)
            if bars:
                x += bar_w
            if label:
                cv.text(self.f_label.render(label), x - 2, y, lab_colour, a)
                y += lh + 2 * k
            for line in lines:
                lx = x
                for run in self._runs(line):
                    s = " ".join(word for word, _ in run)
                    kept = run[0][1]
                    cover = f.render(s)
                    cv.text(cover, lx - 2, y, th["muted"] if (quiet or not kept) else th["text"], a)
                    rw = f.measure(s)
                    if not kept:  # struck out, as Nixi shows it
                        sy, lw = y + mh * 0.54, max(1.0, 1.3 * k)
                        cv.shape(lambda xs, ys, lx=lx, rw=rw, sy=sy, lw=lw: face.rbox(xs, ys, lx + rw / 2, sy, rw / 2,
                                                                                     lw / 2, lw / 2),
                                 (lx - 1, sy - lw, lx + rw + 1, sy + lw), th["muted"], a)
                    lx += rw + space
                y += mh
        key = ("cap", state, label, tuple(tuple(x) for x in lines), bool(bars))
        return Caption(key, w, h, draw, animated=bool(bars), live=live if bars else None,
                       live_box=live_box if bars else None)

    def _wrap(self, tokens, width, rows, newest):
        """Words with whether each is kept, in lines no wider than width: the newest rows while words come in,
        else the first ones, with an ellipsis where some were left out."""
        f = self.f_main
        space = f.measure(" ") or 4
        lines, cur, cur_w = [], [], 0.0
        for word, kept in tokens:
            w = f.measure(word)
            if w > width:
                word = f.fit(word, width)
                w = f.measure(word)
            if cur and cur_w + space + w > width:
                lines.append(cur)
                cur, cur_w = [], 0.0
            cur_w += (space if cur else 0) + w
            cur.append((word, kept))
        if cur:
            lines.append(cur)
        if len(lines) > rows:
            if newest:
                lines = lines[-rows:]
                lines[0] = [("\u2026", True)] + lines[0]
            else:
                lines = lines[:rows]
                word, kept = lines[-1][-1]
                lines[-1][-1] = (word + "\u2026", kept)
        return lines

    @staticmethod
    def _runs(line):
        runs = []
        for word, kept in line:
            if runs and runs[-1][0][1] == kept:
                runs[-1].append((word, kept))
            else:
                runs.append([(word, kept)])
        return runs

    def _row(self, key, kind, expr, left=None, right=None, hot=(), wander=True, rate=0, animated=False, press=None):
        """The small island: something on the left, her eyes, something on the right. left and right are
        (width, draw(cv, x, cy, a, now)) or None."""
        k, th = self.k, self.theme()
        H = self.COMPACT_H * k
        size = self.SMALL_EYES * k
        eyes_w = 2.6 * size if self.face_style == "eyes" else 0
        pad, gap = 15 * k, 11 * k
        parts = [p for p in (left, (eyes_w, None) if eyes_w else None, right) if p]
        inner = sum(p[0] for p in parts) + gap * (len(parts) - 1)
        W = max(84 * k, inner + 2 * pad)

        def draw(cv, ox, oy, Wn, Hn, a, now):
            x = ox + Wn / 2 - inner / 2
            cy = oy + Hn / 2
            if left:
                left[1](cv, x, cy, a, now)
                x += left[0] + gap
            if eyes_w:
                e, open_, lx, ly, _ = self.eye
                face.draw_eyes(cv, x + eyes_w / 2, cy, size, e, open_, (lx, ly), 0.0, now - self.t0, th["eyes"],
                               th["glow"], a)
                x += eyes_w + gap
            if right:
                right[1](cv, x, cy, a, now)
        return Layout(key, kind, W, H, draw, hot=hot, eyes=expr if eyes_w else None, animated=animated, rate=rate,
                      wander=wander, press=press)

    def _idle(self):
        return self._row(("idle",), "idle", "open")

    def _slot_text(self, text, colour, font=None):
        font = font or self.f_compact
        cover = font.render(text)
        w = font.measure(text)

        def draw(cv, x, cy, a, now):
            cv.text(cover, x - 2, cy - font.line / 2 - 1, colour, a)
        return w, draw

    def _battery(self, act):
        k, th = self.k, self.theme()
        d = act.data
        pct, charging, event = d["percent"], d["charging"], d["event"]
        fill = RED if pct <= 20 and not charging else GREEN if charging else th["text"]
        bh = 11 * k

        def glyph(cv, x, cy, a, now):
            face.battery(cv, x, cy, bh, pct, th["text"], fill, charging, a)
        left = (bh * 1.9 + 3 * k, glyph)
        show_pct = plugins.get_options("battery").get("percent", True)
        word = "Full" if event == "full" else f"{pct}%" if show_pct else ("Charging" if charging else "")
        right = self._slot_text(word, fill if fill != th["text"] else th["text"]) if word else None
        expr = "sad" if event == "low" else "open"
        return self._row(("battery", pct, charging, event, word), "battery", expr, left, right)

    def _timer(self, act):
        k, th = self.k, self.theme()
        d = act.data
        font = self.f_compact
        slot_w = font.measure("88:88") + 2 * k

        def ring(cv, x, cy, a, now):
            left = max(0.0, (d["end"] - now) / d["total"])
            face.ring(cv, x + 8 * k, cy, 7 * k, 2.4 * k, left, ORANGE, th["track"], a)

        def clock(cv, x, cy, a, now):
            secs = max(0, int(math.ceil(d["end"] - now)))
            h, rem = divmod(secs, 3600)
            text = f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{rem // 60}:{rem % 60:02d}"
            cv.text(font.render(text), x - 2, cy - font.line / 2 - 1, ORANGE, a)
        return self._row(("timer", d["label"], d["end"]), "timer", "open", (16 * k, ring), (slot_w, clock), rate=1)

    def _media(self, act):
        k, th = self.k, self.theme()
        d = act.data
        size = round(22 * k)
        pic = art.rounded(_resize(d["art"], size), 6 * k) if d.get("art") is not None else None
        if pic is None:
            pic = art.badge(d["app"], size, self._text)

        def cover(cv, x, cy, a, now):
            cv.image(pic, x, cy - size / 2, a)

        def bars(cv, x, cy, a, now):
            lvl = getattr(self.runner.plugin("media"), "level", 0.0) if d["playing"] else 0.0
            face.equalizer(cv, x + 2 * k, cy, 14 * k, GREEN if d["playing"] else th["muted"],
                           min(1.0, lvl * 2.2) if d["playing"] else 0.0, now - self.t0, a)
        expr = "headphones" if d["playing"] else "open"
        return self._row(("media", d["title"], d["artist"], d["playing"], id(d.get("art"))), "media", expr,
                         (size, cover), (16 * k, bars), hot=[("open", 0, 0, 10000, 10000)],
                         rate=15 if d["playing"] else 0)

    def _media_card(self, act):
        k, th = self.k, self.theme()
        d = act.data
        W = self.CARD_W * k
        pad, art_s = 14 * k, round(52 * k)
        pic = art.rounded(_resize(d["art"], art_s), 9 * k) if d.get("art") is not None else None
        if pic is None:
            pic = art.badge(d["app"], art_s, self._text)
        btn, gapb = 28 * k, 4 * k
        controls_w = 3 * btn + 2 * gapb
        tx = pad + art_s + 12 * k
        tw = W - tx - pad - controls_w - 8 * k
        title = self.f_title.fit(d["title"], tw)
        sub = self.f_label.fit(" \u00b7 ".join(x for x in (d["artist"], d["app"]) if x), tw)
        bar_y = pad + art_s + 13 * k
        H = bar_y + 4 * k + 7 * k + self.f_small.line + pad * 0.7
        cy = pad + art_s / 2
        bx0 = W - pad - controls_w
        hot = [("previous", bx0, cy - btn / 2, bx0 + btn, cy + btn / 2),
               ("toggle", bx0 + btn + gapb, cy - btn / 2, bx0 + 2 * btn + gapb, cy + btn / 2),
               ("next", bx0 + 2 * (btn + gapb), cy - btn / 2, bx0 + 3 * btn + 2 * gapb, cy + btn / 2),
               ("open", 0, 0, bx0 - 4 * k, bar_y - 2 * k)]

        def draw(cv, ox, oy, Wn, Hn, a, now):
            cv.image(pic, ox + pad, oy + pad, a)
            cv.text(self.f_title.render(title), ox + tx - 2, oy + cy - self.f_title.line + 1, th["text"], a)
            cv.text(self.f_label.render(sub), ox + tx - 2, oy + cy + 2 * k, th["muted"], a)
            for i, (name, x0, y0, x1, y1) in enumerate(hot[:3]):
                gx, gy = ox + (x0 + x1) / 2, oy + (y0 + y1) / 2
                if name == "toggle":
                    face.play_glyph(cv, gx, gy, 18 * k, d["playing"], th["text"], a)
                else:
                    face.skip_glyph(cv, gx, gy, 14 * k, name == "next", th["text"], a)
            pos = d["position"] + ((now - d["at"]) if d["playing"] else 0.0)
            dur = d["duration"]
            frac = max(0.0, min(1.0, pos / dur)) if dur > 0 else 0.0
            x0, x1, y = ox + pad, ox + Wn - pad, oy + bar_y + 2 * k
            lw = 3.6 * k
            cv.shape(lambda xs, ys: face.rbox(xs, ys, (x0 + x1) / 2, y, (x1 - x0) / 2, lw / 2, lw / 2),
                     (x0 - 1, y - lw, x1 + 1, y + lw), th["track"], a)
            if frac > 0:
                xe = x0 + (x1 - x0) * frac
                cv.shape(lambda xs, ys: face.rbox(xs, ys, (x0 + xe) / 2, y, max(lw / 2, (xe - x0) / 2), lw / 2,
                                                  lw / 2), (x0 - 1, y - lw, xe + 1, y + lw), th["text"], a)
            if dur > 0:
                ty = y + 6 * k
                el, rest = _clock(pos), "-" + _clock(max(0.0, dur - pos))
                cv.text(self.f_small.render(el), x0 - 2, ty, th["muted"], a)
                cover = self.f_small.render(rest)
                cv.text(cover, x1 - cover.shape[1] + 2, ty, th["muted"], a)
        return Layout(("media-card", d["title"], d["artist"], d["playing"], id(d.get("art"))), "media", W, H, draw,
                      radius=self.corner * k, hot=hot, rate=2)

    def _notification(self, act):
        k, th = self.k, self.theme()
        d = act.data
        W = self.CARD_W * k
        pad, bs = 14 * k, round(34 * k)
        pic = art.badge(d["app"], bs, self._text)
        tx = pad + bs + 12 * k
        tw = W - tx - pad
        head = self.f_small.fit((d["app"] + (" \u00b7 on your phone" if d.get("phone") else "")).upper(), tw - 40 * k)
        title = self.f_title.fit(d["title"] or d["app"], tw)
        lines = self.f_label.wrap(d["text"], tw, 2) if d.get("text") else []
        body = self.f_small.line + 3 * k + self.f_title.line + (2 * k + self.f_label.line * len(lines) if lines else 0)
        H = pad * 2 + max(bs, body)
        hot = [("dismiss", W - 30 * k, 0, W, 26 * k), ("open", 0, 0, W, H)]

        def draw(cv, ox, oy, Wn, Hn, a, now):
            cv.image(pic, ox + pad, oy + pad, a)
            y = oy + pad - 1 * k
            cv.text(self.f_small.render(head), ox + tx - 2, y, th["muted"], a)
            if self.hover:
                face.close_glyph(cv, ox + Wn - 18 * k, oy + 14 * k, 12 * k, th["muted"], a)
            else:
                cover = self.f_small.render("now")
                cv.text(cover, ox + Wn - pad - cover.shape[1] + 2, y, th["muted"], a)
            y += self.f_small.line + 3 * k
            cv.text(self.f_title.render(title), ox + tx - 2, y, th["text"], a)
            y += self.f_title.line + 2 * k
            for line in lines:
                cv.text(self.f_label.render(line), ox + tx - 2, y, th["text"], a * 0.86)
                y += self.f_label.line
        return Layout(("note", d["app"], d["title"], d.get("text", ""), id(act)), "notification", W, H, draw,
                      radius=self.corner * k, hot=hot)

    # ------------------------------------------------------------------ cards (island_plugins.Activity)
    def _tallest_card(self):
        """A card's height with every row at its tallest (buttons, two lines and a bar) and "+N more" under them."""
        k = self.k
        row = max(self.f_label.line, self.BUTTON_H * k) + 2 * k + 2 * self.f_small.line + 9 * k
        return 2 * self.CARD_PAD * k + plugins.CARD_ROWS * (row + self.ROW_GAP * k) + self.f_small.line + 5 * k

    @staticmethod
    def _card_rows(d):
        """A card's rows (its "rows", or the card itself as one) as many as show, and how many more there are."""
        rows = list(d.get("rows") or [d])
        return rows[:plugins.CARD_ROWS], int(d.get("more") or 0) + max(0, len(rows) - plugins.CARD_ROWS)

    def _state_colour(self, state):
        th = self.theme()
        return {"waiting_yes": ORANGE, "done": GREEN, "failed": RED}.get(state, th["muted"])

    def _glyph(self, cv, cx, cy, r, row, now, a):
        """How a row's going, small: a ring for how far it's got, a light stepping along three dots once a second
        when that isn't known, an orange ring while it waits on you, a tick once it's done, a cross if it wasn't."""
        th = self.theme()
        state, done = row.get("state") or "running", row.get("progress")
        if state == "done":
            face.tick_glyph(cv, cx, cy, 2.1 * r, GREEN, a)
        elif state in ("failed", "stopped"):
            face.close_glyph(cv, cx, cy, 2.4 * r, RED if state == "failed" else th["muted"], a)
        elif state in ("waiting_yes", "queued") or done is not None:
            part = 1.0 if state == "waiting_yes" else done or 0.0  # none yet: only its track, not a sliver at the top
            face.ring(cv, cx, cy, r, 0.34 * r, part, ORANGE if state == "waiting_yes" else BLUE if part > 0 else
                      th["track"], th["track"], a)
        else:  # the light on dot int(now) % 3: once a second, never a frame for each step of it
            step = 0.95 * r
            face.dots_row(cv, cx - step, cy, 3, step, 0.3 * r, CYAN, 0.0, (int(now) % 3) / 3 / 1.6, "busy", a)

    def _compact(self, act):
        """A card's small island while you aren't pointing at it: how its first row's going (_glyph), her eyes, and
        a few words: how far it's got, how long it's been going, or how many there are."""
        k = self.k
        d = act.data
        rows, more = self._card_rows(d)
        lead = rows[0] if rows else {}
        font = self.f_compact
        text = d.get("short") or lead.get("status") or ""
        since = lead.get("since") if not text else None
        if not text and since is None:
            text = font.fit(str(lead.get("title") or ""), 150 * k)
        colour = self._state_colour(lead.get("state")) if not d.get("short") and lead.get("state") != "running" \
            else self.theme()["text"]
        slot_w = font.measure("88:88") + 2 * k if since is not None else font.measure(text)

        def glyph(cv, x, cy, a, now):
            self._glyph(cv, x + 8 * k, cy, 7 * k, lead, now, a)

        def words(cv, x, cy, a, now):
            cv.text(font.render(text or _clock(max(0.0, now - since))), x - 2, cy - font.line / 2 - 1, colour, a)
        expr = {"done": "happy", "failed": "sad", "waiting_yes": "surprised"}.get(lead.get("state"), "open")
        live = any((r.get("state") or "running") == "running" for r in rows)
        return self._row(("card-row", act.plugin, text, since is not None, repr(lead), len(rows) + more), "card",
                         expr, (16 * k, glyph), (slot_w, words) if slot_w else None, hot=[("pin", 0, 0, 10000, 10000)],
                         rate=1 if live else 0, press={"pin": (act.plugin, "pin", None, False)})

    def _card(self, act):
        """A plugin's card, open while you point at it or after a click on it: up to CARD_ROWS rows, each with how
        it's going (_glyph), its title, a few words at its right, a line or two under it, a bar for how far it's got
        and its buttons, then "+N more". The Tasks plugin's list is one; any plugin can show one without this file
        knowing it (island_plugins.Activity). A clock that's running moves once a second, never every frame."""
        k, th = self.k, self.theme()
        rows, more = self._card_rows(act.data)
        W = self.CARD_W * k
        pad, gap = self.CARD_PAD * k, self.ROW_GAP * k
        hot, press, parts, y = [], {}, [], pad
        for row in rows:
            h, draw_row = self._card_row(row, y, W, pad, act.plugin, hot, press)
            parts.append(draw_row)
            y += h + gap
        tail = f"+{more} more" if more else ""
        H = min(self.island_max_h, y - gap + pad + (self.f_small.line + 5 * k if tail else 0))
        hot.append(("pin", 0, 0, W, H))  # anywhere else on it keeps it open, or lets it go again
        press["pin"] = (act.plugin, "pin", None, False)

        def draw(cv, ox, oy, Wn, Hn, a, now):
            for draw_row in parts:
                draw_row(cv, ox, oy, a, now)
            if tail:
                cv.text(self.f_small.render(tail), ox + pad + 27 * k - 2, oy + y - gap + 5 * k, th["muted"], a)
        live = any((r.get("state") or "running") == "running" for r in rows)
        return Layout(("card", act.plugin, repr(rows), more), "card", W, H, draw, radius=self.corner * k, hot=hot,
                      rate=1 if live else 0, press=press)

    def _card_row(self, row, y0, W, pad, plugin, hot, press):
        """One row of a card from y0: (its height, draw(cv, ox, oy, a, now)). Its buttons go in hot and press."""
        k, th = self.k, self.theme()
        small, label = self.f_small, self.f_label
        bh, bpad, bgap = self.BUTTON_H * k, 10 * k, 6 * k
        buttons, x = [], W - pad
        for b in reversed(row.get("buttons") or []):
            words = str(b.get("label") or b.get("name") or "")
            bw = small.measure(words) + 2 * bpad
            buttons.insert(0, (b, words, x - bw, x))
            x -= bw + bgap
        right = x if buttons else W - pad  # where the words at its right end
        status, since = row.get("status") or "", row.get("since")
        since = since if not status else None
        sw = small.measure(status) if status else small.measure("88:88") if since is not None else 0
        tx = pad + 27 * k
        title = label.fit(" ".join(str(row.get("title") or "").split()), max(20 * k, right - tx - sw - 8 * k))
        lines = [small.fit(" ".join(str(t).split()), right - tx) for t in (row.get("lines") or [])[:2] if t]
        done = row.get("progress")
        h1 = max(label.line, bh if buttons else 0)
        h = h1 + (2 * k + small.line * len(lines) if lines else 0) + (9 * k if done is not None else 0)
        cy = y0 + h1 / 2
        for b, words, bx0, bx1 in buttons:
            name = f"b{len(press)}"
            press[name] = (plugin, b.get("name"), b.get("data"), bool(b.get("careful", b.get("name") == "approve")))
            hot.append((name, bx0 - 2 * k, cy - bh / 2 - 2 * k, bx1 + 2 * k, cy + bh / 2 + 2 * k))
        state_colour = self._state_colour(row.get("state"))

        def draw(cv, ox, oy, a, now):
            self._glyph(cv, ox + pad + 9 * k, oy + cy, 7 * k, row, now, a)
            cv.text(label.render(title), ox + tx - 2, oy + cy - label.line / 2 - 1, th["text"], a)
            words = status or (_clock(max(0.0, now - since)) if since is not None else "")
            if words:
                cover = small.render(words)
                cv.text(cover, ox + right - cover.shape[1] + 2, oy + cy - small.line / 2 - 1, state_colour, a)
            for b, text, bx0, bx1 in buttons:
                approve = b.get("name") == "approve"
                fill, ink = (GREEN, (0.02, 0.02, 0.03)) if approve else \
                    (th["track"], RED if b.get("name") == "stop" else th["text"])
                bx, by, bw = ox + (bx0 + bx1) / 2, oy + cy, (bx1 - bx0) / 2
                cv.shape(lambda xs, ys, bx=bx, by=by, bw=bw: face.rbox(xs, ys, bx, by, bw, bh / 2, bh / 2),
                         (ox + bx0 - 1, by - bh / 2 - 1, ox + bx1 + 1, by + bh / 2 + 1), fill, a)
                cover = small.render(text)
                cv.text(cover, bx - cover.shape[1] / 2, by - small.line / 2 - 0.5, ink, a)
            ly = oy + y0 + h1 + 2 * k
            for line in lines:
                cv.text(small.render(line), ox + tx - 2, ly, th["muted"], a)
                ly += small.line
            if done is not None:  # how far it's got, as the music's bar (_media_card)
                x0, x1, by, lw = ox + tx, ox + right, ly + 4 * k, 3.2 * k
                cv.shape(lambda xs, ys: face.rbox(xs, ys, (x0 + x1) / 2, by, (x1 - x0) / 2, lw / 2, lw / 2),
                         (x0 - 1, by - lw, x1 + 1, by + lw), th["track"], a)
                if done > 0:
                    xe = x0 + (x1 - x0) * min(1.0, done)
                    cv.shape(lambda xs, ys: face.rbox(xs, ys, (x0 + xe) / 2, by, max(lw / 2, (xe - x0) / 2), lw / 2,
                                                      lw / 2), (x0 - 1, by - lw, xe + 1, by + lw),
                             GREEN if row.get("state") == "done" else BLUE, a)
        return h, draw

    # ------------------------------------------------------------------ the frames
    def _wake(self):
        """A frame now, even if the next was set for later (her eyes resting between blinks can wait seconds)."""
        now = time.time()
        if self.job:
            if self.job_due - now <= 0.02:
                return
            self.root.after_cancel(self.job)
        self.last = max(self.last, now - 0.016)
        self.job_due = now
        self.job = self.root.after(0, self._tick)

    def _apply(self, now):
        scene = self._scene(now)
        new = self._make(scene, now)
        self.dirty = False
        if new is None:
            if self.fade > 0:
                self.fade = -1
                if self.layout is not None:
                    self.prev, self.prev_alpha, self.layout, self.content = self.layout, self.content, None, 0.0
            return
        if not self.visible_window:
            self._place()
            self.W.jump(new.w * 0.7)
            self.H.jump(new.h * 0.8)
            self.CW.jump(0.0)
            self.CH.jump(0.0)
            self.alpha, self.layout, self.prev, self.cap_alpha = 0.0, None, None, 0.0
            self.buf[:] = 0
            self.drawn = None
            win.show_no_activate(self.hwnd, self.origin.x, self.origin.y, self.cw, self.ch)
            self._push()
            self.visible_window = True
            self._hover_poll()
        self.fade = 1
        old = self.layout
        if old is not None and (new.key == old.key or old.kind == new.kind == "jev" or
                                (old.kind == new.kind == "card" and old.key[:2] == new.key[:2])):
            self.layout = new  # the same scene with its words moved on, her next step, a card's: straight away
        elif old is None:
            self.layout, self.content, self.changed = new, 0.0, now
        else:
            if self.prev is None or self.content > self.prev_alpha:
                self.prev, self.prev_alpha = old, self.content
            self.layout, self.content, self.changed = new, 0.0, now
        self.W.go(new.w)
        self.H.go(new.h)
        if new.cap:
            self.CW.go(new.cap.w)
            self.CH.go(new.cap.h)

    def _tick(self):
        self.job = None
        now = time.time()
        self.dt = dt = min(0.05, max(0.0, now - self.last))
        self.last = now
        if self.dirty or (self.popup is not None and self.popup.until and now >= self.popup.until and not self.hover):
            self._apply(now)
        if not self.visible_window:
            return
        self.alpha = min(1.0, self.alpha + dt / 0.16) if self.fade > 0 else max(0.0, self.alpha - dt / 0.26)
        if self.prev is not None:
            self.prev_alpha -= dt / 0.1
            if self.prev_alpha <= 0:
                self.prev = None
        if self.layout is not None and now - self.changed > 0.06:
            self.content = min(1.0, self.content + dt / 0.18)
        cap = self.layout.cap if self.layout is not None else None
        self.cap_alpha = min(1.0, self.cap_alpha + dt / 0.16) if cap else max(0.0, self.cap_alpha - dt / 0.12)
        for spring in (self.W, self.H, self.CW, self.CH):
            spring.step(dt)
        lay = self.layout or self.prev
        if lay is not None and lay.eyes is not None:  # once a frame, whatever's fading in or out
            self.eye = self.eyes.update(now, dt, lay.eyes, wander=lay.wander, look_at=self.look_at)
        if lay is not None and lay.kind == "jev":
            src = "mic" if self.jev and self.jev["state"] in MIC_STATES else \
                "voice" if self.jev and self.jev["state"] == "speaking" else None
            self.level = bubble.loudness(src, self.level) if src else self.level * 0.85
        try:
            t = time.perf_counter()
            changed = self._draw(now)
            if changed is not None:
                self._push(changed)
            self.frame_ms = (time.perf_counter() - t) * 1000
        except Exception as exc:  # a drawing error must never take the app down
            print(f"  island draw failed: {exc!r}")
        if self.fade < 0 and self.alpha <= 0:
            win.hide_window(self.hwnd)
            win.set_click_through(self.hwnd, True)
            self.visible_window, self.layout, self.prev, self.hover = False, None, None, False
            return
        lay = self.layout
        moving = not all(sp.resting() for sp in (self.W, self.H, self.CW, self.CH)) or self.prev is not None \
            or (lay is not None and self.content < 1) or 0 < self.alpha < 1 or 0 < self.cap_alpha < 1
        animated = lay is not None and (lay.animated or (lay.cap is not None and lay.cap.animated))
        eyes_moving = lay is not None and lay.eyes is not None and (self.eyes.blink_at is not None or
                                                                     self.eyes.mood is not None or self._looking())
        idle = lay is not None and lay.kind == "idle"
        if moving or (animated and self.face_style == "wave") or \
                (eyes_moving and (not idle or self.eyes.blink_at is not None)):
            wait = 0.016
        elif animated or eyes_moving:  # the dots and bars that go with a voice, and her eyes glancing about while
            wait = 0.033  # nothing's on: 30 frames a second look the same, for half the work
        elif lay is not None and lay.rate:
            wait = 1.0 / lay.rate
        elif lay is not None and lay.eyes is not None:
            wait = self.eyes.wait(now)
        else:
            wait = 1.0
        if self.popup is not None and self.popup.until:
            wait = min(wait, max(0.016, self.popup.until - now))
        ms = max(16, int(wait * 1000))
        self.job_due = now + ms / 1000
        self.job = self.root.after(ms, self._tick)

    def _looking(self):
        e = self.eyes
        return any(abs(e.look[i] - e.target[i]) > 0.004 or abs(e.look_v[i]) > 0.02 for i in (0, 1))

    def _theme_name(self):
        return ("light" if self.light else "dark") if self.theme_name == "system" else self.theme_name

    def _shape(self, x0, W, H, r, y_top):
        """(patch slices, cover, alpha with the shadow, the border's cover or None) of a rounded rectangle. Its
        shadow reaches 5.5k past its sides and 8.5k below it, so the patch goes no further; and once inside the
        corners every column is alike, so the middle is worked out once (a 700 px bar costs what a 90 px one
        does)."""
        key = (round(x0 * 2), round(W * 2), round(H * 2), round(r * 2), round(y_top * 2), self._theme_name(),
               self.border)
        hit = self.shapes.get(key)
        if hit is not None:
            return hit
        k = self.k
        X0, X1 = max(0, int(x0 - 6 * k - 1)), min(self.cw, int(math.ceil(x0 + W + 6 * k + 1)))
        Y0, Y1 = max(0, int(y_top - 3 * k - 1)), min(self.ch, int(math.ceil(y_top + H + 9 * k + 1)))
        xs = np.arange(X0, X1, dtype=np.float32) + 0.5
        ys = np.arange(Y0, Y1, dtype=np.float32)[:, None] + 0.5
        cx, cy = x0 + W / 2, y_top + H / 2
        reach = W / 2 - min(r, W / 2, H / 2) - 7 * k - 2  # past the corners, the shadow's edge and the border
        mid = np.nonzero(np.abs(xs - cx) <= reach)[0] if reach > 0 else ()
        i0 = i1 = None
        if len(mid) > 4:
            i0, i1 = int(mid[0]), int(mid[-1]) + 1
            xs = np.concatenate([xs[:i0], np.asarray([cx], np.float32), xs[i1:]])
        sd = face.rbox(xs, ys, cx, cy, W / 2, H / 2, r)
        cover = np.clip(0.5 - sd, 0.0, 1.0)
        far = face.rbox(xs, ys - 3 * k, cx, cy, W / 2, H / 2, r)
        shadow = self.theme()["shadow"] * np.clip(0.5 - far / (11 * k), 0.0, 1.0) ** 2
        alpha = cover + shadow * (1 - cover)
        edge = np.clip(0.5 - (np.abs(sd + 0.7 * k) - 0.6 * k), 0.0, 1.0) if self.border else None
        if i0 is not None:
            cover, alpha = _spread(cover, i0, i1), _spread(alpha, i0, i1)
            edge = _spread(edge, i0, i1) if edge is not None else None
        hit = ((slice(Y0, Y1), slice(X0, X1)), cover, alpha, edge)
        if len(self.shapes) > 24:
            self.shapes.clear()
        self.shapes[key] = hit
        return hit

    def _paint(self, sl, cover, alpha, edge, body, items, a, over=None):
        """A rounded box and what's on it into the window's picture. over: the rows of the patch (from, to) that
        land on something drawn already this frame, which it goes over; the rest was cleared, so it's written."""
        h, w = cover.shape
        col = np.empty((h, w, 3), np.float32)
        col[:] = body
        cv = face.Canvas(col)
        for draw, ia in items:
            if ia > 0.01:
                draw(cv, min(ia, 1.0))
        self._compose(self.buf[sl], col, cover, alpha, edge, a, over)

    def _paint_part(self, sl, cover, alpha, edge, body, box, draw, a):
        """Only box (x0, y0, x1, y1 in the patch) of a patch painted again: a caption's moving bars, over a
        kept picture of the rest."""
        h, w = cover.shape
        x0, y0 = max(0, int(math.floor(box[0]))), max(0, int(math.floor(box[1])))
        x1, y1 = min(w, int(math.ceil(box[2]))), min(h, int(math.ceil(box[3])))
        if x1 <= x0 or y1 <= y0:
            return
        col = np.empty((y1 - y0, x1 - x0, 3), np.float32)
        col[:] = body
        draw(face.Canvas(col, x0, y0), 1.0)
        out = self.buf[sl[0].start + y0:sl[0].start + y1, sl[1].start + x0:sl[1].start + x1]
        self._compose(out, col, cover[y0:y1, x0:x1], alpha[y0:y1, x0:x1],
                      edge[y0:y1, x0:x1] if edge is not None else None, a, None)

    def _compose(self, out, col, cover, alpha, edge, a, over):
        """Colours (straight, 0 to 1) with their cover and alpha into out, the window's pixels: blue, green, red,
        alpha, premultiplied. Four channels at a time and no more passes than it needs."""
        if edge is not None:
            col += (np.asarray(self.theme()["line"], np.float32) - col) * edge[..., None]
        np.clip(col, 0.0, 1.0, out=col)
        h, w = cover.shape
        src = np.empty((h, w, 4), np.float32)
        np.multiply(col[..., ::-1], (cover * (255.0 * a))[..., None], out=src[..., :3])
        sa = alpha * a if a < 1 else alpha
        np.multiply(sa, 255.0, out=src[..., 3])
        if over is not None and over[1] > over[0]:
            r0, r1 = over
            src[r0:r1] += out[r0:r1] * (1.0 - sa[r0:r1])[..., None]
        src += 0.5
        np.minimum(src, 255.0, out=src)
        out[...] = src

    def _grow(self, sl):
        box = (sl[1].start, sl[0].start, sl[1].stop, sl[0].stop)
        self.drawn = _union(self.drawn, box)

    def _draw(self, now):
        """This frame into the window's picture. Only what the last frame covered is cleared, and only the box
        that holds both is given back for _push: the rest of the picture stays empty."""
        old, self.drawn = self.drawn, None
        if old is not None:
            self.buf[old[1]:old[3], old[0]:old[2]] = 0
        if self.alpha <= 0:
            return old
        k, m, th = self.k, self.m, self.theme()
        W, H = max(self.W.x, 10 * k), max(self.H.x, 10 * k)
        x0 = self._island_x(W)
        y0 = m
        # the words under it first, so the island's shadow falls over them
        caps = [(lay.cap, a) for lay, a in ((self.prev, self.prev_alpha), (self.layout, self.content))
                if lay is not None and lay.cap is not None]
        CW, CH = self.CW.x, self.CH.x
        cap_rows = None
        if caps and self.cap_alpha > 0.01 and CW > 12 * k and CH > 8 * k:
            cx0 = self._island_x(CW)
            cy0 = y0 + H + self.GAP * k
            r = min(CH / 2, 18 * k)
            sl, cover, alpha, edge = self._shape(cx0, CW, CH, r, cy0)
            ox, oy = cx0 - sl[1].start, cy0 - sl[0].start
            ca = self.alpha * self.cap_alpha
            # while the bar stands still with the same words, its picture is kept and only its bars drawn again
            one = caps[0][0] if len(caps) == 1 and caps[0][1] >= 0.999 and ca >= 0.999 else None
            key = (one.key, sl[0].start, sl[0].stop, sl[1].start, sl[1].stop, round(CW * 2), round(CH * 2),
                   self._theme_name(), self.border) if one is not None else None
            if key is not None and key == self.cap_key:
                self.buf[sl] = self.cap_picture
            elif key is not None:
                self._paint(sl, cover, alpha, edge, th["cap"],
                            [(lambda cv, a: one.draw(cv, ox, oy, CW, CH, a, now), 1.0)], ca)
                self.cap_key, self.cap_picture = key, self.buf[sl].copy()
            else:
                def both(cv, a, c):
                    c.draw(cv, ox, oy, CW, CH, a, now)
                    if c.live:
                        c.live(cv, ox, oy, CW, CH, a, now)
                self._paint(sl, cover, alpha, edge, th["cap"],
                            [(lambda cv, a, c=c: both(cv, a, c), c_a) for c, c_a in caps], ca)
                self.cap_key = self.cap_picture = None
            if key is not None and one.live:
                self._paint_part(sl, cover, alpha, edge, th["cap"], one.live_box(ox, oy, CW, CH),
                                 lambda cv, a: one.live(cv, ox, oy, CW, CH, a, now), ca)
            self._grow(sl)
            cap_rows = (sl[0].start, sl[0].stop)
        lay = self.layout or self.prev
        r = (lay.radius if lay is not None and lay.radius else min(H / 2, self.corner * k))
        r = min(r, H / 2)
        sl, cover, alpha, edge = self._shape(x0, W, H, r, y0)
        ox, oy = x0 - sl[1].start, y0 - sl[0].start
        items = [(lambda cv, a, L=L: L.draw(cv, ox, oy, W, H, a, now), la) for L, la in
                 ((self.prev, self.prev_alpha), (self.layout, self.content)) if L is not None]
        over = None
        if cap_rows is not None:  # where its shadow falls on the bar
            over = (max(sl[0].start, cap_rows[0]) - sl[0].start, min(sl[0].stop, cap_rows[1]) - sl[0].start)
        self._paint(sl, cover, alpha, edge, th["body"], items, self.alpha, over)
        self._grow(sl)
        self.island_rect = (x0, y0, x0 + W, y0 + H)
        return _union(old, self.drawn)

    # ------------------------------------------------------------------ pointing and clicking
    def _hover_poll(self):
        self.hover_job = None
        if not self.visible_window:
            return
        now = time.time()
        px, py = win.cursor_pos()
        x, y = px - self.origin.x, py - self.origin.y
        x0, y0, x1, y1 = getattr(self, "island_rect", (0, 0, 0, 0))
        near = x0 - 6 <= x <= x1 + 6 and y0 - 6 <= y <= y1 + 6
        lay = self.layout
        clickable = lay is not None and lay.kind in CLICKABLE
        if (px, py) != self.rest_pos:  # moved: Approve waits for it to rest again (_steady)
            self.rest_pos, self.rest_at = (px, py), now
        if near:
            self.away_at = now
            if not self.hover and now - self.hover_at > 0.15:
                self.hover = True
                self.dirty = True
                self._wake()
        else:
            self.hover_at = now
            if self.hover and now - self.away_at > 0.35:
                self.hover = False
                self.dirty = True
                self._wake()
        win.set_click_through(self.hwnd, not (self.hover and clickable))
        if self.hover and lay is not None and lay.kind == "idle":  # her eyes follow the mouse
            cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
            self.look_at = (max(-1.0, min(1.0, (x - cx) / max(1.0, (x1 - x0) / 2))),
                            max(-1.0, min(1.0, (y - cy) / max(1.0, (y1 - y0)))))
            self._wake()
        elif self.look_at is not None:
            self.look_at = None
            self._wake()
        if self.hover and lay is not None and lay.hot:
            hot = self._hot(x, y)
            try:
                self.top.configure(cursor="hand2" if hot else "arrow")
            except tk.TclError:
                pass
        self.hover_job = self.root.after(70, self._hover_poll)

    def _hot(self, x, y):
        lay = self.layout
        if lay is None:
            return None
        x0, y0 = self.island_rect[:2]
        for name, a, b, c, d in lay.hot:
            if x0 + a <= x <= x0 + c and y0 + b <= y <= y0 + d:
                return name
        return None

    def _click(self, right):
        px, py = win.cursor_pos()
        name = self._hot(px - self.origin.x, py - self.origin.y)
        lay = self.layout
        if lay is None:
            return
        if lay.kind == "notification" and self.popup is not None:
            if name == "open" and not right:
                self.runner.do("notifications", "open", self.popup.data)
            self.popup.until = 0.0  # gone, opened or not
            self.hover = False
            self.dirty = True
            self._wake()
        elif lay.kind == "media" and name and not right:
            self.runner.do("media", name)
        elif lay.kind == "card":
            self._press(lay.press.get(name), right)

    def _press(self, what, right):
        """A click on a card: a right click, or one on the card itself, keeps it open or lets it go; a button is its
        plugin's command, run on the plugins' thread. A careful one (Approve) only once the pointer has rested on it
        and she isn't doing a task in an app (_steady)."""
        if right or what is None or what[1] == "pin":
            plugin = what[0] if what is not None else None
            self.pinned = None if right or self.pinned else plugin
            self.dirty = True
            self._wake()
            return
        plugin, name, data, careful = what
        if careful and not self._steady(time.time()):
            print(f"  island: {name} not pressed, the pointer hadn't rested on it (or she's busy in an app)")
            return
        self.runner.do(plugin, name, data)

    def _steady(self, now):
        """True if the pointer's rested on the island REST seconds, where it is now, and she isn't doing a task in an
        app: her clicks are real ones (winplatform.click moves the pointer there and clicks 80 ms later), so they
        never press Approve, and neither does one landing while hers runs."""
        agent = sys.modules.get("agent")
        if agent is not None and (agent.ACT.locked() or agent.RUNNING.is_set()):
            return False
        return win.cursor_pos() == self.rest_pos and now - self.rest_at >= REST


def _clock(secs):
    secs = int(secs)
    h, rem = divmod(secs, 3600)
    return f"{h}:{rem // 60:02d}:{rem % 60:02d}" if h else f"{rem // 60}:{rem % 60:02d}"


def _resize(rgba, size):
    """A square picture made size px: whole blocks of pixels averaged, then the nearest pixel for the rest."""
    h, w = rgba.shape[:2]
    if h == size and w == size:
        return rgba.astype(np.float32)
    f = min(h, w) // size
    if f >= 2:  # area average first: the nearest pixels alone would shimmer
        rgba = rgba[:(h // f) * f, :(w // f) * f].reshape(h // f, f, w // f, f, 4).mean(axis=(1, 3))
        h, w = rgba.shape[:2]
    ys = np.minimum((np.arange(size) * h / size).astype(int), h - 1)
    xs = np.minimum((np.arange(size) * w / size).astype(int), w - 1)
    return rgba[ys][:, xs].astype(np.float32)
