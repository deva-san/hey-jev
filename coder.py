"""Coding jobs in the background: the OpenCode CLI already on this PC (opencode.ai) does the work in one project
folder while you carry on, and she tells you when it's done.

It's driven the way Hermes Agent drives a coding agent (agent/copilot_acp_client.py, its helpers copied into
hermes_memory/acp_bits.py): `opencode acp` on stdin and stdout, the Agent Client Protocol, one session per job.

Kept on a short leash, because OpenCode itself lets an agent edit files and run commands without asking:
- OPENCODE_CONFIG_CONTENT, which outranks the project's own opencode.json, makes every edit and command a
  permission request, and turns off web fetching and anything outside the folder.
- Only a git project folder, never a system or app-data folder, and a snapshot of it first (git stash create, which
  changes nothing), so whatever it does can be undone.
- Edits inside the folder go ahead: you said yes to the job. Each command goes through tasks.command_policy, the
  same rules as her own: blocked ones are refused, read-only ones go ahead, anything else is asked (ask), or refused
  and listed in her report when there's no way to ask.
- Only a free model, picked from the ones the session offers, or the job doesn't start.
"""
import json
import os
import queue
import shutil
import subprocess
import threading
import time

import opencode
import tasks as tasking
from hermes_memory.acp_bits import _jsonrpc_error, _jsonrpc_result, _model_selection_request, _session_model_ids

CONFINE = {"permission": {"edit": "ask", "bash": "ask", "webfetch": "deny", "external_directory": "deny"}}
MODEL = "opencode/big-pickle"  # free on OpenCode Zen (opencode.FREE_EXTRA); any free one it offers will do
TIMEOUT = 30 * 60
INITIALIZE = {"protocolVersion": 1, "clientCapabilities": {"fs": {"readTextFile": False, "writeTextFile": False}},
              "clientInfo": {"name": "hey-jev", "title": "Hey Jev", "version": "1"}}
GUIDE = ("You're working for the user of Hey Jev, a voice assistant, in the project folder {folder}. Do this:\n{task}\n\n"
         "Work only in this folder and keep the change small. Don't install anything or touch git history. When you're "
         "done, say in one or two plain sentences what you changed and whether the tests passed, for it to be read "
         "out loud.")
NOT_HERE = ("\\windows", "\\program files", "\\programdata", "\\appdata", "\\$recycle.bin", "\\system volume information")
CREATE_NO_WINDOW = 0x08000000


def opencode_exe():
    for path in (os.path.expanduser(r"~\.bun\bin\opencode.exe"), shutil.which("opencode")):
        if path and os.path.isfile(path):
            return path
    return None


def check_folder(folder):
    """The folder it may work in, as a full path, or RuntimeError saying why not."""
    folder = os.path.abspath(os.path.expandvars(str(folder or "")))
    low = folder.lower()
    if not os.path.isdir(folder):
        raise RuntimeError("Say which project folder it's for")
    if folder.rstrip("\\") in (os.path.expanduser("~"), os.path.splitdrive(folder)[0]) or \
            any(part in low + "\\" for part in NOT_HERE):
        raise RuntimeError("That folder's off limits for a coding job")
    if not os.path.isdir(os.path.join(folder, ".git")):
        raise RuntimeError("Coding jobs only work in a git project, so whatever it does can be undone")
    return folder


def snapshot(folder):
    """A git commit of the folder as it is now, changing nothing (git stash create), or HEAD if it's clean."""
    run = lambda *args: subprocess.run(["git", "-C", folder, *args], capture_output=True, text=True, timeout=30,
                                       creationflags=CREATE_NO_WINDOW).stdout.strip()
    return run("stash", "create") or run("rev-parse", "HEAD")


def free_model(session):
    """The free model to use from the ones the session offers, or None."""
    offered = _session_model_ids(session)
    picks = [MODEL] + [m for m in offered if m != MODEL]
    return next((m for m in picks if m in offered and opencode.is_free(m.split("/", 1)[-1])), None)


def choose(options, allow):
    """The option to answer a permission request with: allow once, or reject once."""
    want = ("allow_once",) if allow else ("reject_once", "reject_always")
    for option in options or []:
        if option.get("kind") in want:
            return option.get("optionId")
    return None


class Job:
    def __init__(self, folder, task, ask=None, cancelled=lambda: False, timeout=TIMEOUT):
        """ask(question) -> True/False, or None when there's nobody to ask: then it's refused and reported."""
        self.folder, self.task, self.ask, self.cancelled, self.timeout = folder, task, ask, cancelled, timeout
        self.text, self.refused, self.ran, self.edited = [], [], [], []

    def permission(self, params):
        """True to let a request through. Edits in the folder, yes; commands by her own rules."""
        call = params.get("toolCall") or {}
        kind, title = str(call.get("kind") or ""), str(call.get("title") or "")
        raw = call.get("rawInput") or {}
        if kind == "edit":
            self.edited.append(title)
            return True
        if kind == "execute":
            command = str(raw.get("command") or title)
            level, reason = tasking.command_policy(command, self.folder)
            if level == "allow":
                self.ran.append(command)
                return True
            if level == "confirm" and self.ask is not None and self.ask(f"OpenCode wants to run {command}. Let it?"):
                self.ran.append(command)
                return True
            self.refused.append(f"{command} ({reason})")
            return False
        return kind in ("read", "search", "think")  # nothing else: no fetching, moving or deleting

    def run(self):
        """(it finished, what it says it did) once it's done, cancelled or out of time."""
        exe = opencode_exe()
        if not exe:
            raise RuntimeError("The OpenCode CLI isn't installed")
        env = dict(os.environ, OPENCODE_CONFIG_CONTENT=json.dumps(CONFINE))
        proc = subprocess.Popen([exe, "acp", "--cwd", self.folder], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL, text=True, encoding="utf-8", cwd=self.folder, env=env,
                                creationflags=CREATE_NO_WINDOW)
        inbox, ids = queue.Queue(), iter(range(1, 1 << 30))
        threading.Thread(target=lambda: [inbox.put(line) for line in proc.stdout], daemon=True).start()
        end = time.time() + self.timeout

        def send(message):
            proc.stdin.write(json.dumps(message) + "\n")
            proc.stdin.flush()

        def request(method, params):
            rid = next(ids)
            send({"jsonrpc": "2.0", "id": rid, "method": method, "params": params})
            while time.time() < end and proc.poll() is None:
                if self.cancelled():
                    raise RuntimeError("cancelled")
                try:
                    message = json.loads(inbox.get(timeout=0.2))
                except (queue.Empty, ValueError):
                    continue
                method_in = message.get("method")
                if method_in == "session/update":
                    update = (message.get("params") or {}).get("update") or {}
                    content = update.get("content") or {}
                    if update.get("sessionUpdate") == "agent_message_chunk" and isinstance(content, dict):
                        self.text.append(str(content.get("text") or ""))
                elif method_in == "session/request_permission":
                    params_in = message.get("params") or {}
                    option = choose(params_in.get("options"), self.permission(params_in))
                    send(_jsonrpc_result(message.get("id"), {"outcome": {"outcome": "selected", "optionId": option}}
                                         if option else {"outcome": {"outcome": "cancelled"}}))
                elif method_in:  # files are OpenCode's own business here, and nothing else is offered
                    send(_jsonrpc_error(message.get("id"), -32601, f"Hey Jev doesn't offer {method_in}"))
                elif message.get("id") == rid:
                    if "error" in message:
                        raise RuntimeError(f"OpenCode {method}: {(message['error'] or {}).get('message')}")
                    return message.get("result") or {}
            raise TimeoutError("OpenCode took too long") if proc.poll() is None else \
                RuntimeError("OpenCode stopped")
        try:
            request("initialize", INITIALIZE)
            session = request("session/new", {"cwd": self.folder, "mcpServers": []})
            model = free_model(session)
            if not model:
                raise RuntimeError("OpenCode offered no free model, and Hey Jev only uses free ones")
            selection = _model_selection_request(session, model)
            if selection:
                request(*selection)
            result = request("session/prompt", {"sessionId": session["sessionId"], "prompt": [
                {"type": "text", "text": GUIDE.format(folder=self.folder, task=self.task)}]})
            return result.get("stopReason") == "end_turn", " ".join("".join(self.text).split())
        finally:
            proc.kill()
            try:
                proc.wait(5)
            except subprocess.TimeoutExpired:
                pass
            for pipe in (proc.stdin, proc.stdout):
                try:
                    pipe.close()
                except (OSError, ValueError):
                    pass
