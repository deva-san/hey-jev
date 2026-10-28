"""Typing to her instead of talking (28 October 2026, after Atticus's box): a small dark box, under her answer card or
near the top of the screen, that sends what you type to her as a turn of yours when you press Enter, as if you'd said
it with her name. Clicking your words on her card opens it with them in, to fix a word and send them again. Up and
Down go through what you typed before; Esc closes it; clicking away closes it too, keeping what you'd typed for the
next time it opens empty."""
import ctypes
import tkinter as tk

KEY = "#010203"  # the window's see-through colour: its square corners show what's under them
HINT = "Ask Jev anything"
DARK = {"body": "#262629", "rim": "#3d3d42", "text": "#f2f2f5", "muted": "#8d8d94"}
KEEP = 50  # how many of the things you typed Up and Down go back through


def hexed(rgb):
    """#rrggbb for an (r, g, b) of 0-1 floats, as the island's themes have them."""
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(c * 255))) for c in rgb)


def rounded(cv, x0, y0, x1, y1, r, **kw):
    """A rectangle with round corners on a Tk canvas: one smoothed polygon."""
    pts = (x0 + r, y0, x1 - r, y0, x1, y0, x1, y0 + r, x1, y1 - r, x1, y1, x1 - r, y1, x0 + r, y1, x0, y1,
           x0, y1 - r, x0, y0 + r, x0, y0)
    return cv.create_polygon(pts, smooth=True, **kw)


class AskBox:
    W, H, R, PAD = 380, 46, 18, 16  # logical px: its size, its corners, and the room inside its ends

    def __init__(self, root, send, colours=None, scale=1.0):
        """send(text) takes what you typed; colours() gives {"body", "rim", "text", "muted"} as #rrggbb (DARK if
        not); scale is the island's, so it's as big as her card."""
        self.root, self.send, self.colours, self.k = root, send, colours, scale
        self.top = self.entry = None
        self.past, self.at = [], None  # what you typed, newest last; where Up and Down are in it
        self.hinting, self.draft, self.ink = False, "", DARK

    @property
    def visible(self):
        return self.top is not None

    def open(self, text="", near=None):
        """Shows it with text in it (else what you'd left typed), the cursor at its end, and the keyboard on it.
        near is (x, y, w) in screen pixels of what it goes under, else it's near the top of the screen, in the
        middle."""
        text = " ".join(str(text or "").split()) or self.draft
        self.close(keep=False)
        c = self.ink = {**DARK, **(self.colours() if self.colours else {})}
        k = self.k
        W, H, pad = round(self.W * k), round(self.H * k), round(self.PAD * k)
        top = self.top = tk.Toplevel(self.root)
        top.withdraw()
        top.overrideredirect(True)
        top.attributes("-topmost", True)
        try:
            top.attributes("-transparentcolor", KEY)
        except tk.TclError:  # not on Windows: square corners, still a box
            pass
        top.configure(bg=KEY)
        if near:
            x, y = near[0] + (near[2] - W) // 2, near[1] + round(8 * k)
        else:
            x, y = (top.winfo_screenwidth() - W) // 2, round(96 * k)
        top.geometry(f"{W}x{H}+{int(x)}+{int(y)}")
        cv = tk.Canvas(top, width=W, height=H, bg=KEY, highlightthickness=0, bd=0)
        cv.pack()
        rounded(cv, 1, 1, W - 2, H - 2, self.R * k, fill=c["body"], outline=c["rim"])
        ex, ey = W - pad, H / 2  # Enter's arrow, drawn: not every font has the glyph
        cv.create_line(ex, ey - 5 * k, ex, ey + 3 * k, ex - 10 * k, ey + 3 * k, fill=c["muted"], width=max(1, 1.4 * k),
                       arrow="last", arrowshape=(4 * k, 4.5 * k, 3 * k), joinstyle="round")
        e = self.entry = tk.Entry(cv, bd=0, relief="flat", bg=c["body"], fg=c["text"], insertbackground=c["text"],
                                  highlightthickness=0, font=("Segoe UI", -round(14 * k)))  # px, as her card's
        cv.create_window(pad, H / 2, anchor="w", window=e, width=W - 2 * pad - round(22 * k))
        e.bind("<Return>", self._enter)
        e.bind("<KP_Enter>", self._enter)
        e.bind("<Escape>", lambda _: self.close(keep=False) or "break")
        e.bind("<Up>", lambda _: self._recall(-1))
        e.bind("<Down>", lambda _: self._recall(1))
        e.bind("<Key>", self._key)
        e.bind("<<Paste>>", lambda _: self._unhint())
        e.bind("<KeyRelease>", lambda _: self._rehint())
        e.bind("<FocusOut>", lambda _: top.after(150, self._focus_gone, top))
        self._set(text)
        top.deiconify()
        top.lift()
        top.after(20, self._focus)

    def close(self, keep=True):
        """Gone; what you'd typed is kept for the next time it opens empty, unless keep is False (Esc, or sent)."""
        top, entry = self.top, self.entry
        self.top = self.entry = self.at = None
        if top is None:
            return
        if entry is not None:
            try:
                self.draft = entry.get().strip() if keep and not self.hinting else ""
            except tk.TclError:
                pass
        try:
            top.destroy()
        except tk.TclError:
            pass

    def typed(self):
        """What's typed in it now, in one line: "" while it shows its hint."""
        if self.entry is None or self.hinting:
            return ""
        return " ".join(self.entry.get().split())

    def _focus(self):
        """The keyboard on it. Opened from right Alt, another app is in front and Windows keeps it there unless
        asked the way winplatform.bring_to_front asks."""
        if self.top is None:
            return
        try:
            import winplatform as win
            win.bring_to_front(ctypes.windll.user32.GetParent(self.top.winfo_id()))
        except Exception:  # not on Windows, or Windows said no: a click on it puts the keyboard there
            pass
        try:
            self.top.focus_force()
            self.entry.focus_set()
        except tk.TclError:
            pass

    def _focus_gone(self, top):
        """Clicked away, to another app or the window: it goes, keeping what you'd typed. Not a box opened since."""
        if self.top is None or self.top is not top:
            return
        try:
            now = self.root.focus_get()
        except (KeyError, tk.TclError):  # Tk can't name some of its own pop-ups
            now = None
        inside = now is not None and (str(now) == str(top) or str(now).startswith(str(top) + "."))
        if not inside:
            self.close()

    def _enter(self, _=None):
        text = self.typed()
        if not text:
            return "break"
        if not self.past or self.past[-1] != text:
            self.past = (self.past + [text])[-KEEP:]
        self.close(keep=False)
        self.send(text)
        return "break"

    def _recall(self, step):
        """Up: what you typed before that; Down: back towards now, and an empty box after the newest."""
        if not self.past or self.entry is None:
            return "break"
        at = len(self.past) if self.at is None else self.at
        self.at = max(0, min(len(self.past), at + step))
        self._set(self.past[self.at] if self.at < len(self.past) else "")
        return "break"

    def _set(self, text):
        e = self.entry
        self._unhint()
        e.delete(0, "end")
        if text:
            e.insert(0, text)
            e.icursor("end")
            e.xview_moveto(1.0)
        else:
            self._rehint()

    def _key(self, event):
        """A key that types something clears the hint first, so it isn't typed after it."""
        if self.hinting and ((event.char and event.char.isprintable()) or event.keysym in ("BackSpace", "Delete")):
            self._unhint()

    def _unhint(self):
        if self.hinting and self.entry is not None:
            self.hinting = False
            self.entry.delete(0, "end")
            self.entry.configure(fg=self.ink["text"])

    def _rehint(self):
        if not self.hinting and self.entry is not None and not self.entry.get():
            self.hinting = True
            self.entry.insert(0, HINT)
            self.entry.configure(fg=self.ink["muted"])
            self.entry.icursor(0)
