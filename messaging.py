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
SAME_PERSON = {"mom": "mum", "mommy": "mum", "mummy": "mum", "mumma": "mum", "mama": "mum", "mamma": "mum",
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
    """The app's message box, and who the app says it's to: WhatsApp's 2025 app names it "Type a message to Amma",
    the one before "Type a message". (None, "") where Windows can't see it (Telegram draws its own)."""
    prefix = APPS[app]["compose"]
    if not prefix or hwnd is None:
        return None, ""
    uia = _uia()
    root = uia.ElementFromHandle(hwnd)
    # one lookup for an Edit whose name starts so (MatchSubstring | IgnoreCase), not a walk of the whole tree
    box = root.FindFirst(4, uia.CreateAndCondition(uia.CreatePropertyCondition(30003, 50004),
                                                    uia.CreatePropertyConditionEx(30005, prefix, 3)))
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
    try:
        box, _ = compose_box(app, hwnd)
        return box_value(box) if box else None
    except Exception as exc:
        print(f"  couldn't read the message box: {exc!r}")
        return None


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


def open_chat(app, handle, text):
    """Open that person's chat with the text typed in, through the app's own link. Nothing is sent."""
    spec = APPS[app]
    link = spec["link"].format(id=quote(str(handle), safe=""), text=quote(text, safe=""))
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
        raise RuntimeError(f"I couldn't open {spec['say']}")
    try:
        win.bring_to_front(hwnd)
    except Exception:
        pass
    time.sleep(1.2)  # the chat and the typed text need a moment to appear
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


def prepare(app, contact, text):
    """Open the chat with the message typed in, ready for a yes. Returns what she should read back."""
    app = app_key(app)
    if app is None:
        raise RuntimeError("I can only message on WhatsApp or Telegram so far")
    text = clean_text(text)
    name, handle = find_contact(contact, app)
    hwnd = open_chat(app, handle, text)
    if APPS[app]["compose"] and typed_text(app, hwnd) is None:
        # no message box: not linked to the phone (the Reconnect button: a 7 s look on the 2025 app's big page, so
        # only now), or the chat didn't open, as for a number not on WhatsApp. Never Enter into whatever that is
        why = offline_reason(app, hwnd)
        raise RuntimeError(why or f"{APPS[app]['say']} didn't open the chat with {name}, so I've not typed anything")
    shown = typed_text(app, hwnd)
    if shown is not None and shown != text:  # the link left the text out (WhatsApp's 2025 app): she types it
        type_into(app, hwnd, text)
        shown = text
    _, to = compose_box(app, hwnd) if shown is not None else (None, "")
    return {"app": app, "say": APPS[app]["say"], "contact": name, "handle": handle, "text": text, "hwnd": hwnd,
            "checked": shown is not None, "other": False, "to": to}


def send(ready):
    """Press Enter in the chat she opened, then check it went. Only ever called after a yes."""
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
    if left is not None:  # the box empties when WhatsApp takes the message
        if left == text:
            raise RuntimeError("it's still sitting in the message box, so it may not have sent")
        return True, f"Sent to {ready['contact']}."
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
