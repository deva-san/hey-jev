"""Shared setup for the unit tests. Import it before anything from the project:

    from tests.support import siri, TRIPPED

It points %APPDATA% and %LOCALAPPDATA% at an empty temp folder, so history, tasks, memory, contacts and logs never touch
the real %APPDATA%\\Hey Jev, and replaces everything that acts on the PC or goes online with a tripwire that raises and
is recorded in TRIPPED. A test that needs one of them patches it itself (unittest.mock.patch.object)."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# First, before any project import: the real folders, which winplatform.own_data then refuses for the whole run
# (on 8 Oct a run that imported siri before this file wrote its test turns into her real history)
REAL = os.environ.setdefault("HEYJEV_TESTING", os.pathsep.join(
    (os.environ.get("APPDATA", ""), os.environ.get("LOCALAPPDATA", ""))))
DATA = tempfile.mkdtemp(prefix="heyjev-tests-")
os.environ["APPDATA"] = DATA
os.environ["LOCALAPPDATA"] = DATA
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from tests import winfakes  # noqa: E402

winfakes.install()  # off Windows only: stand-ins for winreg, ctypes.windll, winrt, pycaw, comtypes and sounddevice
needs_windows = winfakes.needs_windows

import requests  # noqa: E402

TRIPPED = []


def tripwire(name):
    def tripped(*_, **__):
        TRIPPED.append(name)
        raise RuntimeError(f"tripwire: {name}")
    tripped.tripwire = name
    return tripped


requests.sessions.Session.request = tripwire("network")  # web, Fish, the model and YouTube all go through requests

import backup  # noqa: E402
import dictation  # noqa: E402
import filesearch  # noqa: E402
import installer  # noqa: E402
import messaging  # noqa: E402
import opencode  # noqa: E402
import siri  # noqa: E402
import sysinfo  # noqa: E402
import winplatform  # noqa: E402

# Her Dictionary (vocabulary.json) and app list (apps.json) live next to the code, where own_data can't see them: a
# word a test learns (siri.learn_words) and a backup a test puts back go to temp ones. The Dictionary is read again
# from there, so a test sees the example words, not hers.
dictation.USER_VOCAB = siri.USER_VOCAB = os.path.join(DATA, "vocabulary.json")
dictation.load_vocab()
backup.HERE = os.path.join(DATA, "repo")

# what acts on the PC: windows, keys, mouse, clipboard, sound, power, browser launches, chat apps and installs
WIN_ACTIONS = (
    "play", "chime", "set_volume", "set_muted", "set_app_volume", "media_command", "set_dark_mode", "set_night_light",
    "lock", "sleep",
    "shutdown", "restart", "abort_shutdown", "launch", "bring_to_front", "open_app", "focus_app", "minimise_app",
    "quit_app", "scroll", "open_url", "press", "type_text", "set_clipboard", "paste", "click", "speak_native",
    # files on the clipboard for a chat, and the clipboard borrowed and put back; and the Start menu, read by starting
    # PowerShell (until 27 October none of these four were tripped, so a test could reach the real PC through them)
    "set_clipboard_files", "clipboard_snapshot", "clipboard_restore", "start_apps",
    "find_and_click_ui_element", "maximize_foreground_window", "restore_foreground_window",
    "minimize_foreground_window", "show_desktop", "open_folder", "open_snipping_tool", "set_start_with_windows",
    "open_windows_page",
    # brightness, Wi-Fi, Bluetooth, the mic and the sound's output (device_step), changed or read on the real PC
    "set_brightness", "set_radio", "set_mic_muted", "set_output", "brightness", "radio_on", "mic_muted",
    "output_devices",
    # UI Automation, for her procedures: it reads what's on the real screen and presses its controls
    "uia", "find_ui", "find_all_ui", "ui_act", "ui_info", "ui_value", "ui_toggle", "ui_at", "ui_focused",
    "ui_dialog_text", "ui_fields", "foreground", "browser_site", "window_at", "root_at", "owner_of", "window_exists",
    "browser_windows", "close_site_tab",
    # and what she reads of the screen for a task in an app: its controls, or a picture of it
    "ui_snapshot", "screenshot",
    # and what a watch looks at (watchers.py): one window's picture, the windows open, what's playing
    "window_image", "open_windows", "media_sessions",
    # and her look-ups of 27 October (siri.LOOK_STEPS): the files selected in the real File Explorer, and what's on
    # the real clipboard, which may be a password just pasted
    "selected_files", "clipboard_text",
    # and what a job in the background reads (27 October): its own window, where it is, and how long since you typed
    "window_of", "window_rect", "idle_seconds",
)
WIN_ORIGINAL = {}  # the real ones, for a test of one that never lets it reach the PC (it patches what that calls)
for _name in WIN_ACTIONS:
    if hasattr(winplatform, _name):
        WIN_ORIGINAL[_name] = getattr(winplatform, _name)
        setattr(winplatform, _name, tripwire(f"win.{_name}"))
for _name in ("open_chat", "send", "prepare", "prepare_other", "_send_other", "_type_now", "discard", "focus_other",
              "whatsapp_people", "bring_up"):
    if hasattr(messaging, _name):
        setattr(messaging, _name, tripwire(f"messaging.{_name}"))
for _name in ("prepare", "install", "_run", "find"):
    if hasattr(installer, _name):
        setattr(installer, _name, tripwire(f"installer.{_name}"))
opencode.chat = tripwire("opencode.chat")
# what's using the real PC's processor and memory (the top_apps look-up), which samples the CPU for 0.5 s too
sysinfo.top_apps = tripwire("sysinfo.top_apps")
# finding your files asks Windows Search's real index, and opening one starts its app
for _name in ("_ask_index", "open_found"):
    setattr(filesearch, _name, tripwire(f"filesearch.{_name}"))
siri.STREAM_SAY = False  # no "One moment" on a thread: tests that want it turn it on
ORIGINAL = {}  # what was swapped for a tripwire, for a test that needs the real one
for _name in ("speak", "fish", "fetch_tts", "warm_cache", "open_page", "see", "spotify_play", "Line"):
    if hasattr(siri, _name):
        ORIGINAL[_name] = getattr(siri, _name)
        setattr(siri, _name, tripwire(f"siri.{_name}"))
# what the planner is told is in the window in front reads the real window: nothing, unless a test gives it one;
# and a page opened in the tab in front would press keys in the real browser: a new tab, as open_page's tripwire has it
# and the decider's encoder for recall by meaning is the real MiniLM where .env names the models (HEYJEV_MODELS): no
# encoder, so no turn starts a thread that loads it, unless a test gives it one (FakeEncoder, tests/test_memory.py)
for _name, _stub in (("screen_view", lambda: None), ("same_tab", lambda url: False), ("meaning", lambda: None)):
    ORIGINAL[_name] = getattr(siri, _name)
    setattr(siri, _name, _stub)
