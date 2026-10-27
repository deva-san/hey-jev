"""Everything you've asked her and what she did, kept on this PC, the way Hermes Agent keeps its sessions: a SQLite
full-text index she can search ("what did we talk about yesterday?"), and one Markdown file a day you can read,
in %APPDATA%\\Hey Jev\\memories\\days. Each turn also keeps where it came from (voice, phone or text) and how it
reached her (by name, as a follow-up, or heard without her name), and, beside history.db in history-vectors.bin, what
its words mean as the decider's 384 numbers, so a recall whose words match little finds "that printer thing" by
meaning instead.
"""
import os
import re
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

from hermes_memory.hermes_bits import _or_relaxed_query, _sanitize_fts5_query
from winplatform import APPDATA_DIR

DB = os.path.join(APPDATA_DIR, "history.db")
DAYS_DIR = os.path.join(APPDATA_DIR, "memories", "days")
VECTORS = "history-vectors.bin"  # beside DB, see add_meaning; backup.py's WIPE names it too
STOP = set("a an and are as at be but by can could did do does for from had has have he her his how i if in into is "
           "it its me my of on or our she so that the their them then there these they this to up was we were what "
           "when where which who why will with would you your about again just like okay ok yeah hey jev please "
           # words that ask about the past rather than say what about: "what did we talk about today"
           "talk talked talking said say ask asked tell told today yesterday conversation conversations discuss "
           "discussed remember earlier".split())
# Where a turn came from, how it reached her, and each one's value for turns kept before these were: voice, and by
# name, the way they were mostly said. "cold" is heard without her name: on 6 and 7 October room talk she'd answered
# was put in her memory as facts about you, so her day's summary and her look back leave those turns out for good
META = (("origin", "voice"), ("gate", "named"))
NOT_COLD = " AND t.rowid NOT IN (SELECT id FROM turns_meta WHERE gate = 'cold')"
# What a turn's words mean: its id and time (a vector counts only for the turn it was worked out from), then the
# decider's 384 numbers (decider.DIM) as float16, 784 bytes a turn, 7.8 MB for 10,000. Not imported from decider.py,
# which would load the speech code into everything that reads her history
RECORD = np.dtype([("id", "<i8"), ("ts", "<f8"), ("v", "<f2", (384,))])
FEW = 3  # fewer turns than this found by their words, and search looks by meaning too
# How alike, to the decider's encoder, a past turn's words and what's asked must be to count as the same thing. On
# 27 October, 25 recalls against 18 past turns with the real encoder: 16 of the 20 with a turn about the same thing
# found it at 0.3 or more ("printer" and "installing the new printer driver" 0.61, "hotel booking" and "book a room
# at zostel in goa" 0.43), and no other turn scored above 0.24, for those or for the 5 with none ("amazon order")
ALIKE = 0.3
FILL = 300  # turns kept before recall by meaning worked out per pass in the background, 16 to 21 ms each
_lock = threading.Lock()


def _db():
    con = sqlite3.connect(DB, timeout=5)
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS turns USING fts5(said, did, reply, plan UNINDEXED, day UNINDEXED, "
                "ts UNINDEXED, tokenize='porter unicode61')")
    # Hermes Agent's second index, by pieces of words (hermes_state_common.py messages_fts_trigram): "careerid"
    # finds "CareerID.in", for when the whole words found nothing. Filled in from turns the first time
    if not con.execute("SELECT 1 FROM sqlite_master WHERE name = 'turns_tri'").fetchone():
        with con:
            con.execute("CREATE VIRTUAL TABLE turns_tri USING fts5(said, reply, tokenize='trigram')")
            con.execute("INSERT INTO turns_tri (rowid, said, reply) SELECT rowid, said, reply FROM turns")
    # Where each turn came from and how it reached her (META), by its rowid. An FTS5 table can't take a new column
    # ("virtual tables may not be altered"), so they're a plain table beside it, each column added in place to a
    # history.db from before, nothing in it rewritten. Turns from before have no row: they count as META's values
    con.execute("CREATE TABLE IF NOT EXISTS turns_meta (id INTEGER PRIMARY KEY)")
    have = {row[1] for row in con.execute("PRAGMA table_info(turns_meta)")}
    for name, default in META:
        if name not in have:
            con.execute(f"ALTER TABLE turns_meta ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
    return con


def _when(ts):
    t = time.localtime(ts)
    return time.strftime("%a %d %b, ", t) + f"{t.tm_hour % 12 or 12}:{t.tm_min:02d} {'AM' if t.tm_hour < 12 else 'PM'}"


def add(said, did="", reply="", plan="", origin="voice", gate="named"):
    """Keep one turn: what she heard, what she did (a few words), what she said, her plan as JSON, where it came
    from (voice, phone or text) and how it reached her (named, follow or cold, heard without her name). Returns its
    id, for add_meaning."""
    ts = time.time()
    day = time.strftime("%Y-%m-%d", time.localtime(ts))
    with _lock:
        con = _db()
        try:
            with con:
                cur = con.execute("INSERT INTO turns (said, did, reply, plan, day, ts) VALUES (?, ?, ?, ?, ?, ?)",
                                  (said, did, reply, plan, day, ts))
                con.execute("INSERT INTO turns_tri (rowid, said, reply) VALUES (?, ?, ?)", (cur.lastrowid, said, reply))
                # OR REPLACE: a row left by a turn taken out by hand (clean_test_data.py) whose id comes round again
                con.execute("INSERT OR REPLACE INTO turns_meta (id, origin, gate) VALUES (?, ?, ?)",
                            (cur.lastrowid, origin, gate))
        finally:
            con.close()
        os.makedirs(DAYS_DIR, exist_ok=True)
        path = os.path.join(DAYS_DIR, day + ".md")
        new = not os.path.exists(path)
        with open(path, "a", encoding="utf-8") as f:
            if new:
                f.write(time.strftime("# %A %d %B %Y\n\nWhat you asked Jev today and what she did.\n\n", time.localtime(ts)))
            f.write(f"- **{_when(ts).split(', ')[1]}** You: {said}\n  Jev: {reply or '(nothing said)'}"
                    + (f"  _did: {did}_" if did else "") + "\n")
    return cur.lastrowid


def recent(n=8, within=1800, cold=True):
    """The last n turns from the last `within` seconds, oldest first, as (ts, said, plan). They outlast a restart.
    cold=False leaves out turns heard without her name, as her look back over the last few does (siri.review)."""
    with _lock:
        con = _db()
        try:
            rows = con.execute("SELECT t.ts, t.said, t.plan FROM turns t WHERE t.ts >= ?" + ("" if cold else NOT_COLD)
                               + " ORDER BY t.ts DESC LIMIT ?", (time.time() - within, n)).fetchall()
        finally:
            con.close()
    return [(float(ts), said, plan) for ts, said, plan in reversed(rows)]


AGO = re.compile(r"(\d+)\s*([hdw])")  # "7d", "24h", "2w", as Hermes' session_search takes them


def _since(after):
    """A time from "7d" / "24h" / "2w" or a YYYY-MM-DD day, or None."""
    after = str(after or "").strip().lower()
    m = AGO.fullmatch(after)
    if m:
        return time.time() - int(m[1]) * {"h": 3600, "d": 86400, "w": 7 * 86400}[m[2]]
    try:
        return time.mktime(time.strptime(after, "%Y-%m-%d"))
    except ValueError:
        return None


def search(query="", day=None, limit=12, after=None, around=1, cold=False, encode=None):
    """Past turns that match the words in query, best first, and/or everything on one day (YYYY-MM-DD), the way
    Hermes Agent's session_search looks: its query cleaner (hermes_state_search.py), every word first, then any of
    them, then pieces of words (turns_tri). If those find fewer than FEW and encode is given (the decider's sentence
    encoder), then by meaning too (_similar). after: only since then ("7d", "24h", "2w" or a day). around: the turns
    either side of the best few hits, so a hit has what led to it. cold: turns heard without her name too, only when
    you ask about those (siri.run_info); her day's summary never reads them. Returns [{"when", "you", "jev", "did",
    "near"?}]."""
    words = [w for w in re.findall(r"\w+", (query or "").lower()) if w not in STOP and len(w) > 1]
    since = _since(after)
    keep = "" if cold else NOT_COLD
    where, args = [], []
    if day:
        where.append("t.day = ?")
        args.append(day)
    if since:
        where.append("CAST(t.ts AS REAL) >= ?")
        args.append(since)
    if not words and not where:
        return []
    with _lock:
        con = _db()
        try:
            rows = _by_words(con, words, where, args, keep, limit) if words else con.execute(
                "SELECT t.rowid, t.ts, t.said, t.did, t.reply FROM turns t WHERE " + " AND ".join(where) + keep
                + " ORDER BY t.ts LIMIT ?", [*args, max(limit, 40)]).fetchall()
        finally:
            con.close()
    if words and len(rows) < FEW and encode is not None:
        rows += _by_meaning(query, encode, where, args, keep, limit - len(rows), {r[0] for r in rows})
    with _lock:
        con = _db()
        try:
            out = []
            for i, (rowid, ts, said, did, reply) in enumerate(rows):
                hit = {"when": _when(float(ts)), "you": said, "jev": reply, "did": did}
                if words and around and i < 3:
                    near = con.execute("SELECT said, reply FROM turns t WHERE t.rowid BETWEEN ? AND ? AND t.rowid != ? "
                                       "AND abs(CAST(t.ts AS REAL) - ?) < 1800" + keep + " ORDER BY t.rowid",
                                       (rowid - around, rowid + around, rowid, float(ts))).fetchall()
                    if near:
                        hit["near"] = [{"you": a[:120], "jev": (b or "")[:120]} for a, b in near]
                out.append(hit)
            return out
        finally:
            con.close()


def _by_words(con, words, where, args, keep, limit):
    """The tiers by words: every word (and words starting with them), then any of them, then pieces of words, the
    first that finds anything. [(rowid, ts, said, did, reply)]"""
    every = _sanitize_fts5_query(" ".join(words))  # each word stays a word, nothing read as FTS5 syntax
    every = " ".join(f'"{w}"' for w in every.replace('"', " ").split())
    prefix = lambda q: re.sub(r'"([^"]+)"', r'"\1"*', q) if q else q  # "lof" finds "lofi"
    for table, match in (("turns", prefix(every)), ("turns", prefix(_or_relaxed_query(every))),
                         ("turns_tri", " OR ".join(f'"{w}"' for w in words if len(w) >= 3))):
        if not match:
            continue
        rows = con.execute(
            "SELECT t.rowid, t.ts, t.said, t.did, t.reply FROM turns t "
            + ("JOIN turns_tri x ON x.rowid = t.rowid WHERE turns_tri MATCH ?" if table == "turns_tri"
               else "WHERE turns MATCH ?")
            + keep + "".join(f" AND {w}" for w in where)
            + f" ORDER BY bm25({table}) LIMIT ?", [match, *args, limit]).fetchall()
        if rows:
            return rows
    return []


def _vectors_path():
    return os.path.join(os.path.dirname(DB), VECTORS)


def _meanings():
    """Every turn's meaning kept so far, as the sidecar's records, or None if there are none. Only whole records: a
    write cut off by the PC going off leaves a part of one at the end."""
    path = _vectors_path()
    try:
        n = os.path.getsize(path) // RECORD.itemsize
    except OSError:
        return None
    return np.fromfile(path, RECORD, count=n) if n else None


def _by_meaning(query, encode, where, args, keep, most, seen):
    """The tier by meaning (_similar), or nothing if it can't be worked out: what the words found still stands. The
    meanings kept are read while the question's are worked out, which doesn't hold her history's lock: on 27
    October, over 10,000 turns with the real encoder, 17.6 ms for both where one after the other took 24.4."""
    if most <= 0:
        return []
    try:
        with ThreadPoolExecutor(1) as pool:
            loading = pool.submit(_loaded)
            wanted = np.asarray(encode(query), np.float32).reshape(RECORD["v"].shape)
            loaded = loading.result()
        if loaded is None:
            return []
        with _lock:
            con = _db()
            try:
                return _similar(con, *loaded, wanted, where, args, keep, most, seen)
            finally:
                con.close()
    except Exception as exc:
        print(f"  couldn't look by meaning: {exc!r}")
        return []


def _loaded():
    """Every meaning kept (_meanings) and their numbers as float32 for the dot product, or None. Float16 to float32
    is most of the time: 6 ms for 10,000, the file's read 3."""
    with _lock:  # clear() can't take the file away mid-read
        found = _meanings()
    return None if found is None else (found, found["v"].astype(np.float32))


def _similar(con, found, numbers, wanted, where, args, keep, most, seen):
    """The tier by meaning: up to `most` turns whose words mean much what was asked (wanted: its numbers), at least
    ALIKE, best first, those already found (seen, rowids) left out. One dot product over every turn kept (found,
    numbers: _loaded). A vector counts only for the turn it was worked out from, by id and time both, so one left
    over from before clear() is never taken for the turn that has its id now."""
    scores = numbers @ wanted
    best = np.flatnonzero(scores >= ALIKE)
    best = best[np.argsort(-scores[best], kind="stable")][:200]
    if not len(best):
        return []
    ids = [int(i) for i in found["id"][best]]
    rows = {r[0]: r for r in con.execute(
        f"SELECT t.rowid, t.ts, t.said, t.did, t.reply FROM turns t WHERE t.rowid IN ({','.join('?' * len(ids))})"
        + keep + "".join(f" AND {w}" for w in where), [*ids, *args]).fetchall()}
    out = []
    for rowid, ts in zip(ids, found["ts"][best].tolist()):
        row = rows.get(rowid)
        if row and rowid not in seen and abs(float(row[1]) - ts) < 1e-3:
            seen.add(rowid)
            out.append(row)
            if len(out) >= most:
                break
    return out


def _yours(said):
    """False for her own lines kept in history, "(heads-up)" and the like: no words of yours to find by meaning."""
    said = str(said or "").strip()
    return bool(said) and not (said.startswith("(") and said.endswith(")"))


def add_meaning(rowid, encode):
    """What one turn's words mean, worked out with encode (the decider's sentence encoder, 16 ms) and kept in
    the sidecar, for recall by meaning (search). Run off the voice thread once she's answered (siri.remember_meaning),
    and the lock isn't held while it works it out. True if it was kept."""
    with _lock:
        con = _db()
        try:
            row = con.execute("SELECT said, ts FROM turns WHERE rowid = ?", (rowid,)).fetchone()
        finally:
            con.close()
    if not row or not _yours(row[0]):
        return False
    try:
        record = np.zeros(1, RECORD)
        record["id"], record["ts"], record["v"] = rowid, float(row[1]), np.asarray(encode(row[0]), np.float32)
    except Exception as exc:
        print(f"  couldn't work out what a turn means: {exc!r}")
        return False
    with _lock:
        with open(_vectors_path(), "ab") as f:
            end = f.tell()
            if end % RECORD.itemsize:  # a write cut off before: what's whole stays, the next record lines up again
                f.truncate(end - end % RECORD.itemsize)
            f.write(record.tobytes())
    return True


def fill_meanings(encode, most=FILL):
    """Works out the meaning of turns kept without one (from before recall by meaning, or while the decider's model
    was missing), newest first, at most `most` a time: 300 take about 6 s, in the background every 3 hours
    (siri.summarize_days), so a history of 10,000 turns is done in under a week. Returns how many were kept."""
    with _lock:
        found = _meanings()
        con = _db()
        try:
            rows = con.execute("SELECT rowid, ts, said FROM turns ORDER BY rowid DESC").fetchall()
        finally:
            con.close()
    have = set(zip(found["id"].tolist(), found["ts"].tolist())) if found is not None else set()
    todo = [rowid for rowid, ts, said in rows if (rowid, float(ts)) not in have and _yours(said)][:most]
    return sum(add_meaning(rowid, encode) for rowid in todo)


def _day_file(day):
    return os.path.join(DAYS_DIR, f"{day}.md")


def days():
    """Every day there's a file for, oldest first, as YYYY-MM-DD."""
    if not os.path.isdir(DAYS_DIR):
        return []
    return sorted(n[:-3] for n in os.listdir(DAYS_DIR) if re.fullmatch(r"\d{4}-\d\d-\d\d\.md", n))


def summary(day):
    """The summary at the end of a day's file, or "" if it hasn't got one yet."""
    try:
        with open(_day_file(day), encoding="utf-8", errors="replace") as f:
            text = f.read()
    except OSError:
        return ""
    return text.split("\n## Summary\n", 1)[1].strip() if "\n## Summary\n" in text else ""


def unsummarized_days():
    """Days before today whose file has no summary yet."""
    today = time.strftime("%Y-%m-%d")
    return [day for day in days() if day < today and not summary(day)]


def mark_summarized(day, text):
    """Put the summary at the end of the day's file."""
    with _lock:
        with open(_day_file(day), "a", encoding="utf-8") as f:
            f.write(f"\n## Summary\n\n{text.strip() or 'Nothing much.'}\n")


def count():
    with _lock:
        con = _db()
        try:
            return con.execute("SELECT count(*) FROM turns").fetchone()[0]
        finally:
            con.close()


def clear():
    """Forget every conversation: the index, what each turn's words meant, and the day files. Her memory (MEMORY.md,
    USER.md) stays."""
    with _lock:
        con = _db()
        try:
            with con:
                con.execute("DELETE FROM turns")
                con.execute("DELETE FROM turns_tri")
                con.execute("DELETE FROM turns_meta")
            con.execute("VACUUM")
        finally:
            con.close()
        try:
            os.remove(_vectors_path())
        except FileNotFoundError:
            pass
        if os.path.isdir(DAYS_DIR):
            for name in os.listdir(DAYS_DIR):
                if re.fullmatch(r"\d{4}-\d\d-\d\d\.md", name):
                    os.remove(os.path.join(DAYS_DIR, name))
