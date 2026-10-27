"""What the Hermes Agent files in this folder take from the rest of Hermes, so they stand alone in Hey Jev: the home
folder, atomic writes, file locks, the few skill-folder helpers, utils.py's JSON and yes-or-no readers, and the
subagent look-ups a finished-job notice makes. sync_hermes.py points their imports here."""
import json
import os
import tempfile
import time
from contextlib import suppress
from pathlib import Path

try:  # tools/memory_tool.py: the lock the memory store takes, msvcrt on Windows
    import fcntl
    msvcrt = None
except ImportError:
    fcntl = None
    try:
        import msvcrt
    except ImportError:
        msvcrt = None

HOME = Path.home() / ".hermes"  # Hey Jev sets %APPDATA%\Hey Jev with set_home(): skills\, memories\ under it
MEMORY_DIR = HOME / "memories"


def set_home(path) -> None:
    global HOME
    HOME = Path(path)


def get_hermes_home() -> Path:
    return HOME


def set_memory_dir(path) -> None:
    global MEMORY_DIR
    MEMORY_DIR = Path(path)


def get_memory_dir() -> Path:
    return MEMORY_DIR


def mkdir_under_hermes_home(path) -> None:
    Path(path).mkdir(parents=True, exist_ok=True)


REPLACE_TRIES = 20  # times the rename is tried while another thread has the file open to read it
REPLACE_PAUSE = 0.01  # seconds between them: a read of a usage or memory file takes well under a millisecond


def replace_soon(tmp, path) -> None:
    """os.replace, tried again for a moment while Windows says the file is in use. On Windows a file another thread
    has open to read can't be replaced (PermissionError), and Hermes' usage and memory files are read without their
    lock: on 27 October a skill she'd just saved lost its "she wrote this" mark (skill_usage's created_by) to a use
    counted on another thread at that moment, was taken for one dropped in by hand and kept back for a scan, so its
    routine didn't run. POSIX replaces an open file, so there the first try always does."""
    for left in range(REPLACE_TRIES - 1, -1, -1):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if not left:
                raise
            time.sleep(REPLACE_PAUSE)


def atomic_write_text(path, content: str, *, encoding: str = "utf-8", tmp_prefix: str = ".tmp_") -> None:
    """Write via a temp file in the same folder, fsync, then an atomic rename: never half-written."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=tmp_prefix, dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        replace_soon(tmp, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp)
        raise


def atomic_json_write(path, data, *, indent=None, sort_keys=False, **_) -> None:
    atomic_write_text(path, json.dumps(data, indent=indent, sort_keys=sort_keys, ensure_ascii=False))


# agent/skill_utils.py: Hey Jev's skills folder, then skills\imported, where the owner drops skills in by hand (27
# October). Hermes treats a folder after the first as external: its curator never archives, patches or consolidates
# a skill there (skill_usage.is_curation_eligible, _scan_local_skills), which is what a hand-dropped skill needs.
# Nothing disabled.
def get_all_skills_dirs():
    return [HOME / "skills", HOME / "skills" / "imported"]


def is_external_skill_path(path) -> bool:
    """True for a path in skills\\imported (see get_all_skills_dirs)."""
    try:
        inside = os.path.normcase(os.path.abspath(path))
        root = os.path.normcase(os.path.abspath(HOME / "skills" / "imported"))
        return inside == root or inside.startswith(root + os.sep)
    except (TypeError, ValueError):
        return False


def get_disabled_skill_names(*_, **__):
    return set()


# utils.py, as Hermes has them at 1ae3c55e: interrupt.py turns on its debug log from the environment, and
# tool_guardrails.py reads a tool's JSON result without trusting it to be JSON
TRUTHY_STRINGS = frozenset({"1", "true", "yes", "on"})


def is_truthy_value(value, default=False) -> bool:
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in TRUTHY_STRINGS
    return bool(value)


def env_var_enabled(name: str, default: str = "") -> bool:
    return is_truthy_value(os.getenv(name, default), default=False)


def safe_json_loads(text, default=None):
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError, ValueError):
        return default


# tools/process_registry_notifications.py: Hermes names the subagent that started a process, and warns when its
# configured subagent model was refused. Hey Jev runs no Hermes subagents and has no such setting, so there's
# nobody to name and never that warning (Hermes' own import delegate_tool: 5,055 lines over 11 files, plus the
# terminal tool).
def get_subagent_attribution(task_id):
    return None


def delegation_notice_lines(results):
    return []
