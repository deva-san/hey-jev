"""Her walkthrough, the first time Hey Jev opens (28 October 2026, the owner's ask, after Atticus's setup window): a
640 px window that slides from page to page with dots under it, Back and Skip All.

Meet Jev (her eyes, and the Right Alt key pressing itself), what she needs (her voice, her brain, the microphone and
her ears, each turning into a green tick as it's ready), Try it now (the key lights up as you hold it and goes green
when she hears you), a short tour with a scripted preview on each page, and You're all set, with things to say
floating out of her eyes. Settings > Walkthrough shows it again.

Nothing here acts on the PC but what you click: a key you paste, the model picker, Windows' microphone settings.
"""
import math
import os
import time
import tkinter as tk
import tkinter.font as tkfont

import providers
import settings
import winplatform as win
from secrets_store import get_secret, missing_secrets, save_secret

W, H = 640, 640
BG, TEXT, MUTED, LINE, CARD = "#ffffff", "#1b1b1b", "#6b6b70", "#e6e6ea", "#f5f5f7"
ACCENT, GREEN, ORANGE, BLUE_LIT = "#0067c0", "#1f9d55", "#e08a00", "#3d9bff"
NAV, GLOW = "#0f1116", "#5ee7f2"
# the things to say on the last page, as Atticus floats its own out of its orb
IDEAS = ("“Open Spotify”", "“Volume to 30”", "“What’s on my screen?”",
         "“Remember I use Chrome”", "“Set a timer for 10 minutes”", "“Transcribe”",
         "“When I say work mode, open Gmail”", "“Any new messages?”", "“Play lo-fi”")


def _ui():
    import assistant_ui  # its helpers (mix, ease, rounded), once the window that opens this has loaded it
    return assistant_ui


class Pill(tk.Canvas):
    """A rounded button drawn on a canvas, as Atticus's are: kind "primary" (blue), "secondary" (grey) or "quiet"
    (words only)."""

    def __init__(self, parent, text, command, kind="primary", font=None, bg=BG, px=lambda n: n):
        self.font = font or ("Segoe UI Semibold", 10)
        self.kind, self.command, self.px, self.hover, self.enabled = kind, command, px, False, True
        super().__init__(parent, highlightthickness=0, bd=0, bg=bg, cursor="hand2", takefocus=1)
        self.set_text(text)
        self.bind("<Enter>", lambda e: self._paint(True))
        self.bind("<Leave>", lambda e: self._paint(False))
        self.bind("<Button-1>", lambda e: self._press())
        self.bind("<Return>", lambda e: self._press())
        self.bind("<space>", lambda e: self._press())

    def set_text(self, text):
        self.text = text
        w = tkfont.Font(root=self, font=self.font).measure(text) + self.px(36 if self.kind != "quiet" else 8)
        self.configure(width=w, height=self.px(34))
        self._paint(self.hover)

    def _paint(self, hover):
        self.hover = hover
        ui = _ui()
        self.delete("all")
        w, h = int(self.cget("width")), int(self.cget("height"))
        if self.kind == "primary":
            fill, fg = (ui.mix(ACCENT, "#000000", 0.12) if hover else ACCENT), "#ffffff"
        elif self.kind == "secondary":
            fill, fg = ("#e4e4e8" if hover else "#efeff2"), TEXT
        else:
            fill, fg = None, (TEXT if hover else MUTED)
        if not self.enabled:
            fill, fg = (fill and "#d5d5da"), "#9a9aa0"
        if fill:
            self.create_polygon(ui.rounded(1, 1, w - 1, h - 1, h / 2), smooth=True, fill=fill, outline="")
        self.create_text(w / 2, h / 2, text=self.text, font=self.font, fill=fg)

    def _press(self):
        if self.enabled and self.command:
            self.command()


class Eyes(tk.Canvas):
    """Her face on a little black island, as at the top of the screen: two glowing eyes that blink now and then and
    glance about. big: the welcome page's."""

    def __init__(self, parent, app, w, h, bg=BG):
        super().__init__(parent, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
        self.app, self.w, self.h = app, w, h
        self.open_, self.look, self.tint = 1.0, 0.0, GLOW
        self.draw()
        self.after(1800, self._blink)
        self.after(3200, self._glance)

    def draw(self):
        ui = _ui()
        self.delete("all")
        w, h = self.w, self.h
        r = h / 2
        self.create_polygon(ui.rounded(2, 2, w - 2, h - 2, r - 2), smooth=True, fill=NAV, outline="")
        size = h * 0.34
        for side in (-1, 1):
            cx = w / 2 + side * size * 1.05 + self.look * size * 0.35
            eh = max(2.0, size * self.open_)
            ew = size * 0.58
            glow = [(size * g, ui.mix(NAV, self.tint, m)) for g, m in ((0.5, 0.05), (0.36, 0.09), (0.25, 0.15),
                                                                       (0.15, 0.24), (0.07, 0.38))]
            for grow, colour in glow + [(0.0, "#f7f7f9")]:
                self.create_polygon(ui.rounded(cx - ew / 2 - grow, h / 2 - eh / 2 - grow, cx + ew / 2 + grow,
                                               h / 2 + eh / 2 + grow, ew / 2 + grow), smooth=True, fill=colour,
                                    outline="")

    def _blink(self):
        if not self.winfo_exists():
            return

        def step(t):
            self.open_ = abs(1 - 2 * t)
            self.draw()
        self.app.animate(f"ob blink {id(self)}", 200, step,
                         lambda: self.after(2600 + int(3400 * abs(math.sin(time.time()))), self._blink))

    def _glance(self):
        if not self.winfo_exists():
            return
        start, end = self.look, (-0.8, 0.0, 0.7, 0.0)[int(time.time()) % 4]

        def step(t):
            self.look = start + (end - start) * t
            self.draw()
        self.app.animate(f"ob look {id(self)}", 320, step, lambda: self.after(2200, self._glance))


class Keycap(tk.Canvas):
    """A key on the keyboard, as Atticus draws its shortcut: up, pressed (down a little), lit (blue, held) or done
    (green, she heard you)."""

    def __init__(self, parent, label, app, big=False, bg=BG):
        self.app, self.label, self.big = app, label, big
        self.font = ("Segoe UI Semibold", 20 if big else 11)
        tw = tkfont.Font(root=parent, font=self.font).measure(label)
        w, h = tw + app.px(56 if big else 34), app.px(86 if big else 46)
        super().__init__(parent, width=w, height=h, bg=bg, highlightthickness=0, bd=0)
        self.w, self.h, self.state, self.down = w, h, "up", 0.0
        self.draw()

    def draw(self):
        ui = _ui()
        self.delete("all")
        w, h, px = self.w, self.h, self.app.px
        sink = self.down * px(3)
        r = px(14 if self.big else 9)
        shade = px(5 if self.big else 3) * (1 - self.down * 0.7)
        face, fg, edge = "#ffffff", MUTED if not self.big else TEXT, LINE
        if self.state == "lit":
            face, fg, edge = BLUE_LIT, "#ffffff", ui.mix(BLUE_LIT, "#000000", 0.15)
        elif self.state == "done":
            face, fg, edge = GREEN, "#ffffff", ui.mix(GREEN, "#000000", 0.15)
        self.create_polygon(ui.rounded(2, 2 + shade + sink, w - 2, h - 2, r), smooth=True, fill="#dcdce0", outline="")
        self.create_polygon(ui.rounded(2, 2 + sink, w - 2, h - 2 - shade + sink * 0.2, r), smooth=True, fill=face,
                            outline=edge)
        self.create_text(w / 2, (h - shade) / 2 + sink, text=self.label, font=self.font, fill=fg)

    def press(self, down):
        start, end = self.down, 1.0 if down else 0.0

        def step(t):
            self.down = start + (end - start) * t
            self.draw()
        self.app.animate(f"ob key {id(self)}", 130, step)

    def set_state(self, state):
        if state != self.state:
            self.state = state
            self.draw()


class Walkthrough:
    """The setup window. app: the AssistantWindow, for its sizes, fonts, animations, model picker and worker."""

    def __init__(self, app):
        self.app, px = app, app.px
        top = self.top = tk.Toplevel(app.root, bg=BG)
        top.title("Set up Hey Jev")
        top.transient(app.root)
        top.resizable(False, False)
        w, h = px(W), px(H)
        x = app.root.winfo_rootx() + (app.root.winfo_width() - w) // 2
        y = app.root.winfo_rooty() + max(0, (app.root.winfo_height() - h) // 2)
        top.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        top.protocol("WM_DELETE_WINDOW", self.finish)
        top.bind("<Escape>", lambda e: self.finish())
        self.f_head = ("Segoe UI Semibold", 22)
        self.f_sub = ("Segoe UI", 11)
        self.f_kick = ("Segoe UI Semibold", 9)
        self.f_body, self.f_bold, self.f_small = app.f_body, app.f_bold, app.f_small
        bar = tk.Frame(top, bg=BG, height=px(44))
        bar.pack(fill="x")
        bar.pack_propagate(False)
        self.back = Pill(bar, "‹  Back", self.go_back, "quiet", self.f_body, px=px)
        self.skip_all = Pill(bar, "Skip All", lambda: self.go("done"), "quiet", self.f_body, px=px)
        self.skip_all.pack(side="right", padx=px(14))
        self.area = tk.Frame(top, bg=BG)
        self.area.pack(fill="both", expand=True)
        self.dots = tk.Canvas(top, height=px(30), bg=BG, highlightthickness=0, bd=0)
        self.dots.pack(fill="x", pady=(0, px(14)))
        self.order = ["welcome", "ready", "try", "pc", "dictate", "screen", "learn", "phone", "done"]
        self.pages, self.current, self.dot_w = {}, None, {name: px(6) for name in self.order}
        self.ticks = []  # what moves on the page in front: its previews, its key, its list
        self.ready_rows, self.heard = {}, False
        self.go("welcome", slide=False)
        self._poll()

    # ------------------------------------------------------------------ pages
    def _page(self, name):
        if name not in self.pages:
            self.pages[name] = getattr(self, f"_build_{name}")()
        return self.pages[name]

    def go(self, name, slide=True, back=False):
        if name == self.current:
            return
        old = self.pages.get(self.current)
        new = self._page(name)
        self.current = name
        dx = self.app.px(40) * (-1 if back else 1)
        new.place(x=dx if slide else 0, y=0, relwidth=1, relheight=1)
        new.tkraise()
        if slide:
            self.app.animate("ob in", 520, lambda t: new.place_configure(x=round(dx * (1 - t))))
        if old is not None:
            if slide:
                self.app.animate("ob out", 340, lambda t: old.place_configure(x=round(-dx * t)),
                                 lambda: old.place_forget() if self.current != self._name_of(old) else None)
            else:
                old.place_forget()
        if name == "welcome":
            self.back.pack_forget()
        elif not self.back.winfo_ismapped():
            self.back.pack(side="left", padx=self.app.px(10))
        if name == "done":
            self.skip_all.pack_forget()
        elif not self.skip_all.winfo_ismapped():
            self.skip_all.pack(side="right", padx=self.app.px(14))
        enter = getattr(self, f"_enter_{name}", None)
        if enter:
            enter()
        self._dots(slide)

    def _name_of(self, frame):
        return next((n for n, f in self.pages.items() if f is frame), None)

    def go_back(self):
        i = self.order.index(self.current)
        if i > 0:
            self.go(self.order[i - 1], back=True)

    def next(self):
        i = self.order.index(self.current)
        self.go(self.order[min(len(self.order) - 1, i + 1)])

    def _dots(self, slide):
        """The dots under the pages: 6 px each, the page in front's stretched to 18 px."""
        px = self.app.px
        start = dict(self.dot_w)
        end = {name: px(18) if name == self.current else px(6) for name in self.order}

        def draw(t):
            ui = _ui()
            self.dots.delete("all")
            ws = {n: start[n] + (end[n] - start[n]) * t for n in self.order}
            total = sum(ws.values()) + px(8) * (len(self.order) - 1)
            x = (self.dots.winfo_width() or px(W)) / 2 - total / 2
            for n in self.order:
                on = n == self.current
                self.dots.create_polygon(ui.rounded(x, px(12), x + ws[n], px(18), px(3)), smooth=True,
                                         fill=ui.mix("#d0d0d6", ACCENT, t if on else 0.0) if on else "#d0d0d6",
                                         outline="")
                x += ws[n] + px(8)
            self.dot_w = ws
        if slide:
            self.app.animate("ob dots", 450, draw)
        else:
            self.top.after(50, lambda: draw(1.0))

    def _frame(self):
        f = tk.Frame(self.area, bg=BG)
        inner = tk.Frame(f, bg=BG)
        inner.pack(expand=True)
        f.inner = inner
        return f

    def _heading(self, parent, kicker, head, sub, wrap=500):
        px = self.app.px
        if kicker:
            tk.Label(parent, text=kicker.upper(), font=self.f_kick, fg=ACCENT, bg=BG).pack(pady=(0, px(6)))
        tk.Label(parent, text=head, font=self.f_head, fg=TEXT, bg=BG).pack()
        if sub:
            tk.Label(parent, text=sub, font=self.f_sub, fg=MUTED, bg=BG, wraplength=px(wrap),
                     justify="center").pack(pady=(px(6), 0))

    def _buttons(self, parent, primary, command, secondary=None, second_command=None):
        px = self.app.px
        row = tk.Frame(parent, bg=BG)
        row.pack(pady=(px(22), 0))
        if secondary:
            b = Pill(row, secondary, second_command or self.next, "secondary", self.f_bold, px=px)
            b.pack(side="left", padx=(0, px(10)))
        main = Pill(row, primary, command, "primary", self.f_bold, px=px)
        main.pack(side="left")
        return main

    # ------------------------------------------------------------------ 1: Meet Jev
    def _mode_words(self):
        return ("Say “Hey Jev” and what you need. Your PC does the rest." if settings.get("mode") == "wake"
                else "Hold Right Alt, say what you need, let go. Your PC does the rest.")

    def _build_welcome(self):
        px = self.app.px
        f = self._frame()
        Eyes(f.inner, self.app, px(150), px(76)).pack(pady=(0, px(26)))
        self._heading(f.inner, "", "Meet Jev", self._mode_words())
        keys = tk.Frame(f.inner, bg=BG)
        keys.pack(pady=(px(22), 0))
        self.welcome_key = Keycap(keys, "“Hey Jev”" if settings.get("mode") == "wake" else "Right Alt", self.app)
        self.welcome_key.pack()
        self._buttons(f.inner, "Get Started", self.next)
        self._act_out()
        return f

    def _act_out(self):
        """The key presses itself, holds and lets go, as Atticus's keycaps act out its shortcut, every 3.6 s."""
        if not self.top.winfo_exists():
            return
        if self.current == "welcome":
            self.welcome_key.press(True)
            self.top.after(900, lambda: self.top.winfo_exists() and self.welcome_key.press(False))
        self.top.after(3600, self._act_out)

    # ------------------------------------------------------------------ 2: what she needs
    def _build_ready(self):
        px = self.app.px
        f = self._frame()
        self._heading(f.inner, "", "Give Jev what she needs",
                      "A few things she uses to hear you, think and talk. You can change them any time.")
        box = tk.Frame(f.inner, bg=CARD, padx=px(4), pady=px(4), highlightthickness=1, highlightbackground=LINE)
        box.pack(pady=(px(18), 0))
        self.rows_box = box
        rows = (("voice", "", "#ff9f0a", "Her voice", "Fish Audio speaks her replies: a free key."),
                ("brain", "", "#7c5cff", "Her brain", "The answer model that works out what you asked."),
                ("mic", "", "#ff375f", "Microphone", "She listens only while you hold Right Alt or say Jev."),
                ("ears", "", "#0a84ff", "Her ears", "Speech-to-text, on this PC. Set up once, at the start."))
        for i, (key, icon, colour, name, why) in enumerate(rows):
            self.ready_rows[key] = self._ready_row(box, i, icon, colour, name, why)
        self.ready_count = tk.Label(f.inner, text="", font=self.f_small, fg=MUTED, bg=BG)
        self.ready_count.pack(pady=(px(10), 0))
        self.ready_next = self._buttons(f.inner, "Skip for Now", self.next)
        return f

    def _ready_row(self, box, i, icon, colour, name, why):
        px = self.app.px
        row = tk.Frame(box, bg=CARD, padx=px(10), pady=px(8))
        tile = tk.Label(row, text=icon, font=(self.app.f_icon[0], 13), fg="#ffffff", bg=colour, width=2,
                        pady=px(3))
        tile.grid(row=0, column=0, rowspan=2, padx=(0, px(10)))
        tk.Label(row, text=name, font=self.f_bold, fg=TEXT, bg=CARD, anchor="w").grid(row=0, column=1, sticky="w")
        sub = tk.Label(row, text=why, font=self.f_small, fg=MUTED, bg=CARD, anchor="w", width=46, justify="left")
        sub.grid(row=1, column=1, sticky="w")
        side = tk.Frame(row, bg=CARD, width=px(150))
        side.grid(row=0, column=2, rowspan=2, sticky="e", padx=(px(10), 0))
        row.grid_columnconfigure(1, weight=1)
        row.side, row.sub, row.why, row.done, row.i = side, sub, why, None, i
        return row

    def _enter_ready(self):
        for i, row in enumerate(self.ready_rows.values()):  # in one after another, 60 ms apart
            row.grid_forget()
            self.top.after(60 * i, lambda r=row, i=i: r.grid(row=i, column=0, sticky="ew") if self.top.winfo_exists()
                           else None)
        self._check_ready(force=True)

    def _ready(self):
        """What's ready now: {row: (ready, what to say)}."""
        model = settings.get("llm_model") or ""
        p, model_id = providers.split(model)
        voice = str(settings.get("voice") or "")
        status = self.app.status.cget("text")
        try:
            mics = bool(win.input_devices())
        except Exception:
            mics = False
        return {
            "voice": (bool(get_secret("FISH_AUDIO_API_KEY")) or voice.startswith(("pocket:", "onecore:")), ""),
            "brain": (providers.ready(p), f"Thinks with {model_id} on {p.name}"),
            "mic": (mics, ""),
            "ears": (self.app.worker_started and status not in ("Starting", "Something went wrong"),
                     "Getting ready…" if self.app.worker_started or not missing_secrets() else
                     "Waiting for her voice key"),
        }

    def _check_ready(self, force=False):
        if "ready" not in self.pages:
            return
        state = self._ready()
        for key, row in self.ready_rows.items():
            ok, note = state[key]
            if row.done is ok and not force:
                continue
            was, row.done = row.done, ok
            for child in row.side.winfo_children():
                child.destroy()
            if ok:
                self._tick(row.side, pop=was is False)
                if key == "brain":
                    row.sub.configure(text=note)
            else:
                row.sub.configure(text=row.why)
                self._fix(key, row, note)
        n = sum(ok for ok, _ in state.values())
        all_ok = n == len(state)
        self.ready_count.configure(text="All set" if all_ok else f"{n} of {len(state)} ready",
                                   fg=GREEN if all_ok else MUTED)
        self.ready_next.set_text("Continue" if all_ok else "Skip for Now")

    def _fix(self, key, row, note):
        """What a row that isn't ready offers: a key to paste, the model picker, Windows' microphone settings."""
        px = self.app.px
        if key == "voice":
            entry = tk.Entry(row.side, show="•", width=14, font=self.f_small, relief="solid", bd=1)
            entry.pack(side="left")
            entry.bind("<Return>", lambda e: self._save_voice(entry))
            Pill(row.side, "Save", lambda: self._save_voice(entry), "primary", self.f_small, CARD, px).pack(
                side="left", padx=(px(6), 0))
        elif key == "brain":
            Pill(row.side, "Choose", self.app.open_model_picker, "primary", self.f_small, CARD, px).pack()
        elif key == "mic":
            Pill(row.side, "Open Settings", lambda: os.startfile("ms-settings:privacy-microphone"), "primary",
                 self.f_small, CARD, px).pack()
        else:
            tk.Label(row.side, text=note, font=self.f_small, fg=MUTED, bg=CARD).pack()

    def _save_voice(self, entry):
        value = entry.get().strip()
        if not value:
            return
        try:
            save_secret("FISH_AUDIO_API_KEY", value)
        except Exception as exc:
            self.ready_count.configure(text=str(exc), fg="#c42b1c")
            return
        if "FISH_AUDIO_API_KEY" in getattr(self.app, "key_fields", {}):
            self.app.key_fields["FISH_AUDIO_API_KEY"].set_hint("Already saved")
        if not missing_secrets():
            self.app._start_worker()  # her ears load now: the row ticks once she's ready
        self._check_ready()

    def _tick(self, parent, pop=True):
        """A green tick in a circle that pops in, its stroke drawn on, as Atticus's do."""
        px = self.app.px
        s = px(24)
        c = tk.Canvas(parent, width=s, height=s, bg=CARD, highlightthickness=0, bd=0)
        c.pack()

        def step(t):
            if not c.winfo_exists():
                return
            c.delete("all")
            grow = min(1.0, t * 1.6)
            r = s / 2 * (grow + 0.12 * math.sin(math.pi * min(1.0, grow)))  # a little past, then back: a spring
            c.create_oval(s / 2 - r, s / 2 - r, s / 2 + r, s / 2 + r, fill=GREEN, outline="")
            draw = max(0.0, (t - 0.45) / 0.55)
            pts = [(s * 0.29, s * 0.52), (s * 0.44, s * 0.66), (s * 0.72, s * 0.37)]
            if draw > 0:
                first = min(1.0, draw * 2)
                x1 = pts[0][0] + (pts[1][0] - pts[0][0]) * first
                y1 = pts[0][1] + (pts[1][1] - pts[0][1]) * first
                c.create_line(pts[0][0], pts[0][1], x1, y1, fill="#ffffff", width=max(2, px(2)), capstyle="round")
                if draw > 0.5:
                    second = (draw - 0.5) * 2
                    x2 = pts[1][0] + (pts[2][0] - pts[1][0]) * second
                    y2 = pts[1][1] + (pts[2][1] - pts[1][1]) * second
                    c.create_line(pts[1][0], pts[1][1], x2, y2, fill="#ffffff", width=max(2, px(2)),
                                  capstyle="round")
        if pop:
            self.app.animate(f"ob tick {id(c)}", 600, step)
        else:
            step(1.0)

    # ------------------------------------------------------------------ 3: Try it now
    def _build_try(self):
        px = self.app.px
        f = self._frame()
        wake = settings.get("mode") == "wake"
        self._heading(f.inner, "", "Try it now",
                      "Say her name anywhere, then what you need." if wake else
                      "Hold Right Alt anywhere, say what you need, then let go. Try one now.")
        self.try_key = Keycap(f.inner, "Hey Jev" if wake else "Right Alt", self.app, big=True)
        self.try_key.pack(pady=(px(30), px(18)))
        self.try_hint = tk.Label(f.inner, text="", font=self.f_sub, fg=MUTED, bg=BG)
        self.try_hint.pack()
        self.try_next = self._buttons(f.inner, "Skip", self.next)
        return f

    def _enter_try(self):
        self._try_hint()

    def _try_hint(self):
        if self.heard:
            return
        if not self.app.worker_started or self.app.status.cget("text") == "Starting":
            self.try_hint.configure(text="She’s still getting ready. Give her a moment…", fg=MUTED)
        else:
            self.try_hint.configure(text="Say “Hey Jev, open Calculator”." if settings.get("mode") == "wake"
                                    else "Hold Right Alt and say “open Calculator”.", fg=MUTED)

    def status(self, state, detail=""):
        """From the window, as she goes: the key lights up while she listens and goes green once she's heard you."""
        if self.heard or "try" not in self.pages:
            return
        if state in ("Listening", "Still listening"):
            self.try_key.set_state("lit")
            self.try_key.press(True)
        elif state in ("Heard", "Thinking", "Doing it", "Looking", "Speaking") and self.try_key.state == "lit":
            self.heard = True
            self.try_key.press(False)
            self.try_key.set_state("done")
            self.try_hint.configure(text="That’s it. Jev is on it.", fg=GREEN)
            self.try_next.set_text("Next")
        elif state == "Ready" and self.try_key.state == "lit":
            self.try_key.press(False)
            self.try_key.set_state("up")

    # ------------------------------------------------------------------ 4-8: the tour
    def _tour(self, kicker, head, sub, chips, preview, note=""):
        px = self.app.px
        f = self._frame()
        self._heading(f.inner, kicker, head, sub)
        stage = tk.Canvas(f.inner, width=px(460), height=px(190), bg=CARD, highlightthickness=0, bd=0)
        stage.pack(pady=(px(18), px(12)))
        f.stage, f.preview, f.started = stage, preview, None
        row = tk.Frame(f.inner, bg=BG)
        row.pack()
        for chip in chips:
            tk.Label(row, text=chip, font=self.f_small, fg=TEXT, bg="#efeff2", padx=px(9), pady=px(3)).pack(
                side="left", padx=px(3))
        if note:
            tk.Label(f.inner, text=note, font=self.f_small, fg=MUTED, bg=BG).pack(pady=(px(10), 0))
        self._buttons(f.inner, "Next", self.next, "Skip", lambda: self.go("done"))
        return f

    def _build_pc(self):
        return self._tour("Your whole PC", "Say it. It’s done.",
                          "Open apps, play music, set timers and change settings, all by voice. Ask for something new "
                          "once, and the next time it’s instant.",
                          ("“Open Spotify”", "“Volume to 30”", "“Dark mode on”",
                           "“A 10 minute timer”"), self._preview_card,
                          "Full access is on: she sends and installs what you ask without asking first."
                          if settings.get("full_access") else
                          "She asks before she sends a message, deletes or installs anything.")

    def _build_dictate(self):
        return self._tour("Dictate anywhere", "Talk instead of typing",
                          "Say “Hey Jev, transcribe”, talk, then “stop transcribing”. She tidies it "
                          "up and pastes it where your cursor is.",
                          ("Fillers go", "“Scratch that”", "“Actually…”"), self._preview_dictate)

    def _build_screen(self):
        return self._tour("She sees your screen", "Ask about what’s in front of you",
                          "“What’s on my screen?”, “click the second video”, or “what is "
                          "this?” with the pointer on it. Only when you ask.",
                          ("“What’s this?”", "“Click the second one”",
                           "“Summarise this page”"), self._preview_screen)

    def _build_learn(self):
        return self._tour("She remembers", "Teach her once",
                          "“Remember my website is careerid.in.” “When I say work mode, open Gmail and "
                          "set the volume to 30.” She keeps it on this PC.",
                          ("“Remember…”", "“When I say…”", "“Forget that”"),
                          self._preview_learn)

    def _build_phone(self):
        return self._tour("On your phone", "Jev on Telegram",
                          "Pair your own bot in Settings › Phone, then message her from anywhere. Only you can "
                          "talk to her there.",
                          ("“What’s on my screen?”", "“Any new messages?”"),
                          self._preview_phone)

    # the previews: scripted loops, drawn only while their page is in front
    def _preview_card(self, c, t):
        """Her island at the top opens into the answer card: your words, what she's doing, her answer."""
        ui, px = _ui(), self.app.px
        w, h = int(c.cget("width")), int(c.cget("height"))
        t %= 6.0
        grow = ui.ease(min(1.0, max(0.0, (t - 0.5) / 0.6)))
        cw, ch = px(120) + (px(330) - px(120)) * grow, px(36) + (px(158) - px(36)) * grow
        x0, y0 = w / 2 - cw / 2, px(14)
        c.create_polygon(ui.rounded(x0, y0, x0 + cw, y0 + ch, min(ch / 2, px(16))), smooth=True, fill=NAV,
                         outline="")
        ex = x0 + (px(26) if grow > 0.5 else cw / 2 - px(10))
        for dx in (0, px(14)):
            c.create_polygon(ui.rounded(ex + dx - px(3), y0 + px(11), ex + dx + px(3), y0 + px(25), px(3)),
                             smooth=True, fill="#f7f7f9", outline="")
        if grow < 1:
            return
        status = "Listening" if t < 2.2 else "Opening YouTube" if t < 3.0 else ""
        if status:
            c.create_text(x0 + px(56), y0 + px(18), text=status, anchor="w", font=self.f_small, fill="#a8a8ae")
        said = "Play lo-fi on YouTube".split()
        n = min(len(said), int((t - 1.1) / 0.22) + 1) if t > 1.1 else 0
        if n:
            words = " ".join(said[:n])
            tw = tkfont.Font(root=c, font=self.f_small).measure(words)
            bx1, by0 = x0 + cw - px(14), y0 + px(44)
            c.create_polygon(ui.rounded(bx1 - tw - px(20), by0, bx1, by0 + px(28), px(12)), smooth=True,
                             fill="#2a2d35", outline="")
            c.create_text(bx1 - px(10), by0 + px(14), text=words, anchor="e", font=self.f_small, fill="#f0f0f3")
        if t > 3.0:
            e = ui.ease(min(1.0, (t - 3.0) / 0.4))
            c.create_text(x0 + px(16), y0 + px(98) + (1 - e) * px(5), text="Playing lo-fi on YouTube.", anchor="w",
                          font=self.f_body, fill=ui.mix(NAV, "#ffffff", e))
            c.create_text(x0 + px(16), y0 + px(138), text="1.42 s", anchor="w", font=("Segoe UI", 8),
                          fill=ui.mix(NAV, "#8e8e93", e))
            c.create_text(x0 + cw - px(16), y0 + px(138), text="Try again", anchor="e", font=("Segoe UI", 8),
                          fill=ui.mix(NAV, "#8e8e93", e))

    def _preview_dictate(self, c, t):
        """Your words as you say them, the fillers struck out, then the tidy sentence in a message."""
        ui, px = _ui(), self.app.px
        w = int(c.cget("width"))
        t %= 7.0
        said = [("so", True), ("um", False), ("I", True), ("think", True), ("we", True), ("should", True),
                ("uh", False), ("meet", True), ("on", True), ("Friday", True)]
        n = min(len(said), int(t / 0.21))
        font = tkfont.Font(root=c, font=self.f_body)
        x, y = px(24), px(40)
        c.create_text(px(24), px(18), text="Dictating…", anchor="w", font=self.f_small, fill=ACCENT)
        for word, kept in said[:n]:
            ww = font.measure(word)
            c.create_text(x, y, text=word, anchor="w", font=self.f_body, fill=TEXT if kept else "#a0a0a6")
            if not kept:
                c.create_line(x, y + 1, x + ww, y + 1, fill="#a0a0a6", width=max(1, px(1)))
            x += ww + font.measure(" ")
        if t > 3.0:
            e = ui.ease(min(1.0, (t - 3.0) / 0.5))
            top = px(80) + (1 - e) * px(8)
            c.create_polygon(ui.rounded(px(24), top, w - px(24), top + px(84), px(12)), smooth=True, fill="#ffffff",
                             outline=LINE)
            c.create_text(px(40), top + px(20), text="To: Sam", anchor="w", font=self.f_small, fill=MUTED)
            c.create_text(px(40), top + px(50), text="So I think we should meet on Friday.", anchor="w",
                          font=self.f_body, fill=ui.mix("#ffffff", TEXT, e))

    def _preview_screen(self, c, t):
        """A page with three videos, and a ring round the second, where she's looking."""
        ui, px = _ui(), self.app.px
        w = int(c.cget("width"))
        t %= 5.0
        c.create_polygon(ui.rounded(px(30), px(16), w - px(30), px(178), px(10)), smooth=True, fill="#ffffff",
                         outline=LINE)
        for i, dot in enumerate(("#ff5f57", "#febc2e", "#28c840")):
            c.create_oval(px(44) + i * px(12), px(26), px(51) + i * px(12), px(33), fill=dot, outline="")
        tw = (w - px(60) - px(40)) / 3
        for i in range(3):
            x0 = px(50) + i * (tw + px(10))
            c.create_polygon(ui.rounded(x0, px(50), x0 + tw, px(120), px(6)), smooth=True,
                             fill=("#c9d6ff", "#ffd3c9", "#d1f2d9")[i], outline="")
            c.create_rectangle(x0, px(128), x0 + tw * 0.8, px(134), fill="#e3e3e8", outline="")
            c.create_rectangle(x0, px(140), x0 + tw * 0.5, px(146), fill="#ececf0", outline="")
        if t > 1.0:
            p = ((t - 1.0) % 1.4) / 1.4
            x0 = px(50) + (tw + px(10))
            grow = px(4) + px(8) * p
            c.create_polygon(ui.rounded(x0 - grow, px(50) - grow, x0 + tw + grow, px(120) + grow, px(8) + grow),
                             smooth=True, fill="", outline=ui.mix(ACCENT, "#ffffff", p), width=max(2, px(2)))
            c.create_text(w / 2, px(165), text="“Click the second video”", font=self.f_small, fill=MUTED)

    def _preview_learn(self, c, t):
        """"Work mode" said once, its steps ticked off, then kept for next time."""
        ui, px = _ui(), self.app.px
        w = int(c.cget("width"))
        t %= 6.0
        c.create_polygon(ui.rounded(w / 2 - px(70), px(18), w / 2 + px(70), px(48), px(15)), smooth=True,
                         fill="#2a2d35", outline="")
        c.create_text(w / 2, px(33), text="“Work mode”", font=self.f_bold, fill="#ffffff")
        for i, step in enumerate(("Gmail, in your Work profile", "Volume to 30%", "Focus on")):
            if t > 1.0 + i * 0.6:
                e = ui.ease(min(1.0, (t - 1.0 - i * 0.6) / 0.35))
                y = px(70) + i * px(28) + (1 - e) * px(5)
                c.create_oval(w / 2 - px(110), y - px(7), w / 2 - px(96), y + px(7), fill=GREEN, outline="")
                c.create_text(w / 2 - px(86), y, text=step, anchor="w", font=self.f_body, fill=ui.mix(CARD, TEXT, e))
        if t > 3.2:
            e = ui.ease(min(1.0, (t - 3.2) / 0.4))
            c.create_text(w / 2, px(168), text="Learned. Next time it’s instant.", font=self.f_small,
                          fill=ui.mix(CARD, GREEN, e))

    def _preview_phone(self, c, t):
        """A phone, your message to her and her answer."""
        ui, px = _ui(), self.app.px
        w = int(c.cget("width"))
        t %= 5.5
        c.create_polygon(ui.rounded(w / 2 - px(80), px(8), w / 2 + px(80), px(182), px(18)), smooth=True,
                         fill="#ffffff", outline=LINE, width=2)
        c.create_text(w / 2, px(24), text="Jev", font=self.f_bold, fill=TEXT)
        if t > 0.6:
            e = ui.ease(min(1.0, (t - 0.6) / 0.3))
            c.create_polygon(ui.rounded(w / 2 - px(10), px(46), w / 2 + px(70), px(74), px(10)), smooth=True,
                             fill=ui.mix("#ffffff", "#2aabee", e), outline="")
            c.create_text(w / 2 + px(30), px(60), text="What’s on my screen?", font=("Segoe UI", 8),
                          fill=ui.mix("#ffffff", "#ffffff", e))
        if t > 1.8:
            e = ui.ease(min(1.0, (t - 1.8) / 0.3))
            c.create_polygon(ui.rounded(w / 2 - px(70), px(84), w / 2 + px(30), px(126), px(10)), smooth=True,
                             fill=ui.mix("#ffffff", "#efeff2", e), outline="")
            c.create_text(w / 2 - px(62), px(105), text="Your report in Word,\npage 3 of 5.", anchor="w",
                          font=("Segoe UI", 8), fill=ui.mix("#ffffff", TEXT, e))

    # ------------------------------------------------------------------ 9: You're all set
    def _build_done(self):
        px = self.app.px
        f = self._frame()
        self.done_pill = tk.Label(f.inner, text="", font=self.f_small, bg=BG, padx=px(10), pady=px(3))
        self.done_pill.pack(pady=(0, px(10)))
        self.bloom = tk.Canvas(f.inner, width=px(520), height=px(250), bg=BG, highlightthickness=0, bd=0)
        self.bloom.pack()
        self.bloom.started = None
        self.done_head = tk.Label(f.inner, text="Go use Jev. Be great.", font=self.f_head, fg=TEXT, bg=BG)
        self.done_head.pack(pady=(px(6), 0))
        self.done_sub = tk.Label(f.inner, text="", font=self.f_sub, fg=MUTED, bg=BG, wraplength=px(480))
        self.done_sub.pack(pady=(px(6), 0))
        self.done_button = self._buttons(f.inner, "Start Using Jev", self.finish)
        return f

    def _enter_done(self):
        state = self._ready()
        missing = [name for key, name in (("voice", "her voice"), ("brain", "her brain"), ("mic", "a microphone"))
                   if not state[key][0]]
        if missing:
            self.done_pill.configure(text="●  Setup isn’t finished yet", fg=ORANGE, bg="#fff4e0")
            self.done_sub.configure(text=f"Still needed: {', '.join(missing)}. You can finish it later in Keys and "
                                         f"Settings.")
            self.done_button.set_text("Finish Setup Later")
        else:
            self.done_pill.configure(text="✔  You’re all set", fg=GREEN, bg="#e3f6ea")
            self.done_sub.configure(text="Say “Hey Jev” anywhere and try one." if settings.get("mode") ==
                                    "wake" else "Hold Right Alt anywhere and try one.")
            self.done_button.set_text("Start Using Jev")
        self.bloom.started = time.time()

    def _draw_bloom(self, now):
        """Her eyes in the middle, and things to say blooming out of them to their places, then bobbing, one lit
        up at a time, as Atticus's idea bubbles do round its orb."""
        ui, px, c = _ui(), self.app.px, self.bloom
        c.delete("all")
        w, h = int(c.cget("width")), int(c.cget("height"))
        t = now - (c.started or now)
        cx, cy = w / 2, h / 2
        spots = [(-0.36, -0.36), (0.34, -0.38), (-0.44, -0.02), (0.44, 0.0), (-0.32, 0.36), (0.32, 0.38),
                 (0.0, -0.46), (0.0, 0.46), (-0.08, 0.2)][:len(IDEAS)]
        lit = int(t / 2.2) % len(IDEAS)
        font = tkfont.Font(root=c, font=self.f_small)
        for i, (idea, (sx, sy)) in enumerate(zip(IDEAS, spots)):
            e = ui.ease(min(1.0, max(0.0, (t - i * 0.045) / 0.9)))
            bob = math.sin(t * 0.9 + i) * px(3)
            tw = font.measure(idea)
            x = min(max(cx + sx * w * e, tw / 2 + px(14)), w - tw / 2 - px(14))  # never past the edge
            y = min(max(cy + sy * h * e + bob, px(16)), h - px(16))
            on = i == lit and t > 1.2
            c.create_polygon(ui.rounded(x - tw / 2 - px(10), y - px(13), x + tw / 2 + px(10), y + px(13), px(13)),
                             smooth=True, fill=ui.mix(BG, "#eaf2fc" if on else CARD, e),
                             outline=ui.mix(BG, ACCENT if on else LINE, e))
            c.create_text(x, y, text=idea, font=self.f_small, fill=ui.mix(BG, ACCENT if on else TEXT, e))
        ew, eh = px(108), px(54)
        c.create_polygon(ui.rounded(cx - ew / 2, cy - eh / 2, cx + ew / 2, cy + eh / 2, eh / 2), smooth=True,
                         fill=NAV, outline="")
        blink = 0.15 if (t % 4.0) < 0.12 else 1.0
        for side in (-1, 1):
            ex = cx + side * px(14)
            ehh = px(18) * blink
            c.create_polygon(ui.rounded(ex - px(5), cy - ehh / 2, ex + px(5), cy + ehh / 2, px(5)), smooth=True,
                             fill="#f7f7f9", outline="")

    # ------------------------------------------------------------------ the clock that moves it all
    def _poll(self):
        """30 times a second while it's open: the preview of the page in front, the bloom; once a second, what's
        ready and the try page's hint."""
        if not self.top.winfo_exists():
            return
        now = time.time()
        page = self.pages.get(self.current)
        if page is not None and getattr(page, "preview", None):
            page.started = page.started or now
            page.stage.delete("all")
            try:
                page.preview(page.stage, now - page.started)
            except tk.TclError:
                pass
        for name, frame in self.pages.items():  # a page that's gone starts its loop again when it's back
            if name != self.current and getattr(frame, "preview", None):
                frame.started = None
        if self.current == "done":
            self._draw_bloom(now)
        if int(now) != getattr(self, "_second", None):
            self._second = int(now)
            if self.current == "ready":
                self._check_ready()
            elif self.current == "try":
                self._try_hint()
        self.top.after(33, self._poll)

    def finish(self):
        settings.put("onboarded", True)
        self.app.walkthrough = None
        try:
            self.top.destroy()
        except tk.TclError:
            pass
