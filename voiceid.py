"""Only your voice: she answers you, not other people, the TV or a video.

Each turn's speech becomes a voice print (speech.Speaker, 3D-Speaker's CAM++ through sherpa-onnx, on this PC), and
it's compared with yours from 10 sentences you read once ("Hey Jev, learn my voice"). The prints and recordings stay
in %LOCALAPPDATA%\\Hey Jev\\voice and never leave the PC.

Settings "voice_id":
    "off"       everyone counts, as before
    "learning"  after you've read the sentences: every turn is scored and logged, nothing is turned away, until
                there are enough of your own turns to set the levels from (see calibrate), then she switches to "on"
    "on"        a turn that isn't your voice is let go silently

Measured on this PC (7 Oct 2026): a second or more of speech tells voices apart, your clips 0.64 to 0.90 against
Windows' David and Zira 0.06 to 0.39. Under a second it doesn't: a bare "Hey Jev" in their voices scored 0.84 to
0.97 against yours, since it's then the words that match, not the voice. So shorter turns aren't checked; ones
with her name, after a bare "Hey Jev" or just after she spoke count as yours, and others are let go while "on".
"""
import json
import os
import threading
import time

import numpy as np

import settings

MIN_SPEECH = 1.0  # seconds of speech a turn needs to be checked, see above
# Levels before calibration, from the clips above: with her name said (or straight after a bare "Hey Jev") a lower
# one, since the name is a good sign it's you; without it a higher one, so the room never reaches the model
NAMED, STRICT = 0.40, 0.50
LEVELS = {"named": (0.30, 0.55), "strict": (0.38, 0.62)}  # how far calibration may move each
CALIBRATE_AFTER = 30  # named turns of a second or more scored while learning, before she sets the levels
GROW_ABOVE = 0.15  # a turn this far over the named level, with her name, adds to her picture of your voice
MOST = 40  # prints kept: the 10 you read plus up to 30 from turns, the way "Hey Siri" fills in over time
SENTENCES = (  # short enough for the popup, and mostly what you say to her anyway
    "Hey Jev, open Chrome and play some music.",
    "Hey Jev, what's the weather like today?",
    "Hey Jev, set a timer for five minutes.",
    "Hey Jev, turn the volume down a little.",
    "Hey Jev, search YouTube for lofi songs.",
    "Remind me in twenty minutes to call Mum.",
    "Hey Jev, close this tab and go back.",
    "What's on my screen right now?",
    "Hey Jev, pause the video, please.",
    "Scroll down and read the next part to me.",
)
_lock = threading.Lock()


def folder():
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Hey Jev", "voice")


def mode():
    value = settings.get("voice_id")
    return value if value in ("learning", "on") else "off"


class Profile:
    """Your voice prints: the ones from the sentences you read (fixed) and from turns since (rolling), the levels,
    and the scores logged while learning."""

    def __init__(self, path=None):
        self.path = path or folder()
        self.read = np.zeros((0, 0), np.float32)  # from the sentences
        self.grown = np.zeros((0, 0), np.float32)  # from turns that were plainly you
        self.named, self.strict = NAMED, STRICT
        self.calibrated = False  # the levels have been set from your own turns
        self.load()

    @property
    def ready(self):
        return len(self.read) > 0

    def load(self):
        try:
            data = np.load(os.path.join(self.path, "profile.npz"))
            self.read, self.grown = data["read"], data["grown"]
            self.named, self.strict = float(data["named"]), float(data["strict"])
            self.calibrated = bool(data["calibrated"])
        except (OSError, KeyError, ValueError):
            pass

    def save(self):
        os.makedirs(self.path, exist_ok=True)
        tmp = os.path.join(self.path, "profile.tmp.npz")
        np.savez(tmp, read=self.read, grown=self.grown, named=self.named, strict=self.strict,
                 calibrated=self.calibrated)
        os.replace(tmp, os.path.join(self.path, "profile.npz"))

    def centre(self):
        prints = [p for p in (self.read, self.grown) if len(p)]
        c = np.concatenate(prints).mean(axis=0)
        return c / (np.linalg.norm(c) or 1.0)

    def score(self, print_):
        """How like your voice, -1 to 1 (cosine with the middle of your prints)."""
        return float(np.dot(self.centre(), print_))

    def enrol(self, prints):
        """The prints from the sentences you read: a new picture of your voice, levels back to the start."""
        with _lock:
            self.read = np.asarray(prints, np.float32)
            self.grown = np.zeros((0, self.read.shape[1]), np.float32)
            self.named, self.strict, self.calibrated = NAMED, STRICT, False
            self.save()
            log = os.path.join(self.path, "scores.jsonl")
            if os.path.exists(log):
                os.remove(log)  # scores against the old picture don't count for the new one

    def grow(self, print_):
        with _lock:
            self.grown = np.concatenate([self.grown.reshape(-1, len(print_)), print_[None]])[-(MOST - len(self.read)):]
            self.save()

    def log(self, entry):
        os.makedirs(self.path, exist_ok=True)
        with open(os.path.join(self.path, "scores.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    def scores(self):
        try:
            with open(os.path.join(self.path, "scores.jsonl"), encoding="utf-8") as f:
                return [json.loads(line) for line in f if line.strip()]
        except (OSError, ValueError):
            return []

    def calibrate(self):
        """Once enough of your named turns are in, set the levels so 95% of them pass with her name and 90%
        without. True if it set them."""
        mine = [e["score"] for e in self.scores() if e.get("level") == "named" and e.get("checked")]
        if len(mine) < CALIBRATE_AFTER:
            return False
        lo, hi = LEVELS["named"]
        named = min(hi, max(lo, float(np.percentile(mine, 5)) - 0.05))
        lo, hi = LEVELS["strict"]
        strict = min(hi, max(lo, max(named + 0.08, float(np.percentile(mine, 10)) - 0.05)))
        with _lock:
            self.named, self.strict, self.calibrated = named, strict, True
            self.save()
        return True


def level(named, kind):
    """Which level a turn is held to: "named" with her name in it or just after a bare "Hey Jev", else "strict"."""
    return "named" if named or kind == "armed" else "strict"


def judge(profile, score, speech_secs, named, kind):
    """(counts, why) for a turn with this score (None: not scored) and seconds of speech. counts is False only
    for a turn that isn't your voice while voice ID is on; while learning everything counts."""
    lvl = level(named, kind)
    if mode() == "off" or not profile.ready:
        return True, "off"
    if score is None or speech_secs < MIN_SPEECH:
        # too short to tell voices apart: her name, a bare "Hey Jev" before it, or just after she spoke means you
        if named or kind in ("armed", "follow_up") or mode() == "learning":
            return True, "short"
        return False, "short, without her name"
    limit = profile.named if lvl == "named" else profile.strict
    if score >= limit or mode() == "learning":
        return True, f"{score:.2f} {lvl}"
    return False, f"{score:.2f} under {limit:.2f} {lvl}"


def after_turn(profile, print_, score, speech_secs, named, kind, counted):
    """Keep the score while learning (switching to "on" once the levels are set, True then), and add a turn that
    was plainly you to her picture of your voice."""
    if not profile.ready or score is None or mode() == "off":
        return False
    checked = speech_secs >= MIN_SPEECH
    if mode() == "learning":
        profile.log({"when": round(time.time()), "score": round(score, 3), "level": level(named, kind),
                     "secs": round(speech_secs, 2), "checked": checked})
        if profile.calibrate():
            settings.put("voice_id", "on")
            return True
    if counted and checked and named and print_ is not None and score >= profile.named + GROW_ABOVE:
        profile.grow(print_)
    return False
