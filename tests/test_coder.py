"""Coding jobs (coder.py) and Hermes' cron rules in the task worker: only a git project, free models only, edits
let through, commands by her own rules, a stand-in OpenCode over the same protocol; jobs ask first, late ones don't
run by themselves, late reminders say when they were for, results go where they were asked from."""
import json
import os
import queue
import subprocess
import sys
import tempfile
import textwrap
import threading
import time
import unittest
from unittest import mock

from tests.support import siri
from tests.test_timers import StopsWorker

import coder
import tasks

FAKE_OPENCODE = textwrap.dedent('''
    import json, sys
    def send(m):
        sys.stdout.write(json.dumps(m) + "\\n"); sys.stdout.flush()
    for line in sys.stdin:
        m = json.loads(line)
        if "method" not in m:
            print(json.dumps({"answer": m}), file=sys.stderr)
            answers.append(m)
            continue
        method, i = m["method"], m["id"]
        if method == "initialize":
            answers = []
            send({"jsonrpc": "2.0", "id": i, "result": {"protocolVersion": 1}})
        elif method == "session/new":
            send({"jsonrpc": "2.0", "id": i, "result": {"sessionId": "s1", "configOptions": [{"id": "model",
                  "category": "model", "currentValue": "opencode/claude-opus-4-5", "options": [
                  {"value": "opencode/claude-opus-4-5"}, {"value": "opencode/big-pickle"}]}]}})
        elif method == "session/set_config_option":
            send({"jsonrpc": "2.0", "id": i, "result": {"chosen": m["params"]["value"]}})
            chosen = m["params"]["value"]
        elif method == "session/prompt":
            options = [{"optionId": "yes1", "kind": "allow_once"}, {"optionId": "no1", "kind": "reject_once"}]
            send({"jsonrpc": "2.0", "id": 100, "method": "session/request_permission", "params": {"sessionId": "s1",
                  "toolCall": {"kind": "edit", "title": "app.py"}, "options": options}})
            send({"jsonrpc": "2.0", "id": 101, "method": "session/request_permission", "params": {"sessionId": "s1",
                  "toolCall": {"kind": "execute", "title": "npm install", "rawInput": {"command": "npm install"}},
                  "options": options}})
            while len(answers) < 2:
                answers.append(json.loads(sys.stdin.readline()))
            picked = [a["result"]["outcome"].get("optionId") for a in answers]
            send({"jsonrpc": "2.0", "method": "session/update", "params": {"update": {
                  "sessionUpdate": "agent_message_chunk", "content": {"type": "text",
                  "text": "Model " + chosen + ", answers " + ",".join(map(str, picked)) + "."}}}})
            send({"jsonrpc": "2.0", "id": i, "result": {"stopReason": "end_turn"}})
''')


def git_folder():
    folder = tempfile.mkdtemp(prefix="heyjev-code-")
    subprocess.run(["git", "-C", folder, "init", "-q"], check=True)
    return folder


class Rules(unittest.TestCase):
    def test_only_a_git_project_and_never_a_system_folder(self):
        folder = git_folder()
        with mock.patch.object(coder, "NOT_HERE", ()):  # temp folders are under AppData
            self.assertEqual(coder.check_folder(folder), os.path.abspath(folder))
            with self.assertRaises(RuntimeError):
                coder.check_folder(tempfile.mkdtemp())  # not git
            with self.assertRaises(RuntimeError):
                coder.check_folder(os.path.expanduser("~"))
        with self.assertRaises(RuntimeError):
            coder.check_folder(folder)  # under AppData
        with self.assertRaises(RuntimeError):
            coder.check_folder(r"C:\Windows")

    def test_only_a_free_model(self):
        offered = lambda *ids: {"configOptions": [{"id": "model", "category": "model",
                                                    "options": [{"value": i} for i in ids]}]}
        self.assertEqual(coder.free_model(offered("opencode/claude-opus-4-5", "opencode/big-pickle")),
                         "opencode/big-pickle")
        self.assertEqual(coder.free_model(offered("opencode/space-bunny-free")), "opencode/space-bunny-free")
        self.assertIsNone(coder.free_model(offered("opencode/claude-opus-4-5", "opencode/gpt-5")))

    def test_edits_go_ahead_and_commands_by_her_own_rules(self):
        here = git_folder()
        job = coder.Job(here, "x")
        self.assertTrue(job.permission({"toolCall": {"kind": "edit", "title": "app.py"}}))
        self.assertTrue(job.permission({"toolCall": {"kind": "execute", "rawInput": {"command": "git status"}}}))
        self.assertFalse(job.permission({"toolCall": {"kind": "execute", "rawInput": {"command": "npm install"}}}))
        self.assertFalse(job.permission({"toolCall": {"kind": "execute", "rawInput": {"command": "format c:"}}}))
        self.assertFalse(job.permission({"toolCall": {"kind": "fetch", "title": "http://x"}}))
        asked = coder.Job(here, "x", ask=lambda q: True)
        self.assertTrue(asked.permission({"toolCall": {"kind": "execute", "rawInput": {"command": "npm install"}}}))
        self.assertFalse(asked.permission({"toolCall": {"kind": "execute", "rawInput": {"command": "format c:"}}}))
        self.assertEqual(len(job.refused), 2)


class OverTheProtocol(unittest.TestCase):
    def test_a_job_runs_with_a_free_model_and_her_answers(self):
        folder = git_folder()
        fake = os.path.join(folder, "fake_opencode.py")
        with open(fake, "w", encoding="utf-8") as f:
            f.write(FAKE_OPENCODE)
        real = subprocess.Popen
        with mock.patch.object(coder, "opencode_exe", lambda: sys.executable), \
                mock.patch.object(coder.subprocess, "Popen",
                                  lambda args, **kw: real([sys.executable, fake], **{**kw, "stderr": subprocess.DEVNULL})):
            job = coder.Job(folder, "add a test", timeout=30)
            ok, said = job.run()
        self.assertTrue(ok)
        self.assertEqual(said, "Model opencode/big-pickle, answers yes1,no1.")  # free model; edit yes, install no
        self.assertEqual(job.refused[0].split(" (")[0], "npm install")


class Steps(unittest.TestCase):
    def test_a_code_step_asks_first_and_a_yes_queues_it(self):
        store = tasks.Store(os.path.join(tempfile.mkdtemp(prefix="heyjev-tasks-"), "tasks.db"))
        folder = git_folder()
        with mock.patch.object(siri, "TASK_STORE", store), mock.patch.object(coder, "NOT_HERE", ()):
            plan = siri.prepare_task_steps({"steps": [{"do": "code", "task": "add a dark mode toggle", "cwd": folder}],
                                            "say": ""})
            self.assertIn("Should I start it?", plan["say"])
            task_id = plan["confirm"]["steps"][0]["id"]
            self.assertEqual(store.get(task_id)["status"], "waiting_approval")
            siri.prepare_task_steps(dict(plan["confirm"]))  # the yes
            self.assertEqual(store.get(task_id)["status"], "queued")
            self.assertTrue(store.get(task_id)["payload"]["approved"])


class Late(unittest.TestCase):
    def run_worker(self, store, said, until):
        worker = threading.Thread(target=siri.task_worker, daemon=True)
        worker.start()
        try:
            return until()
        finally:
            store.stopped = True
            tasks.WAKE.set()
            worker.join(5)

    def test_a_late_command_doesnt_run_and_a_late_reminder_says_when_it_was_for(self):
        store = StopsWorker(os.path.join(tempfile.mkdtemp(prefix="heyjev-worker-"), "tasks.db"))
        said = queue.Queue()
        with mock.patch.object(siri, "TASK_STORE", store), mock.patch.object(siri, "ANNOUNCE", said), \
                mock.patch.object(siri.tasking, "run_command", lambda *a, **k: self.fail("ran late")):
            cmd = store.create("Run the tests", "command", {"command": "npm test", "cwd": "C:\\x", "approved": True},
                               due=time.time() - 3600)
            store.create("Call Mum", "reminder", {"text": "call Mum"}, due=time.time() - 3600)
            lines = self.run_worker(store, said, lambda: [said.get(timeout=5), said.get(timeout=5)])
        self.assertTrue(any(l.startswith(f"Task {cmd} was due") for l in lines), lines)
        self.assertTrue(any(l.startswith("Reminder from ") and l.endswith("call Mum.") for l in lines), lines)
        self.assertEqual(store.get(cmd)["status"], "waiting_approval")

    def test_a_task_asked_on_the_phone_reports_back_there(self):
        store = StopsWorker(os.path.join(tempfile.mkdtemp(prefix="heyjev-worker-"), "tasks.db"))
        said, sent = queue.Queue(), queue.Queue()
        with mock.patch.object(siri, "TASK_STORE", store), mock.patch.object(siri, "ANNOUNCE", said), \
                mock.patch.dict(siri.PHONE, {"send": lambda chat, line: sent.put((chat, line)) or True}):
            store.create("Remind me", "reminder", {"text": "stretch", "origin": {"phone": 7}})
            got = self.run_worker(store, said, lambda: sent.get(timeout=5))
        self.assertEqual(got, (7, "Reminder: stretch."))
        self.assertTrue(said.empty())


if __name__ == "__main__":
    unittest.main()
