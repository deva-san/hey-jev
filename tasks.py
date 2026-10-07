"""Hey Jev's small, durable background task queue.

One SQLite file, one sleeping worker in siri.py, and a guarded hidden PowerShell runner. No job framework or shell
library. Code, never the answer model, decides which commands may run.
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import re
import shlex
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

from winplatform import APPDATA_DIR, CREATE_NO_WINDOW, POWERSHELL

DB_PATH = os.path.join(APPDATA_DIR, "tasks.db")
STATUSES = {"queued", "running", "waiting_approval", "completed", "failed", "cancelled"}
KINDS = {"command", "reminder", "lookup", "research", "install"}
CHANGES_PC = {"command", "install"}  # never re-run by themselves after Jev stopped part-way: they ask again
OUTPUT_LIMIT = 64 * 1024
MAX_COMMAND = 1000
WAKE = threading.Event()


def _json(value, fallback):
    try:
        return json.loads(value) if isinstance(value, str) else value
    except (TypeError, ValueError):
        return fallback


class Store:
    def __init__(self, path=DB_PATH):
        self.path = path
        self._ready = False
        self._lock = threading.Lock()

    def _db(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        con = sqlite3.connect(self.path, timeout=5)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA busy_timeout=5000")
        return con

    def init(self):
        with self._lock:
            if self._ready:
                return
            with self._db() as con:
                con.execute("""CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    description TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    status TEXT NOT NULL,
                    created REAL NOT NULL,
                    due REAL NOT NULL,
                    repeat_spec TEXT,
                    result TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    started REAL,
                    finished REAL,
                    updated REAL NOT NULL
                )""")
                con.execute("CREATE INDEX IF NOT EXISTS task_due ON tasks(status, due)")
            self._ready = True

    def recover(self):
        """Recover work left running by a previous process. Call once, only from task_worker at app startup."""
        self.init()
        with self._db() as con:
            # A command may have changed something before the app stopped. Never repeat it automatically: remove
            # its approval and ask again. Read-only lookups/reminders/research are safe to retry.
            now = time.time()
            for row in con.execute("SELECT id,kind,payload FROM tasks WHERE status='running'").fetchall():
                if row["kind"] in CHANGES_PC:
                    payload = _json(row["payload"], {})
                    payload.pop("approved", None)
                    con.execute("UPDATE tasks SET payload=?, status='waiting_approval', error=?, started=NULL, "
                                "updated=? WHERE id=?", (json.dumps(payload, ensure_ascii=False),
                                f"Jev stopped while this {row['kind']} was running; approve it to retry", now,
                                row["id"]))
                else:
                    con.execute("UPDATE tasks SET status='queued', started=NULL, updated=? WHERE id=?", (now, row["id"]))
        WAKE.set()

    @staticmethod
    def _row(row):
        if row is None:
            return None
        out = dict(row)
        out["payload"] = _json(out.get("payload"), {})
        out["repeat"] = _json(out.pop("repeat_spec", None), None)
        return out

    def create(self, description, kind, payload, due=None, repeat=None, status="queued"):
        self.init()
        kind, status = str(kind), str(status)
        if kind not in KINDS or status not in STATUSES:
            raise ValueError("unsupported task")
        description = " ".join(str(description or kind).split())[:160] or kind
        now, due = time.time(), float(due if due is not None else time.time())
        with self._db() as con:
            cur = con.execute("""INSERT INTO tasks
                (description,kind,payload,status,created,due,repeat_spec,updated)
                VALUES (?,?,?,?,?,?,?,?)""",
                (description, kind, json.dumps(payload, ensure_ascii=False), status, now, due,
                 json.dumps(repeat) if repeat else None, now))
            task_id = cur.lastrowid
        WAKE.set()
        return task_id

    def get(self, task_id):
        self.init()
        with self._db() as con:
            return self._row(con.execute("SELECT * FROM tasks WHERE id=?", (int(task_id),)).fetchone())

    def latest(self):
        self.init()
        with self._db() as con:
            return self._row(con.execute("SELECT * FROM tasks WHERE status!='cancelled' ORDER BY id DESC LIMIT 1").fetchone())

    def list(self, limit=40, active=False):
        self.init()
        where = "WHERE status IN ('queued','running','waiting_approval')" if active else ""
        with self._db() as con:
            rows = con.execute(f"SELECT * FROM tasks {where} ORDER BY CASE status WHEN 'running' THEN 0 "
                               "WHEN 'waiting_approval' THEN 1 WHEN 'queued' THEN 2 ELSE 3 END, due, id DESC LIMIT ?",
                               (max(1, min(200, int(limit))),)).fetchall()
        return [self._row(row) for row in rows]

    def cancel(self, task_id):
        self.init()
        with self._db() as con:
            cur = con.execute("UPDATE tasks SET status='cancelled', updated=? WHERE id=? AND status IN "
                              "('queued','running','waiting_approval')", (time.time(), int(task_id)))
        WAKE.set()
        return bool(cur.rowcount)

    def approve(self, task_id):
        self.init()
        task = self.get(task_id)
        if not task or task["status"] != "waiting_approval":
            return False
        payload = dict(task["payload"])
        payload["approved"] = True
        with self._db() as con:
            cur = con.execute("UPDATE tasks SET payload=?, status='queued', due=?, updated=? WHERE id=? AND "
                              "status='waiting_approval'", (json.dumps(payload, ensure_ascii=False), time.time(),
                                                            time.time(), int(task_id)))
        WAKE.set()
        return bool(cur.rowcount)

    def claim_due(self, now=None, skip=()):
        """The next due task, now running, or None. skip: kinds to leave queued for now."""
        self.init()
        now = float(now if now is not None else time.time())
        con = self._db()
        try:
            con.execute("BEGIN IMMEDIATE")
            row = con.execute(f"SELECT * FROM tasks WHERE status='queued' AND due<=? AND kind NOT IN "
                              f"({','.join('?' * len(skip))}) ORDER BY due,id LIMIT 1", (now, *skip)).fetchone()
            if row is None:
                con.rollback()
                return None
            cur = con.execute("UPDATE tasks SET status='running', started=?, updated=? WHERE id=? AND status='queued'",
                              (now, now, row["id"]))
            if cur.rowcount != 1:
                con.rollback()
                return None
            con.commit()
            return self.get(row["id"])
        finally:
            con.close()

    def wait_for_approval(self, task_id, reason):
        self.init()
        with self._db() as con:
            con.execute("UPDATE tasks SET status='waiting_approval', error=?, started=NULL, updated=? WHERE id=? AND "
                        "status='running'", (str(reason)[:500], time.time(), int(task_id)))

    def finish(self, task_id, result="", error=""):
        self.init()
        task = self.get(task_id)
        if not task or task["status"] == "cancelled":
            return
        now = time.time()
        if task["repeat"]:
            due = next_due(task["due"], task["repeat"], now)
            payload = dict(task["payload"])
            payload.pop("approved", None)  # a mutating recurring command needs approval every time
            with self._db() as con:
                con.execute("""UPDATE tasks SET status='queued', payload=?, due=?, result=?, error=?, started=NULL,
                            finished=?, updated=? WHERE id=? AND status='running'""",
                            (json.dumps(payload, ensure_ascii=False), due, str(result)[:OUTPUT_LIMIT], str(error)[:2000],
                             now, now, int(task_id)))
        else:
            status = "failed" if error else "completed"
            with self._db() as con:
                con.execute("UPDATE tasks SET status=?, result=?, error=?, finished=?, updated=? WHERE id=? AND "
                            "status='running'", (status, str(result)[:OUTPUT_LIMIT], str(error)[:2000], now, now,
                                                 int(task_id)))
        WAKE.set()

    def is_cancelled(self, task_id):
        task = self.get(task_id)
        return not task or task["status"] == "cancelled"

    def wait(self, maximum=30.0, skip=()):
        self.init()
        with self._db() as con:
            row = con.execute(f"SELECT MIN(due) FROM tasks WHERE status='queued' AND kind NOT IN "
                              f"({','.join('?' * len(skip))})", skip).fetchone()
        due = row[0] if row else None
        seconds = maximum if due is None else max(0.1, min(maximum, float(due) - time.time()))
        WAKE.wait(seconds)
        WAKE.clear()


# --------------------------------------------------------------------------- schedules
WEEKDAYS = {name: i for i, name in enumerate(("monday", "tuesday", "wednesday", "thursday", "friday",
                                               "saturday", "sunday"))}
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
           "ten": 10, "eleven": 11, "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50}
UNITS = {"second": 1, "minute": 60, "hour": 3600, "day": 86400}


def _number(text):
    text = str(text).lower()
    return float(text) if re.fullmatch(r"\d+(?:\.\d+)?", text) else NUMBERS.get(text)


def _spoken(text):
    """Times as people say them, the way the patterns below read them: 'in half an hour' -> 'in 30 minutes', 'in an
    hour and a half' -> 'in 1.5 hours', 'every hour' or 'hourly' -> 'every 1 hour', 'twenty five' -> '25'. All of
    these were refused."""
    t = re.sub(r"\bhalf an? hour\b", "30 minutes", str(text).lower())
    t = re.sub(r"\bhourly\b", "every hour", t)
    t = re.sub(r"\b(sec|min|hr)s?\b", lambda m: {"sec": "second", "min": "minute", "hr": "hour"}[m[1]], t)  # "in 15 mins"
    t = re.sub(r"\b(?:(twenty|thirty|forty|fifty)[ -])?(" + "|".join(NUMBERS) + r")\b",
               lambda m: str(NUMBERS.get(m[1], 0) + NUMBERS[m[2]]), t)
    t = re.sub(r"\bat (\d{1,2}) ([0-5]\d)\b", r"at \1:\2", t)  # "at ten thirty" was 10:00
    t = re.sub(r"\ban? (second|minute|hour|day)\b", r"1 \1", t)
    t = re.sub(r"\bevery (second|minute|hour)\b", r"every 1 \1", t)  # "every day" stays: daily, at a time
    return re.sub(r"\b(\d+)(?: and a half)? (second|minute|hour|day)s?(?: and a half)?\b",
                  lambda m: f"{m[1]}.5 {m[2]}s" if "half" in m[0] else m[0], t)


def _clock(text):
    text = str(text).lower()
    if re.search(r"\bmidnight\b", text):
        return 0, 0
    if re.search(r"\b(?:noon|midday)\b", text):
        return 12, 0
    m = re.search(r"\b(\d{1,2})(?::(\d\d))?\s*(am|pm)?\b", text)
    if not m:
        return None
    hour, minute, meridiem = int(m[1]), int(m[2] or 0), (m[3] or "").lower()
    if meridiem:
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if meridiem == "pm" else 0)
    elif re.search(r"\b(?:tonight|night)\b", text) and (hour == 12 or hour < 5):
        hour %= 12  # "tonight at 12" is midnight, not noon the next day, and "tonight at 1" is 1 AM
    elif 0 < hour < 12 and re.search(r"\b(?:tonight|night|evening|afternoon)\b", text):
        hour += 12  # "tonight at 8" was 8 the next morning
    if not 0 <= hour <= 23 or not 0 <= minute <= 59:
        return None
    return hour, minute


def _at(day, clock):
    return day.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)


def normalize_schedule(when=None, repeat=None, now=None):
    """(due timestamp, canonical repeat dict or None). Accepts ISO, 'in 2 hours', 'tomorrow at 6 PM', daily,
    every N units, and weekly weekday/time. The model can send repeat as a dict or plain words."""
    now_dt = dt.datetime.fromtimestamp(float(now if now is not None else time.time()))
    spec = None
    r = repeat or ""
    if isinstance(r, dict):
        kind = str(r.get("kind") or "").lower()
        if kind == "interval":
            seconds = int(r.get("seconds") or 0)
            spec = {"kind": "interval", "seconds": seconds} if seconds >= 60 else None
        elif kind in ("daily", "weekly"):
            clock = _clock(str(r.get("time") or when or ""))
            weekday = WEEKDAYS.get(str(r.get("weekday") or "").lower())
            if clock and (kind == "daily" or weekday is not None):
                spec = {"kind": kind, "hour": clock[0], "minute": clock[1]}
                if kind == "weekly":
                    spec["weekday"] = weekday
    elif r:
        text = _spoken(r).strip()
        m = re.search(r"every\s+(\d+(?:\.\d+)?|" + "|".join(NUMBERS) + r")\s+(seconds?|minutes?|hours?|days?)", text)
        if m:
            seconds = int(_number(m[1]) * UNITS[m[2].rstrip("s")])
            if seconds >= 60:
                spec = {"kind": "interval", "seconds": seconds}
        else:
            clock = _clock(text)
            weekday = next((i for name, i in WEEKDAYS.items() if name in text), None)
            if weekday is not None and clock:
                spec = {"kind": "weekly", "weekday": weekday, "hour": clock[0], "minute": clock[1]}
            # "every day at 9", "every midnight". Not any "every": "every 2 weeks at 9" was every day at 2 AM
            elif clock and re.search(r"\b(?:daily|every ?day|every (?:night|morning|evening|afternoon|midnight|noon|"
                                     r"midday))\b", text):
                spec = {"kind": "daily", "hour": clock[0], "minute": clock[1]}
    if repeat and spec is None:
        raise ValueError("I couldn't understand how often")

    if isinstance(when, (int, float)):
        due = float(when)
    else:
        text = str(when or "").strip()
        due = None
        if text:
            try:
                due = dt.datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp()
            except ValueError:
                pass
        text = _spoken(text)
        m = re.search(r"\b(?:in|after)\s+((?:\d+(?:\.\d+)?\s+(?:second|minute|hour|day)s?\b(?:\s+and)?\s*)+)", text)
        if due is None and m:  # "in 1 hour 30 minutes" is both, and "in 1.5 hours" was 1 AM
            due = now_dt.timestamp() + sum(float(n) * UNITS[u] for n, u in
                                           re.findall(r"(\d+(?:\.\d+)?)\s+(second|minute|hour|day)", m[1]))
        clock = None if re.search(r"\bin \d", text) else _clock(text)  # "in 5 fortnights" isn't 5 AM
        if due is None and clock:
            day = now_dt + dt.timedelta(days=1 if "tomorrow" in text.lower() else 0)
            if "tomorrow" in text and clock[0] < 5 and re.search(r"\bnight\b", text):
                day += dt.timedelta(days=1)  # "tomorrow night at 12" is the small hours after tomorrow, not tonight
            weekday = next((i for name, i in WEEKDAYS.items() if name in text.lower()), None)
            if weekday is not None:
                day += dt.timedelta(days=(weekday - day.weekday()) % 7)
            target = _at(day, clock)
            if target <= now_dt:
                target += dt.timedelta(days=7 if weekday is not None else 1)
            due = target.timestamp()
    if due is None and spec:
        due = next_due(now_dt.timestamp(), spec, now_dt.timestamp())
    if due is None:
        raise ValueError("I couldn't understand when")
    return float(due), spec


def next_due(previous, spec, now=None):
    now = float(now if now is not None else time.time())
    kind = spec.get("kind")
    if kind == "interval":
        seconds = max(60, int(spec["seconds"]))
        return float(previous) + max(1, math.floor((now - float(previous)) / seconds) + 1) * seconds
    here = dt.datetime.fromtimestamp(now)
    if kind == "daily":
        target = _at(here, (int(spec["hour"]), int(spec.get("minute", 0))))
        if target.timestamp() <= now:
            target += dt.timedelta(days=1)
        return target.timestamp()
    if kind == "weekly":
        target = _at(here, (int(spec["hour"]), int(spec.get("minute", 0))))
        target += dt.timedelta(days=(int(spec["weekday"]) - target.weekday()) % 7)
        if target.timestamp() <= now:
            target += dt.timedelta(days=7)
        return target.timestamp()
    raise ValueError("unsupported repeat")


def describe_due(timestamp):
    d = dt.datetime.fromtimestamp(float(timestamp))
    today = dt.datetime.now().date()
    day = "today" if d.date() == today else "tomorrow" if d.date() == today + dt.timedelta(days=1) else d.strftime("%A %d %B")
    return f"{day} at {d.strftime('%I:%M %p').lstrip('0')}"


# --------------------------------------------------------------------------- commands
BLOCKED = (
    (r"\b(?:format|diskpart|bcdedit|reagentc|shutdown|restart-computer|stop-computer|clear-disk|remove-partition)\b",
     "system or disk changes are blocked"),
    (r"\b(?:set-mppreference|add-mppreference|netsh\s+advfirewall|disable-windows|enable-windows|"
     r"reg(?:\.exe)?\s+(?:add|delete)|net\s+(?:user|localgroup)|(?:new|set|remove)-localuser|icacls|takeown)\b",
     "security, account, permission, and registry changes are blocked"),
    (r"\b(?:mshta|rundll32|regsvr32|wscript|cscript|wmic\s+process\s+call\s+create|schtasks\s+/create|"
     r"cmdkey|vaultcmd|get-credential|get-secret)\b", "indirect execution and credential tools are blocked"),
    (r"\b(?:invoke-expression|iex|invoke-restmethod|irm|downloadstring|frombase64string|start-bitstransfer|bitsadmin|"
     r"certutil\s+-urlcache)\b|-(?:e|enc|encodedcommand)\b",
     "hidden or downloaded code is blocked"),
    (r"\b(?:runas|start-process\b[^\r\n]*-verb\s+runas)\b", "administrator commands are blocked"),
    (r"\bgit\s+(?:reset\s+--hard|clean\s+-[a-z]*f|push\b[^\r\n]*--force)\b", "destructive Git commands are blocked"),
    (r"\b(?:rm\s+-[a-z]*r[a-z]*|rmdir\s+/s|del\s+/s)\b|\bremove-item\b[^\r\n]*-recurse",
     "recursive deletion is blocked"),
    (r"(?:\.env\b|credentials?\b|id_rsa\b|id_ed25519\b|\.(?:pem|pfx|key)\b|\benv:|\$env\b)",
     "reading credentials, environment variables, and private keys is blocked"),
    (r"(?:^|\s)(?:cmd(?:\.exe)?\s+/c|powershell(?:\.exe)?\b|pwsh(?:\.exe)?\b)",
     "nested command shells are blocked"),
    (r"\b(?:invoke-webrequest|iwr|curl|wget|scp|sftp|ftp|ssh|telnet|ncat|netcat)\b", "network transfers belong in Jev's browser tools, not commands"),
)
CONFIRM = re.compile(
    r"\b(?:set-content|add-content|out-file|new-item|remove-item|move-item|copy-item|rename-item|clear-content|start-process|"
    r"mkdir|rmdir|robocopy|xcopy|taskkill|stop-process|stop-service|start-service|set-service|setx|winget|choco)\b|"
    r"\b(?:pip|python\s+-m\s+pip)\s+(?:install|uninstall)\b|\bnpm\s+(?:install|uninstall|update)\b|"
    r"\bgit\s+(?:add|commit|push|pull|checkout|switch|merge|rebase|restore|stash|tag)\b|(?:^|\s)(?:del|erase|move|copy)\s",
    re.I)
READ_CMDLETS = {"get-childitem", "get-content", "select-string", "get-process", "get-ciminstance", "get-item",
                "get-command", "test-path", "resolve-path", "measure-object", "where-object", "sort-object"}
SECRET = re.compile(r"(?i)(?:bearer\s+|api[_ -]?key\s*[:=]\s*|token\s*[:=]\s*|password\s*[:=]\s*)\S+|"
                    r"\beyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b|"
                    r"\b(?:sk|pk|ghp|github_pat)_[A-Za-z0-9_-]{16,}\b|\bAKIA[A-Z0-9]{16}\b")
URL_SECRET = re.compile(r"(?i)(https?://)[^/@\s:]+(?::[^@\s]+)?@")


def project_test_command(cwd):
    """The conventional test command already declared by a project, or None. It only inspects filenames/config."""
    cwd = os.path.abspath(os.path.expandvars(str(cwd or "")))
    if not os.path.isdir(cwd):
        return None
    package = os.path.join(cwd, "package.json")
    if os.path.isfile(package):
        try:
            with open(package, encoding="utf-8") as f:
                if "test" in (json.load(f).get("scripts") or {}):
                    return "npm test"
        except (OSError, ValueError):
            pass
    if any(name.lower().endswith((".sln", ".csproj")) for name in os.listdir(cwd)):
        return "dotnet test"
    if os.path.isfile(os.path.join(cwd, "go.mod")):
        return "go test ./..."
    if os.path.isfile(os.path.join(cwd, "Cargo.toml")):
        return "cargo test"
    pytest = any(os.path.exists(os.path.join(cwd, name)) for name in ("pytest.ini", "tox.ini", "conftest.py"))
    pyproject = os.path.join(cwd, "pyproject.toml")
    if not pytest and os.path.isfile(pyproject):
        try:
            with open(pyproject, encoding="utf-8", errors="ignore") as f:
                pytest = "pytest" in f.read(100000).lower()
        except OSError:
            pass
    if pytest:
        python = os.path.join(cwd, ".venv", "Scripts", "python.exe")
        python = python if os.path.isfile(python) else sys.executable
        return f'"{python}" -m pytest'
    return None


def command_policy(command, cwd=None):
    """('allow'|'confirm'|'block', reason). Conservative by design; an unknown simple command needs approval."""
    command = " ".join(str(command or "").split())
    if not command or len(command) > MAX_COMMAND or any(ord(c) < 32 for c in command):
        return "block", "the command is empty, too long, or contains control characters"
    if cwd is not None and (not os.path.isdir(os.path.abspath(os.path.expandvars(str(cwd))))):
        return "block", "the working folder doesn't exist"
    low = command.lower()
    for pattern, reason in BLOCKED:
        if re.search(pattern, low, re.I):
            return "block", reason
    if re.search(r"[`]|\$\(|@\(|\r|\n", command):
        return "block", "nested or multiline PowerShell is blocked"
    try:
        words = [w.strip('"\'') for w in shlex.split(command, posix=False)]
    except ValueError:
        return "block", "the command couldn't be parsed"
    if not words:
        return "block", "the command is empty"
    exe = os.path.basename(words[0]).lower()
    args = [w.lower() for w in words[1:]]
    if CONFIRM.search(command) or re.search(r"[;&|<>]", command):
        return "confirm", "it can change files, programs, or the system"
    if exe in ("git", "git.exe") and args and args[0] in {"status", "diff", "log", "show", "rev-parse", "ls-files", "remote"}:
        return "allow", "read-only Git"
    if exe in ("npm", "npm.cmd") and (args[:1] == ["test"] or len(args) >= 2 and args[0] == "run" and args[1] in
                                       {"test", "build", "lint", "typecheck", "check"} or args == ["--version"]):
        return "allow", "project verification"
    if exe in ("python", "python.exe", "py", "py.exe") and (args and (args[0] in {"--version", "-v"} or
            len(args) >= 2 and args[0] == "-m" and args[1] in {"pytest", "unittest", "compileall", "py_compile"})):
        return "allow", "Python verification"
    if exe in ("pytest", "pytest.exe") or exe in ("node", "node.exe") and args == ["--version"]:
        return "allow", "project verification"
    if exe in ("dotnet", "dotnet.exe") and args and args[0] in {"test", "build", "--info", "--version"}:
        return "allow", "project verification"
    if (exe in ("go", "go.exe") and args[:1] == ["test"]) or \
            (exe in ("cargo", "cargo.exe") and args[:1] in (["test"], ["check"])):
        return "allow", "project verification"
    if exe in READ_CMDLETS or exe in {"dir", "where", "where.exe", "systeminfo", "whoami", "hostname"}:
        return "allow", "read-only diagnostic"
    return "confirm", "it isn't on the automatic read-only list"


def redact(text):
    return SECRET.sub("[redacted]", URL_SECRET.sub(r"\1[redacted]@", str(text or "")))


def _stop_tree(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=CREATE_NO_WINDOW, timeout=10)


def _read_output(path):
    size = os.path.getsize(path)
    with open(path, "rb") as f:
        if size <= OUTPUT_LIMIT:
            data = f.read()
        else:
            half = OUTPUT_LIMIT // 2
            data = f.read(half) + b"\n... output truncated ...\n"
            f.seek(-half, os.SEEK_END)
            data += f.read(half)
    return redact(data.decode("utf-8", "replace").strip())


def run_command(command, cwd, approved=False, timeout=120, cancelled=lambda: False):
    """Run one guarded command with no visible window. Returns {exit_code, output, seconds}; raises on policy/timeout."""
    cwd = os.path.abspath(os.path.expandvars(str(cwd or "")))
    level, reason = command_policy(command, cwd)
    if level == "block":
        raise RuntimeError(reason)
    if level == "confirm" and not approved:
        raise PermissionError(reason)
    timeout = max(1, min(120, int(timeout or 120)))
    fd, path = tempfile.mkstemp(prefix="heyjev-command-", suffix=".log")
    os.close(fd)
    started = time.time()
    try:
        with open(path, "wb") as out:
            proc = subprocess.Popen([POWERSHELL, "-NoLogo", "-NoProfile", "-NonInteractive", "-Command", command],
                                    cwd=cwd, stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                    creationflags=CREATE_NO_WINDOW)
            while proc.poll() is None:
                if cancelled():
                    _stop_tree(proc.pid)
                    raise RuntimeError("cancelled")
                if time.time() - started > timeout:
                    _stop_tree(proc.pid)
                    raise TimeoutError(f"timed out after {timeout} seconds")
                time.sleep(0.1)
        return {"exit_code": proc.returncode, "output": _read_output(path),
                "seconds": round(time.time() - started, 2)}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
