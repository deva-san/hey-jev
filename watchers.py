"""Watches, "when X, do Y": "tell me when my download finishes", "when this video ends, put the PC to sleep", "let
me know when Kiro is done", "shut down the PC in an hour". Each is a durable task (tasks.py, kind "watch") that
siri.task_worker looks at every few seconds, on a thread of its own, until what it waits for happens. Then she tells
you, or does the one thing you asked: lock the PC, put it to sleep or shut it down. Sleeping and shutting down are
asked about first, with a clear yes, come with a minute's warning that "cancel" stops, and are never done after the
PC slept while she watched, nor for anything but what you asked for having happened: a download that stopped, a
window that closed or showed an error, is told about, never powered off for.

OpenJarvis has the idea as operators and monitors (operatives/monitor_operative.py): an agent woken on a schedule
that decides what to do. Here each look costs next to nothing, all on this PC: a listing of the Downloads folder, the
battery, Windows' media controls, whether an app still has a window, or a small picture of one window. Only a window
that has stopped changing is shown to the model, to tell finished from waiting for you (siri.watch_look)."""
from __future__ import annotations

import json
import os
import re
import time

import numpy as np

import sysinfo
import vision
import winplatform as win

POWER = ("shutdown", "sleep")  # asked about first with a clear yes, and never done once the PC has slept
THEN = ("tell", "lock") + POWER
MOST = 8 * 3600  # a watch gives up after this long: a big download, or a long film
GRACE = 60  # seconds' warning, from when she's said it, before a watch shuts the PC down or puts it to sleep
LATE = 90  # seconds a look came after it was due that mean she wasn't watching: the PC slept, or Jev stopped
EVERY = {"download": 10, "media": 8, "battery": 60, "closed": 8, "screen": 10}  # seconds between looks
PARTIAL = (".crdownload", ".part", ".partial", ".download", ".opdownload", ".!qb", ".!ut")  # files still downloading
FRESH = 600  # one of those written to in the last 10 minutes is a download going on; older is one left behind
OTHER = 8  # looks something else plays in the same player, part way through what was watched, before that's it over
STILL = 4  # looks in a row a window hasn't changed before it may be finished (40 s at EVERY["screen"])
LOOKS = 8  # times a still window goes to the model at most, each after a longer wait than the last
CHANGED, MOVED = 18, 0.0015  # grey levels a pixel moves by to have changed, and the share of them that's a change
_LAST = {}  # task id: the last small picture of a watched window, only in memory, so the task list stays small


class CantWatch(Exception):
    """Why she can't watch for that, in words she can say."""


# --------------------------------------------------------------------------- what was asked for
TELL = (r"(?:tell|let|notify|ping|alert|warn|inform|buzz|wake|call) (?:me|us)(?: know)?|give me a (?:shout|heads ?up|"
        r"ping|call|buzz)")
WHEN = r"(?:when(?:ever)?|once|as soon as|right after|after|the (?:moment|minute|second))"
SHUT = (r"(?:shut ?down|turn off|switch off|power (?:off|down)) (?:the |my |this )?(?:computer|pc|laptop|system|machine)"
        r"|shut (?:the |my |this )?(?:computer|pc|laptop|system|machine|it) (?:down|off)|shut ?down")
SLEEP = (r"put (?:the |my |this )?(?:computer|pc|laptop|system|machine|it) to sleep|(?:sleep|hibernate) (?:the |my |this )?"
         r"(?:computer|pc|laptop|system|machine)")
LOCK = r"lock (?:the |my |this )?(?:computer|pc|laptop|screen|system|machine)"
POWER_ACT = rf"(?:{SHUT}|{SLEEP}|{LOCK})"
ACT = rf"(?:{POWER_ACT}|(?:{TELL})(?: to .+)?|remind me(?: to .+)?)"
AND = r"(?:(?:and|then|please|just|also|so) )*"
FORMS = [re.compile(p) for p in (
    rf"(?:{TELL}) {WHEN} (?P<cond>.+)",  # "tell me when my download finishes"
    rf"remind me to (?P<remind>.+?) {WHEN} (?P<cond>.+)",  # "remind me to install it when the download's done"
    rf"remind me {WHEN} (?P<cond>.+)",
    rf"(?:{WHEN}|wait (?:until|till|for)) (?P<cond>.+?) {AND}(?P<act>{ACT})",  # "when the video ends, shut down"
    rf"(?P<act>{POWER_ACT}) {WHEN} (?P<cond>.+)",  # "put the PC to sleep after this movie"
)]
LATER = [re.compile(p) for p in (  # "shut down the PC in an hour", "in 30 minutes put the laptop to sleep"
    rf"(?P<act>{POWER_ACT}) (?:in|after) (?P<dur>.+)",
    rf"(?:in|after) (?P<dur>.+?) {AND}(?P<act>{POWER_ACT})",
)]
TRAILING = re.compile(rf"(?P<cond>.+?) {AND}(?P<act>{POWER_ACT}|{TELL})")  # "tell me when X and shut down"
# Never something on this PC: a person ("let me know when you're done"), or a phone or a car
PEOPLE = re.compile(r"\b(?:i|i'm|im|i've|i'll|me|you|you're|youre|you've|he|he's|she|she's|they|they're|we|we're|"
                    r"someone|somebody|anyone|everyone|phone|phones|mobile|car)\b")
MEDIA_NOUN = r"(?:video|videos|song|songs|track|music|movie|film|episode|show|podcast|audio|clip|lecture)"
NOT_MEDIA = re.compile(r"\b(?:export|render|upload|edit|convert|compress|encod|record|download|install)\w*")
IT = r"(?:it|it's|its|it is|the laptop|laptop|my laptop|this laptop|the pc|pc|the computer|computer|this)"
DONE = (r"(?:is |has |gets |has been |'s )?(?:done|finish(?:es|ed)?|complete[sd]?|ready|through|over)"
        r"(?: (?:with )?(?:it|its? \w+|the \w+|\w+ing(?: .+)?))?")
BUSY = (r"(?:stops?|has stopped|is no longer|isn't|is not) (?:working|running|thinking|busy|loading|installing|"
        r"rendering|exporting|uploading|updating|copying|building|processing|writing|generating|compiling|typing|"
        r"scanning|syncing)")
CLOSES = r"(?:closes|is closed|gets closed|has closed|has been closed|shuts|exits|quits|has quit|is gone|goes away|disappears)"


def parse(t, seconds=None):
    """What a watch is for, from words as siri.plain() has them: {"watch": what to wait for, "then": one of THEN,
    "remind": what to remind you of, or ""}, else None. seconds(text): how long "in 30 minutes" is, for a PC to
    shut down or sleep later (siri.parse_duration)."""
    t = " ".join(str(t or "").split()).strip(" .?!")
    for form in FORMS:
        m = form.fullmatch(t)
        if not m:
            continue
        g = m.groupdict()
        cond, then, remind = g["cond"], "tell", (g.get("remind") or "").strip()
        if g.get("act"):
            then, remind = _action(g["act"])
            if then is None:
                continue
        else:
            tail = TRAILING.fullmatch(cond)  # "tell me when the download finishes and shut down the PC"
            if tail and _action(tail["act"])[0]:
                cond, then = tail["cond"], _action(tail["act"])[0]
        tail = TRAILING.fullmatch(cond)  # "shut down the PC when the download finishes and tell me": it tells anyway
        if tail and _action(tail["act"])[0] == "tell":
            cond = tail["cond"]
        watch = condition(cond)
        if watch:
            return {"watch": watch, "then": then, "remind": remind}
    for form in LATER if seconds else ():
        m = form.fullmatch(t)
        secs = m and seconds(m["dur"])
        if secs and not re.search(rf"\b{WHEN}\b", m["dur"]):
            return {"watch": {"kind": "time", "secs": int(secs)}, "then": _action(m["act"])[0], "remind": ""}
    return None


def _action(act):
    """(one of THEN, what to remind you of) for the words of an action, or (None, "")."""
    act = act.strip()
    for then, words in (("shutdown", SHUT), ("sleep", SLEEP), ("lock", LOCK)):
        if re.fullmatch(words, act):
            return then, ""
    m = re.fullmatch(rf"(?:{TELL})(?: to (?P<r>.+))?|remind me(?: to (?P<r2>.+))?", act)
    return ("tell", (m["r"] or m["r2"] or "").strip()) if m else (None, "")


def condition(c):
    """What to wait for, from the words after "when": a download, the battery, what's playing, an app or window
    closing, an app or the window in front being done, else None. Who's done and what closes are left as said
    ("who"), for siri to find the window."""
    c = re.sub(r"\b(?:that |which )?(?:i'm|im|i am) (?:watching|listening to|playing)\b", "", c)  # the movie I'm watching
    c = " ".join(re.sub(r"\b(?:please|for me)$", "", c.strip()).split()).strip(" ,")
    if not c or PEOPLE.search(c):
        return None
    if re.search(r"\bdownload(?:s|ing|ed)?\b", c):
        return {"kind": "download"}
    if re.search(r"\bbattery\b", c) or re.fullmatch(rf"{IT}(?: is| has| gets| has been|'s)? (?:fully |all )?"
                                                    rf"(?:charged|full|topped up)(?: up)?", c):
        return _battery(c)
    media = _media(c)
    if media:
        return media
    m = re.fullmatch(rf"(?P<who>.+?) {CLOSES}(?: down)?", c)
    if m:
        return {"kind": "closed", "who": m["who"]}
    m = re.fullmatch(rf"(?P<who>.+?) {DONE}", c) or re.fullmatch(rf"(?P<who>.+?) {BUSY}", c) or \
        re.fullmatch(r"(?P<who>it|it's|this|that)(?: is)? (?:done|finished|over|ready)", c)
    if m:
        return {"kind": "screen", "who": re.sub(r"'s$", "", m["who"])}
    return None


def _battery(c):
    n = re.search(r"\b(\d{1,3})\s*(?:%|percent|per cent)?", c)
    down = bool(re.search(r"\b(?:drops?|dropped|falls?|goes down|gets? low|is low|low|below|under|less than|dies|dying|"
                          r"runs? (?:out|low)|empty|flat|dead|critical)\b", c))
    if n:
        level = max(1, min(100, int(n[1])))
    elif down:
        level = 5 if re.search(r"\b(?:dies|dying|dead|runs? out|empty|flat|critical)\b", c) else 20
    else:
        level = 50 if re.search(r"\bhalf\b", c) else 100
    return {"kind": "battery", "level": level, "down": down}


def _media(c):
    if NOT_MEDIA.search(c):
        return None  # "when the video export is done" is a window, "when the video finishes downloading" a download
    noun = re.search(rf"\b{MEDIA_NOUN}\b", c)
    playing = re.fullmatch(r"(?:it|this|that|whatever's|whatever is|what's|what is)(?: (?:is|that's))? (?:stops? playing|"
                           r"is done playing|finishes playing)|nothing(?:'s| is) playing(?: any ?more)?|the (?:sound|"
                           r"playback) stops", c)
    if not noun and not playing:
        return None
    ends = re.search(r"\b(?:ends?|ended|finish(?:es|ed)?|over|done|stops?|stopped|complete[sd]?|changes|playing)\b", c)
    bare = noun and re.fullmatch(rf"(?:the |this |that |my |current )?{MEDIA_NOUN}(?: (?:that's |that is )?playing)?", c)
    if noun and not (ends or bare):
        return None
    what = {"videos": "video", "songs": "song", "track": "song", "film": "movie", "clip": "video", "audio": "music",
            "lecture": "video"}.get(noun[0], noun[0]) if noun else "music"
    stop = bool(playing) or what == "music" or bool(re.search(r"\bstop", c))
    return {"kind": "media", "what": what, "mode": "stop" if stop else "end"}


# --------------------------------------------------------------------------- starting a watch
def download_folders():
    """Where downloads go: Windows' Downloads folder, moved off C on some PCs, and the one Chrome, Edge or Brave
    saves to when set to somewhere else."""
    found = [win.downloads_folder()]
    local = os.environ.get("LOCALAPPDATA", "")
    for profile in (r"Google\Chrome\User Data", r"Microsoft\Edge\User Data", r"BraveSoftware\Brave-Browser\User Data"):
        try:
            with open(os.path.join(local, profile, "Default", "Preferences"), encoding="utf-8") as f:
                where = (json.load(f).get("download") or {}).get("default_directory")
        except (OSError, ValueError, AttributeError):
            continue
        if where and os.path.isdir(where):
            found.append(where)
    return list(dict.fromkeys(os.path.normcase(os.path.abspath(p)) for p in found if p))


def _files(folders):
    """([(name, path, modified)] still downloading, [(name, path, modified)] the other files) in the folders."""
    part, done = [], []
    for folder in folders:
        try:
            with os.scandir(folder) as found:
                for e in found:
                    try:
                        if not e.is_file():
                            continue
                        modified = e.stat().st_mtime
                    except OSError:
                        continue
                    (part if e.name.lower().endswith(PARTIAL) else done).append((e.name, e.path, modified))
        except OSError:
            continue
    return part, done


def playing():
    """What Windows' media controls have, each browser tab its own: [{"app", "title", "status", "pos", "length"}],
    [] if they can't be read."""
    out = []
    try:
        sessions = win.media_sessions()
    except Exception as exc:
        print(f"  couldn't read the media controls: {exc!r}")
        return []
    for s in sessions:
        try:
            title, _ = win.media_props(s)
            out.append({"app": str(s.source_app_user_model_id or ""), "title": title, "status": win.media_status(s),
                        "pos": float(win.media_position(s)), "length": float(win.media_length(s))})
        except Exception:
            continue
    return out


def arm(w, now=None):
    """w ready to watch: what's there to watch now noted in it, as a fresh dict. CantWatch saying why if there's
    nothing to watch: no download going, nothing playing, no battery, or already happened. A window to watch (a
    "closed" or "screen" one) comes with its hwnd, or app and exes, and its name, found by siri."""
    now = time.time() if now is None else now
    w, kind = dict(w), w["kind"]
    if kind == "download":
        folders = download_folders()
        part, _ = _files(folders)
        live = [p for p in part if now - p[2] <= FRESH]
        if not live:
            raise CantWatch("I don't see anything downloading into your Downloads folder right now.")
        w.update(folders=folders, since=now - 2, stale=[p[1] for p in part if now - p[2] > FRESH], count=len(live))
    elif kind == "battery":
        b = sysinfo.battery()
        if not b.get("has_battery"):
            raise CantWatch("This PC doesn't run on a battery.")
        if (b["percent"] <= w["level"]) if w["down"] else (b["percent"] >= w["level"]):
            raise CantWatch(f"It's already at {b['percent']} percent.")
        w["plugged"], w["held"] = bool(b.get("plugged_in")), 0
    elif kind == "media":
        now_playing = [p for p in playing() if p["status"] == "playing"]
        if not now_playing:
            raise CantWatch("Nothing's playing right now.")
        p = now_playing[0]
        try:
            current = win.media_session()
            mine = str(current.source_app_user_model_id or "") if current else ""
            title = win.media_props(current)[0] if current else ""
            p = next((q for q in now_playing if q["app"] == mine and q["title"] == title), p)  # the one Windows shows
        except Exception:
            pass
        w.update(app=p["app"], title=p["title"], pos=p["pos"], length=p["length"], other=0, quiet=0)
    elif kind == "closed":
        if w.get("hwnd") and not win.window_exists(w["hwnd"]) or \
                not w.get("hwnd") and not win.app_windows(win.App(w["app"], w.get("exes") or ())):
            raise CantWatch(f"{w['name']} isn't open.")
    elif kind == "screen":
        if not win.window_exists(w["hwnd"]):
            raise CantWatch(f"I can't find {w['name']}'s window.")
        if win.minimised(w["hwnd"]):
            raise CantWatch(f"{w['name']} is minimised, so I can't see it. Bring it up and ask me again.")
        w.update(still=0, looks=0, moved=False, told="")
    elif kind == "time":
        w["at"] = now + max(60, int(w.pop("secs", 0) or 0))
    else:
        raise CantWatch("I can't watch for that.")
    return w


def every(w, now=None):
    """Seconds to the next look."""
    if w["kind"] == "time":
        return max(1.0, float(w["at"]) - (time.time() if now is None else now))
    return EVERY.get(w["kind"], 10)


# --------------------------------------------------------------------------- looking
def check(w, now=None, key=None, look=None):
    """One look: (verdict, line), w updated with what was seen. verdict: "wait" (not yet), "done" (it happened),
    "waiting" (the window wants you: told, and watched on), "ended" (it went away without happening: a download
    cancelled, the video closed) or "failed" (the window shows an error). key: the task's id, for the window's last
    picture. look(picture, w): ("done" | "working" | "waiting" | "failed", why) from the model, None to go by the
    picture alone."""
    now = time.time() if now is None else now
    return {"download": _check_download, "battery": _check_battery, "media": _check_media, "closed": _check_closed,
            "screen": _check_screen, "time": _check_time}[w["kind"]](w, now, key, look)


def _check_download(w, now, key, look):
    part, done = _files(w["folders"])
    if any(p[1] not in w["stale"] for p in part):
        return "wait", ""
    new = sorted((d for d in done if d[2] >= w["since"] and d[0].lower() != "desktop.ini"
                  and not d[0].lower().endswith((".tmp", ".temp"))), key=lambda d: d[2])
    if not new:
        return "ended", "Your download stopped before it finished."
    names = joined(said_name(d[0]) for d in new[-2:])  # the last one or two
    if len(new) > 1 or w.get("count", 1) > 1:
        return "done", f"Your downloads are finished: {names}."
    return "done", f"Your download's finished: {names}."


def _check_battery(w, now, key, look):
    b = sysinfo.battery()
    if not b.get("has_battery"):
        return "ended", "I can't read the battery any more."
    p = b["percent"]
    if w["down"]:
        if p <= w["level"] and not b.get("plugged_in"):
            return "done", f"The battery's down to {p} percent. Time to plug it in."
        return "wait", ""
    if p >= w["level"]:
        return "done", "The battery's full." if w["level"] >= 100 else f"The battery's at {p} percent."
    # plugged in and no longer charging: as full as it gets (a Lenovo's conservation mode stops at about 60)
    if w["level"] >= 100 and b.get("plugged_in") and p >= 50 and win.charging() is False:
        w["held"] = w.get("held", 0) + 1
        if w["held"] >= 2:
            return "done", f"The battery's stopped charging at {p} percent, so that's as full as it gets."
    else:
        w["held"] = 0
    return "wait", ""


def _check_media(w, now, key, look):
    found, what = playing(), w["what"]
    if w["mode"] == "stop":
        if any(p["status"] == "playing" for p in found):
            w["quiet"] = 0
            return "wait", ""
        w["quiet"] = w.get("quiet", 0) + 1
        return ("done", f"The {what} has stopped.") if w["quiet"] >= 2 else ("wait", "")
    same = [p for p in found if p["app"] == w["app"]]
    mine = next((p for p in same if p["title"] == w["title"]), None)
    near = w["length"] > 0 and w["pos"] >= w["length"] - 30  # at the last look
    ended = f"The {what}'s ended."
    if mine:
        w["other"] = 0
        if mine["status"] == "playing":
            w["pos"], w["length"] = mine["pos"], mine["length"] or w["length"]
            return "wait", ""
        length = mine["length"] or w["length"]
        if length > 0 and mine["pos"] >= length - 5:  # paused at its end: no autoplay
            return "done", ended
        return "wait", ""  # paused part way: you'll carry on
    if near:  # gone at its end: the next one autoplayed, or the next song
        return "done", ended
    # something else in the same player part way through: an ad, or one you picked. Never taken for the end, which
    # would put the PC to sleep with the film half watched
    if same:
        w["other"] = w.get("other", 0) + 1
        return ("ended", f"Something else came on before the {what} ended.") if w["other"] >= OTHER else ("wait", "")
    return "ended", f"The {what} was closed before it ended."


def _check_closed(w, now, key, look):
    def gone():
        return not win.window_exists(w["hwnd"]) if w.get("hwnd") else \
            not win.app_windows(win.App(w["app"], w.get("exes") or ()))
    if gone():
        time.sleep(1.5)  # an app opening a new window for an old one isn't closed
        if gone():
            return "done", f"{w['name']} has closed."
    return "wait", ""


def small(rgb):
    """The window as a small grey picture, for telling whether it's changed."""
    return vision.shrink(rgb, 256).mean(axis=2).astype(np.uint8)


def _check_screen(w, now, key, look):
    name = w["name"]
    if not win.window_exists(w["hwnd"]):
        _LAST.pop(key, None)
        return "ended", f"{name}'s window has closed."
    rgb = win.window_image(w["hwnd"])
    if rgb is None:  # minimised, or it wouldn't draw itself: nothing to go by this time
        return "wait", ""
    pic, before = small(rgb), _LAST.get(key)
    _LAST[key] = pic
    if before is None or before.shape != pic.shape:
        w["still"] = 0
        return "wait", ""
    if float(np.mean(np.abs(pic.astype(np.int16) - before) > CHANGED)) > MOVED:
        w["still"], w["moved"] = 0, True
        return "wait", ""
    w["still"] = w.get("still", 0) + 1
    if look is None:  # only the picture to go by: done once what was changing has stopped
        if w["still"] >= STILL * (1 if w.get("moved") else 3):
            return "done", f"{name} has stopped changing, so it looks done." if w.get("moved") else \
                f"{name} hasn't changed since you asked, so it looks done already."
        return "wait", ""
    if w["still"] < STILL * (1 + w.get("looks", 0)):  # each "still working" waits longer before the next look
        return "wait", ""
    w["looks"], w["still"] = w.get("looks", 0) + 1, 0
    state, why = look(rgb, w)
    why = f": {why}" if why else ""
    if state == "done":  # what it shows then is the model's picture of done, nothing you need to hear
        return "done", f"{name} is done."
    if state == "failed":
        return "failed", f"{name} has hit a problem{why}."
    if w["looks"] >= LOOKS:  # never a model look after look for a window that stays the same
        return "ended", f"{name} is still waiting for you, so I've stopped watching it." if state == "waiting" else \
            f"I couldn't tell when {name} was done, so I've stopped watching it."
    if state == "waiting" and w.get("told") != why:  # told once for each thing it waits for
        w["told"] = why
        return "waiting", f"{name} is waiting for you{why}."
    return "wait", ""


def _check_time(w, now, key, look):
    return ("done", "Time's up.") if now >= float(w["at"]) - 1 else ("wait", "")


def forget(key):
    """The window's last picture goes once its watch is over."""
    _LAST.pop(key, None)


# --------------------------------------------------------------------------- what she says
def said_name(name):
    """A file's name as she says it: no odd characters, at most 60 letters."""
    name = " ".join(re.sub(r"[^\w .,()&+'-]", " ", str(name or "")).split())
    return name[:60].rstrip(" .") or "a file"


def joined(things):
    things = [str(t) for t in things if t]
    return ", ".join(things[:-1]) + " and " + things[-1] if len(things) > 1 else "".join(things)


def span(secs):
    """"30 minutes", "an hour", "an hour and 30 minutes"."""
    secs = max(60, int(round(secs / 60)) * 60)
    h, m = divmod(secs // 60, 60)
    parts = (["an hour" if h == 1 else f"{h} hours"] if h else []) + ([f"{m} minute{'s' * (m != 1)}"] if m else [])
    return " and ".join(parts)


def event(w, now=None):
    """What's waited for, as it ends a sentence: "your download finishes", "the battery's full", "this video ends"."""
    kind = w["kind"]
    if kind == "download":
        return "your downloads finish" if w.get("count", 1) > 1 else "your download finishes"
    if kind == "battery":
        return f"the battery's down to {w['level']} percent" if w["down"] else \
            "the battery's full" if w["level"] >= 100 else f"the battery gets to {w['level']} percent"
    if kind == "media":
        return f"the {w['what']} stops" if w["mode"] == "stop" else f"this {w['what']} ends"
    if kind == "closed":
        return f"{w['name']} closes"
    if kind == "screen":
        return f"{w['name']} is done"
    return f"in {span(float(w['at']) - (time.time() if now is None else now))}"


DOING = {"tell": "tell you", "lock": "lock the PC", "sleep": "put the PC to sleep", "shutdown": "shut down the PC"}
IT_DOING = {"lock": "lock it", "sleep": "put it to sleep", "shutdown": "shut it down"}
STOP_IT = {"shutdown": "Say cancel the shutdown to stop it.", "sleep": "Say cancel the sleep to stop it."}


def at_clock(ts):
    """"6:40 PM"."""
    t = time.localtime(ts)
    return f"{t.tm_hour % 12 or 12}:{t.tm_min:02d} {'AM' if t.tm_hour < 12 else 'PM'}"


def promise(w, then, remind="", now=None):
    """What she says she'll do, for "what are you watching?": "When your download finishes, I'll shut down the
    PC." "In 20 minutes, I'll put the PC to sleep." """
    doing = f"remind you to {remind}" if remind else DOING[then]
    when = event(w, now)
    return f"{when[:1].upper()}{when[1:]}, I'll {doing}." if w["kind"] == "time" else f"When {when}, I'll {doing}."


def setup_line(w, then, remind=""):
    """Her answer once a watch is set: "Okay, I'll tell you when your download finishes.", "Okay, I'll shut it down
    in 30 minutes. Say cancel the shutdown to stop it." """
    when = event(w)
    if remind:
        return f"Okay, when {when} I'll remind you to {remind}."
    if then == "tell":
        return f"Okay, I'll tell you when {when}."
    if w["kind"] == "time":
        return f"Okay, I'll {IT_DOING[then]} {when}." + (f" {STOP_IT[then]}" if then in STOP_IT else "")
    return f"Okay, I'll {IT_DOING[then]} when {when}."


def question(w, then):
    """Asked before a watch that sleeps or shuts down: "Should I shut down the computer when your download
    finishes?" """
    doing = "shut down the computer" if then == "shutdown" else "put the PC to sleep"
    when = event(w)
    return f"Should I {doing} {when}?" if w["kind"] == "time" else f"Should I {doing} when {when}?"


def description(w, then, remind=""):
    """For the task list: "When your download finishes, shut down the PC", "At 6:40 PM, put the PC to sleep"."""
    doing = f"remind me to {remind}" if remind else "tell me" if then == "tell" else DOING[then]
    if w["kind"] == "time":
        return f"At {at_clock(w['at'])}, {doing}"
    return f"When {event(w)}, {doing}"


def then_line(line, verdict, then, remind="", slept=False, unsure=False):
    """What she says once a watch is over: what happened, then what she's doing about it. slept: she couldn't watch
    the whole time (the PC slept, or Jev stopped), so she doesn't power it off. unsure: all she saw was a window stop
    changing, as Vision went off or it became one she doesn't show the model, so she doesn't power it off either."""
    line = line or "Time's up."
    if verdict != "done":
        return line + {"shutdown": " So I'm not shutting down.", "sleep": " So I won't put the PC to sleep."}.get(then, "")
    if remind:
        line += f" Reminder: {remind}."
    if slept and then in POWER:
        return line + " I couldn't watch the whole time, so I've left the PC on."
    if unsure and then in POWER:
        return line + " I couldn't check it had really finished, so I've left the PC on."
    return line + {"shutdown": " I'll shut down the PC in a minute. Say cancel to stop it.",
                   "sleep": " I'll put the PC to sleep in a minute. Say cancel to stop it.",
                   "lock": " Locking the PC."}.get(then, "")


def gave_up(w):
    """Said when a watch has waited MOST."""
    return f"I've stopped watching for when {event(w)}: it's been {MOST // 3600} hours."
