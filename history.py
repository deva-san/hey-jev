"""Everything you've asked her and what she did, kept on this PC, the way Hermes Agent keeps its sessions: a SQLite
full-text index she can search ("what did we talk about yesterday?"), and one Markdown file a day you can read,
in %APPDATA%\\Hey Jev\\memories\\days.
"""
import os
import re
import sqlite3
import threading
import time

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
                con.execute("INSERT INTO turns (said, did, reply, plan, day, ts) VALUES (?, ?, ?, ?, ?, ?)",
                            (said, did, reply, plan, day, ts))
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


def search(query="", day=None, limit=12):
    """Past turns that match the words in query, best first, and/or everything on one day (YYYY-MM-DD).
    Returns [{"when", "you", "jev", "did"}]."""
    words = [w for w in re.findall(r"\w+", (query or "").lower()) if w not in STOP and len(w) > 1]
    sql, args = "SELECT ts, said, did, reply FROM turns", []
    where = []
    if words:  # each word quoted, so nothing she heard can be read as FTS5 syntax
        where.append("turns MATCH ?")
        args.append(" OR ".join(f'"{w}"*' for w in words))
    if day:
        where.append("day = ?")
        args.append(day)
    if not where:
        return []
    sql += " WHERE " + " AND ".join(where) + (" ORDER BY bm25(turns)" if words else " ORDER BY ts") + " LIMIT ?"
    args.append(limit if words else max(limit, 40))
    with _lock:
        con = _db()
        try:
            rows = con.execute(sql, args).fetchall()
        finally:
            con.close()
    return [{"when": _when(float(ts)), "you": said, "jev": reply, "did": did} for ts, said, did, reply in rows]


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
            con.execute("VACUUM")
        finally:
            con.close()
        if os.path.isdir(DAYS_DIR):
            for name in os.listdir(DAYS_DIR):
                if re.fullmatch(r"\d{4}-\d\d-\d\d\.md", name):
                    os.remove(os.path.join(DAYS_DIR, name))
