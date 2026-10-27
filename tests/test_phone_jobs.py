"""Background work on the phone and a running job's question by voice (telegram_bot.Bot.progress and send_document,
siri.progress_tick, tasks_said, job_ask, and tasks.Store.ask and resume). 27 October: the owner asked to see a
background task move on from the phone, to get research and a coding job's report there as a file, and for a coding
job started by voice to ask about a command rather than refuse it, where until then a task said only that it was
done, and a voice-started job refused every command that needed a yes and listed it in its report.

Telegram is faked: the bot's loop runs on a thread of its own with a stand-in for the library's bot. tasks.db is a
temp file, activity's clock a list cell, and nothing here acts on the PC or goes online (tests.support trips that)."""
import asyncio
import contextlib
import io
import os
import queue
import shutil
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.support import TRIPPED, siri  # first: temp APPDATA and the tripwires, before anything of hers
from tests.test_watchers import until

import activity
import coder
import tasks
import telegram_bot


class FakeTelegram:
    """The library's bot, recording what it was asked to do: send_message gives each message its own id."""

    def __init__(self):
        self.sent, self.edits, self.documents = [], [], []

        async def send_message(chat, text, **kw):
            self.sent.append((chat, text))
            return SimpleNamespace(message_id=100 + len(self.sent))

        async def edit_message_text(text, chat_id=None, message_id=None, **kw):
            self.edits.append((chat_id, message_id, text))

        async def send_document(chat, document=None, filename=None, caption=None, **kw):
            self.documents.append((chat, filename, document.read(), caption))
        self.bot = SimpleNamespace(send_message=send_message, edit_message_text=edit_message_text,
                                   send_document=send_document)


class Case(unittest.TestCase):
    """Paired with chat 7, and nothing a test does may reach a tripwire."""

    def setUp(self):
        self.tripped = len(TRIPPED)
        self.addCleanup(lambda: self.assertEqual(TRIPPED[self.tripped:], []))
        p = mock.patch.dict(siri.settings._load(), {"telegram_owner": 7, "phone_progress": "asked"})
        p.start()
        self.addCleanup(p.stop)

    def bot(self):
        """A Bot whose loop runs on its own thread, as it does once Telegram is listening."""
        bot, fake = telegram_bot.Bot(on_message=None, on_tap=None), FakeTelegram()
        bot.app, bot.loop = fake, asyncio.new_event_loop()
        thread = threading.Thread(target=bot.loop.run_forever, daemon=True)
        thread.start()

        def stop():
            bot.loop.call_soon_threadsafe(bot.loop.stop)
            thread.join(5)
            bot.loop.close()
        self.addCleanup(stop)
        return bot, fake


class Progress(Case):
    """One message per job, edited in place at most every PROGRESS_EVERY seconds, only to your chat."""

    def test_one_message_then_edits_of_it_no_more_than_every_ten_seconds(self):
        bot, fake = self.bot()
        self.assertTrue(bot.progress(7, "task:3", "Research flights\nWorking"))
        self.assertFalse(bot.progress(7, "task:3", "Research flights\nWorking \u00b7 step 2 of 6"))  # too soon
        bot.progressing["task:3"]["at"] -= telegram_bot.PROGRESS_EVERY
        self.assertTrue(bot.progress(7, "task:3", "Research flights\nWorking \u00b7 step 3 of 6"))
        bot.progressing["task:3"]["at"] -= telegram_bot.PROGRESS_EVERY
        self.assertFalse(bot.progress(7, "task:3", "Research flights\nWorking \u00b7 step 3 of 6"))  # nothing new
        self.assertTrue(bot.progress(7, "task:3", "Research flights\nDone", final=True))  # whatever the wait
        self.assertEqual(fake.sent, [(7, "Research flights\nWorking")])
        self.assertEqual(fake.edits, [(7, 101, "Research flights\nWorking \u00b7 step 3 of 6"),
                                      (7, 101, "Research flights\nDone")])
        self.assertNotIn("task:3", bot.progressing)  # forgotten once it's over

    def test_each_job_has_its_own_message(self):
        bot, fake = self.bot()
        bot.progress(7, "task:3", "One")
        bot.progress(7, "task:4", "Two")
        self.assertEqual(fake.sent, [(7, "One"), (7, "Two")])

    def test_never_to_a_chat_that_isnt_yours(self):
        bot, fake = self.bot()
        self.assertFalse(bot.progress(8, "task:3", "Research flights"))
        with mock.patch.dict(siri.settings._load(), {"telegram_owner": None}):
            self.assertFalse(bot.progress(7, "task:3", "Research flights"))
        self.assertEqual((fake.sent, fake.edits), ([], []))

    def test_a_first_message_that_failed_is_tried_afresh(self):
        bot = telegram_bot.Bot(on_message=None, on_tap=None)  # not listening: no loop
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(bot.progress(7, "task:3", "Research flights"))
        self.assertNotIn("task:3", bot.progressing)


class Documents(Case):
    """A finished job's note or report as a file: only one of her notes, only to you, and not a big one."""

    def setUp(self):
        super().setUp()
        self.notes = telegram_bot.document_roots()[0]
        os.makedirs(self.notes, exist_ok=True)
        self.note = os.path.join(self.notes, "2026-10-27 Flights to Goa.md")
        with open(self.note, "wb") as f:
            f.write(b"# Flights to Goa\n\nIndiGo on Friday.\n")
        self.addCleanup(os.remove, self.note)

    def test_a_note_goes_to_your_chat_with_its_name(self):
        bot, fake = self.bot()
        self.assertTrue(bot.send_document(7, self.note, "Task 3: Research flights"))
        self.assertEqual(fake.documents, [(7, "2026-10-27 Flights to Goa.md",
                                           b"# Flights to Goa\n\nIndiGo on Friday.\n", "Task 3: Research flights")])

    def test_only_from_her_notes_folder(self):
        bot, fake = self.bot()
        outside = tempfile.mkdtemp(prefix="heyjev-docs-")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        elsewhere = os.path.join(outside, "secrets.md")
        with open(elsewhere, "w", encoding="utf-8") as f:
            f.write("not hers to send")
        settings_file = os.path.join(os.path.dirname(self.notes), "settings.json")  # her data, but not a note
        with contextlib.redirect_stdout(io.StringIO()):
            for path in (elsewhere, settings_file, os.path.join(self.notes, "..", "settings.json"),
                         os.path.join(self.notes, "..", "notes", "..", "tasks.md"), "", None):
                self.assertFalse(bot.send_document(7, path), path)
        self.assertEqual(fake.documents, [])

    def test_only_markdown_or_text_and_not_too_big(self):
        bot, fake = self.bot()
        big, script = os.path.join(self.notes, "big.md"), os.path.join(self.notes, "run.ps1")
        with open(big, "wb") as f:
            f.write(b"x" * (telegram_bot.DOCUMENT_BYTES + 1))
        with open(script, "w", encoding="utf-8") as f:
            f.write("Remove-Item C:\\")
        self.addCleanup(os.remove, big)
        self.addCleanup(os.remove, script)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertFalse(bot.send_document(7, big))
            self.assertFalse(bot.send_document(7, script))
        self.assertEqual(fake.documents, [])

    def test_never_to_a_chat_that_isnt_yours(self):
        bot, fake = self.bot()
        self.assertFalse(bot.send_document(8, self.note))
        self.assertEqual(fake.documents, [])


class Clocked(Case):
    """An empty activity registry with a list-cell clock, and a fake phone that records what it's given."""

    def setUp(self):
        super().setUp()
        self.clock = [time.time()]
        p = mock.patch.object(activity, "_clock", lambda: self.clock[0])
        p.start()
        self.addCleanup(p.stop)
        activity.clear()
        self.addCleanup(activity.clear)
        self.progress, self.documents = [], []
        p = mock.patch.dict(siri.PHONE, {
            "progress": lambda chat, key, text, final: self.progress.append((chat, key, text, final)) or True,
            "document": lambda chat, path, caption: self.documents.append((chat, path, caption)) or True})
        p.start()
        self.addCleanup(p.stop)
        p = mock.patch.dict(siri.PROGRESS_TO, {}, clear=True)
        p.start()
        self.addCleanup(p.stop)


class PhoneProgress(Clocked):
    """siri.progress_tick: a task asked from the phone shows there once it's run a while, and says how it ended."""

    def follow(self, key="task:3", title="Research flights"):
        activity.publish(key, title=title, kind="research", state="running", origin="task")
        siri.PROGRESS_TO[key] = {"chat": 7, "title": title, "shown": False}

    def test_a_quick_task_only_sends_its_result(self):
        self.follow()
        siri.progress_tick(self.clock[0] + 2)
        activity.finish("task:3", "done")
        siri.progress_tick(self.clock[0] + 3)
        self.assertEqual(self.progress, [])
        self.assertEqual(siri.PROGRESS_TO, {})

    def test_a_long_one_moves_on_and_says_done(self):
        self.follow()
        activity.step(2, 6, "Reading pages", key="task:3")
        siri.progress_tick(self.clock[0] + siri.PROGRESS_AFTER + 65)
        self.assertEqual(self.progress, [(7, "task:3", "Research flights\nWorking \u00b7 step 2 of 6 \u00b7 Reading "
                                                       "pages \u00b7 1 min", False)])
        with mock.patch.object(activity, "QUICK", 1e9):  # gone from activity at once, as a quick success is
            activity.finish("task:3", "done")
        siri.progress_tick()
        self.assertEqual(self.progress[-1], (7, "task:3", "Research flights\nDone", True))
        self.assertEqual(siri.PROGRESS_TO, {})

    def test_a_failure_says_so(self):
        self.follow()
        siri.progress_tick(self.clock[0] + siri.PROGRESS_AFTER)
        activity.finish("task:3", "failed", "Open Tasks for the details")
        siri.progress_tick()
        self.assertEqual(self.progress[-1][2:], ("Research flights\nDidn't work \u00b7 Open Tasks for the details",
                                                 True))

    def test_unpaired_meanwhile_nothing_more_goes(self):
        self.follow()
        with mock.patch.dict(siri.settings._load(), {"telegram_owner": 8}):
            siri.progress_tick(self.clock[0] + 60)
        self.assertEqual((self.progress, siri.PROGRESS_TO), ([], {}))

    def test_only_tasks_asked_from_the_phone_unless_settings_say_all(self):
        phone, voice = {"payload": {"origin": {"phone": 7}}}, {"payload": {"origin": {}}}
        self.assertEqual((siri.phone_for(phone), siri.phone_for(voice)), (7, None))
        self.assertIsNone(siri.phone_for({"payload": {"origin": {"phone": 9}}}))  # paired with another since
        with mock.patch.dict(siri.settings._load(), {"phone_progress": "all"}):
            self.assertEqual(siri.phone_for(voice), 7)
        with mock.patch.dict(siri.settings._load(), {"telegram_owner": None, "phone_progress": "all"}):
            self.assertIsNone(siri.phone_for(phone))

    def test_progress_never_reads_tasks_db(self):
        self.follow()
        with mock.patch.object(siri, "TASK_STORE", mock.Mock(side_effect=AssertionError)) as store:
            siri.progress_tick(self.clock[0] + 60)
            siri.tasks_said()
        self.assertEqual(store.mock_calls, [])


class TasksCommand(Clocked):
    """The phone's "tasks", answered from activity's memory."""

    def test_the_words_that_ask_for_it(self):
        for said in ("tasks", "/tasks", "what's running", "what are you working on right now", "progress"):
            self.assertTrue(siri.PHONE_TASKS.fullmatch(said), said)
        for said in ("show my tasks for tomorrow", "cancel task 3", "approve task 3", "add a task"):
            self.assertFalse(siri.PHONE_TASKS.fullmatch(said), said)

    def test_nothing_going(self):
        self.assertEqual(siri.tasks_said(), "Nothing's running in the background right now.")

    def test_what_waits_on_you_first_with_how_to_answer(self):
        activity.publish("task:3", title="Research flights", kind="research", state="running", step=2, total=6,
                         note="Reading pages")
        activity.publish("task:5", title="Fix the failing test", kind="code", state="waiting_yes", needs="5",
                         note="OpenCode wants to run npm install. Let it?")
        self.assertEqual(siri.tasks_said(self.clock[0]).split("\n"), [
            "\u2022 Fix the failing test: Waiting for your yes \u00b7 OpenCode wants to run npm install. Let it? "
            "(send approve task 5 to let it)",
            "\u2022 Research flights: Working \u00b7 step 2 of 6 \u00b7 Reading pages"])


class JobQuestions(Clocked):
    """A coding job's command that needs your yes (siri.job_ask): its row waits with the exact command, a yes
    reaches only its question, a no or Deny refuses only the step, and Stop ends the job."""

    def setUp(self):
        super().setUp()
        folder = tempfile.mkdtemp(prefix="heyjev-jobs-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        self.store = tasks.Store(os.path.join(folder, "tasks.db"))
        self.said = queue.Queue()
        for target, name, value in ((siri, "TASK_STORE", self.store), (siri, "ANNOUNCE", self.said)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(tasks.ASKS.clear)
        self.addCleanup(siri.PENDING.update, plan=None, until=0.0, soon=0.0, origin="voice")

    def running(self, description="Fix the failing test", origin=None):
        tid = self.store.create(description, "code", {"task": "fix it", "cwd": "C:\\p", "approved": True,
                                                      "origin": origin or {}})
        task = self.store.claim_due(skip=tuple(k for k in tasks.KINDS if k != "code"))
        self.assertEqual(task["id"], tid)
        return task

    def asking(self, task, chat=None, wait=5.0, question="OpenCode wants to run npm install. Let it?"):
        """job_ask's ask on a thread of its own, as the job's permission() calls it: a queue its answer comes in."""
        got = queue.Queue()
        threading.Thread(target=lambda: got.put(siri.job_ask(task, chat, wait)(question)), daemon=True).start()
        self.assertTrue(until(lambda: self.store.get(task["id"])["status"] == "waiting_approval"))
        return got

    def test_its_row_waits_with_the_exact_command_and_she_says_it(self):
        task = self.running()
        got = self.asking(task)
        row = self.store.get(task["id"])
        self.assertEqual((row["error"], row["payload"]["asking"]), ("OpenCode wants to run npm install. Let it?",) * 2)
        item = next(i for i in activity.snapshot() if i["key"] == f"task:{task['id']}")
        self.assertEqual((item["state"], item["needs"], item["note"]),
                         ("waiting_yes", str(task["id"]), "OpenCode wants to run npm install. Let it?"))
        line = self.said.get(timeout=5)
        self.assertEqual(line, f"Task {task['id']}: OpenCode wants to run npm install. Let it?")
        self.assertEqual(line.confirm["steps"], [{"do": "task_control", "action": "approve", "id": task["id"]}])
        with contextlib.redirect_stdout(io.StringIO()):
            plan = siri.prepare_task_steps({"steps": [{"do": "task_control", "action": "approve",
                                                       "id": task["id"]}], "say": ""})  # "approve task N"
        self.assertTrue(got.get(timeout=5))
        self.assertEqual(plan["say"], f"Okay, task {task['id']} can go ahead with that.")
        row = self.store.get(task["id"])
        self.assertEqual((row["status"], "asking" in row["payload"], row["payload"]["approved"]),
                         ("running", False, True))  # running on, never queued for a second run
        with contextlib.redirect_stdout(io.StringIO()):
            again = siri.prepare_task_steps({"steps": [{"do": "task_control", "action": "approve",
                                                        "id": task["id"]}], "say": ""})
        self.assertIn("isn't waiting", again["say"])  # one yes, one command

    def test_a_yes_for_one_job_never_answers_another(self):
        first, second = self.running("First job"), self.running("Second job")
        got_first, got_second = self.asking(first), self.asking(second)
        self.assertTrue(self.store.approve(second["id"]))
        self.assertTrue(got_second.get(timeout=5))
        self.assertEqual(self.store.get(first["id"])["status"], "waiting_approval")
        self.assertTrue(got_first.empty())
        self.store.approve(first["id"])
        self.assertTrue(got_first.get(timeout=5))

    def test_deny_on_the_island_refuses_the_command_and_the_job_goes_on(self):
        task = self.running()
        got = self.asking(task)
        self.assertFalse(activity.press(f"task:{task['id']}", "deny", str(task["id"] + 1)))  # another's button
        self.assertTrue(activity.press(f"task:{task['id']}", "deny", str(task["id"])))
        self.assertFalse(got.get(timeout=5))
        self.assertEqual(self.store.get(task["id"])["status"], "running")

    def test_stop_ends_the_job(self):
        task = self.running()
        got = self.asking(task)
        self.assertTrue(activity.press(f"task:{task['id']}", "stop"))
        self.assertFalse(got.get(timeout=5))
        self.assertEqual(self.store.get(task["id"])["status"], "cancelled")

    def test_no_answer_in_time_refuses_it(self):
        task = self.running()
        got = self.asking(task, wait=0.3)
        self.assertFalse(got.get(timeout=5))
        self.assertEqual(self.store.get(task["id"])["status"], "running")
        self.assertFalse(self.store.approve(task["id"]))  # too late now

    def test_a_job_asked_from_the_phone_asks_there_with_its_own_buttons(self):
        buttons = queue.Queue()
        with mock.patch.dict(siri.PHONE, {"buttons": lambda chat, line, key: buttons.put((chat, line, key)) or True}):
            task = self.running(origin={"phone": 7})
            got = self.asking(task, chat=7)
            chat, line, key = buttons.get(timeout=5)
            self.assertEqual((chat, line), (7, f"Task {task['id']}: OpenCode wants to run npm install. Let it?"))
            self.assertTrue(self.said.empty())  # not said out loud as well
            self.assertTrue(siri.JOB_KEYS[key](True))
            self.assertTrue(got.get(timeout=5))
        self.assertNotIn(key, siri.JOB_KEYS)  # an old button does nothing

    def test_a_command_with_a_secret_in_it_is_never_said(self):
        task = self.running()
        got = self.asking(task, wait=0.3, question="OpenCode wants to run curl https://bob:hunter2@x.io. Let it?")
        self.assertNotIn("hunter2", self.said.get(timeout=5))
        self.assertNotIn("hunter2", self.store.get(task["id"])["error"])
        got.get(timeout=5)

    def test_a_clear_yes_to_her_saying_it_runs_only_that_approval(self):
        task = self.running()
        got = self.asking(task)
        line = self.said.get(timeout=5)
        siri.said_out_loud(line)  # as heads_ups' tell does, once she's said it
        self.assertEqual(siri.PENDING["plan"], line.confirm)
        ran = []

        def run_plan(plan, notify):
            ran.append(plan)
            return [], False, None, [plan.get("say") or ""]
        with mock.patch.object(siri, "run_plan", run_plan), mock.patch.object(siri, "learn_later", lambda *a, **k: 0), \
                mock.patch.object(siri, "say", lambda line, notify: None), contextlib.redirect_stdout(io.StringIO()):
            siri.handle("yes")
        self.assertTrue(got.get(timeout=5))
        self.assertEqual([s["do"] for s in ran[0]["steps"]], ["task_queued"])
        self.assertIsNone(siri.PENDING["plan"])

    def test_a_no_to_her_saying_it_refuses_the_command_at_once(self):
        task = self.running()
        got = self.asking(task)
        siri.said_out_loud(self.said.get(timeout=5))
        self.assertTrue(siri.refuse_job(siri.PENDING["plan"]))
        self.assertFalse(got.get(timeout=5))

    def test_never_over_a_question_of_hers_still_waiting_or_once_cut_off(self):
        mine = {"steps": [{"do": "message_send"}], "say": ""}
        siri.PENDING.update(plan=mine, until=time.time() + 30, soon=time.time() + 30, origin="voice")
        siri.said_out_loud(siri.Said("Task 4: OpenCode wants to run npm install. Let it?",
                                     {"steps": [{"do": "task_control", "action": "approve", "id": 4}]}))
        self.assertIs(siri.PENDING["plan"], mine)  # her yes stays hers: it's "approve task 4"
        siri.PENDING.update(plan=None, until=0.0)
        siri.HER.stop.set()
        try:
            siri.said_out_loud(siri.Said("Task 4: ...", {"steps": []}))
        finally:
            siri.HER.stop.clear()
        self.assertIsNone(siri.PENDING["plan"])  # talked over: never a yes to what you didn't hear

    def test_a_job_asking_when_she_stopped_is_asked_about_whole_again(self):
        task = self.running()
        self.assertTrue(self.store.ask(task["id"], "OpenCode wants to run npm install. Let it?", lambda yes: True))
        self.store.recover()  # she started again: nothing in this process is waiting on it
        row = self.store.get(task["id"])
        self.assertEqual(row["status"], "waiting_approval")
        self.assertNotIn("asking", row["payload"])
        self.assertNotIn("approved", row["payload"])  # the job, not its old step, needs your yes
        self.assertIn("asking about a step", row["error"])
        self.assertTrue(self.store.approve(task["id"]))
        self.assertEqual(self.store.get(task["id"])["status"], "queued")


class Reports(Clocked):
    """A finished task's note or report goes to the phone it was asked from, as a file."""

    def setUp(self):
        super().setUp()
        folder = tempfile.mkdtemp(prefix="heyjev-reports-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        self.folder = folder

    def test_a_coding_jobs_report_says_what_it_did_and_how_to_undo_it(self):
        job = coder.Job(self.folder, "fix the failing test")
        job.edited, job.ran, job.refused = ["tests/test_app.py"], ["npm test"], ["npm install (changes the PC)"]
        path = siri.coding_report({"id": 6, "description": "Fix the failing test"}, "Fixed it.", job, "stash:abcdef12")
        self.addCleanup(os.remove, path)
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for bit in ("Task 6: Fix the failing test", "It said: Fixed it.", "- tests/test_app.py", "- npm test",
                    "- npm install (changes the PC)", "git stash apply abcdef12"):
            self.assertIn(bit, text)
        self.assertEqual(telegram_bot.confined(path), os.path.realpath(path))  # one the bot may send

    def test_research_asked_from_the_phone_sends_its_note(self):
        from tests.test_timers import StopsWorker
        store = StopsWorker(os.path.join(self.folder, "tasks.db"))
        notes = []

        def research(topic, announce=True):
            name = siri.save_note("Flights to Goa", "IndiGo on Friday.")
            notes.append(os.path.join(siri.NOTES_DIR, name))
            return True, "IndiGo on Friday is cheapest."
        said = queue.Queue()
        with mock.patch.object(siri, "TASK_STORE", store), mock.patch.object(siri, "ANNOUNCE", said), \
                mock.patch.object(siri, "research", research), \
                mock.patch.dict(siri.PHONE, {"send": lambda chat, line: True}), \
                contextlib.redirect_stdout(io.StringIO()):
            phone = store.create("Research flights", "research", {"topic": "flights", "origin": {"phone": 7}})
            store.create("Research trains", "research", {"topic": "trains", "origin": {}})
            worker = threading.Thread(target=siri.task_worker, daemon=True)
            worker.start()
            try:
                said.get(timeout=5)  # the voice one's result, said: the phone one's went to the phone
                self.assertTrue(until(lambda: len(notes) == 2 and store.get(phone)["status"] == "completed"))
            finally:
                store.stopped = True
                tasks.WAKE.set()
                worker.join(5)
        for path in set(notes):
            os.remove(path)
        self.assertEqual(self.documents, [(7, notes[0], f"Task {phone}: Research flights")])


if __name__ == "__main__":
    unittest.main()
