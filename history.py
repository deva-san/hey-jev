"""Everything you've asked her and what she did, kept on this PC, the way Hermes Agent keeps its sessions: a SQLite
full-text index she can search ("what did we talk about yesterday?"), and one Markdown file a day you can read,
in %APPDATA%\\Hey Jev\\memories\\days.
"""
import os
import re
import sqlite3
import threading
import time

from hermes_memory.hermes_bits import _or_relaxed_query, _sanitize_fts5_query
from winplatform import APPDATA_DIR

DB = os.path.join(APPDATA_DIR, "history.db")
DAYS_DIR = os.path.join(APPDATA_DIR, "memories", "days")
STOP = set("a an and are as at be but by can could did do does for from had has have he her his how i if in into is "
           "it its me my of on or our she so that the their them then there these they this to up was we were what "
           "when where which who why will with would you your about again just like okay ok yeah hey jev please "
           # words that ask about the past rather than say what about: "what did we talk about today"
           "talk talked talking said say ask asked tell told today yesterday conversation conversations discuss "
           "discussed remember earlier".split())
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
    return con


def _when(ts):
    t = time.localtime(ts)
    return time.strftime("%a %d %b, ", t) + f"{t.tm_hour % 12 or 12}:{t.tm_min:02d} {'AM' if t.tm_hour < 12 else 'PM'}"


def add(said, did="", reply="", plan=""):
    """Keep one turn: what she heard, what she did (a few words), what she said, and her plan as JSON."""
    ts = time.time()
    day = time.strftime("%Y-%m-%d", time.localtime(ts))
    with _lock:
        con = _db()
        try:
            with con:
                cur = con.execute("INSERT INTO turns (said, did, reply, plan, day, ts) VALUES (?, ?, ?, ?, ?, ?)",
                                  (said, did, reply, plan, day, ts))
                con.execute("INSERT INTO turns_tri (rowid, said, reply) VALUES (?, ?, ?)", (cur.lastrowid, said, reply))
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


def recent(n=8, within=1800):
    """The last n turns from the last `within` seconds, oldest first, as (ts, said, plan). They outlast a restart."""
    with _lock:
        con = _db()
        try:
            rows = con.execute("SELECT ts, said, plan FROM turns WHERE ts >= ? ORDER BY ts DESC LIMIT ?",
                               (time.time() - within, n)).fetchall()
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


def search(query="", day=None, limit=12, after=None, around=1):
    """Past turns that match the words in query, best first, and/or everything on one day (YYYY-MM-DD), the way
    Hermes Agent's session_search looks: its query cleaner (hermes_state_search.py), every word first, then any of
    them, then pieces of words (turns_tri). after: only since then ("7d", "24h", "2w" or a day). around: the turns
    either side of the best few hits, so a hit has what led to it. Returns [{"when", "you", "jev", "did", "near"?}]."""
    words = [w for w in re.findall(r"\w+", (query or "").lower()) if w not in STOP and len(w) > 1]
    since = _since(after)
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
            rows = []
            if words:
                every = _sanitize_fts5_query(" ".join(words))  # each word stays a word, nothing read as FTS5 syntax
                every = " ".join(f'"{w}"' for w in every.replace('"', " ").split())
                prefix = lambda q: re.sub(r'"([^"]+)"', r'"\1"*', q) if q else q  # "lof" finds "lofi"
                for table, match in (("turns", prefix(every)), ("turns", prefix(_or_relaxed_query(every))),
                                     ("turns_tri", " OR ".join(f'"{w}"' for w in words if len(w) >= 3))):
                    if not match:
                        continue
                    rows = con.execute(
                        f"SELECT t.rowid, t.ts, t.said, t.did, t.reply FROM turns t "
                        + (f"JOIN turns_tri x ON x.rowid = t.rowid WHERE turns_tri MATCH ?" if table == "turns_tri"
                           else "WHERE turns MATCH ?")
                        + "".join(f" AND {w}" for w in where)
                        + f" ORDER BY bm25({table}) LIMIT ?", [match, *args, limit]).fetchall()
                    if rows:
                        break
            else:
                rows = con.execute("SELECT t.rowid, t.ts, t.said, t.did, t.reply FROM turns t WHERE "
                                   + " AND ".join(where) + " ORDER BY t.ts LIMIT ?", [*args, max(limit, 40)]).fetchall()
            out = []
            for i, (rowid, ts, said, did, reply) in enumerate(rows):
                hit = {"when": _when(float(ts)), "you": said, "jev": reply, "did": did}
                if words and around and i < 3:
                    near = con.execute("SELECT said, reply FROM turns WHERE rowid BETWEEN ? AND ? AND rowid != ? "
                                       "AND abs(CAST(ts AS REAL) - ?) < 1800 ORDER BY rowid",
                                       (rowid - around, rowid + around, rowid, float(ts))).fetchall()
                    if near:
                        hit["near"] = [{"you": a[:120], "jev": (b or "")[:120]} for a, b in near]
                out.append(hit)
            return out
        finally:
            con.close()


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
    """Forget every conversation: the index and the day files. Her memory (MEMORY.md, USER.md) stays."""
    with _lock:
        con = _db()
        try:
            with con:
                con.execute("DELETE FROM turns")
                con.execute("DELETE FROM turns_tri")
            con.execute("VACUUM")
        finally:
            con.close()
        if os.path.isdir(DAYS_DIR):
            for name in os.listdir(DAYS_DIR):
                if re.fullmatch(r"\d{4}-\d\d-\d\d\.md", name):
                    os.remove(os.path.join(DAYS_DIR, name))
