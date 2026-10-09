"""Take the unit tests' rows back out of her real data, after the 8 Oct leak. Changes nothing unless told to:

    .venv\\Scripts\\python clean_test_data.py            # says what it would take out, and changes nothing
    .venv\\Scripts\\python clean_test_data.py --apply    # backs everything up first, then takes them out

On 8 Oct between 15:59 and 19:04 a test run from the repo root wrote into her real data (see tests/support.py, which
now makes that impossible): 982 test turns in history.db beside 191 of yours, 1,488 runs in Logs\\agent.jsonl and 88
entries in the dictation log. A row is taken out only if all of these hold:
- it was written in the window (--from and --to, 8 Oct 15:55 to 19:10 by default),
- what it says is word for word a phrase from the tests (tests\\*.py),
- it came in a burst: another such row within BURST seconds (a test run wrote dozens a second, you one at a time),
- and there are more of it than you said: Logs\\Hey Jev.log has every phrase she heard from you, and that many are
  kept, the ones least like a test's burst of rows in the same few seconds.
Everything else stays. A row that matches a test phrase but stands on its own, and rows in the window that came in
bursts like a test's but match no test phrase, are listed for you to look at, not taken out. Every row it would take
out, and every one to look at, is listed in Logs\\clean_test_data.txt, the only file a dry run writes. Her memory
(USER.md, MEMORY.md), skills, notes, contacts, recipes and settings are never touched. Run it with Hey Jev closed: it
refuses while she's running.
"""
import argparse
import ast
import bisect
import collections
import glob
import json
import os
import re
import sqlite3
import sys
import time
import zipfile

import backup

HERE = os.path.dirname(os.path.abspath(__file__))
WINDOW = ("2026-10-08 15:55", "2026-10-08 19:10")
BURST = 2.0  # seconds: test turns came dozens a second, yours one at a time
HEARD = re.compile(r"^> heard: (?P<said>(?:'[^\n]*'|\"[^\n]*\"))")


def plain(text):
    """A phrase compared as words: case, curly quotes, spacing and the full stop at the end don't count."""
    text = str(text or "").replace("’", "'").replace("“", '"').replace("”", '"').lower()
    return " ".join(text.split()).strip(" .?!,")


def test_phrases(folder=None):
    """Every string written out in the tests, as plain(): what a test run said to her."""
    found = set()
    for path in glob.glob(os.path.join(folder or os.path.join(HERE, "tests"), "*.py")):
        with open(path, encoding="utf-8") as f:
            tree = ast.parse(f.read(), path)
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and len(plain(node.value)) > 1:
                found.add(plain(node.value))
    return found


def kept_as(said):
    """A phrase she heard as her history keeps it: siri.route takes her name off ("Hey Jev, open Notepad." is "open
    Notepad"), and siri.handle puts app names and your Dictionary's words right."""
    import siri  # only here: everything else in this script needs none of her
    found = siri.find_name(said)
    return siri.fix_vocab(siri.fix_names(found[1] if found and found[1] else said))


def heard_counts(logs):
    """How many times she heard each phrase from you, from her own log (Hey Jev.log and any older copies), counted
    both as heard and as her history keeps it. Every day's: the log doesn't say which day a line is from, and
    counting more only keeps more."""
    counts = collections.Counter()
    for path in sorted(glob.glob(os.path.join(logs, "Hey Jev.log*"))):
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                m = HEARD.match(line)
                if m:
                    try:
                        said = ast.literal_eval(m["said"])
                    except (ValueError, SyntaxError):
                        continue
                    for text in {plain(said), plain(kept_as(said))}:
                        counts[text] += 1
    return counts


def _burst(times):
    """For each time, how many others are within BURST seconds of it."""
    ordered = sorted(times)
    return {t: bisect.bisect_right(ordered, t + BURST) - bisect.bisect_left(ordered, t - BURST) - 1 for t in times}


def pick(rows, window, phrases, heard):
    """rows are (key, text, when). Returns (the tests' rows to take out, rows to look at, kept). A test phrase on its
    own, with no other within BURST seconds, is never taken out: a real "Hey Jev, open Notepad." in the window is
    one of those, and the dictation log and tasks have no log of what you said to keep yours by."""
    start, end = window
    inside = [r for r in rows if start <= r[2] <= end]
    crowd = _burst([r[2] for r in inside])
    matched = [r for r in inside if plain(r[1]) in phrases]
    near = _burst([r[2] for r in matched])  # other test phrases within BURST seconds
    left = collections.Counter(heard)
    take, look = [], []
    by_text = collections.defaultdict(list)
    for r in matched:
        by_text[plain(r[1])].append(r)
    for text, same in by_text.items():
        same.sort(key=lambda r: near[r[2]])  # yours first: the ones on their own
        for r in same[min(left[text], len(same)):]:
            (take if near[r[2]] else look).append(r)
    look += [r for r in inside if plain(r[1]) not in phrases and crowd[r[2]] >= 3]
    return take, look, len(rows) - len(take)


# --------------------------------------------------------------------------- each place a test run wrote to
def history_plan(db, window, phrases, heard):
    if not os.path.isfile(db):
        return None
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT rowid, said, ts, day FROM turns").fetchall()
    finally:
        con.close()
    days = {r[0]: r[3] for r in rows}
    take, look, kept = pick([(r[0], r[1], float(r[2] or 0)) for r in rows], window, phrases, heard)
    return {"name": "history.db", "path": db, "rows": len(rows), "take": take, "look": look, "kept": kept,
            "days": days}


def tasks_plan(db, window, phrases):
    if not os.path.isfile(db):
        return None
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = con.execute("SELECT id, description, created FROM tasks").fetchall()
    finally:
        con.close()
    take, look, kept = pick([(r[0], r[1], float(r[2] or 0)) for r in rows], window, phrases, {})
    return {"name": "tasks.db", "path": db, "rows": len(rows), "take": take, "look": look, "kept": kept}


def _when(value):
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return time.mktime(time.strptime(str(value), "%Y-%m-%d %H:%M:%S"))
    except ValueError:
        return 0.0


def jsonl_plan(path, when_key, text_key, window, phrases, heard):
    """A log of one JSON object a line: the tests' lines by their time and text. A line that isn't JSON is kept."""
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    rows = []
    for i, line in enumerate(lines):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict):
            rows.append((i, str(entry.get(text_key) or ""), _when(entry.get(when_key))))
    take, look, kept = pick(rows, window, phrases, heard)
    return {"name": os.path.basename(path), "path": path, "rows": len(lines), "take": take, "look": look,
            "kept": len(lines) - len(take), "lines": lines}


def plans(window, appdata=None, local=None, tests=None):
    appdata, local = appdata or backup.appdata(), local or backup.localdata()
    logs = os.path.join(local, "Logs")
    phrases, heard = test_phrases(tests), heard_counts(logs)
    found = [history_plan(os.path.join(appdata, "history.db"), window, phrases, heard),
             tasks_plan(os.path.join(appdata, "tasks.db"), window, phrases)]
    for name in ("agent.jsonl", "agent.1.jsonl"):
        found.append(jsonl_plan(os.path.join(logs, name), "at", "goal", window, phrases, heard))
    found.append(jsonl_plan(os.path.join(logs, "Hey Jev dictation.jsonl"), "time", "text", window, phrases, {}))
    found.append(jsonl_plan(os.path.join(local, "decider", "shadow.jsonl"), "when", "said", window, phrases, heard))
    return [p for p in found if p]


# --------------------------------------------------------------------------- taking them out
def _day_entry(ts, said):
    t = time.localtime(ts)
    return f"- **{t.tm_hour % 12 or 12}:{t.tm_min:02d} {'AM' if t.tm_hour < 12 else 'PM'}** You: {said}"


def _clean_days(appdata, plan):
    """The same turns out of the day files (memories\\days\\<day>.md), one entry for each turn taken out."""
    gone = collections.defaultdict(collections.Counter)
    for rowid, said, ts in plan["take"]:
        gone[plan["days"].get(rowid)][_day_entry(ts, said)] += 1
    for day, entries in gone.items():
        path = os.path.join(appdata, "memories", "days", f"{day}.md")
        if not day or not os.path.isfile(path):
            continue
        with open(path, encoding="utf-8") as f:
            text = f.read()
        parts = re.split(r"(?m)^(?=- \*\*)", text)
        kept = []
        for part in parts:
            head = part.split("\n", 1)[0]
            if entries[head] > 0:
                entries[head] -= 1
                continue
            kept.append(part)
        _write(path, "".join(kept))


def _write(path, text):
    tmp = path + ".clean-tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def apply(found, appdata=None, local=None):
    """Back up her data and the logs about to change, then take the tests' rows out. Returns the backups' paths."""
    appdata, local = appdata or backup.appdata(), local or backup.localdata()
    made = [backup.backup()]
    logs = [p["path"] for p in found if not p["path"].endswith(".db")]
    if logs:  # the backup zip has her data, not her logs: these go in one of their own
        path = made[0][:-len(".zip")] + "-logs.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for log in logs:
                z.write(log, os.path.relpath(log, local))
        made.append(path)
    for p in found:
        if not p["take"]:
            continue
        keys = [r[0] for r in p["take"]]
        if p["name"] == "history.db":
            con = sqlite3.connect(p["path"], timeout=10)
            try:
                with con:
                    con.executemany("DELETE FROM turns WHERE rowid = ?", [(k,) for k in keys])
                    if con.execute("SELECT 1 FROM sqlite_master WHERE name = 'turns_tri'").fetchone():
                        con.executemany("DELETE FROM turns_tri WHERE rowid = ?", [(k,) for k in keys])
            finally:
                con.close()
            _clean_days(appdata, p)
        elif p["name"] == "tasks.db":
            con = sqlite3.connect(p["path"], timeout=10)
            try:
                with con:
                    con.executemany("DELETE FROM tasks WHERE id = ?", [(k,) for k in keys])
            finally:
                con.close()
        else:
            drop = set(keys)
            _write(p["path"], "".join(line for i, line in enumerate(p["lines"]) if i not in drop))
    return made


def write_list(found, path):
    """Every row it would take out, and every one to look at, one a line, for reading before --apply."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for p in found:
            for kind, rows in (("out ", p["take"]), ("look", p["look"])):
                for _, text, ts in sorted(rows, key=lambda r: r[2]):
                    f.write(f"{kind} {p['name']}  {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ts))}  "
                            f"{text!r}\n")


def report(found):
    for p in found:
        print(f"\n{p['name']}: {p['rows']} rows, {len(p['take'])} from the tests to take out, {p['kept']} kept")
        for _, text, ts in p["take"][:5]:
            print(f"  out  {time.strftime('%H:%M:%S', time.localtime(ts))}  {text[:70]!r}")
        if len(p["take"]) > 5:
            print(f"  ... and {len(p['take']) - 5} more")
        if p["look"]:
            print(f"  {len(p['look'])} more stay: a test phrase on its own, or bursts like a test's that match no test "
                  "phrase. Have a look:")
            for _, text, ts in p["look"][:5]:
                print(f"  look {time.strftime('%H:%M:%S', time.localtime(ts))}  {text[:70]!r}")


def leftovers(window, appdata=None, local=None):
    """What a test run may have left that this never changes, for you to look at: files made or changed in the
    window in her memory, skills, notes, phone files and the replies she's watching for."""
    appdata, local = appdata or backup.appdata(), local or backup.localdata()
    seen = []
    for folder in ("memories", "skills", "notes"):
        for path in glob.glob(os.path.join(appdata, folder, "**", "*"), recursive=True):
            if os.path.isfile(path) and window[0] <= os.path.getmtime(path) <= window[1] and \
                    os.sep + "days" + os.sep not in path:
                seen.append(os.path.relpath(path, appdata))
    for path in glob.glob(os.path.join(local, "Phone files", "*")):
        if window[0] <= os.path.getmtime(path) <= window[1]:
            seen.append(os.path.relpath(path, local))
    try:
        with open(os.path.join(appdata, "follow_ups.json"), encoding="utf-8") as f:
            follow = json.load(f)
        seen += [f"follow_ups.json: {key}" for key, v in follow.items()
                 if isinstance(v, dict) and window[0] <= float(v.get("when") or 0) <= window[1]]
    except (OSError, ValueError, AttributeError):
        pass
    return seen


def main(argv=None):
    parser = argparse.ArgumentParser(description="Take the unit tests' rows out of Hey Jev's real data.")
    parser.add_argument("--apply", action="store_true", help="back up, then take them out (without it: a dry run)")
    parser.add_argument("--from", dest="start", default=WINDOW[0], help="window start, YYYY-MM-DD HH:MM local time")
    parser.add_argument("--to", dest="end", default=WINDOW[1], help="window end, YYYY-MM-DD HH:MM local time")
    args = parser.parse_args(argv)
    backup._closed()  # never while she's running: she has the history open
    window = tuple(time.mktime(time.strptime(v, "%Y-%m-%d %H:%M")) for v in (args.start, args.end))
    found = plans(window)
    report(found)
    listed = os.path.join(backup.localdata(), "Logs", "clean_test_data.txt")
    write_list(found, listed)
    print(f"\nEvery row it would take out, and every one to look at, is in {listed}")
    seen = leftovers(window)
    if seen:
        print(f"\nChanged in the window, never touched by this, have a look: {len(seen)}")
        for name in seen[:15]:
            print(f"  {name}")
    total = sum(len(p["take"]) for p in found)
    if not args.apply:
        print(f"\nDry run: nothing changed. {total} rows would go. Run again with --apply to take them out "
              "(everything is backed up first).")
        return 0
    if not total:
        print("\nNothing to take out.")
        return 0
    made = apply(found)
    print(f"\nTook out {total} rows. Backed up first to:\n  " + "\n  ".join(made)
          + f"\nTo undo: python backup.py --restore \"{made[0]}\", and put the logs back from the other zip.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
