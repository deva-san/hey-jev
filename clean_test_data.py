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
refuses while her window is open, and can't see siri.py in a console, so close that too. A log or day file written to
after it was read is left as it was, and said, for another run.
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
from pathlib import Path

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
# Every change is worked out here, before anything is changed, and files are read and written as bytes: what isn't
# taken out goes back byte for byte, even a line that isn't UTF-8, and nothing read can stop it half way.
SUMMARY = re.compile(rb"\n## Summary\r?\n")  # history.mark_summarized's, at the end of a day file
ENTRY = re.compile(rb"(?m)^(?=- \*\*)")  # each turn in a day file starts a line with its time in bold


def _day_entry(ts, said):
    """The first line history.add writes for a turn in its day file."""
    t = time.localtime(ts)
    return f"- **{t.tm_hour % 12 or 12}:{t.tm_min:02d} {'AM' if t.tm_hour < 12 else 'PM'}** You: {said}".split("\n")[0]


def _read(path):
    """A file's bytes, and its size and time from just before, so it's only written back if nothing was added since
    (backup.running() sees her window, not siri.py --wake in a console)."""
    st = os.stat(path)
    with open(path, "rb") as f:
        return f.read(), (st.st_size, st.st_mtime_ns)


def _head(part):
    return part.split(b"\n", 1)[0].rstrip(b"\r").decode("utf-8", "replace")


def day_edits(folder, rows, take):
    """The day files (<day>.md in folder) without the entries of the turns taken out, as [(path, new bytes)], and
    what was left in, with why. history.add wrote each turn into history.db and its day file in the same order, so the
    k-th entry with a time and words is the k-th turn of that day with them: a turn of yours with the same minute and
    words as a test's keeps its own entry. Where a file has a different number of them than history.db, none of them
    goes. The summary at the end stays as it is, though one written on a day of test turns may mention them. Each
    write is (path, new bytes, the file's size and time when read)."""
    taken = {r[0] for r in take}
    days = collections.defaultdict(list)
    for rowid, said, ts, day in sorted(rows):  # by rowid: the order history.add wrote them in
        days[day].append((rowid, _day_entry(float(ts or 0), str(said or ""))))
    writes, left = [], []
    for day, turns in sorted(days.items(), key=lambda d: str(d[0])):
        path = os.path.join(folder, f"{day}.md")
        if not day or not any(rowid in taken for rowid, _ in turns) or not os.path.isfile(path):
            continue
        raw, was = _read(path)
        m = SUMMARY.search(raw)
        parts = ENTRY.split(raw[:m.start()] if m else raw)
        have = collections.Counter(_head(part) for part in parts)
        want = collections.Counter(head for _, head in turns)
        drop, seen, unsure = set(), collections.Counter(), 0
        for rowid, head in turns:
            seen[head] += 1
            if rowid in taken:
                if have[head] == want[head]:
                    drop.add((head, seen[head]))
                else:
                    unsure += 1
        if unsure:
            left.append(f"{path}: {unsure} entries don't line up with history.db, left in")
        seen.clear()
        kept = []
        for part in parts:
            head = _head(part)
            seen[head] += 1
            if (head, seen[head]) not in drop:
                kept.append(part)
        if drop:
            writes.append((path, b"".join(kept) + (raw[m.start():] if m else b""), was))
    return writes, left


def _read_only(db):
    """db, opened read-only. As a URI with its path percent-encoded: a Windows user name can have a # or % in it, and
    a bare file: URI stopped the path at the #."""
    return sqlite3.connect(Path(db).resolve().as_uri() + "?mode=ro", uri=True)


def history_plan(db, window, phrases, heard):
    if not os.path.isfile(db):
        return None
    con = _read_only(db)
    try:
        rows = con.execute("SELECT rowid, said, ts, day FROM turns").fetchall()
    finally:
        con.close()
    take, look, kept = pick([(r[0], r[1], float(r[2] or 0)) for r in rows], window, phrases, heard)
    writes, left = day_edits(os.path.join(os.path.dirname(db), "memories", "days"), rows, take)
    return {"name": "history.db", "path": db, "rows": len(rows), "take": take, "look": look, "kept": kept,
            "writes": writes, "left": left}


def tasks_plan(db, window, phrases):
    if not os.path.isfile(db):
        return None
    con = _read_only(db)
    try:
        rows = con.execute("SELECT id, description, created FROM tasks").fetchall()
    finally:
        con.close()
    take, look, kept = pick([(r[0], r[1], float(r[2] or 0)) for r in rows], window, phrases, {})
    return {"name": "tasks.db", "path": db, "rows": len(rows), "take": take, "look": look, "kept": kept,
            "writes": [], "left": []}


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
    raw, was = _read(path)
    lines = raw.split(b"\n")
    lines = [line + b"\n" for line in lines[:-1]] + ([lines[-1]] if lines[-1] else [])  # each with its own end
    rows = []
    for i, line in enumerate(lines):
        try:
            entry = json.loads(line.decode("utf-8", "replace"))
        except ValueError:
            continue
        if isinstance(entry, dict):
            rows.append((i, str(entry.get(text_key) or ""), _when(entry.get(when_key))))
    take, look, kept = pick(rows, window, phrases, heard)
    drop = {r[0] for r in take}
    writes = [(path, b"".join(line for i, line in enumerate(lines) if i not in drop), was)] if drop else []
    return {"name": os.path.basename(path), "path": path, "rows": len(lines), "take": take, "look": look,
            "kept": len(lines) - len(take), "writes": writes, "left": []}


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
def _write(path, data):
    tmp = path + ".clean-tmp"
    try:
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _delete(db, sql, keys, also=None):
    con = sqlite3.connect(db, timeout=10)
    try:
        with con:
            con.executemany(sql, [(k,) for k in keys])
            if also and con.execute("SELECT 1 FROM sqlite_master WHERE name = ?", (also[0],)).fetchone():
                con.executemany(also[1], [(k,) for k in keys])
    finally:
        con.close()


def apply(found, local=None):
    """Back up her data and the logs about to change, then take the tests' rows out, as planned by plans(). Once
    history.db has changed nothing stops it half way: a change that fails is said and the rest still go ahead.
    Returns (the backups' paths, what couldn't be done)."""
    local = local or backup.localdata()
    made = [backup.backup()]
    logs = [p["path"] for p in found if not p["path"].endswith(".db")]
    if logs:  # the backup zip has her data, not her logs: these go in one of their own
        path = made[0][:-len(".zip")] + "-logs.zip"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            for log in logs:
                z.write(log, os.path.relpath(log, local))
        made.append(path)
    problems = []
    for p in found:
        if not p["take"]:
            continue
        keys = [r[0] for r in p["take"]]
        try:
            if p["name"] == "history.db":  # and its search index; the day files are among its writes
                _delete(p["path"], "DELETE FROM turns WHERE rowid = ?", keys,
                        ("turns_tri", "DELETE FROM turns_tri WHERE rowid = ?"))
            elif p["name"] == "tasks.db":
                _delete(p["path"], "DELETE FROM tasks WHERE id = ?", keys)
        except sqlite3.Error as exc:
            problems.append(f"{p['path']}: {exc}, nothing taken out of it")
            continue  # and its day files stay as they are, with the turns still in history.db
        for path, data, was in p["writes"]:
            try:
                st = os.stat(path)
                if (st.st_size, st.st_mtime_ns) != was:
                    problems.append(f"{path}: written to since it was read, left as it was. Is she running? Close "
                                    "her, then run this again")
                    continue
                _write(path, data)
            except OSError as exc:
                problems.append(f"{path}: {exc}, left as it was")
    return made, problems


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
        for why in p["left"]:
            print(f"  {why}")


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
    if window[0] >= window[1]:
        parser.error("--from has to be before --to")
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
    made, problems = apply(found)
    print(f"\nTook out {total} rows. Backed up first to:\n  " + "\n  ".join(made)
          + f"\nTo undo: python backup.py --restore \"{made[0]}\", and put the logs back from the other zip.")
    if problems:
        print("\nThese couldn't be done:\n  " + "\n  ".join(problems))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
