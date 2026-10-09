"""Where a hand check keeps what it writes. Each check calls this before it imports anything of hers:

    sys.path.insert(0, ROOT)
    from checks import sandbox  # noqa: E402  (checks\\ isn't a package, so unittest discovery never loads it)
    sandbox.use()

A check runs her real code with the real models, and that code writes as it goes: a turn into her history, a line
into the decider's log, her memory. On 8 Oct the old hand checks, run as tests from the repo root, wrote into her
real data. So a check works on a copy: %APPDATA%\\Hey Jev without history.db and tasks.db (a check starts with no
old turns and no tasks), and the voice and decider folders from %LOCALAPPDATA%\\Hey Jev (checks\\voice_id.py reads your
clips there), copied to a temp folder that goes when the check ends. Her real folders are refused for the rest of the
run (winplatform.own_data). The models are the real ones: HEYJEV_MODELS from .env, else %LOCALAPPDATA%\\Hey Jev\\models.

    .venv\\Scripts\\python checks\\open_mic.py --real-data    # on her real data instead, writes and all
"""
import atexit
import os
import shutil
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FLAG = "--real-data"
LOCAL = ("voice", "decider")  # in %LOCALAPPDATA%\Hey Jev: your voice clips and profile, the decider's heads
DATABASES = ("history.db", "tasks.db")  # with SQLite's own side files


def use(argv=None):
    """Point %APPDATA% and %LOCALAPPDATA% at a copy of her data, unless --real-data is in argv (sys.argv). The flag
    is taken out of it either way, so the check's own arguments are as they were. Returns the copy, or None. With
    HEYJEV_TESTING set her real folders are refused already: a unit test imported the check (tests/test_listening.py
    does, for its pair()), and its harness's temp folders, and its guard, stay as they are."""
    argv = sys.argv if argv is None else argv
    real = FLAG in argv
    while FLAG in argv:
        argv.remove(FLAG)
    if os.environ.get("HEYJEV_TESTING") is not None:
        return None
    from dotenv import load_dotenv
    load_dotenv(os.path.join(ROOT, ".env"))  # first, so HEYJEV_MODELS there still wins over the default below
    if real:
        return None
    home = os.path.expanduser("~")
    roaming, local = os.environ.get("APPDATA") or home, os.environ.get("LOCALAPPDATA") or home
    os.environ.setdefault("HEYJEV_MODELS", os.path.join(local, "Hey Jev", "models"))
    copy = tempfile.mkdtemp(prefix="heyjev-check-")
    atexit.register(shutil.rmtree, copy, ignore_errors=True)  # a copy of her memory isn't left in %TEMP%
    skip = shutil.ignore_patterns(*(db + side for db in DATABASES for side in ("", "-wal", "-shm", "-journal")))
    if os.path.isdir(os.path.join(roaming, "Hey Jev")):
        shutil.copytree(os.path.join(roaming, "Hey Jev"), os.path.join(copy, "Roaming", "Hey Jev"), ignore=skip)
    for name in LOCAL:
        if os.path.isdir(os.path.join(local, "Hey Jev", name)):
            shutil.copytree(os.path.join(local, "Hey Jev", name), os.path.join(copy, "Local", "Hey Jev", name))
    os.environ["HEYJEV_TESTING"] = os.pathsep.join((roaming, local))  # her real folders: refused from here on
    os.environ["APPDATA"], os.environ["LOCALAPPDATA"] = os.path.join(copy, "Roaming"), os.path.join(copy, "Local")
    print(f"(on a copy of her data, gone when this ends; {FLAG} to use her own)", file=sys.stderr)
    return copy
