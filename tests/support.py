"""Shared setup for the unit tests. Import it before anything from the project:

    from tests.support import siri, TRIPPED

It points %APPDATA% and %LOCALAPPDATA% at an empty temp folder, so history, tasks, memory, contacts and logs never touch
the real %APPDATA%\\Hey Jev, and replaces everything that acts on the PC or goes online with a tripwire that raises and
is recorded in TRIPPED. A test that needs one of them patches it itself (unittest.mock.patch.object)."""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = tempfile.mkdtemp(prefix="heyjev-tests-")
os.environ["APPDATA"] = DATA
os.environ["LOCALAPPDATA"] = DATA
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import requests  # noqa: E402

TRIPPED = []


def tripwire(name):
    def tripped(*_, **__):
        TRIPPED.append(name)
        raise RuntimeError(f"tripwire: {name}")
    tripped.tripwire = name
    return tripped


requests.sessions.Session.request = tripwire("network")  # web, Fish, the model and YouTube all go through requests

import installer  # noqa: E402
import messaging  # noqa: E402
import opencode  # noqa: E402
import siri  # noqa: E402
import winplatform  # noqa: E402

# what acts on the PC: windows, keys, mouse, clipboard, sound, power, browser launches, chat apps and installs
WIN_ACTIONS = (
    "play", "chime", "set_volume", "set_muted", "set_app_volume", "media_command", "set_dark_mode", "lock", "sleep",
    "shutdown", "restart", "abort_shutdown", "launch", "bring_to_front", "open_app", "focus_app", "minimise_app",
    "quit_app", "scroll", "open_url", "press", "type_text", "set_clipboard", "paste", "click", "speak_native",
    "find_and_click_ui_element", "maximize_foreground_window", "restore_foreground_window",
    "minimize_foreground_window", "show_desktop", "open_folder", "open_snipping_tool", "set_start_with_windows",
)
for _name in WIN_ACTIONS:
    if hasattr(winplatform, _name):
        setattr(winplatform, _name, tripwire(f"win.{_name}"))
for _name in ("open_chat", "send", "prepare", "prepare_other", "_send_other", "_type_now", "discard", "focus_other"):
    if hasattr(messaging, _name):
        setattr(messaging, _name, tripwire(f"messaging.{_name}"))
for _name in ("prepare", "install", "_run", "find"):
    if hasattr(installer, _name):
        setattr(installer, _name, tripwire(f"installer.{_name}"))
opencode.chat = tripwire("opencode.chat")
for _name in ("speak", "fish", "fetch_tts", "warm_cache", "open_page", "see", "spotify_play"):
    if hasattr(siri, _name):
        setattr(siri, _name, tripwire(f"siri.{_name}"))
