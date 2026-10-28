"""What she's working on, live (activity.py), and what feeds it: a background task's row (siri.task_worker), her plan
step by step (run_plan), a task in an app round by round (agent), research round by round, a coding job's edits
(coder.Job), and her question at the PC (show_ask), which the island's Approve answers only as the phone's Yes button
answers one (island_answer). 27 October: the owner asked to see running work live on the island, with Stop, Approve
and Deny, where until then it saw a turn's "Doing it" and nothing of the background at all. Nothing here acts on the
PC or goes online: tests.support trips that, and a list-cell clock stands in for time in the registry."""
import contextlib
import io
import os
import queue
import shutil
import tempfile
import threading
import time
import unittest
from unittest import mock

from tests.support import TRIPPED, siri  # first: temp APPDATA and the tripwires, before anything of hers
from tests.test_timers import StopsWorker
from tests.test_watchers import until

import activity
import agent
import coder
import tasks


class Case(unittest.TestCase):
    """An empty registry, a fake clock in it, and nothing a test does may reach a tripwire."""

    def setUp(self):
        self.tripped = len(TRIPPED)
        self.addCleanup(lambda: self.assertEqual(TRIPPED[self.tripped:], []))
        self.clock = [time.time()]
        p = mock.patch.object(activity, "_clock", lambda: self.clock[0])
        p.start()
        self.addCleanup(p.stop)
        activity.clear()
        self.addCleanup(activity.clear)

    def item(self, key):
        return next((i for i in activity.snapshot() if i["key"] == key), None)

    def later(self, secs):
        self.clock[0] += secs


class Registry(Case):
    """An entry is started, moved on and finished by the code doing the work, and the island reads a copy."""

    def test_an_entry_moves_on_then_says_how_it_went_for_a_moment(self):
        activity.publish("task:1", title="Research phones", kind="research", origin="task", note="Searching")
        token = activity.KEY.set("task:1")
        try:
            self.assertTrue(activity.step(2, 6, "Reading pages"))
        finally:
            activity.KEY.reset(token)
        got = self.item("task:1")
        self.assertEqual((got["state"], got["step"], got["total"], got["note"]), ("running", 2, 6, "Reading pages"))
        self.later(30)
        self.assertTrue(activity.finish("task:1", "done"))
        self.assertEqual(self.item("task:1")["state"], "done")  # 30 s of work: it says it's done
        self.later(activity.LINGER + 0.1)
        self.assertIsNone(self.item("task:1"))  # then it goes
        self.assertFalse(activity.finish("task:1", "done"))  # once

    def test_one_that_worked_at_once_goes_at_once_and_a_failure_stays_a_moment(self):
        activity.publish("turn:1", title="open notepad, type hello", kind="turn", total=2)
        self.later(0.4)
        activity.finish("turn:1", "done")
        self.assertIsNone(self.item("turn:1"))  # you watched it happen: nothing to say
        activity.publish("turn:2", title="open notepad, type hello", kind="turn", total=2)
        self.later(0.4)
        activity.finish("turn:2", "failed")
        self.assertEqual(self.item("turn:2")["state"], "failed")

    def test_titles_and_notes_are_one_short_line(self):
        activity.publish("task:1", title="Research\nthe   best " + "budget phones " * 10, note="x" * 200)
        got = self.item("task:1")
        self.assertLessEqual(len(got["title"]), activity.TITLE_MOST)
        self.assertTrue(got["title"].startswith("Research the best budget phones"))
        self.assertTrue(got["title"].endswith("\u2026"))
        self.assertEqual(len(got["note"]), activity.NOTE_MOST)

    def test_the_ones_waiting_on_you_come_first_then_whats_running(self):
        activity.publish("a", state="queued")
        self.later(1)
        activity.publish("b", state="running")
        self.later(1)
        activity.publish("c", state="waiting_yes", needs="7")
        self.later(1)
        activity.publish("d", state="running")
        self.assertEqual([i["key"] for i in activity.snapshot()], ["c", "b", "d", "a"])

    def test_a_question_goes_when_it_runs_out(self):
        activity.publish("ask", state="waiting_yes", needs="q1", until=self.clock[0] + 16)
        self.later(15)
        self.assertIsNotNone(self.item("ask"))
        self.later(2)
        self.assertIsNone(self.item("ask"))

    def test_nothing_is_made_without_someone_to_report_to(self):
        """Research and a task in an app run the same with no row to tell: a step then is a no-op, not a row."""
        self.assertFalse(activity.step(1, 6, "Searching"))
        self.assertFalse(activity.update("task:9", note="hello"))
        self.assertEqual(activity.snapshot(), [])

    def test_every_change_moves_the_version_on(self):
        seen = activity.version
        activity.publish("task:1", title="Install VLC")
        self.assertGreater(activity.version, seen)
        seen = activity.version
        activity.snapshot()  # reading changes nothing
        self.assertEqual(activity.version, seen)

    def test_only_what_an_entry_has(self):
        with self.assertRaises(TypeError):
            activity.publish("task:1", output="the command's output")
        with self.assertRaises(ValueError):
            activity.publish("task:1", state="thinking")

    def test_the_tasks_tab_rereads_only_when_a_tasks_row_changed(self):
        activity.publish("task:1", title="Install VLC", note="Installing")
        activity.publish("turn:1", title="open notepad", kind="turn")
        seen = activity.signature("task:")
        activity.step(5, 30, "Round 5 of 30", key="turn:1")
        self.assertEqual(activity.signature("task:"), seen)
        activity.update("task:1", note="Almost done")
        self.assertNotEqual(activity.signature("task:"), seen)


class Pressing(Case):
    """Stop, Approve and Deny reach only what the producer left, and only for the question still waiting."""

    def test_stop_runs_what_its_producer_left_for_it(self):
        stopped = []
        activity.publish("task:3", title="Install VLC", stop=lambda: stopped.append(3) or True)
        self.assertTrue(activity.press("task:3", "stop"))
        self.assertEqual(stopped, [3])
        activity.publish("task:4", title="Nothing to stop")
        self.assertFalse(activity.press("task:4", "stop"))

    def test_approve_and_deny_only_for_the_id_still_waiting(self):
        answers = []
        activity.publish("ask", title="Send the message?", state="waiting_yes", needs="q1",
                         answer=lambda yes: answers.append(yes) or True)
        self.assertFalse(activity.press("ask", "approve", "q0"))  # a button left from the question before
        self.assertFalse(activity.press("ask", "approve"))
        self.assertEqual(answers, [])
        self.assertTrue(activity.press("ask", "approve", "q1"))
        self.assertTrue(activity.press("ask", "deny", "q1"))
        self.assertEqual(answers, [True, False])
        activity.publish("ask", state="running", needs="")  # answered: it's under way, nothing waits on you
        self.assertFalse(activity.press("ask", "approve", "q1"))
        self.later(10)
        activity.finish("ask", "done")
        self.assertFalse(activity.press("ask", "stop"))
        self.assertEqual(answers, [True, False])


class Background(Case):
    """A background task's row: running with Stop, waiting with Approve and Deny, and how it ended, from
    task_worker; approved or cancelled from anywhere through tasks.Store."""

    def setUp(self):
        super().setUp()
        folder = tempfile.mkdtemp(prefix="heyjev-activity-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        self.folder = folder
        self.store = StopsWorker(os.path.join(folder, "tasks.db"))
        self.said = queue.Queue()
        for target, name, value in ((siri, "TASK_STORE", self.store), (siri, "ANNOUNCE", self.said),
                                    (activity, "QUICK", -1.0)):  # done stays a moment, however quick
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def worker(self):
        worker = threading.Thread(target=siri.task_worker, daemon=True)
        worker.start()

        def stop():
            self.store.stopped = True
            tasks.WAKE.set()
            worker.join(5)
        self.addCleanup(stop)

    def test_research_shows_while_it_runs_round_by_round_then_done(self):
        seen, release = queue.Queue(), threading.Event()

        def research(topic, announce=True):
            activity.step(2, 6, "Reading pages")
            seen.put(self.item(f"task:{task}"))
            release.wait(5)
            return True, "Phones under 20,000: the Pixel 8a."
        with mock.patch.object(siri, "research", research), contextlib.redirect_stdout(io.StringIO()):
            task = self.store.create("Research phones under 20000", "research", {"topic": "phones"})
            self.worker()
            got = seen.get(timeout=5)
            release.set()
            self.said.get(timeout=5)
            self.assertTrue(until(lambda: (self.item(f"task:{task}") or {}).get("state") == "done"))
        self.assertEqual((got["state"], got["kind"], got["title"], got["step"], got["total"], got["note"],
                          got["stops"]), ("running", "research", "Research phones under 20000", 2, 6,
                                          "Reading pages", True))

    def test_a_command_waits_with_approve_and_deny_and_a_stale_id_does_nothing(self):
        ran = []
        with mock.patch.object(siri.tasking, "run_command", lambda *a, **k: ran.append(a[0]) or
                               {"output": "secret output", "exit_code": 0}), \
                contextlib.redirect_stdout(io.StringIO()):
            task = self.store.create("Make the build folder", "command", {"command": "mkdir build",
                                                                         "cwd": self.folder})
            self.worker()
            self.said.get(timeout=5)  # "Task 1 is waiting for approval"
            self.assertTrue(until(lambda: (self.item(f"task:{task}") or {}).get("state") == "waiting_yes"))
            waiting = self.item(f"task:{task}")
            self.assertEqual((waiting["needs"], waiting["answers"]), (str(task), True))
            self.assertFalse(activity.press(f"task:{task}", "approve", str(task + 1)))  # another task's button
            self.assertEqual(self.store.get(task)["status"], "waiting_approval")
            self.assertTrue(activity.press(f"task:{task}", "approve", str(task)))
            self.said.get(timeout=5)  # "It finished successfully."
            self.assertTrue(until(lambda: (self.item(f"task:{task}") or {}).get("state") == "done"))
        self.assertEqual(ran, ["mkdir build"])
        self.assertNotIn("secret output", repr(activity.snapshot()))  # never a command's output

    def test_approve_is_refused_while_she_does_a_task_in_an_app(self):
        """Her clicks there are real ones: one landing on the island mustn't approve anything."""
        task = self.store.create("Make the build folder", "command", {"command": "mkdir build", "cwd": self.folder},
                                 status="waiting_approval")
        siri.show_task(self.store.get(task), "waiting_yes")
        agent.RUNNING.set()
        try:
            self.assertFalse(activity.press(f"task:{task}", "approve", str(task)))
        finally:
            agent.RUNNING.clear()
        self.assertEqual(self.store.get(task)["status"], "waiting_approval")

    def test_waiting_from_before_she_started_shows_and_deny_cancels_it(self):
        with contextlib.redirect_stdout(io.StringIO()):
            task = self.store.create("Fix the test", "code", {"task": "fix it", "cwd": self.folder},
                                     status="waiting_approval")
            self.worker()
            self.assertTrue(until(lambda: self.item(f"task:{task}") is not None))
        self.assertEqual(self.item(f"task:{task}")["state"], "waiting_yes")
        self.assertTrue(activity.press(f"task:{task}", "deny", str(task)))
        self.assertEqual(self.store.get(task)["status"], "cancelled")
        self.assertEqual(self.item(f"task:{task}")["state"], "stopped")

    def test_approved_or_cancelled_anywhere_the_row_follows(self):
        """The Tasks tab, "approve task 5", the phone and the island all go through tasks.Store."""
        first = self.store.create("Install VLC", "install", {"id": "VideoLAN.VLC"}, status="waiting_approval")
        second = self.store.create("Install Zoom", "install", {"id": "Zoom.Zoom"}, status="waiting_approval")
        for task in (first, second):
            siri.show_task(self.store.get(task), "waiting_yes")
        self.store.approve(first)
        self.store.cancel(second)
        self.assertEqual((self.item(f"task:{first}")["state"], self.item(f"task:{first}")["needs"]), ("queued", ""))
        self.assertEqual(self.item(f"task:{second}")["state"], "stopped")

    def test_a_reminder_a_look_or_a_watch_has_no_row(self):
        for kind in ("reminder", "lookup", "watch"):
            self.assertFalse(siri.show_task({"id": 1, "kind": kind, "description": "x"}, "running"), kind)
        self.assertEqual(activity.snapshot(), [])


class Turns(Case):
    """Her plan step by step, a task in an app round by round, research and a coding job: each a line or two."""

    def setUp(self):
        super().setUp()
        self.said = []
        for target, name, value in ((siri, "say", lambda line, notify: self.said.append(line)),
                                    (siri, "WAIT_AFTER", {})):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def run_plan(self, steps, do_step):
        with mock.patch.object(siri, "do_step", do_step), contextlib.redirect_stdout(io.StringIO()):
            return siri.run_plan({"steps": steps, "say": ""}, None)

    def test_her_plan_shows_step_by_step_and_goes_once_its_done(self):
        rows = []

        def do_step(step):
            rows.append(next(i for i in activity.snapshot() if i["kind"] == "turn"))
        self.run_plan([{"do": "volume", "to": 30}, {"do": "media", "action": "pause"}], do_step)
        self.assertEqual([(r["step"], r["total"], r["state"]) for r in rows], [(1, 2, "running"), (2, 2, "running")])
        self.assertEqual(rows[0]["title"], "volume 30, media pause")
        self.assertTrue(rows[0]["stops"])
        self.assertEqual(activity.snapshot(), [])  # done in no time: gone at once

    def test_a_task_in_an_app_is_titled_by_the_task_in_a_few_words(self):
        rows = []

        def dispatch(step, notify=None, before=(), alone=True):
            rows.append(next(i for i in activity.snapshot() if i["kind"] == "turn"))
            return "", []
        task = "turn on night light in Settings"
        with mock.patch.object(agent, "dispatch", dispatch), contextlib.redirect_stdout(io.StringIO()):
            siri.run_plan({"steps": [{"do": "screen", "task": task}], "say": ""}, None)
            siri.run_plan({"steps": [{"do": "agent_resume", "hold": "abc123", "verb": "send"}], "say": ""}, None)
        self.assertEqual([r["title"] for r in rows], [agent.task_words(task), "The step you said yes to"])
        self.assertTrue(rows[0]["title"])

    def test_one_quick_step_shows_itself_and_has_no_row(self):
        published = []
        with mock.patch.object(activity, "publish", lambda *a, **k: published.append(a)):
            self.run_plan([{"do": "volume", "to": 30}], lambda step: None)
        self.assertEqual(published, [])

    def test_a_step_that_failed_leaves_its_row_saying_so(self):
        def do_step(step):
            if step["do"] == "media":
                raise RuntimeError("Nothing's playing")
        failed = self.run_plan([{"do": "volume", "to": 30}, {"do": "media", "action": "pause"}], do_step)[0]
        self.assertEqual(failed, ["Nothing's playing"])
        self.assertEqual([i["state"] for i in activity.snapshot()], ["failed"])

    def test_stop_on_her_plan_stops_her_as_stop_said_would(self):
        siri.HER.begin()
        self.addCleanup(siri.HER.end)
        self.addCleanup(agent.STOP.clear)
        self.addCleanup(siri.voice_bits.take_speech_interrupted)  # the next turn's model isn't told of this one
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(siri.stop_turn(siri.HER.turn - 1))  # a turn that's over stops nothing now
            self.assertFalse(siri.HER.stop.is_set())
            self.assertTrue(siri.stop_turn(siri.HER.turn))
        self.assertTrue(siri.HER.stop.is_set())
        self.assertTrue(agent.STOP.is_set())  # a task she's doing in an app stops too

    def test_a_task_in_an_app_says_its_round_and_never_what_it_typed(self):
        r = agent.Run(goal="mail Ravi")
        r.rounds, r.notes = 3, ['typed "my PIN is 4321" into "Message"']
        self.assertEqual(agent.round_note(r), "Round 4 of 30, typed")
        r.notes = ['clicked "Pay \u20b95,000 to Ravi"']
        self.assertEqual(agent.round_note(r), "Round 4 of 30, clicked")
        r.notes = ["didn't click the Send button: that's outside the window in front"]
        self.assertEqual(agent.round_note(r), "Round 4 of 30")

    def test_a_step_held_for_your_yes_shows_it_waits(self):
        activity.publish("turn:1", title="send the mail", kind="turn")
        token = activity.KEY.set("turn:1")
        self.addCleanup(activity.KEY.reset, token)
        self.addCleanup(agent.HELD.clear)
        self.addCleanup(agent.ASK.__setitem__, 0, None)
        self.addCleanup(agent.CURRENT.__setitem__, 0, None)
        r = agent.start(goal="send the mail")
        with mock.patch.object(agent.win, "foreground", lambda: (1, "outlook.exe", "Inbox")):
            self.assertEqual(agent.hold(r, 2, "Send it to Ravi?", "send"), "Send it to Ravi?")
        got = self.item("turn:1")
        self.assertEqual((got["state"], got["note"]), ("waiting_yes", "Waiting for your yes"))

    def test_research_reports_each_round(self):
        notes = []
        replies = iter([{"steps": [{"do": "read", "url": "https://example.com/phones"}], "say": ""},
                        {"steps": [], "say": "The Pixel 8a.", "title": "Phones", "note": ""}])

        def ask_plan(messages, **kw):
            got = self.item("task:2")
            notes.append((got["step"], got["note"]))
            plan = next(replies)
            return "{}", plan, {}, "test"
        activity.publish("task:2", title="Research phones", kind="research")
        token = activity.KEY.set("task:2")
        try:
            with mock.patch.object(siri, "ask_plan", ask_plan), mock.patch.object(siri, "run_info",
                                                                                   lambda *a, **k: "results"), \
                    mock.patch.object(siri, "context", lambda: ""), contextlib.redirect_stdout(io.StringIO()):
                ok, _ = siri._research("phones", announce=False)
        finally:
            activity.KEY.reset(token)
        self.assertTrue(ok)
        self.assertEqual(notes, [(1, "Searching"), (2, "Reading pages")])

    def test_a_coding_job_counts_its_edits_never_names_them(self):
        counted = []
        job = coder.Job("C:\\p", "add a toggle", progress=counted.append)
        for name in ("secret_plan.py", "keys.py"):
            self.assertTrue(job.permission({"toolCall": {"kind": "edit", "title": name}}))
        self.assertEqual(counted, [1, 2])
        self.assertEqual((coder.edited(1), coder.edited(2)), ("1 file edited", "2 files edited"))


class Question(Case):
    """Her question at the PC on the island: Approve and Deny answer it as the phone's buttons answer one, and only
    the question still waiting, asked out loud, before it ran out."""

    def setUp(self):
        super().setUp()
        self.ran = []

        def run_plan(plan, notify):
            self.ran.append(plan)
            return [], False, None, [plan.get("say") or ""]
        for target, name, value in ((siri, "run_plan", run_plan), (siri, "learn_later", lambda *a, **k: None),
                                    (siri, "say", lambda line, notify: None)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(siri.PENDING.update, plan=None, until=0.0, origin="voice")
        controls = queue.Queue()
        p = mock.patch.object(siri, "CONTROLS", [controls])
        p.start()
        self.addCleanup(p.stop)
        self.controls = controls

    def ask(self, steps, origin="voice", ask="q1", secs=16.0):
        confirm = {"steps": steps, "say": ""}
        siri.PENDING.update(plan=confirm, until=time.time() + secs, soon=time.time() + secs, origin=origin, id=ask)
        siri.show_ask(confirm)
        return confirm

    def test_her_question_shows_with_approve_and_deny_until_it_runs_out(self):
        self.ask([{"do": "message_send"}])
        got = self.item("ask")
        self.assertEqual((got["title"], got["state"], got["needs"], got["answers"]),
                         ("Send the message?", "waiting_yes", "q1", True))
        self.assertTrue(activity.press("ask", "approve", "q1"))
        self.assertEqual(self.controls.get_nowait(), ("island tap", True, "q1"))  # through siri's controls loop
        self.later(17)
        self.assertIsNone(self.item("ask"))

    def test_a_phone_question_or_a_task_waiting_has_no_question_row(self):
        self.ask([{"do": "shutdown"}], origin="phone")
        self.assertIsNone(self.item("ask"))  # only the phone's button answers that
        self.ask([{"do": "task_control", "action": "approve", "id": 4}])
        self.assertIsNone(self.item("ask"))  # its task's own row has the buttons

    def test_a_tap_answers_only_the_question_still_waiting(self):
        answered = []
        with mock.patch.object(siri, "handle", lambda text, *a, **k: answered.append((text, siri.TAPPED.get()))), \
                contextlib.redirect_stdout(io.StringIO()):
            self.ask([{"do": "shutdown"}])
            self.assertFalse(siri.island_answer(True, "q0"))  # a button from the question before
            self.ask([{"do": "shutdown"}], origin="phone")
            self.assertFalse(siri.island_answer(True, "q1"))  # asked on the phone
            self.ask([{"do": "shutdown"}], secs=-1)
            self.assertFalse(siri.island_answer(True, "q1"))  # ran out
            self.ask([{"do": "shutdown"}])
            agent.RUNNING.set()
            try:
                self.assertFalse(siri.island_answer(True, "q1"))  # she's doing a task in an app
            finally:
                agent.RUNNING.clear()
            self.assertEqual(answered, [])
            self.assertTrue(siri.island_answer(False, "q1"))
        self.assertEqual(answered, [("no", True)])

    def test_one_tap_one_action(self):
        self.addCleanup(siri.POWER_OK.update, until=0.0)
        self.ask([{"do": "shutdown"}])
        with mock.patch.object(siri, "think", lambda *a, **k: self.fail("the model was asked")), \
                contextlib.redirect_stdout(io.StringIO()):
            self.assertTrue(siri.island_answer(True, "q1"))
            self.assertFalse(siri.island_answer(True, "q1"))  # the same button again
        self.assertEqual([[s["do"] for s in p["steps"]] for p in self.ran], [["shutdown"]])
        self.assertIsNone(siri.PENDING["plan"])
        self.assertIsNone(self.item("ask"))


if __name__ == "__main__":
    unittest.main()
