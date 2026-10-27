"""What she's working on right now, kept in memory for the island and the Tasks tab: her plan's steps, a task in an
app round by round, a background command, install, research or coding job, and a question waiting on your yes. Each
is an entry, started and moved on by the code doing the work (publish, step) and ended by it (finish); a finished one
says done or failed for a few seconds, then goes. The island's Tasks plugin (island_plugins.py) only ever reads a
copy (snapshot), from memory: never tasks.db, whose 5 s busy wait would stall the music and the notifications on
its thread. A producer's call is a locked dict update, a few microseconds, so the voice path is no slower.

What an entry says is written by code: a title from the plan (siri.describe, agent.task_words) or a task's own
description, and notes like "Round 3 of 30" or "2 files edited". Never a command's output, a page's text or a
message: those stay in the Tasks tab or nowhere (assistant_ui.PRIVACY).

Stop, Approve and Deny on the island come back here (press) and run what the producer left for them: a background
task's Store.cancel or Store.approve, or her question's answer through siri's controls loop, as the phone's buttons
answer one. Approve and Deny only reach an entry still waiting on a yes, with the very id the button was drawn for."""
import contextvars
import threading
import time

STATES = ("waiting_yes", "running", "queued", "done", "failed", "stopped")  # the order they're shown in
OVER = {"done", "failed", "stopped"}
LINGER = 4.0  # seconds a finished one stays, saying how it went, before it goes
QUICK = 3.0  # one that worked in less than this goes at once: you saw it happen, there's nothing to say
TITLE_MOST = NOTE_MOST = 60  # letters: a title and a note are a line on the island each
FIELDS = ("title", "kind", "state", "step", "total", "note", "needs", "origin", "until")
KEY = contextvars.ContextVar("activity_key", default=None)  # the entry this thread's work reports to (step)
CHANGED = threading.Event()  # set on every change, for whoever waits on one
version = 0  # goes up on every change: the Tasks tab reads tasks.db again only when it has
_items = {}  # key: the entry, with its stop() and answer(yes)
_lock = threading.Lock()
_clock = time.time  # swapped for a fake clock in the tests


def _clip(text, most):
    text = " ".join(str(text or "").split())
    return text if len(text) <= most else text[:most - 1].rstrip() + "…"


def _changed():
    global version
    version += 1
    CHANGED.set()


def _set(item, fields, now):
    for name, value in fields.items():
        if name not in FIELDS:
            raise TypeError(f"an activity has no {name}")
        if name == "state" and value not in STATES:
            raise ValueError(f"no such state: {value}")
        if name == "state" and value == "running" and item["state"] != "running":
            item["started"] = now  # how long it's been going counts from when it went, not from its wait
        item[name] = _clip(value, TITLE_MOST if name == "title" else NOTE_MOST) if name in ("title", "note") else \
            str(value or "") if name == "needs" else value


def publish(key, stop=None, answer=None, **fields):
    """Starts the entry key, or moves it on: title, kind (turn, ask, command, install, research, code), state,
    step and total (step of total, 1 on; 0 when it isn't known), note, needs (the id an answer must carry), origin
    and until (when it goes by itself, as a question that runs out). stop(): what Stop on the island does for it;
    answer(yes): what Approve and Deny do, for one waiting on your yes."""
    now = _clock()
    with _lock:
        item = _items.get(key)
        if item is None or item["ends"] is not None:  # new, or again after it finished (a repeating task)
            item = _items[key] = {"key": key, "title": "", "kind": "task", "state": "running", "step": 0, "total": 0,
                                  "note": "", "needs": "", "origin": "", "started": now, "until": None, "ends": None,
                                  "stop": None, "answer": None}
        _set(item, fields, now)
        if stop is not None:
            item["stop"] = stop
        if answer is not None:
            item["answer"] = answer
        _changed()


def update(key, **fields):
    """Moves on an entry that's there and not finished; False, and nothing made, if there's none."""
    if key is None:
        return False
    with _lock:
        item = _items.get(key)
        if item is None or item["ends"] is not None:
            return False
        _set(item, fields, _clock())
        _changed()
    return True


def step(i, n, note=None, key=None):
    """Step i of n of the entry this thread works for (KEY, set by whoever started it), and what it's doing now.
    Nothing when no one did: research or a task in an app run the same with no island to tell."""
    return update(key or KEY.get(), step=int(i), total=int(n), **({} if note is None else {"note": note}))


def finish(key, state="done", note=None):
    """It's over: done, failed or stopped. Its buttons go. One that worked quickly goes at once; one that took a
    while, or didn't work, says so for LINGER seconds first. False if it wasn't there, or had finished already."""
    if state not in OVER:
        raise ValueError(f"not an end: {state}")
    with _lock:
        item = _items.get(key)
        if item is None or item["ends"] is not None:
            return False
        now = _clock()
        item.update(state=state, needs="", stop=None, answer=None, until=None)
        if note is not None:
            item["note"] = _clip(note, NOTE_MOST)
        if state == "done" and now - item["started"] < QUICK:
            del _items[key]
        else:
            item["ends"] = now + LINGER
        _changed()
    return True


def drop(key):
    """Gone at once, finished or not, saying nothing: a question answered, or passed over for something else."""
    with _lock:
        if _items.pop(key, None) is not None:
            _changed()


def clear():
    """Everything gone: for the tests."""
    with _lock:
        _items.clear()
        _changed()


def snapshot(now=None):
    """Copies of the entries, with whether each can be stopped (stops) or answered (answers) in place of what does
    it: the ones waiting on you first, then what's running, what's queued and what's finished, the oldest first in
    each. Those whose time is up go."""
    now = _clock() if now is None else now
    with _lock:
        gone = [key for key, item in _items.items() if (item["ends"] is not None and now >= item["ends"]) or
                (item["until"] is not None and now >= item["until"])]
        for key in gone:
            del _items[key]
        if gone:
            _changed()
        out = [{**{k: v for k, v in item.items() if k not in ("stop", "answer")}, "stops": item["stop"] is not None,
                "answers": item["answer"] is not None} for item in _items.values()]
    return sorted(out, key=lambda item: (STATES.index(item["state"]), item["started"]))


def signature(prefix=""):
    """What the entries whose keys start with prefix say, as a tuple that changes when they do: the Tasks tab reads
    tasks.db again when its tasks' changes, not for each round of a task in an app."""
    return tuple((i["key"], i["state"], i["note"]) for i in snapshot() if i["key"].startswith(prefix))


def press(key, what, needs=""):
    """Stop, Approve or Deny pressed for the entry key, run on the caller's thread (never the island's or its
    plugins'). Approve and Deny only for an entry still waiting on a yes, with the needs id the button was drawn
    with: a button left from before, or for another question, does nothing. True if something was done."""
    with _lock:
        item = _items.get(key)
        if item is None or item["ends"] is not None:
            return False
        if what == "stop":
            fn, args = item["stop"], ()
        elif what in ("approve", "deny"):
            if item["state"] != "waiting_yes" or not item["needs"] or str(needs) != item["needs"]:
                return False
            fn, args = item["answer"], (what == "approve",)
        else:
            return False
    if fn is None:
        return False
    return bool(fn(*args))
