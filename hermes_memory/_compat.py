"""What the Hermes Agent files in this folder take from the rest of Hermes, so they stand alone in Hey Jev: the home
folder, atomic writes, file locks, the few skill-folder helpers, utils.py's JSON and yes-or-no readers, and the
subagent look-ups a finished-job notice makes. sync_hermes.py points their imports here."""
import json
import os
import tempfile
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
        os.replace(tmp, path)
    except BaseException:
        with suppress(OSError):
            os.unlink(tmp)
        raise


def atomic_json_write(path, data, *, indent=None, sort_keys=False, **_) -> None:
    atomic_write_text(path, json.dumps(data, indent=indent, sort_keys=sort_keys, ensure_ascii=False))


# agent/skill_utils.py: Hey Jev has one skills folder, no external ones, and nothing disabled
def get_all_skills_dirs():
    return [HOME / "skills"]


def is_external_skill_path(path) -> bool:
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
