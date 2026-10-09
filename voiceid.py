"""Only your voice: she answers you, not other people, the TV or a video.

Each turn's speech becomes a voice print (speech.Speaker, 3D-Speaker's CAM++ through sherpa-onnx, on this PC), and
it's compared with yours from 20 sentences you read once ("Hey Jev, learn my voice"). The prints and recordings stay
in %LOCALAPPDATA%\\Hey Jev\\voice and never leave the PC.

Settings "voice_id":
    "off"       everyone counts, as before
    "learning"  after you've read the sentences: nothing is turned away, and each turn is scored and logged, as yours
                if she acted on it and as room talk if she let it go, until there are enough to set the levels from
                (see calibrate). She switches to "on" by herself only if she can tell you apart at them, and says so
                either way
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
# Your own turns of a second or more, scored while learning, before she sets the levels: the ones she acted on, with
# her name or without, since with "Answer without her name" on her name was in 1 of 150 turns and named ones never
# came. And as many phrases she let go, to see if other voices would pass
CALIBRATE_AFTER = 30
# She switches on by herself only if at the levels she set this many of your turns pass, and no more than this many of
# what she let go. That's other voices, and yours to someone else too, so it can only make her wait, never let one in
YOURS_PASS, OTHERS_PASS = 0.97, 0.05
KEEP = 300  # of each, the latest: the levels follow how you sound now, and the log stays small
ACTED = (True, "playing", "dictate")  # what a turn she acted on returns (siri.handle): yours, while learning
# A turn of yours she acted on, once she's on, that scores this far over the level without her name against the
# sentences you read, adds to her picture of your voice. Never one with her name just for that: anyone can say it
GROW_ABOVE = 0.15
MOST = 40  # prints kept: the ones you read plus the rest from turns, the way "Hey Siri" fills in over time
# A sentence whose print scores under this against the rest of what you read is left out, the least alike first, down
# to ENROL_KEEP: on 8 Oct two scored 0.37 and 0.43 against the other eight and were kept. Your clips were 0.64 up
ENROL_AGREE, ENROL_KEEP = 0.55, 12
# Short enough for the popup, and mostly what you say to her anyway: commands, questions, a yes, and more without her
# name than with it, since that's how you talk to her
SENTENCES = (
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
    "Open YouTube and play the next video.",
    "Turn on the night light, please.",
    "Yes, okay, go ahead and send it.",
    "What time is the match on tonight?",
    "Open Chrome and search for cricket scores.",
    "Can you lock the computer for me?",
    "How much battery is left on this laptop?",
    "No, not that one, the one below it.",
    "Read me today's news headlines.",
    "Okay, that's enough for now, thank you.",
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
        self.told = False  # she's said she can't tell you apart here yet (see after_turn)
        self.logged = None  # the scores logged while learning, read from the file once (see scores)
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
            self.told = bool(data["told"]) if "told" in data.files else False
        except (OSError, KeyError, ValueError):
            pass

    def save(self):
        os.makedirs(self.path, exist_ok=True)
        tmp = os.path.join(self.path, "profile.tmp.npz")
        np.savez(tmp, read=self.read, grown=self.grown, named=self.named, strict=self.strict,
                 calibrated=self.calibrated, told=self.told)
        os.replace(tmp, os.path.join(self.path, "profile.npz"))

    def centre(self, read_only=False):
        """The middle of your prints. The ones added from turns count for half at most, and each was checked against
        the ones you read (after_turn), so turns that weren't quite you can't walk it over to another voice: the
        guard against drift PLAN promised."""
        unit = lambda c: c / (np.linalg.norm(c) or 1.0)
        c = unit(self.read.mean(axis=0))
        return c if read_only or not len(self.grown) else unit(c + unit(self.grown.mean(axis=0)))

    def score(self, print_, read_only=False):
        """How like your voice, -1 to 1 (cosine with the middle of your prints, or of the ones you read)."""
        return float(np.dot(self.centre(read_only), print_))

    def enrol(self, prints):
        """The prints from the sentences you read: a new picture of your voice, levels back to the start."""
        with _lock:
            self.read = np.asarray(prints, np.float32)
            self.grown = np.zeros((0, self.read.shape[1]), np.float32)
            self.named, self.strict, self.calibrated, self.told = NAMED, STRICT, False, False
            self.save()
            log = os.path.join(self.path, "scores.jsonl")
            if os.path.exists(log):
                os.remove(log)  # scores against the old picture don't count for the new one
            self.logged = []

    def grow(self, print_):
        with _lock:
            self.grown = np.concatenate([self.grown.reshape(-1, len(print_)), print_[None]])[-(MOST - len(self.read)):]
            self.save()

    def log(self, entry):
        """A score added to the log: a line on the file, which is cut back to the latest KEEP of each now and then."""
        logged = self.scores()
        logged.append(entry)
        os.makedirs(self.path, exist_ok=True)
        path = os.path.join(self.path, "scores.jsonl")
        if len(logged) <= 3 * KEEP:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            return
        yours, room = ([i for i, e in enumerate(logged) if e.get("who") == who][-KEEP:] for who in ("you", "room"))
        logged[:] = [logged[i] for i in sorted(yours + room)]
        with open(path + ".tmp", "w", encoding="utf-8") as f:
            f.writelines(json.dumps(e) + "\n" for e in logged)
        os.replace(path + ".tmp", path)

    def scores(self):
        """The scores logged while learning: read from the file once, then kept here. Read again on every phrase, on
        the listening thread before the turn ran, it took 25 ms at 166 lines and 48 ms at 14,000. Lines from before
        they said whose they were are left out."""
        if self.logged is None:
            try:
                with open(os.path.join(self.path, "scores.jsonl"), encoding="utf-8") as f:
                    self.logged = [e for e in map(json.loads, filter(str.strip, f)) if e.get("who") in ("you", "room")]
            except (OSError, ValueError):
                self.logged = []
        return self.logged

    def calibrate(self):
        """Once there are CALIBRATE_AFTER of your turns and of what she let go, the levels from yours: about 97% of
        them pass without her name, and with it a little lower. A turn far under the rest of yours (someone else's she
        acted on while learning) is left out of that, so a few can't drag the levels down and let other voices in.
        Then "on" if she can tell you apart at those levels: YOURS_PASS of all your turns pass, and no more than
        OTHERS_PASS of what she let go (on 8 Oct a video scored 0.70 to 0.84 and your commands 0.33 to 0.54).
        Else "unsure", the levels kept for "only answer me". None while there are too few."""
        logged = self.scores()
        mine = np.array([e["score"] for e in logged if e.get("who") == "you"][-KEEP:], np.float32)
        room = np.array([e["score"] for e in logged if e.get("who") == "room"][-KEEP:], np.float32)
        if len(mine) < CALIBRATE_AFTER or len(room) < CALIBRATE_AFTER:
            return None
        middle = float(np.median(mine))
        spread = max(0.05, 1.4826 * float(np.median(np.abs(mine - middle))))  # how far yours spread, robustly
        lo, hi = LEVELS["strict"]
        strict = round(min(hi, max(lo, float(np.percentile(mine[mine >= middle - 3 * spread], 3)) - 0.03)), 2)
        lo, hi = LEVELS["named"]
        named = round(min(hi, max(lo, strict - 0.08)), 2)
        with _lock:
            if (named, strict, True) != (self.named, self.strict, self.calibrated):  # saved only when they move
                self.named, self.strict, self.calibrated = named, strict, True
                self.save()
        apart = (mine >= strict).mean() >= YOURS_PASS and (room >= strict).mean() <= OTHERS_PASS
        return "on" if apart else "unsure"


def alike(prints):
    """How like the rest each print is: its score against the middle of the others."""
    v = np.asarray(prints, np.float32)
    rest = v.sum(axis=0) - v
    return (v * rest).sum(axis=1) / np.maximum(np.linalg.norm(rest, axis=1), 1e-9)


def keep_alike(prints):
    """Which of the sentences you read make her picture of your voice: the one least like the rest is left out while
    it's under ENROL_AGREE, then the next, keeping ENROL_KEEP at least."""
    keep = list(range(len(prints)))
    while len(keep) > ENROL_KEEP:
        scores = alike([prints[i] for i in keep])
        if scores.min() >= ENROL_AGREE:
            break
        del keep[int(np.argmin(scores))]
    return keep


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


def after_turn(profile, print_, score, speech_secs, named, kind, counted, result=None):
    """Once a turn is over, result being what she did with it (siri's run_turn; False: let go). While learning the
    score of one of a second or more is kept, as yours if she acted on it (ACTED: a command she did, a yes to her
    question) and as room talk if she let it go, and the levels are set once there are enough (calibrate). Returns
    "on" when that switched her on, "unsure" the first time it couldn't, else None. Once she's on, a turn she acted on
    that was plainly you adds to her picture of your voice (see GROW_ABOVE)."""
    if not profile.ready or score is None or mode() == "off" or speech_secs < MIN_SPEECH:
        return None  # under a second it's the words that match, not the voice: kept out of the levels
    said = None
    if mode() == "learning" and (result in ACTED or result is False):
        profile.log({"when": round(time.time()), "score": round(score, 3), "level": level(named, kind),
                     "secs": round(speech_secs, 2), "who": "you" if result in ACTED else "room"})
        said = profile.calibrate()
        if said == "on":
            settings.put("voice_id", "on")
        elif said == "unsure" and not profile.told:
            with _lock:
                profile.told = True
                profile.save()
        else:
            said = None
    if mode() == "on" and profile.calibrated and counted and result in ACTED and print_ is not None \
            and profile.score(print_, read_only=True) >= profile.strict + GROW_ABOVE:
        profile.grow(print_)
    return said
