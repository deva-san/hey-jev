"""Jobs in the background (agent.Job, agent.background, siri.run_job): every task can go on while you keep talking to
her (the owner's ask, 27 October). A job is a task row of kind agent, run on the agent lane beside the slow tasks,
never in a turn: it holds no busy and sets no RUNNING, so a voice turn goes on meanwhile; it has its own stop, so
"stop" said to her or another job stopped leaves it be; its held step is keyed by its task id and step id, so a yes
to job A can't release job B's; it reads and presses its own window by UI Automation, and takes the screen only for
keys, typing, a click at a point, scrolling, opening or switching, after a lull in your typing and never while a turn
of yours acts; and Hermes' goal judge decides at the end whether it's done, blocked or worth another go. Nothing here
acts on the PC or goes online: FakeApp stands in for the PC (read window by window here), a script for the model and
the judge, a fake clock for the waits, and a temporary tasks.db."""
import json
import os
import queue
import sqlite3
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.support import TRIPPED, siri, winplatform  # first: temp APPDATA and the tripwires
from tests.test_agent import Control, Live
from tests.test_timers import StopsWorker

import activity
import agent
import tasks

ORIGINAL_ASK_ALONE = siri.ask_alone  # the real one: the rest of these tests script the judge in its place
WORDS = "send hi to ravi@example.com from the mail app in the background"


class Jobs(Live):
    """Live's FakeApp, scripted model and fake clock, read window by window (a job reads its own, whatever's in
    front), a temporary tasks.db, ANNOUNCE as a queue, a judge that says done, and nothing tripped."""

    def setUp(self):
        super().setUp()
        self.tripped = len(TRIPPED)
        self.addCleanup(lambda: self.assertEqual(TRIPPED[self.tripped:], []))
        self.store = tasks.Store(os.path.join(tempfile.mkdtemp(prefix="heyjev-jobs-"), "tasks.db"))
        self.told, self.idle, self.locked, self.judged = queue.Queue(), [60.0], [False], []
        self.verdicts = []  # the judge's verdicts in turn, then done
        for target, name, value in (
                (siri, "TASK_STORE", self.store), (siri, "ANNOUNCE", self.told),
                (winplatform, "window_of", self.window_of), (winplatform, "front_window", self.front_window),
                (winplatform, "bring_to_front", self.bring_to_front), (winplatform, "ui_snapshot", self.snapshot),
                (winplatform, "ui_info", self.ui_info), (winplatform, "find_ui", self.find_ui),
                (winplatform, "find_all_ui", self.find_all_ui), (winplatform, "ui_fields", self.ui_fields),
                (winplatform, "idle_seconds", lambda: self.idle[0]),
                (winplatform, "session_locked", lambda: self.locked[0]),
                (siri.vision, "of_window", lambda hwnd: self.capture()), (siri, "ask_alone", self.judge)):
            self.patch(target, name, value)
        for cell in (agent.JOBS, agent.JOB_HELD):
            cell.clear()
        agent.PLAN_ACTING[0] = agent.BACKGROUND[0] = 0
        self.addCleanup(agent.JOBS.clear)
        self.addCleanup(agent.JOB_HELD.clear)
        activity.clear()
        self.addCleanup(activity.clear)
        siri.JOB_NEWS.clear()
        self.addCleanup(siri.JOB_NEWS.clear)
        desk = self.app.window("explorer", "explorer.exe", "Program Manager")  # yours, in front
        desk.controls = [Control("Recycle Bin", "listitem")]
        self.app.show("explorer")

    # FakeApp read window by window, as UI Automation reads one by its handle
    def by_hwnd(self, hwnd):
        return next((w for w in self.app.windows.values() if w.hwnd == hwnd), None) if hwnd else self.app.front

    def window_of(self, hwnd):
        w = self.by_hwnd(hwnd)
        return (w.hwnd, w.exe, w.title) if hwnd and w is not None and hwnd not in self.app.closed else (None, "", "")

    def front_window(self):
        return self.app.front.hwnd if self.app.front else None

    def bring_to_front(self, hwnd):
        self.app.front = self.by_hwnd(hwnd)

    def snapshot(self, hwnd=None, most=60):
        w = self.by_hwnd(hwnd)
        self.app.snapshots += 1
        items = [{"id": n + 1, "role": c.role, "name": winplatform.clean_name(c.name), "value": c.value,
                  "state": c.state, "password": c.password, "focus": False, "aid": "", "el": c}
                 for n, c in enumerate(w.controls[:most])]
        return {"hwnd": w.hwnd, "title": w.title, "exe": w.exe, "site": w.site, "focus": None, "items": items,
                "total": len(w.controls), "cut": False, "focused": None}

    def owner(self, el):
        return next((w for w in self.app.windows.values() if el in w.controls), None)

    def ui_info(self, el):
        if self.owner(el) is None:
            raise RuntimeError("element not available")
        return {"name": winplatform.clean_name(el.name), "role": el.role, "aid": "", "password": el.password, "el": el}

    def find_all_ui(self, name=None, role=None, aid=None, hwnd=None):
        want = winplatform.clean_name(name).lower()
        return [c for c in self.by_hwnd(hwnd).controls
                if winplatform.clean_name(c.name).lower() == want and role in (None, c.role)]

    def find_ui(self, name=None, role=None, aid=None, hwnd=None, wait=0.0, unique=True, strict=False):
        hits = self.find_all_ui(name, role, aid, hwnd)
        return hits[0] if hits and (len(hits) == 1 or not unique) else None

    def ui_fields(self, el=None):
        w = self.owner(el) if el is not None else self.app.front
        return [(c.role, winplatform.clean_name(c.name), c.value) for c in w.controls]

    def judge(self, messages, **kw):
        """Hermes' goal judge, scripted: its verdicts in turn, then done."""
        self.judged.append(messages)
        verdict = self.verdicts.pop(0) if self.verdicts else "done"
        return json.dumps({"verdict": verdict, "reason": f"judged {verdict}"}), {}, "test"

    def mail(self):
        """A mail app: To, Message and Send, which sends and leaves "Sent" in its place."""
        w = self.app.window("mail", "mail.exe", "Mail")
        self.app.sent = []

        def send():
            self.app.sent.append({c.name: c.value for c in w.controls})
            w.controls = [Control("Sent", "text")]
        w.controls = [Control("To", "edit", value=""), Control("Message", "edit", value=""), Control("Send", on=send)]
        return w

    def queue_job(self, goal, words=None, named=True):
        """A job asked for in words, as prepare_task_steps queues one: its task id."""
        said, name = agent.SAID.set(words or goal), agent.NAMED.set(named)
        try:
            return siri.queue_job(goal)
        finally:
            agent.SAID.reset(said)
            agent.NAMED.reset(name)

    def claim(self, tid):
        """The worker's claim of the job's row: running, as run_job gets it."""
        task = self.store.claim_due()
        self.assertEqual(task["id"], tid)
        return task

    def run_in_job(self, tid, fn, goal="a job"):
        """fn() on a run of job tid's own, as agent.background runs one."""
        job = agent.job_for(tid, goal, goal, True)
        token = agent.JOB.set(job)
        try:
            r = agent.start(goal=goal)
            r.task = True
            run_token = agent.RUN.set(r)
            try:
                return fn(job, r)
            finally:
                agent.RUN.reset(run_token)
        finally:
            agent.JOB.reset(token)


class Mail(Jobs):
    """A mail written and sent in the background, the send held for a yes keyed to that job and step."""

    def held_mail(self, words=WORDS):
        self.mail()
        self.model({"steps": [{"do": "open", "app": "mail"}]},
                   lambda: {"steps": [{"do": "click", "id": 1, "text": "ravi@example.com"},
                                      {"do": "click", "id": 2, "text": "hi"}, {"do": "click", "id": 3}]},
                   {"steps": [], "done": True, "expect": {"has": "Sent"}, "say": "Sent it to Ravi."})
        tid = self.queue_job("send hi to ravi@example.com in the mail app", words)
        siri.run_job(self.claim(tid))
        return tid

    def test_it_asks_keyed_to_its_step_and_only_that_yes_sends_it(self):
        tid = self.held_mail()
        row = self.store.get(tid)
        self.assertEqual(row["status"], "waiting_approval")
        self.assertEqual(self.app.sent, [])  # nothing sent before the yes
        asked = self.told.get_nowait()
        self.assertIsInstance(asked, siri.JobAsk)
        self.assertTrue(asked.startswith(f"Task {tid} asks: "), asked)
        self.assertIn("r a v i at e x a m p l e dot c o m", asked)  # read back in full, as a turn's send is
        self.assertEqual((asked.task_id, asked.hold), (tid, row["payload"]["hold"]))
        self.assertEqual(self.app.front.exe, "explorer.exe")  # the screen given back after it opened its app
        self.assertEqual(agent.HELD, {})  # a turn's slot untouched
        self.assertIsNone(agent.ASK[0])
        self.assertFalse(self.store.approve(tid, "0123abcd"))  # an old question's yes, or another job's
        self.assertTrue(self.store.approve(tid, asked.hold))
        siri.run_job(self.claim(tid))
        self.assertEqual(self.app.sent, [{"To": "ravi@example.com", "Message": "hi", "Send": None}])
        self.assertEqual(self.store.get(tid)["status"], "completed")
        self.assertEqual(self.told.get_nowait(), f"Task {tid} finished: {row['description']}. Sent it to Ravi.")
        self.assertEqual(len(self.judged), 1)  # one judge call, at the end
        news = siri.take_job_news()
        self.assertTrue(news.startswith(f"[Background job {tid} finished]\nGoal: send hi"), news)
        self.assertIn("Status: done", news)
        self.assertEqual(siri.take_job_news(), "")  # told to the model once

    def test_a_yes_said_out_loud_after_its_question_approves_that_step_only(self):
        tid = self.held_mail()
        asked = self.told.get_nowait()
        self.assertTrue(siri.job_asked(asked))
        pending = siri.PENDING["plan"]
        self.assertTrue(siri.said_yes("yes, send it", pending))
        self.assertFalse(siri.said_yes("right", pending))  # a strict yes, as for any send
        plan = siri.prepare_task_steps(json.loads(json.dumps(pending)))
        self.assertEqual(plan["say"], f"Task {tid} approved and queued.")
        self.assertTrue(self.store.get(tid)["payload"]["approved"])

    def test_her_question_never_goes_over_a_turns_question_still_waiting(self):
        self.held_mail()
        asked = self.told.get_nowait()
        turns = {"steps": [{"do": "message_send"}], "say": ""}
        siri.PENDING.update(plan=turns, until=time.time() + 30, origin="voice")
        self.assertFalse(siri.job_asked(asked))
        self.assertIs(siri.PENDING["plan"], turns)

    def test_a_no_to_its_question_stops_that_job(self):
        tid = self.held_mail()
        self.assertTrue(siri.job_asked(self.told.get_nowait()))
        siri.PENDING["soon"] = time.time() + 30
        with mock.patch.object(siri, "quick", lambda *a, **k: self.fail("a no is no request")):
            siri.handle("no", "no")
        self.assertEqual(self.store.get(tid)["status"], "cancelled")
        self.assertNotIn(tid, agent.JOBS)

    def test_the_phones_buttons_are_keyed_to_the_job_and_its_step(self):
        tid = self.held_mail()
        hold = self.store.get(tid)["payload"]["hold"]
        self.assertIsNone(siri.job_tap("a1b2c3", True))  # a turn's question: not a job's
        self.assertFalse(siri.job_tap(f"task:{tid}:0123abcd", True))
        self.assertTrue(siri.job_tap(f"task:{tid}:{hold}", True))
        self.assertEqual(self.store.get(tid)["status"], "queued")

    def test_asked_on_the_phone_it_asks_there_with_buttons(self):
        sent = []
        self.patch(siri.telegram_bot, "owner", lambda: 42)
        self.patch(siri, "PHONE", {**siri.PHONE, "ask_job": lambda chat, q, key: sent.append((chat, q, key)) or True})
        with mock.patch.object(siri, "asked_from", lambda: {"phone": 42}):
            tid = self.held_mail()
        hold = self.store.get(tid)["payload"]["hold"]
        self.assertEqual([(c, k) for c, _, k in sent], [(42, f"task:{tid}:{hold}")])
        self.assertTrue(self.told.empty())  # not said out loud as well

    def test_the_words_said_since_never_widen_who_it_writes_to(self):
        """Its words are pinned when it was asked: an address said in a later turn isn't one it may send to."""
        self.mail()
        self.patch(agent, "lately_said", lambda: "and copy boss@evil.test")
        self.model({"steps": [{"do": "open", "app": "mail"}]},
                   {"steps": [{"do": "click", "id": 1, "text": "boss@evil.test"}]})
        tid = self.queue_job("write to boss@evil.test in the mail app", "write a mail in the mail app")
        siri.run_job(self.claim(tid))
        self.assertEqual(self.app.windows["mail"].controls[0].value, "")
        self.assertEqual(self.store.get(tid)["status"], "failed")


class Lease(Jobs):
    """The screen, only for steps that need it: after a lull in your typing, never while a turn acts or the PC is
    locked, one job at a time, the focus given back after."""

    def test_keys_wait_for_a_lull_in_your_typing(self):
        pressed = []
        self.patch(siri, "press_keys", lambda keys, vetted=False: pressed.append(self.clock[0]))
        typing_till = 7.0
        self.patch(winplatform, "idle_seconds", lambda: max(0.0, self.clock[0] - typing_till))
        w = self.app.window("notepad", "notepad.exe", "Untitled - Notepad")
        w.controls = [Control("Text editor", "document", value="")]

        def go(job, r):
            r.pin = w.hwnd
            with agent.screen(r):
                return self.clock[0], self.app.front.exe
        began, front = self.run_in_job(5, go)
        self.assertGreaterEqual(began, typing_till + agent.LULL)
        self.assertEqual(front, "notepad.exe")  # its own window brought in front for it
        self.assertEqual(self.app.front.exe, "explorer.exe")  # and yours given back after

    def test_after_long_enough_it_goes_unless_youre_typing_that_moment(self):
        self.idle[0] = agent.TYPING + 0.1  # never 2 s quiet, but not typing now
        began = self.run_in_job(5, lambda job, r: self.go_with_screen(r))
        self.assertGreaterEqual(began, agent.LULL_MOST)

    def go_with_screen(self, r):
        with agent.screen(r):
            return self.clock[0]

    def test_never_while_a_turn_of_yours_acts_or_the_pc_is_locked(self):
        for name in ("plan", "locked"):
            with self.subTest(name):
                self.clock[0] = 0.0
                if name == "plan":
                    agent.plan_acting(1)
                else:
                    self.locked[0] = True
                start = self.clock[0]

                def later(secs, name=name, start=start):  # the turn's steps end, or you unlock, 20 s on
                    self.clock[0] += secs
                    if self.clock[0] - start >= 20:
                        if name == "plan" and agent.PLAN_ACTING[0]:
                            agent.plan_acting(-1)
                        self.locked[0] = False
                self.patch(agent, "_sleep", later)
                self.assertGreaterEqual(self.run_in_job(5, lambda job, r: self.go_with_screen(r)) - start, 20)

    def test_a_job_with_the_screen_lets_go_once_a_turn_acts(self):
        def go(job, r):
            with agent.screen(r):
                agent.plan_acting(1)  # her plan's steps start
                try:
                    with self.assertRaises(agent.Yielded):
                        agent.act(lambda: self.fail("pressed between a turn's steps"))
                finally:
                    agent.plan_acting(-1)
        self.run_in_job(5, go)

    def test_keys_or_typing_without_the_screen_are_refused(self):
        w = self.app.window("notepad", "notepad.exe", "Untitled - Notepad")
        w.controls = [Control("Text editor", "document", value="")]

        def go(job, r):
            r.pin = w.hwnd
            obs = agent.observe(r)
            for step in ({"do": "keys", "keys": "ctrl+s"}, {"do": "type", "text": "hi"},
                         {"do": "click", "x": 3, "y": 4}):
                with self.subTest(step["do"]), self.assertRaises(agent.Refused):
                    agent.do_one(r, step, obs, None)
        self.run_in_job(5, go)
        self.assertEqual(w.controls[0].value, "")

    def test_a_click_by_id_on_its_own_window_needs_no_screen(self):
        w = self.app.window("notepad", "notepad.exe", "Untitled - Notepad")
        w.controls = [Control("Text editor", "edit", value="")]
        self.patch(winplatform, "idle_seconds", lambda: self.fail("it waited for the screen"))

        def go(job, r):
            r.pin = w.hwnd
            obs = agent.observe(r)
            return agent.do_one(r, {"do": "click", "id": 1, "text": "Lima"}, obs, None)
        self.assertTrue(self.run_in_job(5, go, goal="type Lima in Notepad"))
        self.assertEqual((w.controls[0].value, self.app.front.exe), ("Lima", "explorer.exe"))  # yours stays in front

    def test_one_job_has_the_screen_at_a_time(self):
        entered = threading.Event()
        agent.SCREEN.acquire()
        try:
            thread = threading.Thread(target=self.run_in_job, args=(6, lambda job, r: self.enter(r, entered)),
                                      daemon=True)
            thread.start()
            self.assertFalse(entered.wait(0.4))
        finally:
            agent.SCREEN.release()
        self.assertTrue(entered.wait(5))
        thread.join(5)

    def enter(self, r, entered):
        with agent.screen(r):
            entered.set()

    def test_a_click_by_id_the_mouse_or_a_paste_would_do_takes_the_screen(self):
        """27 October's review: a list item or tab with no Invoke is clicked by the real mouse at its middle, and a box
        with no Value it may write is focused and pasted into, both landing on your window in front. Without the
        screen that's refused, as keys are; with it, it's done in its own window in front, a paste after the check
        that it isn't a command window."""
        w = self.app.window("settings", "systemsettings.exe", "Settings")
        tab, box = Control("Display", "tabitem"), Control("Find a setting", "edit", value="")
        tab.falls_back = box.falls_back = True
        w.controls = [tab, box]
        shell = []
        self.patch(siri, "not_into_shell", lambda keys=(): shell.append(self.app.front.exe))

        def go(job, r):
            r.pin = w.hwnd
            obs = agent.observe(r)
            steps = ({"do": "click", "id": 1}, {"do": "click", "id": 2, "text": "night"})
            self.assertTrue(all(agent.needs_screen(s, obs) for s in steps))
            for s in steps:
                with self.subTest(s.get("text") or "click"), self.assertRaises(agent.Refused):
                    agent.do_one(r, s, obs, None)
            self.assertEqual(self.app.done, [])
            with agent.screen(r):
                return [agent.do_one(r, s, agent.observe(r), None) for s in steps]
        self.assertEqual(self.run_in_job(5, go, goal="search night in settings"), [True, True])
        self.assertEqual(self.app.done, [("Display", "press"), ("Find a setting", "night")])
        self.assertEqual(shell, ["systemsettings.exe"])  # its own window in front for the paste
        self.assertEqual(self.app.front.exe, "explorer.exe")  # yours given back

    def test_without_the_screen_it_acts_by_a_pattern_only(self):
        """What changed between its look and its press still never reaches the mouse: ui_act is told focus_free."""
        w = self.app.window("notepad", "notepad.exe", "Untitled - Notepad")
        w.controls = [Control("Text editor", "edit", value="")]
        self.patch(siri, "not_into_shell", lambda keys=(): self.fail("your window in front was judged"))

        def go(job, r):
            r.pin = w.hwnd
            el = agent.observe(r)["items"][0]
            w.controls[0].falls_back = True  # its Value went read-only between the check and the press
            with self.assertRaisesRegex(RuntimeError, "needs the screen"):
                agent.act(agent.perform, {"do": "click", "id": 1, "text": "Lima"}, el, None)
        self.run_in_job(5, go, goal="type Lima in Notepad")
        self.assertEqual(w.controls[0].value, "")

    def test_a_plan_of_yours_never_waits_long_on_a_jobs_action(self):
        """A job's action holds ACT (a paste, an open, an Invoke on a dialog): a plan of yours starting counts itself
        at once, waits for it only while a job has the screen, and then PLAN_WAIT at most. It waited up to 10 s."""
        agent.ACT.acquire()
        try:
            began = time.monotonic()
            agent.plan_acting(1)
            self.assertLess(time.monotonic() - began, 0.3)
            self.assertTrue(agent.turn_acting())  # no job's action starts after this (act)
            agent.plan_acting(-1)
            job = agent.job_for(9, "a job")
            job.leased = True
            began = time.monotonic()
            agent.plan_acting(1)
            self.assertLess(time.monotonic() - began, agent.PLAN_WAIT + 0.4)
        finally:
            agent.ACT.release()
            agent.plan_acting(-1)

    def test_a_slow_app_isnt_pinned_till_it_comes_up_and_yours_never_is(self):
        """After opening Outlook, Word or a cold Chrome, what's in front for a while is still yours: it pinned that
        after half a second, and read and pressed your document as its own."""
        mail = self.mail()
        late = [None]

        def slow(step):  # nothing comes up in front at once
            self.app.opened.append(step)
            late[0] = self.clock[0] + 3.0
        self.patch(siri, "do_step", slow)
        sleep = agent._sleep

        def tick(secs):
            sleep(secs)
            if late[0] is not None and self.clock[0] >= late[0]:
                self.app.show("mail")
                late[0] = None
        self.patch(agent, "_sleep", tick)

        def go(job, r, comes_up):
            with agent.screen(r):
                obs = agent.observe(r)
                if not comes_up:
                    self.patch(siri, "do_step", lambda step: self.app.opened.append(step))
                agent.do_one(r, {"do": "open", "app": "mail"}, obs, None)
                return r.pin
        self.assertEqual(self.run_in_job(5, lambda job, r: go(job, r, True)), mail.hwnd)
        self.app.show("explorer")
        began = self.clock[0]
        self.assertIsNone(self.run_in_job(6, lambda job, r: go(job, r, False)))  # never yours, Program Manager
        self.assertGreaterEqual(self.clock[0] - began, agent.PIN_WAIT)

    def test_it_reads_only_its_own_window_never_yours(self):
        bank = self.app.window("bank", "chrome.exe", "My Bank - Net Banking", "mybank.com")
        bank.controls = [Control("Balance", "text", value="12,000")]
        self.app.show("bank")

        def go(job, r):
            return agent.screen_text(agent.observe(r))
        text = self.run_in_job(5, go)
        self.assertNotIn("Bank", text)
        self.assertIn("no window open yet", text)
        self.assertEqual(self.app.snapshots, 0)


class Sites(Jobs):
    """A job's page is judged by its own window's address bar, read when it acts: it was always None, so a link to a
    site you never named was typed on with no question."""

    def typing(self, exe, site):
        w = self.app.window("page", exe, "Sign in", site)
        w.controls = [Control("Your name", "edit", value="")]

        def go(job, r):
            r.pin = w.hwnd
            obs = agent.observe(r)
            r.read = False  # a page read asks for each step anyway (gate's read rule): this is the site's own rule
            el = {"name": "Your name", "role": "edit", "aid": "", "password": False, "el": w.controls[0]}
            return obs["site"], agent.gate(r, 0, {"do": "click", "id": 1, "text": "Hari"}, el)
        return self.run_in_job(5, go, goal="fill in the form on the shop page")

    def test_typing_on_a_site_you_never_named_asks(self):
        site, verdict = self.typing("chrome.exe", "phish.test")
        self.assertEqual(site, "phish.test")
        self.assertEqual(verdict, ("ask", "typing on phish.test, which you didn't ask for"))

    def test_a_page_whose_site_it_cant_read_asks_too(self):
        self.assertEqual(self.typing("firefox.exe", None)[1], ("ask", "typing on a page whose site I couldn't read"))

    def test_its_site_is_read_afresh_where_a_link_took_it(self):
        w = self.app.window("page", "chrome.exe", "Shop", "shop.example")

        def go(job, r):
            r.pin = w.hwnd
            agent.observe(r)
            w.site = "mybank-netbanking.test"  # a link on the page, followed since
            return agent.site_in(r, "chrome.exe")
        self.assertEqual(self.run_in_job(5, go), "mybank-netbanking.test")


class Stopping(Jobs):
    """Each job its own stop: "stop" said to her stops none of them, and stopping one leaves the other."""

    def test_stopping_one_job_leaves_the_other(self):
        runs = {}
        for tid in (1, 2):
            runs[tid] = self.run_in_job(tid, lambda job, r: r)
        agent.STOP.set()  # "stop" said in a voice turn, or sent from the phone
        siri.HER.stop.set()
        try:
            self.assertFalse(agent.stopped(runs[1]) or agent.stopped(runs[2]))
        finally:
            agent.STOP.clear()
            siri.HER.begin()
        self.assertTrue(agent.stop_job(1))
        self.assertTrue(agent.stopped(runs[1]))
        self.assertFalse(agent.stopped(runs[2]))

    def test_stop_task_n_stops_only_n(self):
        a, b = self.queue_job("job a"), self.queue_job("job b")
        agent.job_for(a, "job a")
        agent.job_for(b, "job b")
        plan = siri.prepare_task_steps(siri.quick(f"stop task {a}"))
        self.assertEqual(plan["say"], f"Task {a} cancelled.")
        self.assertEqual((self.store.get(a)["status"], self.store.get(b)["status"]), ("cancelled", "queued"))
        self.assertNotIn(a, agent.JOBS)
        self.assertFalse(agent.JOBS[b].cancelled())

    def test_its_own_thread_bit_is_hermes_interrupt(self):
        job = agent.job_for(9, "a job")
        job.tid = threading.get_ident()
        try:
            job.stop()
            self.assertTrue(job.cancelled())
            self.assertTrue(agent.interrupt.is_thread_interrupted(job.tid))
        finally:
            agent.interrupt.set_interrupt(False)
            job.tid = None

    def test_a_stopped_job_says_nothing(self):
        self.model(lambda: self.store.cancel(tid) and {"steps": [], "done": True, "say": "Lima."})
        tid = self.queue_job("find the capital of Peru")
        task = self.claim(tid)
        siri.run_job(task)
        self.assertTrue(self.told.empty())
        self.assertEqual(self.store.get(tid)["status"], "cancelled")


class Judge(Jobs):
    """Hermes' goal judge at the end of a go: done, blocked, or another go, at most JUDGE_MOST of them."""

    def test_continue_sends_it_on_with_hermes_line_then_done(self):
        model = self.model({"steps": [], "say": "I'm not sure yet."},
                           {"steps": [], "done": True, "say": "Lima is the capital of Peru."})
        self.verdicts = ["continue", "done"]
        tid = self.queue_job("find the capital of Peru")
        siri.run_job(self.claim(tid))
        self.assertIn("[Continuing toward your standing goal]", model.text(1))
        self.assertEqual(agent.JOBS.get(tid), None)  # over, forgotten
        self.assertEqual(self.store.get(tid)["status"], "completed")
        self.assertTrue(self.told.get_nowait().endswith("Lima is the capital of Peru."))
        self.assertEqual(len(self.judged), 2)
        self.assertIn("Goal:\nfind the capital of Peru", self.judged[0][1]["content"])

    def test_blocked_ends_it_and_says_so(self):
        self.model({"steps": [], "say": "There's a sign-in in the way."})
        self.verdicts = ["blocked"]
        tid = self.queue_job("find my last order on the shop site")
        siri.run_job(self.claim(tid))
        self.assertEqual(self.store.get(tid)["status"], "failed")
        self.assertTrue(self.told.get_nowait().startswith(f"Task {tid} failed:"))
        self.assertIn("Status: blocked", siri.take_job_news())

    def test_it_goes_on_at_most_judge_most_times(self):
        self.model(*[{"steps": [], "say": "Still looking."}] * 6)
        self.verdicts = ["continue"] * 6
        tid = self.queue_job("find the capital of Peru")
        siri.run_job(self.claim(tid))
        self.assertEqual(len(self.judged), agent.JUDGE_MOST)
        self.assertEqual(self.store.get(tid)["status"], "failed")

    def test_a_held_step_or_a_stop_isnt_judged(self):
        Mail.held_mail(self)
        self.assertEqual(self.judged, [])


class Learning(Jobs):
    """A job's verified run is learned only as a turn's is: plainly asked for, and nothing steering it."""

    def toggled(self, named):
        w = self.app.window("settings", "systemsettings.exe", "Settings")
        w.controls = [Control("Night light", "checkbox", state="off")]
        self.model({"steps": [{"do": "open", "app": "settings"}]},
                   {"steps": [{"do": "click", "id": 1, "state": "on"}], "done": True,
                    "expect": {"has": "Night light", "state": "on"}, "say": "Night light's on."})
        tid = self.queue_job("turn on night light in settings", named=named)
        siri.run_job(self.claim(tid))
        return w

    def test_an_unnamed_job_is_never_learned(self):
        w = self.toggled(False)
        self.assertEqual(w.controls[0].state, "on")
        self.assertEqual(self.learned(), {})

    def test_a_named_one_done_and_seen_to_be_is(self):
        self.toggled(True)
        self.assertEqual(list(self.learned()), ["turn-on-night-light-in-settings"])

    def test_a_tainted_one_is_never(self):
        def go(job, r):
            r.tainted, r.named = True, True
            return agent.unlearnable(r)
        self.assertIn("orders", self.run_in_job(5, go))


class Alongside(Jobs):
    """A job never holds the turn: no busy, no RUNNING, and a voice turn goes on while it waits on the model."""

    def test_a_voice_turn_runs_while_a_job_waits_on_the_model(self):
        asked, release = threading.Event(), threading.Event()

        def slow_model(messages, **kw):
            asked.set()
            release.wait(10)
            return json.dumps({"steps": [], "done": True, "say": "Lima."}), \
                siri.parse_plan(json.dumps({"steps": [], "done": True, "say": "Lima."})), {}, "test"
        self.patch(siri, "ask_plan", slow_model)
        tid = self.queue_job("find the capital of Peru")
        task = self.claim(tid)
        worker = threading.Thread(target=siri.run_job, args=(task,), daemon=True)
        worker.start()
        try:
            self.assertTrue(asked.wait(5))
            self.assertFalse(agent.RUNNING.is_set())  # her turns stay as they are: not only "stop" heard
            self.assertEqual(agent.background_jobs(), 1)
            self.assertEqual(siri.handle("what time is it", "what time is it"), True)
            self.assertTrue(self.said[-1].startswith("It's "), self.said)
        finally:
            release.set()
            worker.join(5)
        self.assertEqual((agent.background_jobs(), self.store.get(tid)["status"]), (0, "completed"))

    def test_what_are_you_working_on_comes_from_whats_going_on(self):
        self.assertEqual(siri.quick("what are you working on")["say"], "Nothing right now.")
        siri.show_task({"id": 7, "kind": "agent", "description": "Find the capital of Peru"}, "running")
        self.assertEqual(siri.quick("what are you working on")["say"],
                         "Task 7, Find the capital of Peru, working on it.")


class Calls(Jobs):
    """Its model calls: the voice's model, one try at a time, after a turn's thinking, never costing the voice."""

    def setUp(self):
        super().setUp()
        self.patch(siri, "ask_alone", ORIGINAL_ASK_ALONE)
        self.calls = []
        self.patch(siri.opencode, "chat", self.chat)
        get = siri.settings.get
        self.patch(siri.settings, "get", lambda key, *a, **k: "anthropic/claude-haiku-4-5" if key == "llm_model"
                   else get(key, *a, **k))

    def chat(self, key, messages, **kw):
        self.calls.append(kw.get("model"))
        return '{"verdict": "done"}', {}, kw.get("model")

    def test_it_waits_while_a_turn_thinks(self):
        siri.THINKING.set()
        got = []
        thread = threading.Thread(target=lambda: got.append(siri.ask_alone([{"role": "user", "content": "x"}])),
                                  daemon=True)
        try:
            thread.start()
            time.sleep(0.3)
            self.assertEqual(self.calls, [])
        finally:
            siri.THINKING.clear()
        thread.join(5)
        self.assertEqual(self.calls, ["anthropic/claude-haiku-4-5"])  # the voice's own model, once: never hedged

    def test_a_429_puts_nothing_on_cooldown(self):
        def busy(key, messages, **kw):
            raise RuntimeError("opencode 429 too many requests")
        self.patch(siri.opencode, "chat", busy)
        with mock.patch.dict(siri.COOLDOWN, clear=True):
            with self.assertRaises(RuntimeError):
                siri.ask_alone([{"role": "user", "content": "x"}])
            self.assertEqual(siri.COOLDOWN, {})

    def test_it_backs_off_a_model_told_to_wait(self):
        with mock.patch.dict(siri.COOLDOWN, {"anthropic/claude-haiku-4-5": time.time() + 0.3}):
            began = time.time()
            siri.ask_alone([{"role": "user", "content": "x"}])
        self.assertGreaterEqual(time.time() - began, 0.25)


class Asking(Jobs):
    """How a voice request becomes a job: in so many words, the planner's background step, or a task in an app
    still going when her turn stops waiting."""

    def test_in_the_background_makes_the_task_a_job(self):
        plan = {"steps": [{"do": "open", "app": "Notepad"}, {"do": "screen", "task": "type a poem in Notepad"}],
                "say": "Okay."}
        for words in ("type a poem in notepad in the background", "type a poem in notepad, let me know when it's done",
                      "type a poem in notepad while I make tea"):
            with self.subTest(words):
                got = siri.backgrounded(plan, words)
                self.assertEqual(got["steps"], [{"do": "background", "goal": "type a poem in Notepad"}])
        self.assertIs(siri.backgrounded(plan, "type a poem in notepad"), plan)

    def test_the_planners_background_step_is_a_job_with_your_words_pinned(self):
        said, name = agent.SAID.set("find the cheapest flight to Goa and note it, in the background"), \
            agent.NAMED.set(True)
        try:
            plan = siri.prepare_task_steps({"steps": [{"do": "background", "goal": "find the cheapest flight to Goa "
                                                       "and note it"}], "say": "Sure."})
        finally:
            agent.SAID.reset(said)
            agent.NAMED.reset(name)
        (queued,) = plan["steps"]
        row = self.store.get(queued["id"])
        self.assertEqual((row["kind"], row["status"]), ("agent", "queued"))
        self.assertEqual(row["payload"]["words"], "find the cheapest flight to Goa and note it, in the background")
        self.assertTrue(row["payload"]["named"])
        self.assertEqual(plan["say"], f"I'll do that in the background as task {queued['id']}, and tell you when "
                                      f"it's done.")

    def test_a_goal_is_cut_and_needs_saying(self):
        payload = siri.background_payload({"kind": "agent", "goal": "x " * 400, "pin": True})
        self.assertEqual((len(payload["goal"]), payload["pin"]), (siri.GOAL_MOST, None))
        with self.assertRaisesRegex(RuntimeError, "didn't catch"):
            siri.background_payload({"kind": "agent", "goal": "  "})

    def test_a_job_planned_after_a_read_runs_read(self):
        """"Read my latest email and, in the background, reply to it": think marks the task step read, and the job
        keeps it, so each click and typing asks first as it would in a turn. It ran unread till 27 October."""
        plan = {"steps": [{"do": "screen", "task": "reply to Asha in the mail app", "read": True}], "say": ""}
        got = siri.backgrounded(plan, "reply to it in the background")
        self.assertEqual(got["steps"], [{"do": "background", "goal": "reply to Asha in the mail app", "read": True}])
        self.assertIn("background", siri.MARKED)  # think marks the planner's own background step read too
        self.assertNotIn("read", siri._known([{"do": "background", "goal": "x", "read": True}])[0])  # only she sets it
        said, name = agent.SAID.set(WORDS), agent.NAMED.set(True)
        try:
            (queued,) = siri.prepare_task_steps(got)["steps"]
        finally:
            agent.SAID.reset(said)
            agent.NAMED.reset(name)
        self.assertTrue(self.store.get(queued["id"])["payload"]["read"])
        self.mail()
        self.model({"steps": [{"do": "open", "app": "mail"}]},
                   lambda: {"steps": [{"do": "click", "id": 1, "text": "ravi@example.com"}]})
        siri.run_job(self.claim(queued["id"]))
        self.assertEqual(self.store.get(queued["id"])["status"], "waiting_approval")
        self.assertEqual(self.app.windows["mail"].controls[0].value, "")  # asked before typing, not after
        self.assertIsInstance(self.told.get_nowait(), siri.JobAsk)

    def test_a_task_still_going_when_her_turn_stops_waiting_is_handed_over(self):
        release = threading.Event()

        def going(step, notify, before, alone):
            r = agent.start(goal=step["task"])
            r.hwnd, r.notes = 77, ["opened Notepad", 'typed "Roses are red"']
            while not agent.stopped(r) and not release.is_set():
                time.sleep(0.02)
            return "", []
        self.patch(agent, "dispatch", going)
        self.patch(siri, "SCREEN_WAIT", 0.3)
        try:
            siri.run_plan({"steps": [{"do": "screen", "task": "type a poem in Notepad"}], "say": ""}, None)
        finally:
            release.set()
        (row,) = self.store.list(active=True)
        self.assertEqual((row["kind"], row["payload"]["pin"]), ("agent", 77))
        self.assertIn('typed "Roses are red"', row["payload"]["hints"])
        self.assertIn(f"in the background as task {row['id']}", self.said[-1])


class Restart(Jobs):
    """A job Jev stopped in the middle of is asked about again at start, keyed by it, by voice or on the phone."""

    def test_it_asks_again_and_only_that_yes_starts_it(self):
        store = StopsWorker(self.store.path)
        self.patch(siri, "TASK_STORE", store)
        tid = store.create("Write to Ravi", "agent", {"goal": "write to Ravi", "approved": True})
        store.claim_due()  # running when Jev stopped
        worker = threading.Thread(target=siri.task_worker, daemon=True)
        worker.start()
        try:
            asked = self.told.get(timeout=5)
        finally:
            store.stopped = True
            tasks.WAKE.set()
            worker.join(5)
        self.assertIsInstance(asked, siri.JobAsk)
        self.assertEqual(asked, f"Task {tid} asks: I'd stopped in the middle of Write to Ravi. Should I start it "
                                f"again?")
        self.assertEqual(asked.hold, store.get(tid)["payload"]["hold"])
        self.assertFalse(siri.job_tap(f"task:{tid + 1}:{asked.hold}", True))  # another job's key
        self.assertTrue(siri.job_asked(asked))
        self.assertTrue(siri.said_yes("yes, start it again", siri.PENDING["plan"]))
        self.assertTrue(siri.job_tap(f"task:{tid}:{asked.hold}", True))
        self.assertEqual(store.get(tid)["status"], "queued")


class Store(unittest.TestCase):
    """tasks.py for jobs: the agent kind changes the PC, a progress column, and approvals keyed by step."""

    def setUp(self):
        self.path = os.path.join(tempfile.mkdtemp(prefix="heyjev-jobs-"), "tasks.db")

    def test_a_restart_asks_again_before_a_job_goes_on(self):
        store = tasks.Store(self.path)
        tid = store.create("Write to Ravi", "agent", {"goal": "write to Ravi", "approved": True, "hold": "ab12"})
        store.claim_due()
        self.assertEqual(store.recover(), [tid])
        row = store.get(tid)
        self.assertEqual(row["status"], "waiting_approval")
        self.assertNotIn("approved", row["payload"])
        # its held step was in memory, gone with it: it starts again, asked about with a key of its own
        self.assertNotIn(row["payload"]["hold"], ("", "ab12"))
        self.assertFalse(store.approve(tid, "ab12"))
        self.assertIn("this job was running", row["error"])

    def test_one_due_while_the_pc_was_off_asks_again_too(self):
        self.assertIn("agent", tasks.CHANGES_PC)

    def test_an_old_tasks_db_gets_the_progress_column(self):
        con = sqlite3.connect(self.path)
        con.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY AUTOINCREMENT, description TEXT NOT NULL, kind TEXT "
                    "NOT NULL, payload TEXT NOT NULL, status TEXT NOT NULL, created REAL NOT NULL, due REAL NOT NULL, "
                    "repeat_spec TEXT, result TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '', started REAL, "
                    "finished REAL, updated REAL NOT NULL)")
        con.execute("INSERT INTO tasks (description,kind,payload,status,created,due,updated) VALUES "
                    "('old','reminder','{}','completed',0,0,0)")
        con.commit()
        con.close()
        store = tasks.Store(self.path)
        self.assertIsNone(store.get(1)["progress"])
        tid = store.create("A job", "agent", {"goal": "x"})
        self.assertFalse(store.update_progress(tid, "Part 1 of 3"))  # only while it runs
        store.claim_due()
        self.assertTrue(store.update_progress(tid, "Part 1 of 3"))
        self.assertEqual(store.get(tid)["progress"], "Part 1 of 3")

    def test_an_approval_for_job_a_cant_release_job_b(self):
        store = tasks.Store(self.path)
        a = store.create("A", "agent", {"goal": "a"})
        b = store.create("B", "agent", {"goal": "b"})
        for tid, hold in ((a, "aaaa"), (b, "bbbb")):
            store.claim_due()
            store.wait_for_approval(tid, "Should I send it?", hold=hold)
        self.assertFalse(store.approve(b, "aaaa"))
        self.assertFalse(store.approve(a, "bbbb"))
        self.assertEqual({store.get(a)["status"], store.get(b)["status"]}, {"waiting_approval"})
        self.assertTrue(store.approve(a, "aaaa"))
        self.assertEqual((store.get(a)["status"], store.get(b)["status"]), ("queued", "waiting_approval"))
        self.assertTrue(store.get(a)["payload"]["approved"])
        self.assertNotIn("approved", store.get(b)["payload"])

    def test_and_in_memory_neither(self):
        a, b = agent.Job(1, "a"), agent.Job(2, "b")
        agent.JOB_HELD[1] = {"id": "aaaa"}
        try:
            self.assertIsNone(agent.resume_job(b, "aaaa"))  # B has nothing held, whatever id it's given
            self.assertIsNone(agent.resume_job(a, "bbbb"))
            self.assertIn(1, agent.JOB_HELD)
        finally:
            agent.JOB_HELD.clear()


if __name__ == "__main__":
    unittest.main()
