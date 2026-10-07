"""Window and model settings, saved to %APPDATA%\\Hey Jev\\settings.json (the Mac build used NSUserDefaults)."""
import json
import os
import threading

from winplatform import APPDATA_DIR

PATH = os.path.join(APPDATA_DIR, "settings.json")
DEFAULTS = {
    "mode": "ptt",
    "mic": "",
    "keep_on_top": False,
    "llm_model": "space-bunny-free",  # OpenCode Zen, free, zero retention, and allowed outside OpenCode's own app
    # speech to text on this PC: parakeet, nemotron (writes as you talk, but lost "Hey Jev" in Hari's voice), or whisper
    "stt_engine": "parakeet",
    "echo_cancel": True,  # the mic in Windows' speech mode, so she hears you over videos and music
    "popup": True,  # the pill at the bottom of the screen while she listens, thinks and talks
    "name": "",  # what she calls you
    "welcome": True,  # hello when you sign in or come back to the laptop, and what she can do
    "met": False,  # she's introduced herself since her memory was last started fresh, see backup.py --fresh
    "voice": "",  # her Fish Audio voice, an ID from VOICES or a pasted fish.audio link. Empty: the first in VOICES
    "vision": True,  # she may look at the screen when you ask about it, see siri.see()
    "heads_ups": True,  # she mentions what needs you: messages, a low battery, a nearly full drive, see watch.py
    "notifications": True,  # she may read Windows' notifications, for heads-ups and "any new messages?"
    "learning": True,  # she looks back over turns to learn, Hermes Agent's learning loop, see siri.review()
    # no "Hey Jev" needed: anything said that could be a request goes to the answer model, which decides if it was
    # for her or for someone else in the room, see siri.route()
    "no_name": False,
    "call_aware": True,  # during WhatsApp/Teams/Zoom/browser calls, unnamed speech is for the call; say Jev/Jarvis
    "spoken_answers": True,  # a question, even "Google when is...", is looked up and answered out loud, see siri
}
# Fish Audio voices that speak well on its free model, for Settings > Voice: (name, ID, what she sounds like)
VOICES = (  # the first is the default when none is picked, so Hannah stays first
    ("Hannah", "9a9cf47702da476aa4629e2506d4a857", "friendly, clear"),
    ("Sarah", "933563129e564b19a115bedd57b7406a", "soft, gentle"),
    ("Laura", "e3cd384158934cc9a01029cd7d278634", "warm, calm"),
    ("Miku", "75cea27272464f8e8a529c9105d40297", "Indian accent"),
    ("Assistant", "fa97330bb80549fbb3cf84a1c421d70c", "crisp, American"),
    ("Ethan", "536d3a5e000945adb7038665781a4aca", "calm, a man"),
    # Windows' own voices: offline, instant, no Fish account needed
    ("Windows Heera", "onecore:MSTTS_V110_enIN_HeeraM", "offline, Indian English"),
    ("Windows Ravi", "onecore:MSTTS_V110_enIN_RaviM", "offline, Indian English, a man"),
    ("Windows Mark", "onecore:MSTTS_V110_enUS_MarkM", "offline, American, a man"),
    ("Windows Zira", "onecore:MSTTS_V110_enUS_ZiraM", "offline, American"),
    ("Windows David", "onecore:MSTTS_V110_enUS_DavidM", "offline, American, a man"),
)
ENV = {"llm_model": "OPENCODE_MODEL"}  # a value in .env wins, like the keys do

_lock = threading.Lock()
_data = None


def _load():
    global _data
    if _data is None:
        try:
            with open(PATH, encoding="utf-8") as f:
                _data = json.load(f)
        except (OSError, ValueError):
            _data = {}
    return _data


def get(name):
    env = ENV.get(name)
    if env and os.getenv(env):
        return os.getenv(env)
    with _lock:
        value = _load().get(name)
    if value is None or (value == "" and name in ENV):  # an emptied model box means the default model
        return DEFAULTS.get(name)
    return value


def put(name, value):
    with _lock:
        data = _load()
        data[name] = value
        tmp = PATH + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, PATH)
