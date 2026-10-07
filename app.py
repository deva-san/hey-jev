"""Entry point for the shortcut: same as `python siri.py --ui`, with output saved to %LOCALAPPDATA%\\Hey Jev\\Logs\\Hey Jev.log."""
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
from winplatform import log_path  # noqa: E402

log = open(log_path("Hey Jev.log"), "a", buffering=1, encoding="utf-8", errors="backslashreplace")
sys.stdout = sys.stderr = log

from assistant_ui import run_app  # noqa: E402

run_app()
