"""What the Hermes Agent files in this folder take from the rest of Hermes, so they stand alone in Hey Jev: the home
folder, atomic writes, file locks, and the few skill-folder helpers. sync_hermes.py points their imports here."""
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
