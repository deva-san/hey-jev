"""Hey Jev's messaging: open the chat with the text typed in, read it back, and send only after a yes.

Two deliberate choices, both for safety:

- The recipient comes from your own contacts book (%APPDATA%\\Hey Jev\\contacts.json), as a phone number or
  username, and the chat is opened with the app's own link (whatsapp://send, tg://resolve). Searching a chat list
  by a name she heard could land on the wrong person; a number cannot.
- Nothing is ever sent until you say yes. The link only types the text into the compose box.

She learns as she goes: the first time you name someone she asks once, saves the alias, and from then on
"message Mum on WhatsApp: hi" is one step.

Apps with no link of their own (Signal, Slack, Discord and the rest) take the long way round, the way you would:
bring the app up, press its search shortcut, type the name, open the chat, type the message, stop. She can't read
any of that back, so your yes is confirming the chat as well as the words. That yes is also what teaches her: the
shortcut that worked and the name that found the person are saved, so the next one is a single sentence.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import subprocess
import time
from ctypes import wintypes as w
from urllib.parse import quote

import winplatform as win

CONTACTS_PATH = os.path.join(win.APPDATA_DIR, "contacts.json")
MAX_TEXT = 1000
user32 = ctypes.WinDLL("user32", use_last_error=True)

# Each app: how to say it, the program its window runs as, the link that opens a chat with the text typed in, what
# the link needs, and what UI Automation can read in it (None: nothing readable, see verify)
APPS = {
    "whatsapp": {
        "say": "WhatsApp",
        "exes": ("WhatsApp.exe", "WhatsApp.Root.exe"),
        "classes": ("WinUIDesktopWin32WindowClass",),
        "link": "whatsapp://send?phone={id}&text={text}",
        "needs": "number",
        # its message box is a real element, named "Type a message to Amma" in the 2025 app ("Type a message"
        # before), and a Reconnect button means the desktop app has no link to the phone
        "compose": "Type a message",
        "offline_button": "Reconnect",
    },
    "telegram": {
        "say": "Telegram",
        "exes": ("Telegram.exe",),
        "classes": ("Qt51519QWindowIcon", "Qt5QWindowIcon", "Qt6QWindowIcon"),
        "link": "tg://resolve?domain={id}&text={text}",
        "needs": "username",
        "compose": None,  # Telegram draws its own interface, so Windows exposes nothing inside it
        "offline_button": None,
    },
}
ALIASES = {"whats app": "whatsapp", "whatsup": "whatsapp", "whats up": "whatsapp", "watsapp": "whatsapp",
           "telegramme": "telegram", "telegraph": "telegram"}

# --------------------------------------------------------------------------- apps with no link of their own
RECIPES_PATH = os.path.join(win.APPDATA_DIR, "recipes.json")
OTHER_MAX_TEXT = 300  # typed on the keyboard rather than handed over in a link, so keep it to a message
# Nearly every chat app works the same way: a shortcut puts the cursor in search, the name finds the person,
# Enter opens their chat, Enter sends. She tries this, you look at the screen, and your yes is what saves it.
DEFAULT_RECIPE = {"search": ["ctrl", "f"], "pick": ["enter"], "settle": 1.2}  # long enough for results to appear
FIRST_TRY = {"slack": ["ctrl", "k"], "discord": ["ctrl", "k"], "element": ["ctrl", "k"],
             "signal": ["ctrl", "f"], "teams": ["ctrl", "e"]}  # what each one actually uses, where it's known
MODS = {"ctrl", "alt", "shift", "cmd"}
SPECIAL = {"enter", "tab", "esc", "space", "backspace", "delete", "up", "down", "left", "right", "home", "end"}


class NeedContact(RuntimeError):
    """She doesn't know who that is yet. The message says what to ask for."""


def app_key(name):
    key = re.sub(r"[^a-z]+", "", str(name or "").lower())
    if key in APPS:
        return key
    spoken = " ".join(str(name or "").lower().split())
    return ALIASES.get(spoken) or ALIASES.get(key)


def other_key(name):
    """The name of an app with no link, flattened so "VS Code" and "vscode" are the same app."""
    return re.sub(r"[^a-z0-9]+", "", str(name or "").lower())


def needs_of(app):
    """What she needs to reach someone there: a phone number, a username, or a name to type into search."""
    spec = APPS.get(app)
    return spec["needs"] if spec else "search"


def say_of(app):
    spec = APPS.get(app)
    if spec:
        return spec["say"]
    return (read_recipes().get(app) or {}).get("say") or str(app or "that app").title()


def clean_number(value):
    """A phone number as WhatsApp's link wants it: digits only, with the country code."""
    digits = re.sub(r"\D", "", str(value or ""))
    if not 7 <= len(digits) <= 15:
        raise ValueError("that doesn't look like a phone number with its country code")
    return digits


def clean_username(value):
    name = str(value or "").strip().lstrip("@")
    if not re.fullmatch(r"[A-Za-z0-9_]{4,32}", name):
        raise ValueError("a Telegram username is 4 to 32 letters, numbers or underscores")
    return name


def clean_search(value):
    """A name to type into an app's search box: just the name, on one line."""
    name = " ".join(str(value or "").split())
    name = "".join(c for c in name if c.isprintable())
    if not name or not re.search(r"\w", name):
        raise ValueError("I need a name to look for")
    return name[:60]


def clean_handle(app, value):
    want = needs_of(app)
    return clean_number(value) if want == "number" else clean_username(value) if want == "username" \
        else clean_search(value)


def clean_text(value):
    text = " ".join(str(value or "").split())
    text = "".join(c for c in text if c.isprintable())
    if not text:
        raise ValueError("there's nothing to send")
    return text[:MAX_TEXT]


# Speech-to-text writes the same person more than one way: Nemotron heard "Message Mum" as "Message Mom"
# not "mama": in Telugu, Tamil and Hindi that's an uncle, and his number would have gone in as Mum's
SAME_PERSON = {"mom": "mum", "mommy": "mum", "mummy": "mum", "mumma": "mum",
               "amma": "mum", "ammi": "mum", "dad": "dad", "daddy": "dad", "papa": "dad", "pappa": "dad",
               "appa": "dad", "abbu": "dad"}


def alias_key(name):
    words = re.sub(r"[^\w\s']+", " ", str(name or "").lower()).split()
    words = [w for w in words if w not in ("my", "the")] or words  # "my mum" is mum
    return " ".join(SAME_PERSON.get(w, w) for w in words)


# --------------------------------------------------------------------------- the contacts book
def read_contacts():
    try:
        with open(CONTACTS_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_contact(alias, app, handle):
    """Remember who someone is, so the next message to them is one step. Returns how she'd say it."""
    key = alias_key(alias)
    app = app_key(app) or next((k for k in (other_key(app),) if k in read_recipes()), None)
    if not key or app is None:
        raise ValueError("I need a name and an app I know")
    handle = clean_handle(app, handle)
    book = read_contacts()
    entry = book.setdefault(key, {"name": " ".join(str(alias).split())[:60]})
    entry[app] = handle
    _write_json(CONTACTS_PATH, book)
    return f"{entry['name']} on {say_of(app)}"


def _write_json(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)


def forget_contact(alias):
    book = read_contacts()
    if book.pop(alias_key(alias), None) is None:
        return False
    _write_json(CONTACTS_PATH, book)
    return True


def find_contact(alias, app):
    """(display name, handle) for someone in the book, or NeedContact with what to ask for."""
    key, book = alias_key(alias), read_contacts()
    entry = book.get(key)
    if entry is None:  # "mum" vs "my mum", and nicknames inside a longer name, by whole words only: "ravi" inside
        # "ravindra" would send Ravindra's message to Ravi, and Supriya's to Priya
        hits = [v for k, v in book.items() if k and (f" {k} " in f" {key} " or f" {key} " in f" {k} ")]
        entry = hits[0] if len(hits) == 1 else None
    want = needs_of(app)
    if entry is None or not entry.get(app):
        said = " ".join(str(alias).split())[:40] or "them"
        if want == "search":  # nothing to ask for: she types the name you said and you check the chat she lands on
            return said, clean_search(alias)
        asked = "phone number, with the country code" if want == "number" else f"{say_of(app)} username"
        raise NeedContact(f"I don't know {said} on {say_of(app)} yet. What's their {asked}?")
    return entry.get("name") or said_name(key), entry[app]


def said_name(key):
    return key.title() if key else "them"


def known_for(app):
    """The names she can message on an app, for the model and the window."""
    return sorted((v.get("name") or k).strip() for k, v in read_contacts().items() if v.get(app))


# --------------------------------------------------------------------------- the people she's messaging for you
# Everyone she sends a message or a file to for you, so a reply from them is told to you as theirs, on the PC and on
# your phone, whenever it comes (asked for on 8 October: "all days, 24/7"; see watch.Watcher and siri.replied). Kept
# in %APPDATA%\Hey Jev\follow_ups.json, on this PC only, until FOLLOW_MAX newer ones push it out.
FOLLOW_PATH = os.path.join(win.APPDATA_DIR, "follow_ups.json")
FOLLOW_MAX = 200


def read_follows():
    try:
        with open(FOLLOW_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def follow(app, contact, to="", handle=""):
    """Note that she messaged contact (what you call them) on app (as Windows' notifications name it: "WhatsApp"), by
    the name a notification of theirs carries: the chat's own name in the app (to), and their number. Only where the
    app can't show the chat's name (Telegram, the apps she types her way into) by what you call them."""
    chat = " ".join(str(to or "").split())
    names = [n for n in dict.fromkeys((chat or " ".join(str(contact or "").split()), str(handle or ""))) if _letters(n)]
    if not names:
        return
    book = read_follows()
    book[f"{other_key(app)}:{alias_key(contact) or _letters(names[0])}"] = {
        "app": str(app), "contact": " ".join(str(contact or names[0]).split())[:60], "names": names[:2],
        "by_alias": not chat, "when": time.time()}
    if len(book) > FOLLOW_MAX:  # the ones messaged longest ago go first
        book = dict(sorted(book.items(), key=lambda kv: kv[1].get("when", 0))[-FOLLOW_MAX:])
    _write_json(FOLLOW_PATH, book)


def followed(app, sender):
    """The person she's been messaging for you that a notification on app from sender is, or None. By the chat's own
    name, spaces and case aside but emoji kept ("Buntyyy🐼" is "Buntyyy 🐼", not "Buntyyy 🎂"), or by their number:
    never by a shorter name, as your "Ravi" is Ravi Kumar, and another Ravi isn't."""
    got, digits = _chat_key(sender), re.sub(r"\D", "", str(sender or ""))
    number = len(digits) >= 7 and re.fullmatch(r"[\d\s()+.-]+", str(sender or "").strip())
    if not _letters(sender):
        return None

    def same(entry, name):
        if number:
            return re.sub(r"\D", "", name) == digits
        return (_letters(name) == _letters(sender)) if entry.get("by_alias") else _chat_key(name) == got
    hits = [entry for entry in read_follows().values() if str(entry.get("app", "")).casefold() == str(app).casefold()
            and any(same(entry, n) for n in entry.get("names") or [])]
    # one chat you've called two things ("buntyy", then "buntyyy"): who you messaged last
    return max(hits, key=lambda e: e.get("when", 0)) if hits else None


# --------------------------------------------------------------------------- the recipes she's been taught
def read_recipes():
    try:
        with open(RECIPES_PATH, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def clean_keys(keys, fallback):
    """A shortcut she may press: up to three modifiers and one ordinary key. Anything else falls back."""
    names = [str(k).strip().lower() for k in (keys or []) if str(k).strip()]
    if not names or len(names) > 4:
        return list(fallback)
    *mods, last = names
    if any(m not in MODS for m in mods):
        return list(fallback)
    if not ((len(last) == 1 and last.isalnum()) or last in SPECIAL):
        return list(fallback)
    return names


def recipe_for(app):
    """How to reach a chat in that app: what she was taught, else what it's known to use, else the usual way."""
    saved = read_recipes().get(app) or {}
    first = FIRST_TRY.get(app, DEFAULT_RECIPE["search"])
    settle = saved.get("settle", DEFAULT_RECIPE["settle"])
    try:
        settle = min(3.0, max(0.3, float(settle)))
    except (TypeError, ValueError):
        settle = DEFAULT_RECIPE["settle"]
    return {"search": clean_keys(saved.get("search"), first),
            "pick": clean_keys(saved.get("pick"), DEFAULT_RECIPE["pick"]),
            "settle": settle, "taught": bool(saved.get("uses"))}


def save_recipe(app, say, recipe):
    """Keep what just worked, so the next message in that app is one sentence."""
    book = read_recipes()
    entry = book.setdefault(app, {})
    entry.update(say=str(say or "").strip()[:40] or app.title(), search=list(recipe["search"]),
                 pick=list(recipe["pick"]), settle=recipe["settle"], uses=int(entry.get("uses") or 0) + 1,
                 learned=time.strftime("%Y-%m-%d"))
    _write_json(RECIPES_PATH, book)
    return entry


def forget_recipe(app):
    book = read_recipes()
    if book.pop(other_key(app), None) is None:
        return False
    _write_json(RECIPES_PATH, book)
    return True


def learned_apps():
    """The apps she's worked out how to message in, for the model and the window."""
    return sorted((v.get("say") or k) for k, v in read_recipes().items() if v.get("uses"))


# --------------------------------------------------------------------------- the app's window
def window_of(app):
    """The messaging app's main window, or None. Its own tray window and helpers are skipped by class."""
    spec = APPS[app]
    wanted = {e.lower() for e in spec["exes"]}
    found = []

    def visit(hwnd, _):
        cls = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, cls, 256)
        if cls.value in spec["classes"] and os.path.basename(win.window_exe(hwnd)).lower() in wanted:
            found.append(hwnd)
        return True

    user32.EnumWindows(ctypes.WINFUNCTYPE(w.BOOL, w.HWND, w.LPARAM)(visit), 0)
    return found[0] if found else None


def again(fn, tries=3, pause=0.4):
    """fn(), tried again a moment later on a COM error: WhatsApp's web view answers UI Automation with "An event
    was unable to invoke any of the subscribers" now and then while it redraws, or "NULL COM pointer access": never
    tried again, that left a message unchecked after Enter. The last error if it never works."""
    for i in range(tries):
        try:
            return fn()
        except Exception as exc:
            if not ("COMError" in type(exc).__name__ or "NULL COM pointer" in str(exc)) or i == tries - 1:
                raise
            time.sleep(pause)


def _uia():
    import comtypes.client
    comtypes.client.GetModule("UIAutomationCore.dll")
    from comtypes.gen.UIAutomationClient import CUIAutomation, IUIAutomation
    return comtypes.client.CreateObject(CUIAutomation, interface=IUIAutomation)


def _find(uia, root, control_type, name, scope=4):  # 4 = TreeScope_Descendants
    """One targeted lookup. Never FindAll: the whole tree is 13,000 elements and takes seconds."""
    return root.FindFirst(scope, uia.CreateAndCondition(
        uia.CreatePropertyCondition(30003, control_type), uia.CreatePropertyCondition(30005, name)))


def offline_reason(app, hwnd):
    """Why the app can't send right now, or None. WhatsApp Desktop shows Reconnect when the phone isn't linked."""
    spec = APPS[app]
    if not spec["offline_button"] or hwnd is None:
        return None
    try:
        uia = _uia()
        root = uia.ElementFromHandle(hwnd)
        if _find(uia, root, 50000, spec["offline_button"]):  # 50000 = Button
            return f"{spec['say']} on this PC isn't connected to your phone"
    except Exception as exc:
        print(f"  couldn't check {app}: {exc!r}")
    return None


def compose_box(app, hwnd):
    """See _compose_box: tried again on a COM error."""
    return again(lambda: _compose_box(app, hwnd))


def _compose_box(app, hwnd):
    """The app's message box, and who the app says it's to: WhatsApp's 2025 app names it "Type a message to Amma",
    the one before "Type a message". (None, "") where Windows can't see it (Telegram draws its own)."""
    prefix = APPS[app]["compose"]
    if not prefix or hwnd is None:
        return None, ""
    uia = _uia()
    root = uia.ElementFromHandle(hwnd)
    # one lookup for an Edit whose name has it (MatchSubstring | IgnoreCase), not a walk of the whole tree: the 2025
    # app's "Type a message to Amma" first, as the caption box of its preview is "Type a message" too
    edit = uia.CreatePropertyCondition(30003, 50004)
    box = root.FindFirst(4, uia.CreateAndCondition(edit, uia.CreatePropertyConditionEx(30005, prefix + " to ", 3)))
    if not box:
        box = root.FindFirst(4, uia.CreateAndCondition(edit, uia.CreatePropertyConditionEx(30005, prefix, 3)))
    if not box:  # a NULL element, not None: reading it was "NULL COM pointer access", every time
        return None, ""
    name = str(box.CurrentName or "")
    to = name[len(prefix):].strip() if name.lower().startswith(prefix.lower()) else ""
    return box, re.sub(r"^to\s+", "", to, flags=re.I).strip()


def box_value(box):
    """What a message box holds: "" when it's empty (WhatsApp's holds a line break then)."""
    from comtypes.gen.UIAutomationClient import IUIAutomationValuePattern
    value = box.GetCurrentPattern(10002)  # UIA_ValuePatternId
    return " ".join(str(value.QueryInterface(IUIAutomationValuePattern).CurrentValue or "").split()) if value else ""


def typed_text(app, hwnd):
    """What the app's message box holds, where Windows exposes it, else None (Telegram draws its own)."""
    def read():
        box, _ = _compose_box(app, hwnd)
        return box_value(box) if box else None
    try:
        return again(read)
    except Exception as exc:
        print(f"  couldn't read the message box: {exc!r}")
        return None


def box_shown(app, hwnd, wait=4.0):
    """What the chat's message box holds once it's there, giving the chat the link opened a few seconds to draw it;
    None if it never comes (not linked to the phone, or the chat didn't open)."""
    end = time.time() + wait
    while True:
        shown = typed_text(app, hwnd)
        if shown is not None or time.time() > end:
            return shown
        time.sleep(0.5)


def type_into(app, hwnd, text):
    """Type text into the chat's message box, as WhatsApp's 2025 app leaves its link's text out: the box is put in
    focus first, with the app in front, and whatever was in it cleared. Then read back. Raises if it isn't there, so
    nothing half typed is ever asked about."""
    end = time.time() + 3.0  # the chat the link opened may still be drawing its box: a moment, then again
    while True:
        box, _ = compose_box(app, hwnd)
        if box and in_front(app, hwnd):
            if not box.CurrentHasKeyboardFocus:  # the link usually leaves it there already
                box.SetFocus()
                time.sleep(0.2)
            if box.CurrentHasKeyboardFocus and in_front(app, hwnd):
                break
        if time.time() > end:
            raise RuntimeError(f"I couldn't get to the message box in {APPS[app]['say']}, so I've not typed "
                               f"anything" if box else f"{APPS[app]['say']} didn't come to the front, so I've not "
                               f"typed anything")
        time.sleep(0.3)
    if box_value(box):  # a draft from before: it would be sent along with this
        win.press("ctrl", "a")
        win.press("backspace")
    win.type_text(text)
    time.sleep(0.4)
    if box_value(box) != text:
        win.press("ctrl", "a")
        win.press("backspace")
        raise RuntimeError(f"{APPS[app]['say']} didn't take the message, so I've not sent anything")


def drawn(hwnd):
    """True once WhatsApp's page is drawn, its search box there, giving it up to LOADING. Started from closed ("Close
    WhatsApp" quits the 2025 app) the window shows long before: the chat was looked for 4 s, and a number that was
    fine got "didn't open the chat", so you had to ask again."""
    end, why = time.time() + LOADING, None
    while True:
        try:
            uia = _uia()
            if again(lambda: _search_box(uia, uia.ElementFromHandle(hwnd))) is not None:
                return True
        except Exception as exc:  # the window may still be coming up
            why = exc
        if time.time() > end:
            if why is not None:
                print(f"  couldn't look at WhatsApp's page: {why!r}")
            return False
        time.sleep(0.5)


def open_chat(app, handle, text):
    """Open that person's chat with the text typed in, through the app's own link. Nothing is sent."""
    link = APPS[app]["link"].format(id=quote(str(handle), safe=""), text=quote(text, safe=""))
    hwnd = bring_up(app, link)
    time.sleep(1.2)  # the chat and the typed text need a moment to appear
    return hwnd


def bring_up(app, link):
    """Start the app's link and wait for its window to show, then put it in front: shown from the tray too, where
    WhatsApp's window is hidden and has nothing in it to read. Its window, or raises."""
    before = window_of(app)
    subprocess.run(["cmd", "/c", "start", "", link], check=False, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=win.CREATE_NO_WINDOW,
                   timeout=20)
    hwnd, end = before, time.time() + 12
    while time.time() < end:
        time.sleep(0.4)
        hwnd = window_of(app) or hwnd
        if hwnd and user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
            break
    if hwnd is None:
        raise RuntimeError(f"I couldn't open {APPS[app]['say']}")
    try:
        win.bring_to_front(hwnd)
    except Exception:
        pass
    return hwnd


def in_front(app, hwnd):
    """True if that app's window is the one in front, so Enter goes to the chat and nowhere else: its own window, or
    the web view inside it, which WhatsApp's 2025 app puts in front once its message box has the keyboard."""
    front = user32.GetForegroundWindow()
    if not front or not hwnd:
        return False
    if front == hwnd:
        return os.path.basename(win.foreground_exe()).lower() in {e.lower() for e in APPS[app]["exes"]}
    return _hosted_by(front, hwnd)


def _hosted_by(front, hwnd):
    """True if window front is a web view (msedgewebview2.exe) that the program of window hwnd started: inside that
    app, not another one that happens to use a web view too."""
    if os.path.basename(win.window_exe(front)).lower() != "msedgewebview2.exe":
        return False
    import psutil
    try:
        owner, proc = win._pid(hwnd), psutil.Process(win._pid(front))
        for _ in range(4):  # the view's own process, the web view's main one, then the app
            proc = proc.parent()
            if proc is None:
                return False
            if proc.pid == owner:
                return True
    except (psutil.Error, OSError):
        return False
    return False


# --------------------------------------------------------------------------- finding someone in WhatsApp itself
# Someone she hasn't been told about is often in your WhatsApp already, saved on your phone. She looks them up the way
# you would: the name in WhatsApp's own search, each chat it finds opened, the number read off its contact panel, and
# then she asks you if that's them (siri.look_up). No key is pressed: the search box is filled and emptied through UI
# Automation, and a chat is opened with a click on its result only where that spot is WhatsApp's own window, so
# nothing can land in a chat, and nothing is sent. Opening a chat does mark it read, as it would for you.
LOOK_AT = 3  # chats she opens to read the number of, a second or two each
LOADING = 25.0  # seconds for WhatsApp started from closed to draw its page: "Close WhatsApp" quits it
SHOWN_NUMBER = re.compile(r"\+\d[\d\s()-]{6,}\d")  # a number as WhatsApp shows it: "+91 95733 09199"
MARKS = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")  # the direction marks it wraps a number in
HEADINGS = ("Chats", "Contacts", "Groups in common", "Messages", "Other contacts")  # rows among the results too
PEOPLE = ("Chats", "Contacts", "Other contacts")  # the headings people are under: not groups, not messages
PANELS = ("Contact info", "Business info", "Group info")  # the contact panel's title says what the chat is


def whatsapp_people(name, most=LOOK_AT, stop=None):
    """The people WhatsApp itself finds for a name, in its order, at most most and no groups: [{"name": "Buntyyy",
    "number": "919573309199", "shown": "+91 95733 09199"}]. [] if it finds nobody. RuntimeError if WhatsApp can't
    be looked in. Not linked to the phone, it finds nobody: the message she then stages says why. stop: called
    before each chat is opened, True to open no more (you talked over her)."""
    # the name as alias_key has it, in your own letters: "my mum" typed in found nobody, where "mum" finds Mum
    name = clean_search(" ".join([w for w in str(name or "").split() if w.lower() not in ("my", "the")]) or name)
    hwnd = bring_up("whatsapp", "whatsapp:")
    uia = _uia()
    root = uia.ElementFromHandle(hwnd)
    box, end = None, time.time() + LOADING
    while box is None:  # started from closed, its page takes a while to draw: the window shows long before
        box = again(lambda: _search_box(uia, root))
        if box is None:
            if time.time() > end:
                raise RuntimeError("I couldn't find WhatsApp's search box")
            time.sleep(0.5)
            root = uia.ElementFromHandle(hwnd)
    try:
        found = _look_for(uia, root, hwnd, box, name, most, stop)
        words = name.split()
        if not found and len(words) > 1 and len(words[0]) >= 3 and not (stop and stop()):
            found = _look_for(uia, root, hwnd, box, words[0], most, stop)  # "Bunty Kumar", saved as just Bunty
        print(f"  WhatsApp found {len(found)} for {name!r}")
        return found
    finally:
        try:
            _set_value(box, "")  # its chat list back
        except Exception as exc:
            print(f"  couldn't empty WhatsApp's search: {exc!r}")


def _search_box(uia, root):
    """WhatsApp's search box: the first box that isn't a chat's message box. None if there's none."""
    found = root.FindFirst(4, uia.CreateAndCondition(uia.CreatePropertyCondition(30003, 50004), uia.CreateNotCondition(
        uia.CreatePropertyConditionEx(30005, APPS["whatsapp"]["compose"], 3))))
    return found if found else None


def _set_value(element, text):
    """Fill or empty a box through UI Automation: no key is pressed, so nothing can land anywhere else. Keys typed
    into WhatsApp's search box just after it was given the keyboard were lost, every time."""
    from comtypes.gen.UIAutomationClient import IUIAutomationValuePattern
    element.GetCurrentPattern(10002).QueryInterface(IUIAutomationValuePattern).SetValue(text)


def _look_for(uia, root, hwnd, box, name, most, stop=None):
    box.SetFocus()  # the keyboard in WhatsApp's page: without it a click on a result didn't open its chat
    time.sleep(0.3)
    stale = again(lambda: _rows(uia, root)) if box_value(box) else None  # the results for what's in the box now
    _set_value(box, name)
    labels = _results(uia, root, None if stale is None else [label for label, _ in stale])
    if labels is None:
        raise RuntimeError("WhatsApp didn't show its search results")
    found = []
    for i, label in enumerate(labels[:most + 2]):  # a group or two among them, not a long list
        if len(found) >= most or (stop and stop()):
            break
        try:  # never tried again: that would click the chat again
            person = _read_person(uia, root, hwnd, i, label)
        except Exception as exc:
            print(f"  couldn't read that WhatsApp contact: {type(exc).__name__}")
            continue
        if person and all(p["number"] != person["number"] for p in found):
            found.append(person)
    return found


STALE_FOR = 2.0  # seconds the results of what was in the search box before don't count: it searches again by then


def _results(uia, root, stale=None, wait=5.0):
    """The labels of the people WhatsApp's search shows ("Buntyyy 9:47 am Photo"), once two looks agree: it draws
    them as you type. [] if it shows nobody, None if it shows neither. stale: what showed for the text before, not
    taken for the answer until it has had time to search again."""
    start, last = time.time(), None
    while True:
        time.sleep(0.5)
        began = time.time()
        rows = again(lambda: _rows(uia, root))
        labels = None if rows is None else [label for label, _ in rows]
        if stale is not None and labels == stale and began - start < STALE_FOR:
            labels = None
        if labels is not None and labels == last:
            return labels
        if began - start > wait:  # a look begun after the wait has the last word: one begun before may have missed
            return labels
        last = labels


NOBODY = "No chats, contacts or messages found"  # what its search shows in place of results


def _rows(uia, root):
    """(label, row) for each person among the search results, in order: the rows under Chats or Contacts that open a
    chat. Each shows three times in the tree; one of them can be picked. [] if WhatsApp says it found nobody, None
    if it shows neither yet: one lookup for both, as a lookup for what isn't there reads the whole page, for seconds."""
    shown = root.FindFirst(4, uia.CreateOrCondition(
        uia.CreateAndCondition(uia.CreatePropertyCondition(30003, 50028),
                               uia.CreatePropertyCondition(30005, "Search results.")),
        uia.CreateAndCondition(uia.CreatePropertyCondition(30003, 50020), uia.CreatePropertyCondition(30005, NOBODY))))
    if not shown:
        return None
    if shown.CurrentControlType != 50028:
        return []
    items = shown.FindAll(4, uia.CreatePropertyCondition(30003, 50029))
    out, under = [], ""
    for i in range(items.Length if items else 0):
        try:
            row = items.GetElement(i)
            label = str(row.CurrentName or "")
            if label in HEADINGS:
                under = label
            elif under in PEOPLE and row.CurrentIsKeyboardFocusable and row.GetCurrentPropertyValue(30036):
                out.append((label, row))  # 30036: it can be picked (SelectionItem)
        except Exception:  # gone while it redrew: what follows can't be placed under a heading
            under = ""
    return out


def _read_person(uia, root, hwnd, i, label):
    """Open the i-th person among the results, if it's still label, and read their number off the contact panel:
    {"name", "number", "shown"}, both as the panel shows them, and only if the panel is that result's chat. None for
    a group, a panel with no number, or another chat's."""
    rows = _rows(uia, root) or []
    if i >= len(rows) or rows[i][0] != label:
        return None  # the results changed under her
    if not _open_row(hwnd, rows[i][1], label):
        return None
    details = _find_button(hwnd, "Profile details")
    if details is None:
        return None
    try:
        _click(details)
    except Exception as exc:  # Invoke often reports an error for a click that worked: _panel sees if it opened
        print(f"  opening WhatsApp's contact panel: {type(exc).__name__}")
    panel, title = _panel(uia, root, hwnd)
    if panel is None:
        return None
    try:
        if title == "Group info":
            return None
        texts = panel.FindAll(4, uia.CreatePropertyCondition(30003, 50020))
        said = [" ".join(MARKS.sub("", str(texts.GetElement(j).CurrentName or "")).split())
                for j in range(texts.Length if texts else 0)]
        # the number on a line of its own, under the name: never one inside their About
        at = next((j for j, s in enumerate(said) if SHOWN_NUMBER.fullmatch(s)), None)
        if at is None:
            return None
        name, shown = (said[at - 1] if at and said[at - 1] not in PANELS else ""), said[at]
        # the panel names the chat she clicked: by its name, or by its number for one not saved (the result then
        # starts with the number). Never the result's own label for a name: it ends with their last message
        if not _same_chat(label, name or shown):
            return None  # another chat's panel: the one she clicked hadn't come up
        return {"name": name or shown, "number": clean_number(shown), "shown": shown}
    finally:
        try:
            close = panel.FindFirst(4, uia.CreateAndCondition(uia.CreatePropertyCondition(30003, 50000),
                                                              uia.CreatePropertyCondition(30005, "Close")))
            if close:  # the panel's own: the window's Close sent WhatsApp to the tray
                _click(close)
        except Exception as exc:  # the number read stands
            print(f"  closing WhatsApp's contact panel: {type(exc).__name__}")


def _open_row(hwnd, row, label):
    """Open a search result's chat with a click on its name, as you would: a result's own action opened one chat
    and then nothing more, every time. Only if WhatsApp is in front and that spot is its own window, so nothing else
    is ever clicked: not the popup over it, not another app. True once the chat open is that result's, by the name
    its message box is to; False if it isn't clicked, or doesn't come up."""
    with win._real_pixels():  # the real pixels window_at and click use, whatever the screen's scaling
        r = row.CurrentBoundingRectangle
    x, y = r.left + (r.right - r.left) * 0.6, (r.top + r.bottom) / 2  # on the name, clear of the photo
    if r.right <= r.left or r.bottom <= r.top or not in_front("whatsapp", hwnd) or not _ours(hwnd, win.root_at(x, y)):
        return False
    win.click(x, y)
    start = time.time()
    while True:
        time.sleep(0.3)
        began = time.time()
        _, to = compose_box("whatsapp", hwnd)
        if to and _same_chat(label, to):
            if began - start < 0.5:  # it was to them already: a chat by the same name may still be coming up
                time.sleep(0.8)
            return True
        if began - start > 4.0:
            return False


def _ours(hwnd, at):
    """True if window at is WhatsApp's own, or the web view its page is in."""
    return bool(at) and (at == hwnd or _hosted_by(at, hwnd))


def _chat_key(name):
    """A chat's name compared without spaces, case or emoji variation marks, the emoji themselves kept."""
    return re.sub(r"[\s\ufe0f]+", "", str(name or "")).casefold()


def _letters(text):
    """"Buntyyy 🐼 9:47 am" -> "buntyyy947am": a name compared without its emoji or spaces."""
    return re.sub(r"\W+", "", str(text)).casefold()


def _same_chat(label, name):
    """True if a search result's label starts with that name: by its letters and digits, or as it is for a name
    that's only emoji."""
    key = _letters(name)
    if key:
        return _letters(label).startswith(key)
    name = " ".join(str(name).split())
    return bool(name) and " ".join(str(label).split()).startswith(name)


def _panel(uia, root, hwnd, wait=3.0):
    """The contact panel just opened and its title: (element, "Contact info"), or (None, "") if it didn't open. The
    panel is the title's container, as far up as it keeps clear of the chat list and the chat, and below WhatsApp's
    window: a number in a message is never read as theirs, and only the panel's own Close is ever found."""
    titles = uia.CreatePropertyCondition(30005, PANELS[0])
    for title in PANELS[1:]:
        titles = uia.CreateOrCondition(titles, uia.CreatePropertyCondition(30005, title))
    want = uia.CreateAndCondition(uia.CreatePropertyCondition(30003, 50020), titles)
    end = time.time() + wait
    while True:
        time.sleep(0.3)
        head = root.FindFirst(4, want)
        if head:
            break
        if time.time() > end:
            return None, ""
    keep_clear = [e.CurrentBoundingRectangle for e in (_search_box(uia, root), compose_box("whatsapp", hwnd)[0]) if e]
    if not keep_clear:  # nothing to tell the panel from the rest of the page by: no guessing
        return None, ""
    walker, panel = uia.ControlViewWalker, head
    while True:
        up = walker.GetParentElement(panel)
        if not up or uia.CompareElements(up, root):
            break
        r = up.CurrentBoundingRectangle
        if r.right <= r.left or any(r.left <= (k.left + k.right) / 2 <= r.right and
                                    r.top <= (k.top + k.bottom) / 2 <= r.bottom for k in keep_clear):
            break
        panel = up
    return panel, str(head.CurrentName)


# Files and photos, on WhatsApp: put on the clipboard as File Explorer's Copy does and pasted into the chat, where
# WhatsApp shows them in its preview ("Open photo, holiday.jpg, item 1 of 2", "Send 2 selected"), read back from there
# before the yes, and sent with its own Send button after it. A no presses Esc and its Discard.
MAX_FILES = 10
MAX_FILE_MB = 100  # WhatsApp takes up to 2 GB, but she'd be uploading for minutes: past this, send it yourself


def check_files(paths):
    """The files, if they can go: there, files, and not too many or too big. Raises with why not."""
    paths = [os.path.abspath(str(p)) for p in paths or []]
    if not paths:
        raise RuntimeError("there's no file to send")
    if len(paths) > MAX_FILES:
        raise RuntimeError(f"that's {len(paths)} files, I send up to {MAX_FILES} at a time")
    for p in paths:
        if not os.path.isfile(p):
            raise RuntimeError(f"I can't find {os.path.basename(p)} any more")
        if os.path.getsize(p) > MAX_FILE_MB * 1024 * 1024:
            raise RuntimeError(f"{os.path.basename(p)} is over {MAX_FILE_MB} MB, send that one yourself")
    return paths


def _button(hwnd, name, part=False):
    """See _find_button: tried again on a COM error."""
    return again(lambda: _find_button(hwnd, name, part))


def _find_button(hwnd, name, part=False):
    """A button in the app's window by its name, or the start of... any part of it with part (one quick lookup when
    it's there; a long one when it isn't, so only where it's expected or in a clean-up). None if there's none."""
    uia = _uia()
    root = uia.ElementFromHandle(hwnd)
    named = uia.CreatePropertyConditionEx(30005, name, 3) if part else uia.CreatePropertyCondition(30005, name)
    found = root.FindFirst(4, uia.CreateAndCondition(uia.CreatePropertyCondition(30003, 50000), named))
    return found if found else None


def _click(button):
    """Clicks a button through UI Automation: no mouse, no keys, so nothing else can be hit."""
    from comtypes.gen.UIAutomationClient import IUIAutomationInvokePattern
    button.GetCurrentPattern(10000).QueryInterface(IUIAutomationInvokePattern).Invoke()  # UIA_InvokePatternId


WAITING = re.compile(r"Open [\w ]+, (?P<name>.+), item \d+ of \d+")  # "Open photo, holiday.jpg, item 1 of 2"


def waiting(hwnd):
    """See _waiting: tried again on a COM error."""
    return again(lambda: _waiting(hwnd))


def _waiting(hwnd):
    """What WhatsApp's preview holds now: ([its file names], how many its Send button says), ([], 0) with none. One
    look through all its buttons, about 3 s on this PC: the quick lookups by name missed a preview that was there,
    and which box has the keyboard isn't a sure sign of one (a test picture was left waiting in a chat that way)."""
    uia = _uia()
    found = uia.ElementFromHandle(hwnd).FindAll(4, uia.CreatePropertyCondition(30003, 50000))
    names, count = {}, 0
    for i in range(found.Length if found else 0):
        try:
            label = str(found.GetElement(i).CurrentName or "")
        except Exception:  # one element gone while it redrew: the rest still count
            continue
        m = WAITING.fullmatch(label)
        if m:  # the page shows each element more than once: by the whole label, whose item number tells them apart
            names[label] = m["name"]
        m = re.fullmatch(r"Send (\d+) selected", label)
        if m:
            count = int(m[1])
    return sorted(names.values()), count


def _caption_box(hwnd):
    """See _find_caption_box: tried again on a COM error."""
    return again(lambda: _find_caption_box(hwnd))


def _find_caption_box(hwnd):
    """The caption box of WhatsApp's preview: an Edit named "Type a message", to nobody. None if there's none."""
    uia = _uia()
    found = uia.ElementFromHandle(hwnd).FindFirst(4, uia.CreateAndCondition(
        uia.CreatePropertyCondition(30003, 50004), uia.CreatePropertyCondition(30005, "Type a message")))
    return found if found else None


def _focus_box(app, hwnd):
    """The chat's message box, with the keyboard in it and the app in front, or raises."""
    end = time.time() + 3.0  # the chat the link opened may still be drawing its box: a moment, then again
    while True:
        box, _ = compose_box(app, hwnd)
        if box and in_front(app, hwnd):
            if not box.CurrentHasKeyboardFocus:  # the link usually leaves it there already
                box.SetFocus()
                time.sleep(0.2)
            if box.CurrentHasKeyboardFocus and in_front(app, hwnd):
                return box
        if time.time() > end:
            raise RuntimeError(f"I couldn't get to the message box in {APPS[app]['say']}, so I've not typed "
                               f"anything" if box else f"{APPS[app]['say']} didn't come to the front, so I've not "
                               f"typed anything")
        time.sleep(0.3)


def prepare_files(app, contact, paths, caption=""):
    """Open the chat and put the files in WhatsApp's preview, with a caption if there's one, ready for a yes.
    Nothing is sent. Returns what she should read back, as prepare does."""
    app = app_key(app)
    if app != "whatsapp":
        raise RuntimeError("I can only send files on WhatsApp so far")
    paths = check_files(paths)
    caption = " ".join(str(caption or "").split())[:MAX_TEXT]
    name, handle = find_contact(contact, app)
    cold = window_of(app) is None  # as in prepare
    hwnd = open_chat(app, handle, "")
    if cold and not drawn(hwnd):
        raise RuntimeError(offline_reason(app, hwnd) or f"{APPS[app]['say']} is still starting, so I've not sent "
                           f"anything. Ask me again in a moment")
    if box_shown(app, hwnd) is None:  # as in prepare: not linked, or the chat didn't open
        why = offline_reason(app, hwnd)
        raise RuntimeError(why or f"{APPS[app]['say']} didn't open the chat with {name}, so I've not sent anything")
    if waiting(hwnd)[1] and not discard_preview(app, hwnd):  # files left waiting from before would go too
        raise RuntimeError(f"something's already waiting to go in {APPS[app]['say']}, so I've not added anything")
    box = _focus_box(app, hwnd)
    _, to = compose_box(app, hwnd)
    if box_value(box):  # a draft from before: it would go as the caption
        win.press("ctrl", "a")
        win.press("backspace")
    saved, changed = win.clipboard_snapshot(), None
    names, count = [], 0
    try:
        win.set_clipboard_files(paths)
        changed = win.clipboard_sequence()
        time.sleep(1.2)  # the chat the link just opened can miss a paste straight away
        if not (in_front(app, hwnd) and box.CurrentHasKeyboardFocus):
            raise RuntimeError(f"{APPS[app]['say']} went out of the front, so I've not sent anything")
        win.press("ctrl", "v")
        for _ in range(4):
            time.sleep(1.0)
            names, count = waiting(hwnd)
            if count:
                break
    except Exception as exc:  # whatever was pasted is taken out again, never left one Enter from going
        discard_preview(app, hwnd)
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"{APPS[app]['say']} stopped answering, so I've not sent anything") from exc
    finally:
        try:  # what you'd copied comes back, all of it, unless you've copied something since
            if changed is None or win.clipboard_sequence() == changed:
                win.clipboard_restore(saved)
        except Exception as exc:
            print(f"  couldn't put the clipboard back: {exc!r}")
    if count != len(paths) or names != sorted(os.path.basename(p) for p in paths):
        discard_preview(app, hwnd)
        raise RuntimeError(f"{APPS[app]['say']} didn't take {'the file' if len(paths) == 1 else 'all the files'} "
                           f"as they are, so I've not sent anything")
    try:
        return _with_caption(app, hwnd, caption, {"app": app, "say": APPS[app]["say"], "contact": name,
                                                  "handle": handle, "text": caption, "hwnd": hwnd, "checked": True,
                                                  "other": False, "to": to, "files": paths})
    except Exception as exc:
        discard_preview(app, hwnd)
        if isinstance(exc, RuntimeError):
            raise
        raise RuntimeError(f"{APPS[app]['say']} stopped answering, so I've not sent anything") from exc


def _with_caption(app, hwnd, caption, ready):
    """The caption typed into the preview's own box and read back, then ready as it is."""
    if caption:  # into the preview's own caption box: "Type a message", to nobody
        box = _caption_box(hwnd)
        if box and not box.CurrentHasKeyboardFocus:
            box.SetFocus()
            time.sleep(0.2)
        if not (box and box.CurrentHasKeyboardFocus and in_front(app, hwnd)):
            discard_preview(app, hwnd)
            raise RuntimeError("I couldn't get to the caption box, so I've not sent anything")
        win.type_text(caption)
        time.sleep(0.4)
        if box_value(box) != caption:
            discard_preview(app, hwnd)
            raise RuntimeError(f"{APPS[app]['say']} didn't take the caption, so I've not sent anything")
    return ready


def discard_preview(app, hwnd):
    """Take the files out of WhatsApp's preview with its own Remove attachment buttons, so they aren't left waiting
    in the chat (Esc only asks "Discard unsent message?"), then check none are. In front or not: the buttons are
    clicked through UI Automation, so nothing else can be hit."""
    if not hwnd or not user32.IsWindow(hwnd):
        return False
    for _ in range(MAX_FILES + 4):
        try:
            if not waiting(hwnd)[1]:
                return True
            button = _button(hwnd, "Remove attachment")
            if button is None:
                break
            _click(button)
        except Exception as exc:  # "An event was unable to invoke any of the subscribers": a moment, then again
            print(f"  clearing WhatsApp's preview: {type(exc).__name__}, again")
        time.sleep(0.6)
    try:
        return not waiting(hwnd)[1]
    except Exception:
        return False


def send_files(ready):
    """Click Send in WhatsApp's preview, once it still holds exactly these files in the same chat, then check it went
    (the preview closes, and the chat's message box has the keyboard again). Only ever called after a yes."""
    app, hwnd, paths = ready["app"], ready.get("hwnd"), ready["files"]
    if not hwnd or not user32.IsWindow(hwnd):
        raise RuntimeError(f"{APPS[app]['say']} isn't open any more, so I've not sent it")
    try:
        win.bring_to_front(hwnd)
    except Exception:
        pass
    time.sleep(0.5)
    if not in_front(app, hwnd):
        raise RuntimeError(f"{APPS[app]['say']} isn't in front, so I've not sent it")
    _, to = compose_box(app, hwnd)
    if ready.get("to") and to != ready["to"]:
        raise RuntimeError("another chat is open now, so I've not sent it")
    names, count = waiting(hwnd)
    button = _button(hwnd, f"Send {count} selected") if count else None
    if count != len(paths) or names != sorted(os.path.basename(p) for p in paths) or button is None:
        raise RuntimeError("what's waiting to go changed, so I've not sent it")
    try:
        _click(button)  # once, whatever it says: Invoke often reports an error for a click that worked
    except Exception as exc:
        print(f"  clicking Send: {type(exc).__name__}, checking what it did")
    answered = False
    for _ in range(6):  # the preview closes once WhatsApp has taken them
        time.sleep(1.0)
        try:
            left = waiting(hwnd)[1]
        except Exception:
            continue
        answered = True
        if not left:
            what = os.path.basename(paths[0]) if len(paths) == 1 else f"{len(paths)} files"
            return True, f"Sent {what} to {ready['contact']}."
    if not answered:
        raise RuntimeError("I pressed Send but couldn't check it went, so look at WhatsApp before asking again")
    raise RuntimeError("WhatsApp still shows it waiting to go, so it may not have sent")


def prepare(app, contact, text):
    """Open the chat with the message typed in, ready for a yes. Returns what she should read back."""
    app = app_key(app)
    if app is None:
        raise RuntimeError("I can only message on WhatsApp or Telegram so far")
    text = clean_text(text)
    name, handle = find_contact(contact, app)
    cold = APPS[app]["compose"] and window_of(app) is None  # quit, not just in the tray: see drawn
    hwnd = open_chat(app, handle, text)
    if cold and not drawn(hwnd):
        raise RuntimeError(offline_reason(app, hwnd) or f"{APPS[app]['say']} is still starting, so I've not typed "
                           f"anything. Ask me again in a moment")
    # what the box holds, as box_shown read it: read a second time it could come back unreadable, and then the text
    # the 2025 app's link leaves out was never typed
    shown = box_shown(app, hwnd) if APPS[app]["compose"] else typed_text(app, hwnd)
    if APPS[app]["compose"] and shown is None:
        # no message box: not linked to the phone (the Reconnect button: a 7 s look on the 2025 app's big page, so
        # only now), or the chat didn't open, as for a number not on WhatsApp. Never Enter into whatever that is
        why = offline_reason(app, hwnd)
        raise RuntimeError(why or f"{APPS[app]['say']} didn't open the chat with {name}, so I've not typed anything")
    if shown is not None and shown != text:  # the link left the text out (WhatsApp's 2025 app): she types it
        type_into(app, hwnd, text)
        shown = text
    _, to = compose_box(app, hwnd) if shown is not None else (None, "")
    return {"app": app, "say": APPS[app]["say"], "contact": name, "handle": handle, "text": text, "hwnd": hwnd,
            "checked": shown is not None, "other": False, "to": to}


def send(ready):
    """Press Enter in the chat she opened, then check it went. Only ever called after a yes."""
    if ready.get("files"):
        return send_files(ready)
    if ready.get("other"):
        return _send_other(ready)
    app, hwnd, text = ready["app"], ready.get("hwnd"), ready["text"]
    if not hwnd or not user32.IsWindow(hwnd):
        raise RuntimeError(f"{APPS[app]['say']} isn't open any more, so I've not sent it")
    try:
        win.bring_to_front(hwnd)
    except Exception:
        pass
    time.sleep(0.5)
    if not in_front(app, hwnd):
        raise RuntimeError(f"{APPS[app]['say']} isn't in front, so I've not sent it")
    box, to = compose_box(app, hwnd) if APPS[app]["compose"] else (None, "")
    if box:
        if ready.get("to") and to != ready["to"]:
            raise RuntimeError("another chat is open now, so I've not sent it")
        if box_value(box) != text:
            raise RuntimeError("the message in the box changed, so I've not sent it")
        if not box.CurrentHasKeyboardFocus:  # Enter in the box, where it sends
            box.SetFocus()
            time.sleep(0.15)
        if not box.CurrentHasKeyboardFocus or not in_front(app, hwnd):
            raise RuntimeError(f"I couldn't get to the message box in {APPS[app]['say']}, so I've not sent it")
    elif ready.get("checked"):
        raise RuntimeError(f"I can't see the message box in {APPS[app]['say']} now, so I've not sent it")
    win.press("enter")
    time.sleep(1.0)
    left = typed_text(app, hwnd)
    for _ in range(4 if box else 0):  # a box that was there a moment ago: read again, never guessed at
        if left is not None:
            break
        time.sleep(0.5)
        left = typed_text(app, hwnd)
    if left is not None:  # the box empties when WhatsApp takes the message
        if left == text:
            raise RuntimeError("it's still sitting in the message box, so it may not have sent")
        return True, f"Sent to {ready['contact']}."
    if box:  # never "Sent" unchecked: after "Sent, as far as I can tell" you said it hadn't come, and asked again, and
        # "Hi" went four times (8 October)
        return False, (f"I pressed Enter, but couldn't read {APPS[app]['say']} back to check it went. Look at the "
                       f"chat before asking me again.")
    return True, f"Sent to {ready['contact']}, as far as I can tell. {APPS[app]['say']} doesn't let me read it back."


# --------------------------------------------------------------------------- the long way round, for other apps
def in_front_of(app_obj):
    """True if that app is the one in front, so a keystroke lands in it and nowhere else."""
    return bool(app_obj) and app_obj.matches(win.foreground_exe())


def focus_other(app_obj, say):
    """Bring the app up and wait until it really is in front. Nothing is typed before this says yes."""
    try:
        win.open_app(app_obj)
    except RuntimeError as exc:
        raise RuntimeError(f"I couldn't open {say}: {exc}")
    end = time.time() + 10
    while time.time() < end:
        windows = win.app_windows(app_obj)
        if windows:
            try:
                win.bring_to_front(windows[0])
            except Exception:
                pass
            time.sleep(0.4)
            if in_front_of(app_obj):
                return windows[0]
        time.sleep(0.3)
    raise RuntimeError(f"I couldn't get {say} to the front, so I've typed nothing")


def _type_now(app_obj, say, value):
    """Type, but only while that app is still the window in front."""
    if not in_front_of(app_obj):
        raise RuntimeError(f"{say} isn't in front any more, so I've stopped and sent nothing")
    win.type_text(value)


def prepare_other(spoken, app_obj, contact, text):
    """Walk an app that has no link of its own: search the name, open the chat, type the message, stop.

    None of it can be read back, so the yes that follows is confirming the chat as much as the words."""
    say = str(getattr(app_obj, "name", "") or spoken or "").strip()
    say = say if any(c.isupper() for c in say) else say.title()  # "signal" as heard reads better as Signal
    app = other_key(spoken) or other_key(say)
    if not app:
        raise RuntimeError("I need the name of an app")
    text = clean_text(text)[:OTHER_MAX_TEXT]
    name, search = find_contact(contact, app)
    recipe = recipe_for(app)
    focus_other(app_obj, say)
    win.press(*recipe["search"])  # the cursor lands in search, and the name typed next replaces what was there
    time.sleep(0.5)
    _type_now(app_obj, say, search)
    time.sleep(recipe["settle"])
    if not in_front_of(app_obj):
        raise RuntimeError(f"{say} isn't in front any more, so I've stopped and sent nothing")
    win.press(*recipe["pick"])  # open the chat it found
    time.sleep(recipe["settle"])
    _type_now(app_obj, say, text)
    time.sleep(0.3)
    return {"app": app, "say": say, "contact": name, "handle": search, "text": text, "hwnd": None,
            "checked": False, "other": True, "recipe": recipe, "obj": app_obj}


def _send_other(ready):
    """Press Enter, then keep what worked: the shortcut, and the name that found the person."""
    app_obj, say = ready["obj"], ready["say"]
    if not in_front_of(app_obj):
        raise RuntimeError(f"{say} isn't in front any more, so I've not sent it")
    win.press("enter")
    time.sleep(0.6)
    try:
        save_recipe(ready["app"], say, ready["recipe"])
        save_contact(ready["contact"], ready["app"], ready["handle"])
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"  sent, but couldn't remember how: {exc!r}")
    return True, f"Sent to {ready['contact']} on {say}. I can't read {say} back, so do check it landed."


def discard(ready):
    """Clear a message you said no to, so it isn't left sitting in someone's chat. Only if the app is in front."""
    if not ready:
        return False
    try:
        app, hwnd = ready.get("app"), ready.get("hwnd")
        if ready.get("files"):
            return discard_preview(app, hwnd)
        if not (in_front_of(ready["obj"]) if ready.get("other") else (hwnd and in_front(app, hwnd))):
            return False
        win.press("ctrl", "a")
        time.sleep(0.15)
        win.press("backspace")
        time.sleep(0.2)
        left = None if ready.get("other") else typed_text(app, hwnd)
        return left is None or not str(left).strip()
    except Exception as exc:
        print(f"  couldn't clear the message box: {exc!r}")
        return False
