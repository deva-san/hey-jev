"""How her skills and tasks in apps really went, kept by Jev herself in skills\\.outcomes.json: runs, successes and
failures for each routine, procedure and skill she wrote herself, and the last few tasks in each app that ended
without being done. Hermes' skill_usage counts how often a skill was loaded, never whether it worked, and until
27 October nothing ever read a failed run back (agent.py wrote it to Logs\\agent.jsonl only), so a task that got
stuck in the same app every week taught her nothing. Her learning review reads both (siri.review): the counts to
judge a skill by, the failures to write one lesson for that app (siri.learn_lesson).

Stdlib only, a small JSON file, written only after a run or a turn, never on the voice path.
"""
import json
import threading
import time

from hermes_memory import skills
from hermes_memory._compat import atomic_write_text

FILE = ".outcomes.json"
FAILURES_KEPT = 3  # tasks per app that ended without being done, the newest kept: what a review reads for a lesson
WHY_CHARS = 160  # of what she said when it ended, for the review: a reason, never a page's text
_lock = threading.Lock()


def path():
    return skills.SKILLS_DIR / FILE


def load():
    """{"skills": {name: {runs, ok, failed, last}}, "failures": {app: [{at, goal, outcome, why}]}}."""
    try:
        data = json.loads(path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    data = data if isinstance(data, dict) else {}
    return {"skills": data.get("skills") if isinstance(data.get("skills"), dict) else {},
            "failures": data.get("failures") if isinstance(data.get("failures"), dict) else {}}


def _save(data):
    path().parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(path(), json.dumps(data, indent=1, sort_keys=True, ensure_ascii=False), tmp_prefix=".outcomes_")


def count(name, ok):
    """One run of the skill name: ok if it did what was asked."""
    name = str(name or "").strip()
    if not name:
        return
    with _lock:
        data = load()
        s = data["skills"].setdefault(name, {"runs": 0, "ok": 0, "failed": 0})
        s["runs"] = int(s.get("runs") or 0) + 1
        key = "ok" if ok else "failed"
        s[key] = int(s.get(key) or 0) + 1
        s["last"] = round(time.time())
        _save(data)


def app_key(app):
    """The app as failures are kept under it: a site's host, else the program's file name, lower case."""
    return " ".join(str(app or "").lower().split())


def failed_run(app, goal, outcome, why=""):
    """A task in app (a site or an exe) that ended stuck, out of time, refused or unchecked, the newest
    FAILURES_KEPT kept."""
    app = app_key(app)
    if not app:
        return
    with _lock:
        data = load()
        kept = [f for f in data["failures"].get(app) or [] if isinstance(f, dict)]
        kept.append({"at": round(time.time()), "goal": " ".join(str(goal or "").split())[:200],
                     "outcome": str(outcome), "why": " ".join(str(why or "").split())[:WHY_CHARS]})
        data["failures"][app] = kept[-FAILURES_KEPT:]
        _save(data)


def failures(app):
    """The last few failed tasks in app, oldest first."""
    return list(load()["failures"].get(app_key(app)) or [])


def for_review(names=None, most=8):
    """How her skills went, in a line each for her review: the ones named first, then the most run, at most most."""
    counted = load()["skills"]
    order = [n for n in names or () if n in counted] + \
        sorted(counted, key=lambda n: int((counted[n] or {}).get("runs") or 0), reverse=True)
    lines = []
    for name in list(dict.fromkeys(order))[:most]:
        s = counted[name] or {}
        lines.append(f"- {name}: run {int(s.get('runs') or 0)} times, worked {int(s.get('ok') or 0)}, "
                     f"failed {int(s.get('failed') or 0)}")
    return "\n".join(lines)
