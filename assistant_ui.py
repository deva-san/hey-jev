"""Hey Jev's window on Windows: status on top, sidebar tabs for stats, the dictionary, apps, history, settings and keys."""
import json
import os
import queue
import re
import sys
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

import hermes_memory
import history
import messaging
import opencode
import settings
import tasks as tasking
import winplatform as win
from bubble import Bubble
from dictation import HISTORY, read_vocab, save_vocab
from hermes_memory import skills
from secrets_store import KEY_NAMES, OPTIONAL, get_secret, missing_secrets, save_secret

TITLE = "Hey Jev"
HERE = os.path.dirname(os.path.abspath(__file__))
ICON = os.path.join(HERE, "assets", "icon.ico")
W, H, SIDEBAR = 940, 640, 210
HINTS = {"ptt": "Hold right Alt to talk", "wake": "Say \u201cHey Jev\u201d, \u201cHello Jev\u201d or just \u201cJev\u201d, "
                                                 "then what you want. Right after she answers, just keep talking. "
                                                 "Holding right Alt works too."}
ENGINES = {"parakeet": "Parakeet (hears her name best)", "nemotron": "Nemotron (writes as you talk)",
           "whisper": "Whisper small.en (slower)"}
MODES = ("ptt", "wake")
MODE_LABELS = {"ptt": "Hold Right Alt", "wake": "Hey Jev"}
TABS = (("home", "Home"), ("tasks", "Tasks"), ("contacts", "Contacts"), ("dict", "Dictionary"), ("apps", "Apps"),
        ("hist", "Dictation history"), ("mem", "Memory"), ("priv", "Privacy"), ("settings", "Settings"),
        ("keys", "Keys"))
hermes_memory.set_memory_dir(os.path.join(win.APPDATA_DIR, "memories"))  # the same places siri.py keeps them
hermes_memory.set_home(win.APPDATA_DIR)
skills.set_skills_dir(os.path.join(win.APPDATA_DIR, "skills"))
NOTES_DIR = os.path.join(win.APPDATA_DIR, "notes")
# What the window says she's doing, as the popup shows it (see bubble.LOOKS)
PILL = {"Listening": "listening", "Still listening": "window", "Transcribing": "thinking", "Thinking": "thinking",
        "Looking": "looking", "Doing it": "doing", "Speaking": "speaking", "Time's up": "speaking",
        "Dictating": "dictating", "Finishing": "finishing", "Something went wrong": "error"}
LOG_FILE = win.log_path("Hey Jev.log")
TYPING_WPM, SPEAKING_WPM = 40, 150  # average typing vs talking speed, for "time saved"
ACTION_NAMES = {"open": "Open app", "close": "Close app", "minimise": "Minimise", "website": "Websites",
                "youtube": "YouTube", "google": "Google", "media": "Play and pause", "volume": "Volume",
                "scroll": "Scroll", "keys": "Shortcuts", "type": "Typing", "new_tab": "New tab", "timer": "Timers",
                "dark_mode": "Dark mode", "lock": "Lock", "memory": "Remembered", "screen": "Looked at the screen",
                "skill": "Skills learned", "research": "Research", "note": "Notes", "open_notes": "Notes",
                "task_queued": "Background tasks", "task_control": "Background tasks", "command": "Commands",
                "schedule": "Schedules", "install_run": "Apps installed", "message_send": "Messages sent",
                # names from before the planner, still in older logs
                "app_open": "Open app", "app_quit": "Close app", "app_hide": "Minimise", "app_minimise": "Minimise",
                "app_focus": "Open app", "media_play": "Play and pause", "media_pause": "Play and pause",
                "media_next": "Next track", "media_previous": "Previous track", "timer_set": "Timers",
                "browser_open_site": "Websites", "browser_new_tab": "New tab"}
APPS_FILE = os.path.join(HERE, "apps.json")
MIC_SUB = "Switches straight away. Plugged in a new one? Restart Jev to see it here."
HOW_TO = ("Say \u201cHey Jev\u201d and what you want: \u201cplay Arijit Singh songs\u201d, \u201copen Notepad and "
          "write a poem about rain\u201d, \u201cscroll down\u201d, \u201cwhat\u2019s the weather in Delhi\u201d, "
          "\u201cremind me in 10 minutes to call Mum\u201d. In Hold Right Alt mode, hold right Alt and just say it. "
          "For a few seconds after she answers, keep talking without \u201cHey Jev\u201d. She hears you over YouTube "
          "and music, since Windows takes what the PC plays out of the mic (Settings, Echo cancelling). "
          "\u201cHey Jev, transcribe\u201d starts dictating, and \u201cstop transcribing\u201d pastes it where your cursor is.\n"
          "She remembers: \u201cremember that my website CareerID is careerid.in\u201d, then \u201copen CareerID\u201d. Ask "
          "\u201cwhat did we talk about yesterday?\u201d, or about the PC: \u201chow much space is on my C drive?\u201d, "
          "\u201cis my laptop charging?\u201d. Browser profiles work by name: \u201copen Gmail in my Work profile\u201d.\n"
          "She can see the screen when you ask: \u201cwhat\u2019s on my screen?\u201d, \u201cclick the second video\u201d, "
          "\u201cread this page to me\u201d, \u201csearch for lofi in this box\u201d.\n"
          "Ask her about the world: \u201cwho directed Iron Man 2?\u201d, \u201cwhat\u2019s the latest news?\u201d, "
          "\u201cwill it rain tomorrow?\u201d. \u201cAny new messages?\u201d reads your notifications, and Phone Link "
          "brings in your phone\u2019s. \u201cResearch the best budget phones under 20,000\u201d carries on in the "
          "background, then she tells you and saves a note. Schedule durable work: \u201cevery Monday at 9 check my C "
          "drive\u201d; guarded terminal work: \u201ccheck git status in C:\\path\u201d. The Tasks tab shows, cancels and approves it. "
          "Teach her routines: \u201cwhen I say work mode, open Gmail "
          "in my Work profile and set the volume to 30\u201d, then just say \u201cwork mode\u201d. She learns from your "
          "corrections, and her personality is yours to change in the Memory tab.\n"
          "Closing the window keeps her listening, quit from the sidebar or with Ctrl+Q.")
PRIVACY = (
    ("Stays on your PC", "Everything the mic hears, and all your dictation. Speech is turned into text on this PC to "
     "listen for \u201cHey Jev\u201d, and anything that isn't for her is thrown away, never sent. Simple commands like "
     "\u201copen Notepad\u201d or \u201cpause\u201d are worked out here too, and so are questions about the PC like "
     "\u201chow much space is on my C drive\u201d. The log only keeps phrases that start with \u201chey\u201d, to check "
     "how her name was heard. Her memory, skills, notes, personality (SOUL.md) and your conversations with her are "
     "kept in %APPDATA%\\Hey Jev, see the Memory tab. Your dictionary and apps stay in this folder, logs in "
     "%LOCALAPPDATA%\\Hey Jev."),
    ("Answer model on OpenCode Zen or Kilo  \u00b7  text", "What you ask her, as text: the words after \u201cHey Jev\u201d "
     "and what you say in the few seconds after she answers, with the name of the app in front, what's playing, the "
     "time, her personality, what she remembers about you, her skills, your last half hour with her and the names of "
     "your browser profiles, to work out what to do. With Answer without her name on in Settings, also anything said "
     "near the PC that could be a request, a phrase with a word like open, play or what in it, and up to three things "
     "said in the half minute before it, so she can tell a conversation with someone else. When she looks something "
     "up for it, the answer: how full a drive is, what you said on a day, what a web page says. Once a day, the day "
     "before's conversation, for a short summary and anything worth remembering, and the turns her learning looks "
     "back over, always to space-bunny-free, which keeps nothing and isn't trained on. Other free models may use what "
     "you send to improve the model: opencode.ai/docs/zen lists which on OpenCode, and Kilo says some of its free "
     "ones log what they're sent."),
    ("Messaging  ·  stays on this PC", "Who you can message and their number or username are kept in "
     "%APPDATA%\\Hey Jev\\contacts.json, on this PC. The chat is opened with WhatsApp's or Telegram's own link, so "
     "the message goes to that app and nowhere else, and nothing is sent until you say yes. In an app with no link "
     "of its own she types the name into that app's search instead, which she can't read back, so your yes is "
     "confirming the chat as well; what worked is kept in %APPDATA%\\Hey Jev\\recipes.json. She never reads your "
     "chats, and no screenshot of a chat is taken. The words you dictate reach the answer model only when it had to "
     "work out the request, the same as anything else you say."),
    ("Background tasks  ·  stays on this PC", "Tasks, schedules, command text, working folders, status and command "
     "output are kept in %APPDATA%\\Hey Jev\\tasks.db. Command output is never sent to the answer model or spoken; "
     "the Tasks tab shows it. Jev only says whether it finished."),
    ("Internet  \u00b7  search words, web addresses, roughly where you are", "When you ask about the world, the words "
     "to look up go to Wikipedia, DuckDuckGo\u2019s instant answers and Google News, and she opens pages by their "
     "address, as a browser does. The weather comes from Open-Meteo, for roughly where you are: ipinfo.io works that "
     "out from your internet address. Research does the same in the background. What pages say reaches the answer "
     "model as information, never as instructions, and a page that tries to give her orders is left out."),
    ("Notifications  \u00b7  read on your PC", "She reads Windows\u2019 list of notifications on this PC. Heads-ups and "
     "\u201cwelcome back\u201d only say who it\u2019s from and the app, and nothing is sent for them. What a message "
     "says goes to the answer model only when you ask, as in \u201cany new messages?\u201d. Turn it off in Settings."),
    ("Learning  \u00b7  text", "Now and then, after a correction or a task of a few steps, your last few turns with "
     "her go to the answer model, to pick out a fact to remember, a routine or a word speech-to-text got wrong. What "
     "it finds stays on this PC, in the Memory tab and your Dictionary. Turn it off in Settings."),
    ("Vision  \u00b7  a screenshot", "Only when you ask about the screen, or for something she has to see to do, like "
     "\u201cclick the second video\u201d or \u201cwhat\u2019s on my screen?\u201d: a picture of the screen in front goes to "
     "the answer model, and again after each step she takes there, five at most. Never otherwise. Her popup is left "
     "out of it, and without her name she asks first. Turn it off in Settings."),
    ("YouTube  \u00b7  search words", "When she plays something, what you asked for, to find the top video."),
    ("Fish Audio  \u00b7  text", "The text of her replies, to turn into her voice. Scripted replies are saved after the "
     "first time, so most are never sent again."),
)
KEY_ROWS = (
    ("OpenCode Zen", "OPENCODE_ZEN_API_KEY", "Works out what you asked and answers, on free models only",
     "https://opencode.ai/zen"),
    ("Fish Audio", "FISH_AUDIO_API_KEY", "Her voice, on Fish's free model", "https://fish.audio/?fpr=henryk"),
    ("Kilo", "KILO_API_KEY", "More free models, like the quick Ling 3.0 Flash, free ones only",
     "https://kilo.ai/docs/gateway/authentication"),
)

BG, SIDE, HOVER, SELECT, CARD, LINE = "#ffffff", "#f3f3f3", "#e9e9e9", "#e0e0e0", "#f4f4f5", "#e3e3e3"
TEXT, MUTED, ACCENT, ERROR, TEAL = "#1b1b1b", "#5c5c5c", "#0067c0", "#c42b1c", "#0f766e"
STATUS_COLORS = {
    "Starting": "#d97706", "Ready": "#16a34a", "Listening": "#dc2626", "Transcribing": "#2563eb",
    "Thinking": "#7c3aed", "Looking": "#0891b2", "Doing it": "#ea580c", "Speaking": "#0d9488",
    "Something went wrong": "#dc2626",
    "Still listening": "#dc2626",
    "Time's up": "#ca8a04", "Dictating": "#dc2626", "Finishing": "#2563eb",
}


def app_key(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")  # "Claude Code" -> claude_code, what Jev matches on


def split_list(text):
    return [a.strip() for a in text.split(",") if a.strip()]


class HintEntry(ttk.Entry):
    """An entry with grey hint text while it's empty, since Tk entries have no placeholder."""

    def __init__(self, parent, hint, secure=False, **kw):
        super().__init__(parent, **kw)
        self.hint, self.secure, self.showing = hint, secure, False
        self.bind("<FocusIn>", self._hide_hint, add="+")
        self.bind("<FocusOut>", self._show_hint, add="+")
        self._show_hint()

    def _hide_hint(self, _=None):
        if self.showing:
            self.showing = False
            self.delete(0, "end")
            self.configure(style="TEntry", show="\u2022" if self.secure else "")

    def _show_hint(self, _=None):
        if not self.showing and not super().get():
            self.showing = True
            self.configure(style="Hint.TEntry", show="")
            self.insert(0, self.hint)

    def get(self):
        return "" if self.showing else super().get()

    def clear(self):
        self._hide_hint()
        self.delete(0, "end")
        try:
            focused = self.focus_get() is self
        except (KeyError, tk.TclError):
            focused = False
        if not focused:
            self._show_hint()

    def set_hint(self, hint):
        self.hint = hint
        if self.showing:
            self.delete(0, "end")
            self.insert(0, hint)


class AssistantWindow:
    def __init__(self, root):
        self.root = root
        self.controls, self.events = queue.Queue(), queue.Queue()
        self.worker_started = False
        self.mode = settings.get("mode") if settings.get("mode") in MODES else "ptt"
        self.mic = settings.get("mic") or ""
        self.on_top = bool(settings.get("keep_on_top"))
        self.popup = bool(settings.get("popup"))
        self.s = root.winfo_fpixels("1i") / 96  # Windows display scaling, 1.0 at 100%
        self._setup_root()
        self._setup_styles()
        self.bubble = Bubble(root)
        self._build_sidebar()
        self._build_main()
        self.pages = {"home": self._build_home(), "tasks": self._build_tasks(),
                      "contacts": self._build_contacts(), "dict": self._build_dictionary(),
                      "apps": self._build_apps(), "hist": self._build_history(), "mem": self._build_memory(),
                      "priv": self._build_privacy(), "settings": self._build_settings(), "keys": self._build_keys()}
        self._select_tab("keys" if missing_secrets() else "home")
        self.root.after(50, self._drain)
        self.root.after(500, self._tick)
        self.root.after(150, self.root.focus_force)
        if missing_secrets():
            self._set_status("Starting", "Add your API keys to begin")
        else:
            self._start_worker()

    def px(self, n):
        return round(n * self.s)

    # ------------------------------------------------------------------ window
    def _setup_root(self):
        root = self.root
        root.title(TITLE)
        root.configure(bg=BG)
        if os.path.exists(ICON):
            root.iconbitmap(default=ICON)
        w, h = self.px(W), self.px(H)
        x = (root.winfo_screenwidth() - w) // 2
        y = max(0, (root.winfo_screenheight() - h) // 2 - self.px(30))
        root.geometry(f"{w}x{h}+{x}+{y}")
        root.minsize(self.px(820), self.px(560))
        root.attributes("-topmost", self.on_top)
        root.protocol("WM_DELETE_WINDOW", root.iconify)  # closing keeps her listening, the taskbar button brings it back
        root.bind("<Control-q>", lambda e: self.quit())
        root.bind("<Control-m>", lambda e: root.iconify())
        root.bind("<Control-t>", lambda e: self.toggle_on_top())
        for cls in ("TEntry", "TCombobox"):  # Ctrl+T swaps letters in a text box, the window shortcut wins
            root.bind_class(cls, "<Control-t>", lambda e: None)
        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(0, weight=1)

    def _setup_styles(self):
        self.f_body = ("Segoe UI", 10)
        self.f_small = ("Segoe UI", 9)
        self.f_bold = ("Segoe UI Semibold", 10)
        self.f_h2 = ("Segoe UI Semibold", 11)
        self.f_status = ("Segoe UI Semibold", 13)
        self.f_title = ("Segoe UI Semibold", 17)
        self.f_brand = ("Segoe UI Semibold", 13)
        self.f_value = ("Segoe UI Semibold", 19)
        self.f_mono = ("Consolas", 11)
        style = ttk.Style(self.root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure(".", font=self.f_body)
        style.configure("Treeview", rowheight=self.px(26), font=self.f_body)
        style.configure("Treeview.Heading", font=self.f_bold)
        style.configure("TButton", padding=(self.px(10), self.px(3)))
        style.configure("Hint.TEntry", foreground="#6e6e6e")
        style.configure("TCheckbutton", background=BG)
        style.configure("TCombobox", padding=self.px(2))

    def _label(self, parent, text="", font=None, fg=TEXT, bg=BG, **kw):
        anchor = "nw" if "wraplength" in kw else "w"  # if a long text runs out of room, lose the end, not the start
        return tk.Label(parent, text=text, font=font or self.f_body, fg=fg, bg=bg, anchor=anchor, justify="left", **kw)

    def _link(self, parent, text, url, bg=BG):
        link = tk.Label(parent, text=text, font=("Segoe UI", 9, "underline"), fg=ACCENT, bg=bg, cursor="hand2")
        link.bind("<Button-1>", lambda e: webbrowser.open(url))
        return link

    # ------------------------------------------------------------------ layout
    def _build_sidebar(self):
        side = tk.Frame(self.root, bg=SIDE, width=self.px(SIDEBAR))
        side.grid(row=0, column=0, sticky="ns")
        side.pack_propagate(False)
        self._label(side, "Hey Jev", self.f_brand, bg=SIDE).pack(fill="x", padx=self.px(22), pady=(self.px(22), self.px(14)))
        self.tab_buttons = {}
        for key, title in TABS:
            b = tk.Button(side, text=title, anchor="w", relief="flat", bd=0, bg=SIDE, fg=TEXT, font=self.f_body,
                          activebackground=SELECT, activeforeground=TEXT, padx=self.px(12), pady=self.px(5),
                          highlightthickness=1, highlightbackground=SIDE, highlightcolor=ACCENT, cursor="hand2",
                          command=lambda k=key: self._select_tab(k))
            b.pack(fill="x", padx=self.px(10), pady=1)
            b.bind("<Enter>", lambda e, k=key: self._hover_tab(k, True))
            b.bind("<Leave>", lambda e, k=key: self._hover_tab(k, False))
            self.tab_buttons[key] = b
        bottom = tk.Frame(side, bg=SIDE)
        bottom.pack(side="bottom", fill="x", padx=self.px(20), pady=(0, self.px(14)))
        self.timer_rows = []
        for _ in range(3):  # up to 3 timers, soonest on top
            row = tk.Frame(bottom, bg=SIDE)
            name = self._label(row, "", self.f_small, MUTED, SIDE)
            left = tk.Label(row, text="", font=self.f_mono, fg=TEAL, bg=SIDE)
            name.pack(side="left")
            left.pack(side="right")
            self.timer_rows.append((row, name, left))
        self.hint = self._label(bottom, HINTS[self.mode], self.f_small, MUTED, SIDE, wraplength=self.px(SIDEBAR - 40))
        self.hint.pack(fill="x", pady=(self.px(8), self.px(6)))
        tk.Button(bottom, text="Quit Hey Jev", relief="flat", bd=0, bg=SIDE, fg=MUTED, font=self.f_small,
                  activebackground=HOVER, cursor="hand2", anchor="w", highlightthickness=1, highlightbackground=SIDE,
                  highlightcolor=ACCENT, command=self.quit).pack(fill="x")

    def _hover_tab(self, key, inside):
        if key != getattr(self, "current_tab", None):
            self.tab_buttons[key].configure(bg=HOVER if inside else SIDE)

    def _build_main(self):
        main = tk.Frame(self.root, bg=BG)
        main.grid(row=0, column=1, sticky="nsew")
        header = tk.Frame(main, bg=BG)
        header.pack(fill="x", padx=self.px(24), pady=(self.px(16), self.px(12)))
        seg = tk.Frame(header, bg=LINE, padx=1, pady=1)  # the mode switch, a 1px border round two buttons
        seg.pack(side="right", anchor="n")
        self.mode_buttons = {}
        for mode in MODES:
            b = tk.Button(seg, text=MODE_LABELS[mode], relief="flat", bd=0, font=self.f_body, padx=self.px(12),
                          pady=self.px(4), cursor="hand2", highlightthickness=0, command=lambda m=mode: self.set_mode(m))
            b.pack(side="left")
            self.mode_buttons[mode] = b
        self._paint_mode()
        status = tk.Frame(header, bg=BG)
        status.pack(side="left", fill="x", expand=True)
        row = tk.Frame(status, bg=BG)
        row.pack(anchor="w")
        self.dot = tk.Label(row, text="\u25cf", font=("Segoe UI", 13), fg=STATUS_COLORS["Starting"], bg=BG)
        self.dot.pack(side="left")
        self.status = self._label(row, "Starting", self.f_status)
        self.status.pack(side="left", padx=(self.px(6), 0))
        self.detail = self._label(status, "Loading speech models\u2026", fg=MUTED)
        self.detail.pack(anchor="w", fill="x")
        tk.Frame(main, bg=LINE, height=1).pack(fill="x")
        self.page_area = tk.Frame(main, bg=BG)
        self.page_area.pack(fill="both", expand=True)
        self.page_area.grid_rowconfigure(0, weight=1)
        self.page_area.grid_columnconfigure(0, weight=1)

    def _paint_mode(self):
        for mode, b in self.mode_buttons.items():
            on = mode == self.mode
            b.configure(bg=ACCENT if on else BG, fg="#ffffff" if on else TEXT,
                        activebackground=ACCENT if on else HOVER, activeforeground="#ffffff" if on else TEXT)

    def _page(self, title, subtitle, scroll=False):
        page = tk.Frame(self.page_area, bg=BG, padx=self.px(24), pady=self.px(18))
        page.grid(row=0, column=0, sticky="nsew")
        if scroll:  # a page taller than the window scrolls, with the mouse wheel too
            outer, canvas = page, tk.Canvas(page, bg=BG, highlightthickness=0, bd=0)
            bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
            page = tk.Frame(canvas, bg=BG)
            item = canvas.create_window(0, 0, window=page, anchor="nw")
            canvas.configure(yscrollcommand=bar.set)
            canvas.pack(side="left", fill="both", expand=True)

            def fit(event=None):
                if event is not None and event.widget is canvas:
                    canvas.itemconfigure(item, width=event.width)
                canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), page.winfo_reqheight()))
                if page.winfo_reqheight() > canvas.winfo_height() > 1:
                    bar.pack(side="right", fill="y", before=canvas)
                else:
                    bar.pack_forget()
                    canvas.yview_moveto(0)
            page.bind("<Configure>", fit)
            canvas.bind("<Configure>", fit)
            wheel = lambda e: canvas.yview_scroll(int(-e.delta / 120), "units") if bar.winfo_ismapped() else None
            outer.bind("<Enter>", lambda e: canvas.bind_all("<MouseWheel>", wheel))
            outer.bind("<Leave>", lambda e: canvas.unbind_all("<MouseWheel>"))
            page.outer = outer  # what the tabs raise
        self._label(page, title, self.f_title).pack(fill="x")
        self._label(page, subtitle, fg=MUTED, wraplength=self.px(660)).pack(fill="x", pady=(self.px(2), self.px(14)))
        return page

    def _table(self, parent, columns, editable=True):
        frame = tk.Frame(parent, bg=BG)
        tree = ttk.Treeview(frame, columns=[c[0] for c in columns], show="headings", selectmode="browse")
        for ident, title, width in columns:
            tree.heading(ident, text=title, anchor="w")
            tree.column(ident, width=self.px(width), anchor="w", stretch=True)
        bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=bar.set)
        tree.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        if editable:
            tree.bind("<Double-1>", lambda e: self._edit_at(tree, e))
            tree.bind("<F2>", lambda e: self._edit_selected(tree))  # keyboard way in, F2 like Explorer
        return frame, tree

    def _bottom_bar(self, page, button_text, command):
        bar = tk.Frame(page, bg=BG)
        bar.pack(fill="x", pady=(self.px(10), 0))
        ttk.Button(bar, text=button_text, command=command).pack(side="left")
        message = self._label(bar, "", self.f_small, MUTED)
        message.pack(side="left", padx=self.px(10))
        return message

    # ------------------------------------------------------------------ table editing
    def _edit_at(self, tree, event):
        if tree.identify_region(event.x, event.y) != "cell":
            return
        row, col = tree.identify_row(event.y), tree.identify_column(event.x)
        if row:
            self._edit(tree, row, int(col[1:]) - 1)

    def _edit_selected(self, tree):
        sel = tree.selection()
        if sel:
            self._edit(tree, sel[0], 0)

    def _edit(self, tree, row, col):
        tree.see(row)
        tree.update_idletasks()
        box = tree.bbox(row, f"#{col + 1}")
        if not box:
            return
        ident = tree["columns"][col]
        entry = ttk.Entry(tree)
        entry.insert(0, tree.set(row, ident))
        entry.select_range(0, "end")
        entry.place(x=box[0], y=box[1], width=box[2], height=box[3])
        entry.focus_set()
        done = [False]

        def finish(save):
            if done[0]:
                return
            done[0] = True
            value = entry.get()
            entry.destroy()
            if save:
                self._cell_edited(tree, int(row), ident, value)

        entry.bind("<Return>", lambda e: finish(True))
        entry.bind("<Escape>", lambda e: finish(False))
        entry.bind("<FocusOut>", lambda e: finish(True))

    def _cell_edited(self, tree, row, ident, value):
        value = value.strip()
        if tree is self.apps_table:
            entry = self.apps[row]
            if ident == "heard":
                entry[2] = split_list(value)
            elif ident == "say" and app_key(value):
                entry[0] = app_key(value)
            elif ident == "app" and value:
                entry[1] = value
            elif ident == "exe":
                entry[4] = split_list(value)
            self._save_apps("Saved, restart Jev to use it")
        elif tree is getattr(self, "contacts_table", None):
            key, entry = self.contacts[row]

            def rewrite(name):  # a contact is one row per name, so a change means writing the row again
                messaging.forget_contact(key)
                for app, handle in entry.items():
                    if app != "name" and handle:
                        messaging.save_contact(name, app, handle)
            if ident == "other":
                self._load_contacts("Jev learns those herself, so there's nothing to edit here")
                return
            try:
                if ident == "name" and value:
                    rewrite(value)
                elif ident in ("whatsapp", "telegram"):
                    if value:
                        messaging.save_contact(entry.get("name") or key, ident, value)
                    else:
                        entry.pop(ident, None)
                        rewrite(entry.get("name") or key)
                self._load_contacts("Saved")
            except (ValueError, RuntimeError) as exc:
                self._load_contacts(f"Couldn't save: {exc}")
        elif tree is self.table:
            entry = self.vocab[self.visible[row]]
            if ident == "word":
                if value:
                    entry[0] = value
            else:
                entry[1] = split_list(value)
            self._save_vocab("Saved, used straight away")

    # ------------------------------------------------------------------ home
    def _build_home(self):
        page = self._page("Your Jev stats", "Everything since you started using Jev. Refreshes each time you open this tab.",
                          scroll=True)
        grid = tk.Frame(page, bg=BG)
        grid.pack(fill="x")
        for c in range(3):
            grid.grid_columnconfigure(c, weight=1, uniform="card")
        self.stat_cards = []
        for i in range(6):
            card = tk.Frame(grid, bg=CARD, padx=self.px(16), pady=self.px(10))
            card.grid(row=i // 3, column=i % 3, sticky="nsew", padx=(0, self.px(12) if i % 3 < 2 else 0), pady=(0, self.px(12)))
            value = self._label(card, "", self.f_value, bg=CARD)
            title = self._label(card, "", self.f_bold, bg=CARD)
            sub = self._label(card, "", self.f_small, MUTED, CARD)
            for v in (value, title, sub):
                v.pack(fill="x")
            self.stat_cards.append((value, title, sub))
        self._label(page, "Most used", self.f_h2).pack(fill="x", pady=(self.px(6), self.px(2)))
        self.top_actions = self._label(page, "", fg=MUTED, wraplength=self.px(660))
        self.top_actions.pack(fill="x")
        self._label(page, "How to use", self.f_h2).pack(fill="x", pady=(self.px(12), self.px(2)))
        self._label(page, HOW_TO, fg=MUTED, wraplength=self.px(660)).pack(fill="x")
        return page

    def _load_stats(self):
        words = dictations = words_today = dictations_today = 0
        today = time.strftime("%Y-%m-%d")
        if os.path.exists(HISTORY):
            with open(HISTORY, encoding="utf-8") as f:
                for line in f:
                    try:
                        item = json.loads(line)
                    except ValueError:
                        continue
                    n = len(item.get("text", "").split())
                    words += n
                    dictations += 1
                    if item.get("time", "").startswith(today):
                        words_today += n
                        dictations_today += 1
        heard, actions, answered, opened = 0, {}, 0, {}
        if os.path.exists(LOG_FILE):
            with open(LOG_FILE, encoding="utf-8", errors="replace") as f:
                for line in f:
                    if line.startswith("> heard:"):
                        heard += 1
                    elif line.startswith("  action: "):
                        parts = line.split(None, 2)  # "  action: open Google Chrome"
                        if len(parts) < 2:
                            continue
                        actions[parts[1]] = actions.get(parts[1], 0) + 1
                        if parts[1] in ("open", "app_open") and len(parts) > 2:
                            opened[parts[2].strip()] = opened.get(parts[2].strip(), 0) + 1
                    elif line.startswith("  llm ") and not line.startswith("  llm failed"):
                        answered += 1
        saved = words / TYPING_WPM - words / SPEAKING_WPM
        saved_text = (f"{int(saved // 60)} h {int(saved % 60)} min" if saved >= 60 else f"{saved:.0f} min" if saved >= 1
                      else f"{saved * 60:.0f} sec")
        names = {row[0]: row[3] or row[1] for row in getattr(self, "apps", [])}
        fav = max(opened, key=opened.get) if opened else None
        fav_name = names.get(fav, (fav or "None yet").replace("_", " "))
        cards = (
            (saved_text, "Time saved", f"vs typing at {TYPING_WPM} words a minute"),
            (f"{words:,}", "Words dictated", f"{words_today:,} today"),
            (f"{dictations:,}", "Dictations", f"{dictations_today:,} today"),
            (f"{sum(actions.values()):,}", "Commands done", f"from {heard:,} things she heard"),
            (fav_name if len(fav_name) <= 14 else fav_name[:13] + "\u2026", "Most opened app",
             f"opened {opened[fav]} times" if fav else "Say \u201cHey Jev, open Spotify\u201d"),
            (f"{answered:,}", "Questions answered", "by free models, $0"),
        )
        for (value, title, sub), (v, t, s) in zip(self.stat_cards, cards):
            value.configure(text=v)
            title.configure(text=t)
            sub.configure(text=s)
        merged = {}  # old and new names for the same thing count together
        for a, n in actions.items():
            label = ACTION_NAMES.get(a, a.replace("_", " ").capitalize())
            merged[label] = merged.get(label, 0) + n
        top = sorted(merged.items(), key=lambda kv: -kv[1])[:6]
        self.top_actions.configure(text="   \u00b7   ".join(f"{label}  {n}" for label, n in top)
                                   or "Nothing yet. Say \u201cHey Jev\u201d and a command to get started.")

    # ------------------------------------------------------------------ contacts
    def _build_contacts(self):
        page = self._page("Contacts", "Who Jev can message, and how. She asks once, then remembers. Nothing is ever "
                          "sent until you say yes. Double-click a cell to fix it.")
        frame, self.contacts_table = self._table(page, (("name", "Name you say", 150),
                                                        ("whatsapp", "WhatsApp number", 170),
                                                        ("telegram", "Telegram username", 170),
                                                        ("other", "Found in other apps as", 190)))
        frame.pack(fill="both", expand=True)
        self.contacts_message = self._bottom_bar(page, "Remove", self.remove_contact)
        self._load_contacts()
        return page

    def _load_contacts(self, message=None):
        self.contacts = sorted(messaging.read_contacts().items())
        self.contacts_table.delete(*self.contacts_table.get_children())
        for row, (key, entry) in enumerate(self.contacts):
            # whatever she learned elsewhere: the name she types into Signal's or Slack's own search
            elsewhere = ", ".join(f"{messaging.say_of(a)}: {h}" for a, h in sorted(entry.items())
                                  if a not in ("name", "whatsapp", "telegram") and h)
            self.contacts_table.insert("", "end", iid=str(row), values=(entry.get("name") or key,
                                       entry.get("whatsapp", ""), entry.get("telegram", ""), elsewhere))
        taught = messaging.learned_apps()
        note = message or f"{len(self.contacts)} saved"
        if taught and not message:
            note += " \u00b7 also learned to message in " + ", ".join(taught)
        self.contacts_message.configure(text=note, fg=MUTED)

    def remove_contact(self):
        sel = self.contacts_table.selection()
        if not sel:
            self.contacts_message.configure(text="Pick someone in the list first", fg=ERROR)
            return
        key = self.contacts[int(sel[0])][0]
        messaging.forget_contact(key)
        self._load_contacts(f"Removed {key}")

    # ------------------------------------------------------------------ tasks
    def _build_tasks(self):
        page = self._page("Background tasks", "Durable work and reminders. They survive a restart; commands that can "
                          "change things wait for approval.")
        self.task_store = tasking.Store()
        frame, self.tasks_table = self._table(page, (("id", "ID", 42), ("task", "Task", 245),
                                                         ("status", "Status", 115), ("next", "Next run", 145),
                                                         ("result", "Last result", 220)), editable=False)
        frame.pack(fill="both", expand=True)
        bar = tk.Frame(page, bg=BG)
        bar.pack(fill="x", pady=(self.px(10), 0))
        ttk.Button(bar, text="Refresh", command=self._load_tasks).pack(side="left")
        ttk.Button(bar, text="Cancel", command=lambda: self._task_action("cancel")).pack(side="left",
                                                                                         padx=(self.px(6), 0))
        ttk.Button(bar, text="Approve", command=lambda: self._task_action("approve")).pack(side="left",
                                                                                           padx=(self.px(6), 0))
        self.tasks_message = self._label(bar, "", self.f_small, MUTED)
        self.tasks_message.pack(side="left", padx=self.px(10))
        return page

    def _load_tasks(self, message=None):
        self.tasks_table.delete(*self.tasks_table.get_children())
        try:
            rows = self.task_store.list(80)
        except Exception as exc:
            self.tasks_message.configure(text=f"Couldn't read tasks: {exc}", fg=ERROR)
            return
        for task in rows:
            due = tasking.describe_due(task["due"]) if task["status"] in ("queued", "waiting_approval") else "—"
            result = task.get("error") or task.get("result") or ""
            result = " ".join(str(result).split())
            self.tasks_table.insert("", "end", iid=str(task["id"]), values=(task["id"], task["description"],
                                    task["status"].replace("_", " "), due, result[:100]))
        self.tasks_message.configure(text=message or f"{len(rows)} task{'s' if len(rows) != 1 else ''}", fg=MUTED)

    def _task_action(self, action):
        selected = self.tasks_table.selection()
        if not selected:
            self.tasks_message.configure(text="Pick a task first", fg=ERROR)
            return
        task_id = int(selected[0])
        ok = self.task_store.cancel(task_id) if action == "cancel" else self.task_store.approve(task_id)
        self._load_tasks(f"Task {task_id} {action + 'led' if action == 'cancel' else 'approved'}" if ok else
                         f"Task {task_id} can't be {action + 'led' if action == 'cancel' else 'approved'}")

    # ------------------------------------------------------------------ dictionary
    def _build_dictionary(self):
        page = self._page("Dictionary", "Words the transcriber gets wrong. Anything under \u201cheard as\u201d is swapped for the word. "
                                        "Double-click a cell, or press F2, to edit it.")
        top = tk.Frame(page, bg=BG)
        top.pack(fill="x", pady=(0, self.px(10)))
        self.new_word = HintEntry(top, "Correct word", width=20)
        self.new_alts = HintEntry(top, "Heard as, comma separated", width=34)
        self.new_word.pack(side="left")
        self.new_alts.pack(side="left", padx=self.px(8))
        self.new_alts.bind("<Return>", lambda e: self.add_word())  # Return in the second box adds it
        ttk.Button(top, text="Add word", command=self.add_word).pack(side="left")
        self.search = HintEntry(top, "Search", width=16)
        self.search.pack(side="right")
        self.search.bind("<KeyRelease>", lambda e: self._filter_vocab())
        frame, self.table = self._table(page, (("word", "Word", 170), ("heard", "Heard as", 440)))
        frame.pack(fill="both", expand=True)
        self.dict_message = self._bottom_bar(page, "Remove", self.remove_word)
        self.vocab = [[w, list(alts)] for w, alts in read_vocab().items()]
        self._filter_vocab()
        return page

    def _filter_vocab(self):
        q = self.search.get().strip().lower()
        self.visible = [i for i, (w, alts) in enumerate(self.vocab)
                        if not q or q in w.lower() or any(q in a.lower() for a in alts)]
        self.table.delete(*self.table.get_children())
        for row, i in enumerate(self.visible):
            word, alts = self.vocab[i]
            self.table.insert("", "end", iid=str(row), values=(word, ", ".join(alts)))

    def _save_vocab(self, message):
        try:
            save_vocab({w: alts for w, alts in self.vocab})
            self.dict_message.configure(text=message, fg=MUTED)
        except Exception as exc:
            self.dict_message.configure(text=f"Couldn't save: {exc}", fg=ERROR)
        self._filter_vocab()

    def add_word(self):
        word = self.new_word.get().strip()
        alts = split_list(self.new_alts.get())
        if not word or not alts:
            self.dict_message.configure(text="Add the word and at least one way it gets misheard", fg=ERROR)
            return
        for entry in self.vocab:
            if entry[0].lower() == word.lower():  # already there, just add the new spellings
                entry[1] += [a for a in alts if a.lower() not in (x.lower() for x in entry[1])]
                break
        else:
            self.vocab.insert(0, [word, alts])
        for field in (self.new_word, self.new_alts, self.search):
            field.clear()
        self._save_vocab(f"Added {word}, used straight away")
        self.new_word.focus_set()

    def remove_word(self):
        sel = self.table.selection()
        if not sel:
            self.dict_message.configure(text="Pick a word in the list first", fg=ERROR)
            return
        word = self.vocab.pop(self.visible[int(sel[0])])[0]
        self._save_vocab(f"Removed {word}")

    # ------------------------------------------------------------------ apps
    def _build_apps(self):
        page = self._page("Apps", "What Jev can open, quit, minimise or switch to. App is its name in the Start menu. Program is "
                                  "the .exe, only needed if quit or switch can't find it. Restart Jev after changes.")
        top = tk.Frame(page, bg=BG)
        top.pack(fill="x", pady=(0, self.px(10)))
        self.new_say = HintEntry(top, "Name you say", width=16)
        self.new_app = HintEntry(top, "App, as in the Start menu", width=24)
        self.new_heard = HintEntry(top, "Heard as (optional)", width=20)
        for i, field in enumerate((self.new_say, self.new_app, self.new_heard)):
            field.pack(side="left", padx=(0 if i == 0 else self.px(8), 0))
        self.new_heard.bind("<Return>", lambda e: self.add_app())
        ttk.Button(top, text="Add app", command=self.add_app).pack(side="left", padx=self.px(8))
        frame, self.apps_table = self._table(page, (("say", "Name you say", 120), ("app", "App", 160), ("exe", "Program", 130),
                                                    ("heard", "Heard as", 240)))
        frame.pack(fill="both", expand=True)
        self.apps_message = self._bottom_bar(page, "Remove", self.remove_app)
        with open(APPS_FILE, encoding="utf-8") as f:
            raw = json.load(f)
        # each row is [name you say (the key), app, heard as, spoken name in replies or None, exe names]
        self.apps = []
        for k, v in raw.items():
            if isinstance(v, str):
                self.apps.append([k, v, [], None, []])
            else:
                exe = v.get("exe", [])
                self.apps.append([k, v["app"], list(v.get("heard_as", [])), v.get("say"),
                                  [exe] if isinstance(exe, str) else list(exe)])
        self._fill_apps()
        return page

    def _fill_apps(self):
        self.apps_table.delete(*self.apps_table.get_children())
        for row, (key, app, heard, _, exes) in enumerate(self.apps):
            self.apps_table.insert("", "end", iid=str(row), values=(key.replace("_", " "), app, ", ".join(exes), ", ".join(heard)))

    def _save_apps(self, message):
        lines = []
        for key, app, heard, say, exes in self.apps:
            if heard or say or exes:
                value = {"app": app, **({"say": say} if say else {}),
                         **({"exe": exes[0] if len(exes) == 1 else exes} if exes else {}),
                         **({"heard_as": heard} if heard else {})}
            else:
                value = app
            lines.append(f"  {json.dumps(key)}: {json.dumps(value, ensure_ascii=False)}")
        try:
            with open(APPS_FILE, "w", encoding="utf-8") as f:
                f.write("{\n" + ",\n".join(lines) + "\n}\n")  # one app per line, like the file you'd write by hand
            self.apps_message.configure(text=message, fg=MUTED)
        except Exception as exc:
            self.apps_message.configure(text=f"Couldn't save: {exc}", fg=ERROR)
        self._fill_apps()

    def add_app(self):
        say, app = self.new_say.get().strip(), self.new_app.get().strip()
        heard = split_list(self.new_heard.get())
        if not say or not app:
            self.apps_message.configure(text="Add the name you say and the app\u2019s name", fg=ERROR)
            return
        key = app_key(say)
        if any(row[0] == key for row in self.apps):
            self.apps_message.configure(text=f"{say} is already in the list", fg=ERROR)
            return
        found = win.find_start_app(app)
        self.apps.append([key, found[0] if found else app, heard, None, []])
        for field in (self.new_say, self.new_app, self.new_heard):
            field.clear()
        note = "" if found else f", but there's no \u201c{app}\u201d in the Start menu"
        self._save_apps(f"Added {say}{note}. Restart Jev to use it")
        self.new_say.focus_set()

    def remove_app(self):
        sel = self.apps_table.selection()
        if not sel:
            self.apps_message.configure(text="Pick an app in the list first", fg=ERROR)
            return
        name = self.apps.pop(int(sel[0]))[0].replace("_", " ")
        self._save_apps(f"Removed {name}, restart Jev to finish")

    # ------------------------------------------------------------------ history
    def _build_history(self):
        page = self._page("Dictation history", "Everything you\u2019ve dictated, newest first. Kept on this PC only.")
        frame, self.hist_table = self._table(page, (("time", "When", 130), ("text", "Text", 520)), editable=False)
        frame.pack(fill="both", expand=True)
        self.hist_message = self._bottom_bar(page, "Copy", self.copy_history)
        self.hist_table.bind("<Double-1>", lambda e: self.copy_history())
        self.history = []
        return page

    def _load_history(self):
        self.history = []
        if os.path.exists(HISTORY):
            with open(HISTORY, encoding="utf-8") as f:
                for line in f:
                    try:
                        item = json.loads(line)
                        self.history.append({"time": item["time"][:16], "text": item["text"]})
                    except (ValueError, KeyError):
                        continue  # skip a half-written line
        self.history.reverse()
        self.hist_table.delete(*self.hist_table.get_children())
        for row, item in enumerate(self.history):
            self.hist_table.insert("", "end", iid=str(row), values=(item["time"], item["text"].replace("\n", " ")))
        self.hist_message.configure(text="" if self.history else "Nothing yet. Say \u201cHey Jev, transcribe\u201d to start.", fg=MUTED)

    def copy_history(self):
        sel = self.hist_table.selection()
        if not sel:
            self.hist_message.configure(text="Pick one in the list first", fg=ERROR)
            return
        try:
            win.set_clipboard(self.history[int(sel[0])]["text"])
            self.hist_message.configure(text="Copied", fg=MUTED)
        except Exception as exc:
            self.hist_message.configure(text=str(exc), fg=ERROR)

    # ------------------------------------------------------------------ memory
    def _build_memory(self):
        page = self._page("Memory", "What she knows about you, read into everything you ask, her own notes and the "
                                    "skills she\u2019s learned. Say \u201cHey Jev, remember that \u2026\u201d, \u201cforget "
                                    "that \u2026\u201d, or teach her: \u201cwhen I say \u2026, do \u2026\u201d. Kept on this "
                                    "PC, the way Hermes Agent keeps its memory.")
        frame, self.mem_table = self._table(page, (("about", "About", 110), ("text", "What she remembers", 540)),
                                            editable=False)
        frame.pack(fill="both", expand=True)
        bar = tk.Frame(page, bg=BG)
        bar.pack(fill="x", pady=(self.px(10), 0))
        for i, (text, command) in enumerate((("Forget this", self.forget_memory),
                                             ("Edit personality", self.edit_personality),
                                             ("Open notes", self.open_notes), ("Open the folder", self.open_memory_folder),
                                             ("Clear conversations", self.clear_conversations))):
            ttk.Button(bar, text=text, command=command).pack(side="left", padx=(self.px(6) if i else 0, 0))
        self.mem_message = self._label(page, "", self.f_small, MUTED, wraplength=self.px(660))
        self.mem_message.pack(fill="x", pady=(self.px(6), 0))
        self.memories = []
        return page

    def _load_memory(self, message=None):
        store = hermes_memory.MemoryStore()
        try:
            store.load_from_disk()
            learned = skills.list_skills()
        except Exception as exc:
            self.mem_message.configure(text=f"Couldn't read her memory: {exc}", fg=ERROR)
            return
        self.memories = [("user", e) for e in store.user_entries] + [("memory", e) for e in store.memory_entries] + \
                        [("skill", s) for s in learned]
        self.mem_table.delete(*self.mem_table.get_children())
        about = {"user": "You", "memory": "Her notes", "skill": "Skill"}
        for row, (target, entry) in enumerate(self.memories):
            if target == "skill":  # "work-mode: Their work setup (you say: work mode)"
                says = ", ".join(f"\u201c{t}\u201d" for t in entry["triggers"])
                entry = f"{entry['name']}: {entry['description']}" + (f"  (you say {says})" if says else "")
            self.mem_table.insert("", "end", iid=str(row), values=(about[target], " ".join(entry.split())))
        try:
            turns = history.count()
        except Exception:
            turns = 0
        kept = f"She keeps what you say to her ({turns:,} so far) and can look back through it." if turns else ""
        empty = "" if self.memories else "Nothing yet. Say \u201cHey Jev, remember that \u2026\u201d. "
        self.mem_message.configure(text=message or (empty + kept), fg=MUTED)

    def forget_memory(self):
        sel = self.mem_table.selection()
        if not sel:
            self.mem_message.configure(text="Pick one in the list first", fg=ERROR)
            return
        target, entry = self.memories[int(sel[0])]
        if target == "skill":
            result = skills.delete_skill(entry["dir"], really=True)  # you asked: gone, not archived
        else:
            result = hermes_memory.memory_tool(hermes_memory.MemoryStore(), "remove", target, old_text=entry)
        if result.get("success"):
            self._load_memory("Forgotten")
        else:
            self.mem_message.configure(text=str(result.get("error") or "Couldn't forget that")[:120], fg=ERROR)

    def edit_personality(self):
        """Her SOUL.md in Notepad or whatever opens .md files: how she talks, read fresh for every request."""
        try:
            import siri  # loaded already, she's been listening since the window opened
            siri.soul()  # writes the default the first time
            os.startfile(siri.SOUL_PATH)
            self.mem_message.configure(text="Save the file and she talks that way from the next thing you ask. "
                                            "Delete it to go back to how she was.", fg=MUTED)
        except Exception as exc:
            self.mem_message.configure(text=f"Couldn't open it: {exc}", fg=ERROR)

    def open_notes(self):
        os.makedirs(NOTES_DIR, exist_ok=True)
        os.startfile(NOTES_DIR)

    def open_memory_folder(self):
        os.makedirs(win.APPDATA_DIR, exist_ok=True)
        os.startfile(win.APPDATA_DIR)  # her memory, skills, notes, personality and conversations

    def clear_conversations(self):
        if not messagebox.askyesno(TITLE, "Forget every conversation you've had with her? What she remembers about "
                                          "you stays.", parent=self.root):
            return
        try:
            history.clear()
            self._load_memory("Conversations cleared")
        except Exception as exc:
            self.mem_message.configure(text=str(exc), fg=ERROR)

    # ------------------------------------------------------------------ privacy
    def _build_privacy(self):
        page = self._page("Privacy", "In Hey Jev mode the mic is always on, but it\u2019s heard on your PC first. Only this ever leaves it.",
                          scroll=True)
        for title, body in PRIVACY:
            self._label(page, title, self.f_h2).pack(fill="x", pady=(self.px(4), 0))
            self._label(page, body, fg=MUTED, wraplength=self.px(660)).pack(fill="x", pady=(0, self.px(12)))
        return page

    # ------------------------------------------------------------------ settings
    def _build_settings(self):
        page = self._page("Settings", "The microphone Jev listens with, the models she uses, and the window.", scroll=True)
        form = tk.Frame(page, bg=BG)
        form.pack(fill="x")
        form.grid_columnconfigure(0, weight=1)

        def row(r, title, sub):
            self._label(form, title, self.f_h2).grid(row=r * 2, column=0, sticky="w", pady=(self.px(12), 0))
            label = self._label(form, sub, self.f_small, MUTED, wraplength=self.px(310))
            label.grid(row=r * 2 + 1, column=0, sticky="w")
            return label

        self.mic_sub = row(0, "Microphone", MIC_SUB)
        self.mic_menu = ttk.Combobox(form, state="readonly", width=38)
        self.mic_menu.grid(row=0, column=1, rowspan=2, sticky="e")
        self.mic_menu.bind("<<ComboboxSelected>>", lambda e: self.mic_changed())

        row(1, "Answer model", "Free model on OpenCode Zen or Kilo that works out what you asked and answers. "
                               "Refresh lists the free ones that answer here, fastest first.")
        models = tk.Frame(form, bg=BG)
        models.grid(row=2, column=1, rowspan=2, sticky="e")
        self.llm_menu = ttk.Combobox(models, width=29, values=opencode.FALLBACK_FREE)
        self.llm_menu.set(settings.get("llm_model"))
        self.llm_menu.pack(side="left")
        ttk.Button(models, text="Refresh", command=self.refresh_models).pack(side="left", padx=(self.px(6), 0))
        for event in ("<<ComboboxSelected>>", "<Return>", "<FocusOut>"):
            self.llm_menu.bind(event, lambda e: self.model_changed("llm_model", self.llm_menu))

        row(2, "Speech to text", "Turns what you say into text, on this PC. Nemotron shows your words as you talk, "
                                 "but it lost \u201cHey Jev\u201d in a real voice. Takes effect when Hey Jev next starts.")
        self.stt_menu = ttk.Combobox(form, state="readonly", width=38, values=list(ENGINES.values()))
        self.stt_menu.set(ENGINES.get(settings.get("stt_engine"), ENGINES["parakeet"]))
        self.stt_menu.grid(row=4, column=1, rowspan=2, sticky="e")
        self.stt_menu.bind("<<ComboboxSelected>>", lambda e: self.engine_changed())

        row(3, "Hear me over videos", "Windows takes what the PC is playing out of the mic, so she hears you over "
                                      "YouTube and music. Turn it off if she stops hearing you.")
        self.echo_var = tk.BooleanVar(value=bool(settings.get("echo_cancel")))
        ttk.Checkbutton(form, text="Echo cancelling", variable=self.echo_var,
                        command=self.echo_changed).grid(row=6, column=1, rowspan=2, sticky="e")

        row(4, "Keep on top", "Keeps this window above other apps. Ctrl+T switches it too.")
        self.on_top_var = tk.BooleanVar(value=self.on_top)
        ttk.Checkbutton(form, text="Keep window on top", variable=self.on_top_var,
                        command=lambda: self.toggle_on_top(self.on_top_var.get())).grid(row=8, column=1, rowspan=2, sticky="e")

        row(5, "Popup", "A small pill at the bottom of the screen: listening, what she heard, thinking, and what "
                        "she's saying. Dictation always shows it.")
        self.popup_var = tk.BooleanVar(value=self.popup)
        ttk.Checkbutton(form, text="Show the popup", variable=self.popup_var,
                        command=self.popup_changed).grid(row=10, column=1, rowspan=2, sticky="e")

        row(6, "Start with Windows", "Opens Hey Jev, minimised, when you sign in.")
        self.startup_var = tk.BooleanVar(value=win.starts_with_windows())
        ttk.Checkbutton(form, text="Start when I sign in", variable=self.startup_var,
                        command=self.startup_changed).grid(row=12, column=1, rowspan=2, sticky="e")

        row(7, "Welcome", "When you sign in or come back to the laptop she says hello, by this name, and asks what "
                          "she can do. Just answer, no \u201cHey Jev\u201d needed.")
        welcome = tk.Frame(form, bg=BG)
        welcome.grid(row=14, column=1, rowspan=2, sticky="e")
        name_box = HintEntry(welcome, "Your name", width=16)
        if settings.get("name"):
            name_box._hide_hint()
            name_box.insert(0, settings.get("name"))
        name_box.pack(side="left")
        for event in ("<Return>", "<FocusOut>"):
            name_box.bind(event, lambda e: self.name_changed(name_box.get()), add="+")
        self.welcome_var = tk.BooleanVar(value=bool(settings.get("welcome")))
        ttk.Checkbutton(welcome, text="Say hello", variable=self.welcome_var,
                        command=lambda: settings.put("welcome", self.welcome_var.get())).pack(side="left",
                                                                                              padx=(self.px(8), 0))

        row(8, "Voice", "Her voice, on Fish Audio\u2019s free model until 30 November, then made on this PC (Jev on "
                        "this PC). Try it plays a line. To use any other Fish voice, paste its link from fish.audio.")
        voice = tk.Frame(form, bg=BG)
        voice.grid(row=16, column=1, rowspan=2, sticky="e")
        self.voice_menu = ttk.Combobox(voice, width=24, values=[self._voice_label(v) for _, v, _ in settings.VOICES])
        self.voice_menu.set(self._voice_label(settings.get("voice")))
        self.voice_menu.pack(side="left")
        ttk.Button(voice, text="Try it", command=self.try_voice).pack(side="left", padx=(self.px(6), 0))
        for event in ("<<ComboboxSelected>>", "<Return>", "<FocusOut>"):
            self.voice_menu.bind(event, lambda e: self.voice_changed())

        row(9, "Vision", "When you ask about the screen, or for something she has to see like \u201cclick the "
                         "second video\u201d, she looks at a screenshot of it and acts on it. Never otherwise.")
        self.vision_var = tk.BooleanVar(value=bool(settings.get("vision")))
        ttk.Checkbutton(form, text="Let her see the screen", variable=self.vision_var,
                        command=lambda: settings.put("vision", self.vision_var.get())).grid(row=18, column=1,
                                                                                            rowspan=2, sticky="e")
        self.switches = {}
        for r, (key, title, sub, text) in enumerate((
                ("no_name", "Without her name", "No \u201cHey Jev\u201d needed: she listens all the time, and the "
                 "answer model works out whether you were talking to her or to someone else. What\u2019s said that "
                 "could be a request goes to it as text.", "Answer without her name"),
                ("call_aware", "During calls", "When WhatsApp, Teams, Zoom, Discord or a browser call has the mic, "
                 "unnamed speech is for the call. Say Jev or Jarvis to talk to her.", "Require her name on calls"),
                ("heads_ups", "Heads-ups", "She speaks up when something needs you: the battery at 20 and 10 "
                 "percent, the C drive nearly full, the PC flat out for a while, the internet going, a new message. "
                 "Quiet from 11 at night to 7 in the morning, except a nearly flat battery.", "Tell me"),
                ("notifications", "Notifications", "She reads the Windows notification list on this PC, for \u201cany "
                 "new messages?\u201d, welcome back and heads-ups. Phone Link brings in your phone\u2019s WhatsApp "
                 "and texts.", "Read my notifications"),
                ("learning", "Learning", "After a correction, or a task that took a few steps, she looks back over it "
                 "and keeps what she learned: a fact, a routine, a word she misheard. It all shows in the Memory tab.",
                 "Learn as she goes")), start=10):
            row(r, title, sub)
            var = self.switches[key] = tk.BooleanVar(value=bool(settings.get(key)))
            ttk.Checkbutton(form, text=text, variable=var, command=lambda k=key, v=var: settings.put(k, v.get())
                            ).grid(row=r * 2, column=1, rowspan=2, sticky="e")
        row(15, "Your voice", "She answers only you, not other people, the TV or a video. Press Learn, or say "
                              "“Hey Jev, learn my voice”, and read her 10 short sentences. She learns your "
                              "voice for a few days first. The recordings stay on this PC.")
        yours = tk.Frame(form, bg=BG)
        yours.grid(row=30, column=1, rowspan=2, sticky="e")
        self.voice_id_var = tk.BooleanVar(value=settings.get("voice_id") != "off")
        ttk.Checkbutton(yours, text="Only answer my voice", variable=self.voice_id_var,
                        command=self.voice_id_changed).pack(side="left")
        ttk.Button(yours, text="Learn", command=self.learn_voice).pack(side="left", padx=(self.px(6), 0))
        self.settings_note = self._label(page, "", self.f_small, MUTED, wraplength=self.px(660))
        self.settings_note.pack(fill="x", pady=(self.px(18), 0))
        self.models_loaded = False
        return page

    def _load_mics(self):
        names = win.input_devices()
        _, auto = win.auto_input()
        self.mic_names = names
        self.mic_menu.configure(values=[f"Automatic ({auto})"] + [
            n + ("  (PC sound only)" if "stereo mix" in n.lower() else "") for n in names])
        if self.mic in names:
            self.mic_menu.current(names.index(self.mic) + 1)
            self._mic_note()
        else:
            self.mic_menu.current(0)
            self.mic_sub.configure(text=MIC_SUB, fg=MUTED)
            gone = f"{self.mic} isn\u2019t plugged in, so " if self.mic else ""
            self._note(f"{gone}Microphone: {auto}. Automatic skips Stereo Mix, which only hears what the PC plays.")

    def mic_changed(self):
        i = self.mic_menu.current()
        self.mic = "" if i <= 0 else self.mic_names[i - 1]
        settings.put("mic", self.mic)
        self.controls.put(("mic", self.mic))
        self._load_mics()

    def _mic_note(self):
        self._note(f"Microphone: {self.mic}")
        if "stereo mix" in self.mic.lower():  # it records the speakers, never the person talking
            self.mic_sub.configure(text="Stereo Mix only hears what the PC plays, so she can\u2019t hear you. Pick "
                                        "Automatic or your microphone to talk to her.", fg=ERROR)
        else:
            self.mic_sub.configure(text=MIC_SUB, fg=MUTED)

    def echo_changed(self):
        on = self.echo_var.get()
        settings.put("echo_cancel", on)
        self.controls.put(("mic", self.mic))  # opens the mic again, the new way
        self._note("Echo cancelling on, she hears you over videos and music" if on else
                   "Echo cancelling off. While a video plays, say \u201cHey Jev\u201d close to the mic, or hold right Alt")

    def learn_voice(self):
        self.controls.put("learn voice")
        self._note("Read her each sentence in the popup, one at a time. Say “stop” to stop.")

    def voice_id_changed(self):
        import voiceid
        if not self.voice_id_var.get():
            settings.put("voice_id", "off")
            self._note("She answers everyone again.")
            return
        profile = voiceid.Profile()
        if not profile.ready:  # she needs your voice first; reading the sentences turns it on
            self.voice_id_var.set(False)
            self.learn_voice()
            return
        settings.put("voice_id", "on" if profile.calibrated else "learning")
        self.controls.put("voice on")
        self._note("She answers only you." if profile.calibrated else
                   "She's learning your voice for a few days, then she'll answer only you.")

    @staticmethod
    def _voice_label(voice):
        """"Hannah · friendly and clear" for a voice in the list, else the ID itself."""
        voice = voice or settings.VOICES[0][1]
        return next((f"{name} \u00b7 {about}" for name, v, about in settings.VOICES if v == voice), voice)

    @staticmethod
    def _voice_id(text):
        """The voice ID for what's in the voice box: one from the list, or a pasted link or ID. None if neither."""
        t = (text or "").strip()
        for name, v, about in settings.VOICES:
            if t.lower() in (name.lower(), f"{name} \u00b7 {about}".lower()):
                return v
        if t.lower().startswith(("onecore:", "sapi:", "pocket:")):
            return t
        m = re.search(r"[0-9a-f]{32}", t.lower())
        return m[0] if m else None

    def voice_changed(self):
        voice = self._voice_id(self.voice_menu.get())
        if not voice:
            self.voice_menu.set(self._voice_label(settings.get("voice")))
            self._note("That isn\u2019t a recognized voice. Pick one from the list, or paste a voice ID.", error=True)
            return
        self.voice_menu.set(self._voice_label(voice))
        if voice == (settings.get("voice") or settings.VOICES[0][1]):
            return
        settings.put("voice", voice)
        self._note("Voice saved. Her usual replies are made again in it in the background, so for a few minutes some "
                   "may start a moment later.")
        siri = sys.modules.get("siri")
        if siri:
            threading.Thread(target=siri.warm_cache, daemon=True).start()

    def try_voice(self):
        voice = self._voice_id(self.voice_menu.get())
        if not voice:
            self._note("Pick a voice first, or paste a voice\u2019s link from fish.audio.", error=True)
            return
        name = settings.get("name")
        line = f"Hi{' ' + name if name else ''}, this is how I'd sound. Anything you'd like me to do?"
        self._note("Playing a line\u2026")

        def play():
            try:
                import siri
                siri.speak(line, voice=voice)
                self.events.put(("note", "", False))
            except Exception as exc:
                self.events.put(("note", f"Couldn\u2019t play it: {exc}", True))
        threading.Thread(target=play, daemon=True).start()

    def startup_changed(self):
        on = self.startup_var.get()
        try:
            win.set_start_with_windows(on)
            self._note("Hey Jev starts when you sign in" if on else "Hey Jev won't start by itself any more")
        except OSError as exc:
            self.startup_var.set(win.starts_with_windows())
            self._note(f"Couldn't change that: {exc}", error=True)

    def name_changed(self, name):
        name = " ".join(name.split())
        if name == (settings.get("name") or ""):
            return
        settings.put("name", name)
        self._note(f"She'll call you {name}" if name else "She won't use a name")

    def popup_changed(self):
        self.popup = self.popup_var.get()
        settings.put("popup", self.popup)
        if not self.popup:
            self.bubble.hide()

    def engine_changed(self):
        engine = list(ENGINES)[self.stt_menu.current()]
        settings.put("stt_engine", engine)
        self._note(f"Saved. Quit Hey Jev and open it again to switch to {ENGINES[engine]}.")

    def model_changed(self, name, box):
        value = box.get().strip()
        if value == (settings.get(name) or ""):
            return
        if value and not opencode.is_free(value):  # free only, a paid model never gets saved
            box.set(settings.get(name))
            self._note(f"{value} isn't free. Hey Jev only uses free models, the ones ending in -free or :free.",
                       error=True)
            return
        settings.put(name, value)
        box.set(settings.get(name))  # an emptied box goes back to the default
        model = settings.get(name)
        key = get_secret("OPENCODE_ZEN_API_KEY")
        if not key:
            self._note(f"Saved, she now thinks with {model}")
            return
        self._note(f"Saved, checking {model} answers\u2026")

        def check():
            ok, result = opencode.check_model(key, model)
            self.events.put(("note", f"{model} answered in {result:.1f}s" if ok else f"{model}: {result}", not ok))
        threading.Thread(target=check, daemon=True).start()

    def refresh_models(self):
        key = get_secret("OPENCODE_ZEN_API_KEY")
        self._note("Checking which free models answer here\u2026" if key else "Getting the list from OpenCode\u2026")

        def fetch():
            try:
                working, free = opencode.working_free_models(key) if key else (None, opencode.free_chat_models())
                self.events.put(("models", working, free))
            except Exception as exc:
                self.events.put(("note", f"Couldn't get the model list: {exc}", True))
        threading.Thread(target=fetch, daemon=True).start()

    def _note(self, text, error=False):
        self.settings_note.configure(text=text, fg=ERROR if error else MUTED)

    def _show_models(self, working, free):
        """working is None without a key to check with, else the free models that answered, fastest first."""
        current = settings.get("llm_model")
        if working is None:
            self.llm_menu.configure(values=free or opencode.FALLBACK_FREE)
            self._note(f"{len(free)} free models on OpenCode. Add your OpenCode key in Keys to check which answer here.")
            return
        self.llm_menu.configure(values=working or free)
        if not working:
            self._note("None of OpenCode's free models answer outside OpenCode right now, so only simple commands like "
                       "\u201copen Notepad\u201d or \u201cpause\u201d work.", error=True)
        elif current not in working and opencode.is_free(current):
            self._note(f"{current} doesn't answer here any more, pick one from the list. Working now: "
                       f"{', '.join(working)}", error=True)
        else:
            self._note(f"{len(working)} of {len(free)} free models answer here, fastest first: {', '.join(working)}. "
                       "The rest are busy, or only run inside OpenCode itself.")

    # ------------------------------------------------------------------ keys
    def _build_keys(self):
        page = self._page("Keys", "Saved in Windows Credential Manager. A key in .env wins over these. Saved keys stay hidden.")
        form = tk.Frame(page, bg=BG)
        form.pack(fill="x")
        form.grid_columnconfigure(0, weight=1)
        self.key_fields = {}
        for i, (title, key_name, use, url) in enumerate(KEY_ROWS):
            head = tk.Frame(form, bg=BG)
            head.grid(row=i * 2, column=0, sticky="w", pady=(self.px(12), 0))
            self._label(head, title, self.f_h2).pack(side="left")
            self._link(head, "Get a key", url).pack(side="left", padx=(self.px(8), 0))
            self._label(form, use, self.f_small, MUTED).grid(row=i * 2 + 1, column=0, sticky="w")
            hint = "Already saved" if get_secret(key_name) else ("Optional" if key_name in OPTIONAL else "Paste key")
            field = HintEntry(form, hint, secure=True, width=40)
            field.grid(row=i * 2, column=1, rowspan=2, sticky="e", pady=(self.px(12), 0))
            field.bind("<Return>", lambda e: self.save_keys())
            self.key_fields[key_name] = field
        bar = tk.Frame(page, bg=BG)
        bar.pack(fill="x", pady=(self.px(20), 0))
        ttk.Button(bar, text="Save keys", command=self.save_keys).pack(side="right")
        self.keys_message = self._label(bar, "", self.f_small, ERROR)
        self.keys_message.pack(side="left")
        return page

    def save_keys(self):
        try:
            for key_name in KEY_NAMES:
                field = self.key_fields[key_name]
                value = field.get()
                if value:
                    save_secret(key_name, value)
                    field.clear()
                    field.set_hint("Already saved")
            still_missing = missing_secrets()
            if still_missing:
                names = ", ".join(n.replace("_API_KEY", "").replace("_", " ").title() for n in still_missing)
                self.keys_message.configure(text=f"Still needed: {names}", fg=ERROR)
                return
            from siri import reload_keys
            reload_keys()
            self.keys_message.configure(text="Saved", fg=MUTED)
            self._start_worker()
        except Exception as exc:
            self.keys_message.configure(text=str(exc), fg=ERROR)

    # ------------------------------------------------------------------ tabs
    def _select_tab(self, key):
        if key == "tasks":
            self._load_tasks()
        if key == "contacts":
            self._load_contacts()
        if key == "hist":
            self._load_history()
        if key == "mem":
            self._load_memory()
        if key == "home":
            self._load_stats()
        if key == "settings":
            self._load_mics()
            if not self.models_loaded:
                self.models_loaded = True
                self.refresh_models()
        self.current_tab = key
        getattr(self.pages[key], "outer", self.pages[key]).tkraise()
        for name, b in self.tab_buttons.items():
            on = name == key
            b.configure(bg=SELECT if on else SIDE, font=self.f_bold if on else self.f_body)

    # ------------------------------------------------------------------ assistant
    def _start_worker(self):
        if self.worker_started:
            return
        self.worker_started = True
        threading.Thread(target=self._run_assistant, daemon=True).start()

    def _run_assistant(self):
        try:
            from siri import run_voice_assistant
            run_voice_assistant(self.notify, self.controls, self.mode, self.mic)
        except Exception as exc:
            print(f"assistant stopped: {exc}")
            self.notify("Something went wrong", str(exc))

    def notify(self, state, detail=""):
        """Called from the assistant's threads, Tk is only touched from the main thread in _drain."""
        self.events.put(("status", state, detail))

    def _drain(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "status":
                    self._set_status(event[1], event[2])
                elif event[0] == "note":
                    self._note(event[1], error=event[2])
                elif event[0] == "models":
                    self._show_models(*event[1:])
        except queue.Empty:
            pass
        self.root.after(50, self._drain)

    def _set_status(self, state, detail):
        self.status.configure(text=state)
        if detail is not None:  # None keeps what's there, like her last reply
            detail = " ".join(str(detail).split())
            self.detail.configure(text=detail if len(detail) <= 110 else detail[:109] + "\u2026")
        self.dot.configure(fg=STATUS_COLORS.get(state, TEXT))
        pill = PILL.get(state)
        if pill and (self.popup or pill in ("dictating", "finishing")):
            # "Go ahead" and "Let go of right Alt" are for the window, the popup says Listening
            hint = state == "Listening" and str(detail or "").startswith(("Go ahead", "Let go"))
            self.bubble.show(pill, None if hint else detail)
            if pill == "error":
                self.bubble.hide(3000)
        else:
            self.bubble.hide(900 if state == "Ready" else 0)

    def _tick(self):
        siri = sys.modules.get("siri")
        timers = siri.timer_snapshot()[:3] if hasattr(siri, "timer_snapshot") else []  # siri may still be loading
        for i, (row, name, left) in enumerate(self.timer_rows):
            if i < len(timers):
                label, secs = timers[i]
                m, sec = divmod(int(secs + 0.999), 60)
                h, m = divmod(m, 60)
                name.configure(text=label if len(label) <= 18 else label[:17] + "\u2026")
                left.configure(text=f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}")
                if not row.winfo_ismapped():
                    row.pack(fill="x", before=self.hint)
            elif row.winfo_ismapped():
                row.pack_forget()
        self.root.after(500, self._tick)

    def set_mode(self, mode):
        if mode == self.mode:
            return
        self.mode = mode
        settings.put("mode", mode)
        self.hint.configure(text=HINTS[mode])
        self._paint_mode()
        self.controls.put(("mode", mode))

    def toggle_on_top(self, value=None):
        self.on_top = (not self.on_top) if value is None else bool(value)
        settings.put("keep_on_top", self.on_top)
        self.root.attributes("-topmost", self.on_top)
        self.on_top_var.set(self.on_top)

    def quit(self):
        self.bubble.close()
        self.root.destroy()


def run_app():
    win.prepare_gui()  # before Tk starts, so text is sharp on scaled screens
    if not win.single_instance():
        win.show_existing(TITLE)  # already running with the window closed, bring it back
        return
    root = tk.Tk()
    AssistantWindow(root)
    if "--startup" in sys.argv:  # started as you signed in: on the taskbar, she says hello and listens
        root.after(300, root.iconify)
    root.mainloop()
    sys.stdout.flush()
    os._exit(0)  # the mic, keyboard hook and speech threads all stop with the app
