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

from tests.support import needs_windows, siri
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

    @needs_windows
    def test_never_under_app_data_or_windows(self):
        folder = git_folder()
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


    def test_its_own_tests_ask_once_it_changed_anything(self):
        """Edits go ahead, and "npm test" ran by itself as the project's own test: but it runs whatever package.json
        says, so a job that rewrote scripts.test could run any command with nobody asked."""
        here = git_folder()
        with open(os.path.join(here, "package.json"), "w", encoding="utf-8") as f:
            json.dump({"scripts": {"test": "jest", "build": "tsc"}}, f)
        test = {"toolCall": {"kind": "execute", "title": "npm test", "rawInput": {"command": "npm test"}}}
        job = coder.Job(here, "fix the failing test")
        self.assertTrue(job.permission(test))  # nothing changed yet: the project's own test goes ahead
        # a test file or a test runner's config it rewrote runs as the test too: os.system added to
        # tests/test_app.py ran under pytest with nobody asked
        python = git_folder()
        with open(os.path.join(python, "conftest.py"), "w", encoding="utf-8") as f:
            f.write("")
        pytest = {"toolCall": {"kind": "execute", "rawInput": {"command": "python -m pytest"}}}
        self.assertTrue(coder.Job(python, "x").permission(pytest))
        for edited in ("src/app.js", "tests/test_app.py", "jest.config.js", "vite.config.ts"):
            for folder, run in ((here, test), (python, pytest)):
                job = coder.Job(folder, "fix the failing test")
                self.assertTrue(job.permission({"toolCall": {"kind": "edit", "title": edited}}))
                self.assertFalse(job.permission(run), edited)
                self.assertIn("code this job changed", job.refused[0])
        for edit in ({"title": "package.json"}, {"title": "Edit", "rawInput": {"filePath": "C:\\p\\package.json"}},
                     {"title": "Edit", "locations": [{"path": "C:\\p\\tests\\conftest.py"}]}, {"title": "web/.npmrc"}):
            job = coder.Job(here, "fix the failing test")
            self.assertTrue(job.permission({"toolCall": {"kind": "edit", **edit}}))  # the edit itself still goes
            self.assertFalse(job.permission(test), edit)
            build = {"toolCall": {"kind": "execute", "rawInput": {"command": "npm run build"}}}
            self.assertFalse(job.permission(build))
            self.assertEqual([r.split(" (")[0] for r in job.refused], ["npm test", "npm run build"])
        asked = []
        job = coder.Job(here, "x", ask=lambda q: asked.append(q) or True)
        job.permission({"toolCall": {"kind": "edit", "title": "package.json"}})
        self.assertTrue(job.permission(test))
        self.assertEqual(asked, ["OpenCode wants to run npm test. Let it?"])


def git(folder, *args):
    return subprocess.run(["git", "-C", folder, "-c", "user.name=t", "-c", "user.email=t@x", *args], check=True,
                          capture_output=True, text=True).stdout.strip()


class Snapshots(unittest.TestCase):
    """The folder as it was before a job, to put back."""

    def setUp(self):
        p = mock.patch.object(coder, "CREATE_NO_WINDOW", 0)  # Windows only
        p.start()
        self.addCleanup(p.stop)
        self.folder = git_folder()
        self.write("app.py", "print(1)\n")
        git(self.folder, "add", "app.py")
        git(self.folder, "commit", "-q", "-m", "first")

    def write(self, name, text):
        with open(os.path.join(self.folder, name), "w", encoding="utf-8") as f:
            f.write(text)

    def read(self, name):
        with open(os.path.join(self.folder, name), encoding="utf-8") as f:
            return f.read()

    def test_new_files_git_doesnt_track_yet_are_kept_too(self):
        """git stash create leaves out files not added yet: with only those, there was nothing to keep, and a job that
        overwrote your notes.md left no copy of what you'd written, and an undo line that said to delete it."""
        self.write("notes.md", "my notes\n")
        self.write("app.py", "print(2)\n")
        snap = coder.snapshot(self.folder)
        self.assertTrue(snap.startswith("files:"), snap)
        self.assertEqual(git(self.folder, "status", "--porcelain"), "M app.py\n?? notes.md")  # nothing changed
        self.write("notes.md", "the job's\n")
        self.write("app.py", "print(3)\n")
        line = coder.undo_line(snap)
        self.assertIn("git restore --source", line)
        git(self.folder, "restore", "--source", snap.split(":")[1][:10], "--worktree", ".")  # as the line says
        self.assertEqual((self.read("notes.md"), self.read("app.py")), ("my notes\n", "print(2)\n"))
        self.assertIn(snap.split(":")[1], git(self.folder, "for-each-ref", "refs/heyjev"))  # kept from git's clean-up

    def test_tracked_changes_alone_are_a_stash_as_before(self):
        self.write("app.py", "print(2)\n")
        snap = coder.snapshot(self.folder)
        self.assertTrue(snap.startswith("stash:"), snap)
        self.assertIn("stash apply", coder.undo_line(snap))
        git(self.folder, "checkout", "app.py")
        self.assertTrue(coder.snapshot(self.folder).startswith("head:"))  # nothing to keep

    def test_new_files_it_cant_keep_mean_it_doesnt_start(self):
        self.write("notes.md", "my notes\n")
        real = subprocess.run
        with mock.patch.object(coder.subprocess, "run", lambda args, **kw: real(
                args + ["--no-such-option"] if "add" in args else args, **kw)):
            with self.assertRaises(RuntimeError):
                coder.snapshot(self.folder)

    def test_git_too_slow_means_it_doesnt_start_with_a_reason(self):
        """git add took past its 30 s on a folder with a big venv nobody ignored: TimeoutExpired went up uncaught,
        and the task failed with "Open Tasks for the details"."""
        self.write("notes.md", "my notes\n")
        real = subprocess.run

        def slow(args, **kw):
            if "add" in args:
                raise subprocess.TimeoutExpired(args, 30)
            return real(args, **kw)
        with mock.patch.object(coder.subprocess, "run", slow):
            with self.assertRaisesRegex(RuntimeError, "keep a copy"):
                coder.snapshot(self.folder)

    def test_git_too_slow_to_list_or_stash_means_it_doesnt_start(self):
        """A slow ls-files read as "no new files" and a slow stash create as "nothing uncommitted": the job started
        with notes.md kept nowhere, or with an undo line, git checkout ., that would wipe your unsaved edit."""
        self.write("app.py", "print(2)\n")
        real = subprocess.run
        for step, new in (("ls-files", True), ("stash", False)):
            if new:
                self.write("notes.md", "my notes\n")
            elif os.path.exists(os.path.join(self.folder, "notes.md")):
                os.remove(os.path.join(self.folder, "notes.md"))

            def slow(args, **kw):
                if step in args:
                    raise subprocess.TimeoutExpired(args, 30)
                return real(args, **kw)
            with mock.patch.object(coder.subprocess, "run", slow):
                with self.assertRaisesRegex(RuntimeError, "too long"):
                    coder.snapshot(self.folder)

    def test_too_many_new_files_arent_copied_into_git(self):
        """Every new file went into .git for good: a 180 MB venv-like folder grew .git from 205 to 382 MB."""
        os.makedirs(os.path.join(self.folder, "venv", "lib"))
        self.write("venv/lib/big.bin", "x" * 3000)
        self.write("notes.md", "my notes\n")
        with mock.patch.object(coder, "SNAPSHOT_MAX_BYTES", 2000):
            with self.assertRaisesRegex(RuntimeError, "venv"):
                coder.snapshot(self.folder)
        self.assertEqual(git(self.folder, "for-each-ref", "refs/heyjev"), "")
        self.assertEqual(git(self.folder, "count-objects").split()[0], "3")  # the first commit's, nothing more
        with mock.patch.object(coder, "SNAPSHOT_MAX_FILES", 1):
            with self.assertRaisesRegex(RuntimeError, "too many new files"):
                coder.snapshot(self.folder)
        self.assertTrue(coder.snapshot(self.folder).startswith("files:"))  # small enough: kept as before

    def test_only_the_last_ways_back_are_kept_and_the_real_index_is_reused(self):
        """Snapshots stayed under refs/heyjev for ever. And read-tree gave the spare index none of the real one's
        file times, so every tracked file was hashed again for each job."""
        real, calls, stamps = subprocess.run, [], iter(f"2026010{n}-000000" for n in range(1, 10))

        def seen(args, **kw):
            calls.append(args)
            return real(args, **kw)
        with mock.patch.object(coder, "KEEP_SNAPSHOTS", 2), mock.patch.object(coder.subprocess, "run", seen), \
                mock.patch.object(coder.time, "strftime", lambda fmt: next(stamps)):
            snaps = []
            for n in range(3):
                self.write("notes.md", f"notes {n}\n")
                snaps.append(coder.snapshot(self.folder).split(":")[1])
        kept = git(self.folder, "for-each-ref", "--format=%(objectname)", "refs/heyjev").split()
        self.assertEqual(sorted(kept), sorted(snaps[1:]))
        self.assertFalse([c for c in calls if "read-tree" in c])
        self.assertEqual(git(self.folder, "status", "--porcelain"), "?? notes.md")  # the real index untouched


class OverTheProtocol(unittest.TestCase):
    @needs_windows  # runs a real process with CREATE_NO_WINDOW
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


class ReviewFixes(unittest.TestCase):
    def test_a_code_step_survives_parsing(self):
        plan = siri.parse_plan(r'{"steps": [{"do": "code", "task": "add a test", "cwd": "C:\\p"}], "say": ""}')
        self.assertEqual([s["do"] for s in plan["steps"]], ["code"])

    def test_starting_a_job_needs_a_clear_yes(self):
        plan = {"steps": [{"do": "task_control", "action": "approve", "id": 4}]}
        for said, ok in (("yes", True), ("yes, start it", True), ("go ahead", True), ("right", False),
                         ("fine", False)):
            self.assertIs(siri.said_yes(said, plan), ok, said)

    def test_never_her_own_folder_or_a_bare_one(self):
        for folder in ("", ".", None, "projects\\x", coder.HERE):
            with self.assertRaises(RuntimeError, msg=folder):
                coder.check_folder(folder)

    def test_the_undo_line_fits_the_snapshot(self):
        self.assertIn("stash apply abc", coder.undo_line("stash:abcdef"))
        self.assertNotIn("stash", coder.undo_line("head:abcdef"))
        self.assertEqual(coder.undo_line(""), "")

    def test_a_weekday_schedule_never_starts_on_a_weekend(self):
        import datetime as dt
        saturday_8am = dt.datetime(2026, 10, 10, 8, 0).timestamp()
        due, spec = tasks.normalize_schedule("9 AM", "every weekday at 9", now=saturday_8am)
        self.assertEqual(dt.datetime.fromtimestamp(due).weekday(), 0)

    def test_results_only_go_to_the_account_paired_now(self):
        said, sent = [], []
        with mock.patch.object(siri, "ANNOUNCE", mock.Mock(put=said.append)),                 mock.patch.dict(siri.PHONE, {"send": lambda chat, line: sent.append(chat) or True}),                 mock.patch.dict(siri.settings._load(), {"telegram_owner": 8}):
            siri.tell_task({"payload": {"origin": {"phone": 7}}}, "done")
        self.assertEqual((said, sent), (["done"], []))


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

    def stopped_job(self, why, cancel=False):
        """A coding job that changed two files, then stopped with why (and was cancelled first, with cancel): what's
        said, and what's kept in Tasks."""
        store = StopsWorker(os.path.join(tempfile.mkdtemp(prefix="heyjev-worker-"), "tasks.db"))
        said = queue.Queue()

        class Stopped:
            def __init__(self, folder, task, ask=None, cancelled=None):
                self.edited, self.ran, self.refused = ["app.py", "util.py"], [], []

            def run(self):
                if cancel:
                    store.cancel(task)
                raise why
        with mock.patch.object(siri, "TASK_STORE", store), mock.patch.object(siri, "ANNOUNCE", said), \
                mock.patch.object(coder, "check_folder", lambda folder: folder), \
                mock.patch.object(coder, "snapshot", lambda folder: "stash:abcdef1234567890"), \
                mock.patch.object(coder, "Job", Stopped):
            task = store.create("Add a toggle", "code", {"task": "add a toggle", "cwd": "C:\\p", "approved": True})
            return task, self.run_worker(store, said, lambda: said.get(timeout=5)), store.get(task)

    def test_a_job_that_stops_part_way_says_how_to_undo_it(self):
        """A job that ran out of its 30 minutes, or that OpenCode stopped, said only "Open Tasks for the details": what
        it had changed stayed, and the snapshot of your work before it was a loose commit only git fsck could find."""
        undo = "To undo it: git checkout . then git stash apply abcdef1234, in that folder."
        for why in (TimeoutError("OpenCode took too long"), RuntimeError("OpenCode stopped")):
            task, line, row = self.stopped_job(why)
            self.assertEqual(line, f"Task {task} failed: Add a toggle. It changed 2 files first. {undo}")
            self.assertEqual(json.loads(row["result"])["snapshot"], "stash:abcdef1234567890")
            self.assertEqual(row["error"], str(why))
        task, line, _ = self.stopped_job(RuntimeError("cancelled"), cancel=True)  # cancelled: said, not silent
        self.assertEqual(line, f"Task {task} was cancelled: Add a toggle. It changed 2 files first. {undo}")

    def test_a_task_asked_on_the_phone_reports_back_there(self):
        store = StopsWorker(os.path.join(tempfile.mkdtemp(prefix="heyjev-worker-"), "tasks.db"))
        said, sent = queue.Queue(), queue.Queue()
        with mock.patch.object(siri, "TASK_STORE", store), mock.patch.object(siri, "ANNOUNCE", said), \
                mock.patch.dict(siri.PHONE, {"send": lambda chat, line: sent.put((chat, line)) or True}),                 mock.patch.dict(siri.settings._load(), {"telegram_owner": 7}):
            store.create("Remind me", "reminder", {"text": "stretch", "origin": {"phone": 7}})
            got = self.run_worker(store, said, lambda: sent.get(timeout=5))
        self.assertEqual(got, (7, "Reminder: stretch."))
        self.assertTrue(said.empty())


if __name__ == "__main__":
    unittest.main()
