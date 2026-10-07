"""Back up Hey Jev's data, put a backup back, or start her memory fresh. Close Hey Jev first.

    python backup.py                  zip her data to %LOCALAPPDATA%\\Hey Jev\\Backups
    python backup.py --restore FILE   put a backup back (what's there now is backed up first, so it can be undone)
    python backup.py --fresh          back up, then clear her memory, skills and old chats; she introduces herself

The zip holds all of %APPDATA%\\Hey Jev (memory, skills, history.db, settings, contacts, tasks, personality), the
Dictionary (vocabulary.json) and app list (apps.json) from this folder, and her voice profile and decider data from
%LOCALAPPDATA%\\Hey Jev when they exist. The models and logs aren't in it: a fresh start never touches them.
"""
import argparse
import ctypes
import json
import logging
import os
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from contextlib import suppress
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_FILES = ("vocabulary.json", "apps.json")  # the Dictionary and the app list live next to the code
LOCAL_DIRS = ("voice", "decider")  # in %LOCALAPPDATA%\Hey Jev: her picture of your voice, the decider's data
# What --fresh clears in %APPDATA%\Hey Jev: what she knows about you, her notes and day files (memories), the skills
# she learned, and old chats. Settings, contacts, tasks, SOUL.md, the Dictionary and the app list stay.
WIPE = ("memories", "skills", "history.db", "history.db-wal", "history.db-shm")
SIDE_FILES = (".db-wal", ".db-shm", ".db-journal")  # SQLite's own; the backup copy of the .db already has them merged


def appdata():
    return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "Hey Jev")


def localdata():
    return os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Hey Jev")


def running():
    """True while Hey Jev is open: she holds this mutex for as long as she runs (winplatform.single_instance)."""
    if os.name != "nt":
        return False
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenMutexW.restype = ctypes.c_void_p
    kernel32.OpenMutexW.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_wchar_p)
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    handle = kernel32.OpenMutexW(0x00100000, False, "Local\\HeyJevSingleInstance")  # SYNCHRONIZE
    if handle:
        kernel32.CloseHandle(handle)
    return bool(handle)


def _closed():
    if running():
        raise SystemExit("Hey Jev is running. Quit her first (right-click her taskbar icon), then run this again.")


# --- Hermes Agent, hermes_cli/backup_sqlite.py:21-82 (MIT, commit 3569fba6): a consistent copy of a live database ---

class _SQLiteBackupTimeout(RuntimeError):
    """Raised when a SQLite snapshot remains busy past its deadline."""


def _close_quietly(conn: Optional[sqlite3.Connection]) -> None:
    if conn is not None:
        with suppress(Exception):
            conn.close()


def _safe_copy_db(src: Path, dst: Path, *, timeout_seconds: float = 10.0) -> bool:
    """Copy a SQLite database with the backup() API (WAL-safe consistent snapshot).

    Fails closed when no consistent snapshot can be made: copying only the main file loses WAL data.
    """
    conn = backup_conn = None
    try:
        # sqlite3.connect() creates a missing destination with the process
        # umask, which is commonly 0022 (0644).  Snapshot databases contain
        # session and tool state, so create the inode owner-only before SQLite
        # writes its first byte.  O_NOFOLLOW also refuses a planted symlink on
        # platforms that support it.  Tighten an existing internal staging
        # file as well (NamedTemporaryFile callers already create it 0600).
        if os.name != "nt":
            open_flags = os.O_WRONLY | os.O_CREAT
            if hasattr(os, "O_NOFOLLOW"):
                open_flags |= os.O_NOFOLLOW
            secure_fd = os.open(dst, open_flags, 0o600)
            try:
                os.fchmod(secure_fd, 0o600)
            finally:
                os.close(secure_fd)
        # timeout=0.0 disables sqlite3's implicit busy wait so the progress callback owns the
        # full locked-source deadline instead of adding the default timeout before each callback.
        conn = sqlite3.connect(f"{src.resolve().as_uri()}?mode=ro", uri=True, timeout=0.0)
        backup_conn = sqlite3.connect(str(dst))
        busy_deadline = time.monotonic() + max(0.0, timeout_seconds)

        def _check_backup_progress(status: int, _remaining: int, _total: int) -> None:
            nonlocal busy_deadline
            now = time.monotonic()
            if status in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED):
                if now >= busy_deadline:
                    raise _SQLiteBackupTimeout(f"database remained locked for {timeout_seconds:g} seconds")
            else:
                busy_deadline = now + max(0.0, timeout_seconds)

        conn.backup(backup_conn, pages=256, progress=_check_backup_progress, sleep=0.1)
        return True
    except Exception as exc:
        logger.warning("SQLite safe copy failed for %s: %s", src, exc)
        # Windows won't remove the partial destination while SQLite still has it open.
        _close_quietly(backup_conn)
        backup_conn = None
        with suppress(OSError):
            dst.unlink(missing_ok=True)
        return False
    finally:
        _close_quietly(backup_conn)
        _close_quietly(conn)

# --- end of Hermes' code ---


def _files(folder, prefix):
    """(path on disk, name in the zip) for every file under folder."""
    for root, _, names in os.walk(folder):
        for name in sorted(names):
            full = os.path.join(root, name)
            yield full, prefix + os.path.relpath(full, folder).replace(os.sep, "/")


def backup(folder=None):
    """Zip her data and return the zip's path. A .db goes in through SQLite's own backup, so it's never half-written."""
    _closed()
    folder = folder or os.path.join(localdata(), "Backups")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, time.strftime("heyjev-%Y-%m-%d_%H-%M-%S.zip"))
    n = 1
    while os.path.exists(path):  # two in the same second, the restore's own safety backup right after one
        n += 1
        path = os.path.join(folder, time.strftime(f"heyjev-%Y-%m-%d_%H-%M-%S-{n}.zip"))
    partial = path + ".partial"
    items = list(_files(appdata(), "appdata/"))
    items += [(os.path.join(HERE, name), "repo/" + name) for name in REPO_FILES
              if os.path.isfile(os.path.join(HERE, name))]
    for name in LOCAL_DIRS:
        items += _files(os.path.join(localdata(), name), f"local/{name}/")
    try:
        with tempfile.TemporaryDirectory() as tmp, zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as z:
            for full, arc in items:
                if full.endswith(SIDE_FILES):
                    continue
                if full.endswith(".db"):
                    copy = Path(tmp, "copy.db")
                    if not _safe_copy_db(Path(full), copy):
                        raise RuntimeError(f"couldn't make a clean copy of {full}")
                    z.write(copy, arc)
                    copy.unlink()
                else:
                    z.write(full, arc)
            z.writestr("manifest.json", json.dumps({"made": time.strftime("%Y-%m-%d %H:%M:%S"),
                                                    "files": [arc for full, arc in items
                                                              if not full.endswith(SIDE_FILES)]}, indent=1))
        with zipfile.ZipFile(partial) as z:
            bad = z.testzip()
        if bad:
            raise RuntimeError(f"the backup didn't read back: {bad}")
        os.replace(partial, path)
    finally:
        with suppress(OSError):
            os.remove(partial)
    return path


def _inside(base, name):
    target = os.path.abspath(os.path.join(base, name))
    if os.path.commonpath([target, os.path.abspath(base)]) != os.path.abspath(base):
        raise RuntimeError(f"a path outside her folders in the backup: {name}")
    return target


def _remove(path):
    if os.path.isdir(path):
        shutil.rmtree(path)
    elif os.path.exists(path):
        os.remove(path)


def restore(path):
    """Put a backup back. What's there now is backed up first; returns that backup's path."""
    _closed()
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "manifest.json" not in names:
            raise SystemExit(f"{path} isn't a Hey Jev backup.")
        bad = z.testzip()
        if bad:
            raise SystemExit(f"{path} is damaged ({bad}), nothing was changed.")
        now = backup()
        data = appdata()
        os.makedirs(data, exist_ok=True)
        for item in os.listdir(data):  # her folder comes back exactly as it was, nothing newer left in it
            _remove(os.path.join(data, item))
        for name in LOCAL_DIRS:  # a voice profile or decider data in the backup replaces today's
            if any(n.startswith(f"local/{name}/") for n in names):
                _remove(os.path.join(localdata(), name))
        for name in names:
            if name.endswith("/"):
                continue
            if name.startswith("appdata/"):
                target = _inside(data, name[len("appdata/"):])
            elif name.startswith("repo/") and name[len("repo/"):] in REPO_FILES:
                target = _inside(HERE, name[len("repo/"):])
            elif name.startswith("local/") and name.split("/")[1] in LOCAL_DIRS:
                target = _inside(localdata(), name[len("local/"):])
            else:
                continue
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(name) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out)
    return now


def fresh():
    """Back up, then clear what she's learned and old chats, so she starts fresh. Returns the backup's path."""
    path = backup()
    data = appdata()
    for name in WIPE:
        _remove(os.path.join(data, name))
    settings = os.path.join(data, "settings.json")
    try:
        with open(settings, encoding="utf-8") as f:
            values = json.load(f)
    except (OSError, ValueError):
        values = {}
    values["met"] = False  # she introduces herself on her next start
    tmp = settings + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(values, f, indent=2)
    os.replace(tmp, settings)
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description="Back up Hey Jev's data, put a backup back, or start fresh.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--restore", metavar="ZIP", help="put this backup back")
    group.add_argument("--fresh", action="store_true", help="back up, then clear her memory, skills and old chats")
    args = parser.parse_args(argv)
    if args.restore:
        now = restore(args.restore)
        print(f"Restored {args.restore}.\nWhat was there before is in {now}.")
    elif args.fresh:
        path = fresh()
        print(f"Backed up to {path}.\nHer memory, skills and old chats are cleared; she'll introduce herself when "
              f"she starts.\nTo undo: python backup.py --restore \"{path}\"")
    else:
        path = backup()
        print(f"Backed up to {path}.\nTo put it back: python backup.py --restore \"{path}\"")


if __name__ == "__main__":
    sys.exit(main())
