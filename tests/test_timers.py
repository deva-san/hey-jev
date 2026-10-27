"""Timers, reminders and schedules: what she sets, cancels and reports, and when the durable reminders run."""
import datetime as dt
import os
import queue
import tempfile
import threading
import time
import unittest
from unittest import mock

from tests.support import installer, siri

import tasks

WED_7PM = dt.datetime(2026, 10, 7, 19, 0).timestamp()  # a Wednesday evening in the user's local time


def at(day, hour, minute=0):
    return dt.datetime(2026, 10, day, hour, minute).timestamp()


class Durations(unittest.TestCase):
    """P1: common phrasings were refused or silently wrong."""

    def test_spoken_durations(self):
        for said, secs in (("set a timer for a quarter of an hour", 900), ("timer for half a minute", 30),
                           ("set a timer for 1 minute 30", 90), ("set a timer for 1 hour 30", 5400),
                           ("set a timer for one and a half hours", 5400), ("two and a half minutes", 150),
                           ("seventy minutes", 4200), ("an hour and a quarter", 4500),
                           ("three quarters of an hour", 2700),
                           # still as before
                           ("set a timer for 5 minutes", 300), ("set a timer for an hour and a half", 5400),
                           ("set a timer for twenty five minutes", 1500), ("a minute and a half", 90),
                           ("set a timer for 1 minute 30 seconds", 90), ("half an hour", 1800)):
            self.assertEqual(siri.parse_duration(said), secs, said)

    def test_reminder_counts_from_in_not_from_every_duration(self):
        plan = siri.quick("remind me to stretch for 10 minutes in 1 hour")
        step = plan["steps"][0]
        self.assertEqual(step["when"], "in 3600 seconds")
        self.assertEqual(step["task"]["text"], "stretch for 10 minutes")

    def test_two_durations_count_from_in(self):
        """R3: parse_duration still added up every duration in the sentence, so "stretch for 10 minutes in 20 minutes"
        came out as 30 minutes. With an "in" or "after", that is when; without one, all of it, as before."""
        for said, secs in (("remind me to stretch for 10 minutes in 1 hour", 3600),
                           ("remind me to stretch for 10 minutes in 20 minutes", 1200),
                           ("remind me after an hour and a half to eat", 5400), ("set a timer for 1 hour 30", 5400)):
            self.assertEqual(siri.parse_duration(said), secs, said)
        self.assertEqual(siri.parse_reminder("remind me to stretch for 10 minutes in 20 minutes"),
                         "stretch for 10 minutes")

    def test_reminder_in_still_works(self):
        for said in ("remind me in 5 min to call mum", "remind me to call mum in 5 minutes"):
            step = siri.quick(said)["steps"][0]
            self.assertEqual((step["when"], step["task"]["text"]), ("in 300 seconds", "call mum"), said)

    def test_every_or_daily_in_what_to_do_is_still_once(self):
        for said, secs, text in (("remind me in 10 minutes to water every plant", 600, "water every plant"),
                                 ("remind me in 5 minutes to join the daily standup", 300, "join the daily standup")):
            step = siri.quick(said)["steps"][0]
            self.assertEqual((step["when"], step["repeat"], step["task"]["text"]), (f"in {secs} seconds", "", text), said)
        for said in ("remind me every twenty minutes to look away", "remind me in 10 minutes and every hour after to "
                     "drink water"):  # these repeat: never a one-off
            plan = siri.quick(said)
            self.assertFalse(plan and any(s.get("do") == "schedule" and not s.get("repeat") for s in plan["steps"]),
                             said)

    def test_one_and_half_without_a(self):
        """Said in India without the "a": "one and half hour" was refused."""
        for said, secs in (("set a timer for one and half hour", 5400), ("set a timer for one hour and half", 5400),
                           ("two and half minutes", 150)):
            self.assertEqual(siri.parse_duration(said), secs, said)
        self.assertEqual(tasks.normalize_schedule("in one and half hour", None, WED_7PM)[0], WED_7PM + 5400)


class Schedules(unittest.TestCase):
    """P2: normalize_schedule read 'tonight at 8' as 8 tomorrow morning and refused everyday phrasings."""

    def due(self, when="", repeat=None):
        return tasks.normalize_schedule(when, repeat, WED_7PM)

    def test_evening_words_mean_pm(self):
        for when in ("tonight at 8", "this evening at 8", "at 8 tonight"):
            self.assertEqual(self.due(when)[0], at(7, 20), when)
        self.assertEqual(self.due("tomorrow evening at 7")[0], at(8, 19))
        self.assertEqual(self.due("tomorrow at 6 PM")[0], at(8, 18))  # unchanged
        self.assertEqual(self.due("this morning at 9")[0], at(8, 9))  # gone already: the next one

    def test_spoken_relative_times(self):
        for when, secs in (("in twenty minutes", 1200), ("in an hour", 3600), ("in half an hour", 1800),
                           ("in a minute", 60), ("in twenty five minutes", 1500), ("in 2 hours", 7200)):
            self.assertEqual(self.due(when)[0], WED_7PM + secs, when)

    def test_midnight_and_noon(self):
        self.assertEqual(self.due("at midnight")[0], at(8, 0))
        self.assertEqual(self.due("tomorrow at noon")[0], at(8, 12))
        due, spec = self.due(repeat="every midnight")
        self.assertEqual((due, spec), (at(8, 0), {"kind": "daily", "hour": 0, "minute": 0}))
        self.assertEqual(self.due(repeat="every day at midnight")[1], {"kind": "daily", "hour": 0, "minute": 0})

    def test_iso_still_works(self):
        self.assertEqual(self.due("2026-10-07T18:00:00")[0], at(7, 18))

    def test_tonight_at_12_is_midnight(self):
        """'Remind me tonight at 12 to wish Rahul' is local now, and it was set for noon the next day."""
        for when, due in (("tonight at 12", at(8, 0)), ("tonight at 12:30", at(8, 0, 30)), ("at 12 tonight", at(8, 0)),
                          ("tonight at 1", at(8, 1)), ("tomorrow night at 12", at(9, 0)),
                          ("tonight at 11", at(7, 23)), ("tomorrow at 12", at(8, 12))):  # the last two as before
            self.assertEqual(self.due(when)[0], due, when)
        step = siri.quick("remind me tonight at 12 to wish rahul")["steps"][0]
        self.assertEqual(self.due(step["when"])[0], at(8, 0))

    def test_unknown_repeats_are_refused_not_daily(self):
        """'every <anything> at 9' became daily: 'every 2 weeks at 9' was every day at 2 AM."""
        for repeat in ("every month on the 5th at 9", "every other day at 9",
                       "every weekend at 10", "every 2 weeks at 9", "every year at 9"):
            with self.assertRaises(ValueError, msg=repeat):
                self.due(repeat=repeat)
        for repeat in ("every weekday at 9", "weekdays at 9 am", "monday to friday at 9"):  # Hermes' cron 1-5
            self.assertEqual(self.due(repeat=repeat)[1], {"kind": "weekdays", "hour": 9, "minute": 0}, repeat)
        for repeat, hour in (("every morning at 8", 8), ("every night at 10", 22), ("everyday at 9", 9)):
            self.assertEqual(self.due(repeat=repeat)[1], {"kind": "daily", "hour": hour, "minute": 0}, repeat)

    def test_weekdays_skip_the_weekend(self):
        import datetime as dt
        friday_10am = dt.datetime(2026, 10, 9, 10, 0).timestamp()
        nxt = dt.datetime.fromtimestamp(siri.tasking.next_due(friday_10am, {"kind": "weekdays", "hour": 9, "minute": 0},
                                                              friday_10am))
        self.assertEqual((nxt.weekday(), nxt.hour), (0, 9))  # Monday at 9, not Saturday

    def test_relative_times_are_never_a_clock(self):
        """'in 15 mins' was 3 PM, 'after 10 minutes' 10 AM and 'at ten thirty' 10:00."""
        for when, secs in (("in 15 mins", 900), ("in 2 hrs", 7200), ("after 10 minutes", 600), ("in 45 min", 2700)):
            self.assertEqual(self.due(when)[0], WED_7PM + secs, when)
        self.assertEqual(self.due("at ten thirty")[0], at(8, 10, 30))
        self.assertEqual(self.due("after 8 pm")[0], at(7, 20))  # a clock, as before
        with self.assertRaises(ValueError):
            self.due("in 5 fortnights")  # not 5 AM

    def test_reminder_tonight_is_local(self):
        plan = siri.quick("remind me tonight at 8 to call mum")
        step = plan["steps"][0]
        self.assertEqual((step["do"], step["task"]["text"]), ("schedule", "call mum"))
        self.assertEqual(self.due(step["when"])[0], at(7, 20))


class ClockTimes(unittest.TestCase):
    """22 October, with Haiku's thinking off: "remind me to call Mum at 6 pm" said at 2:40 pm was planned as a timer of
    12,600 s (20 minutes late) or of 0; and "remind me at 6 to call Mum" in the afternoon was for 6 the next morning."""
    T240PM = dt.datetime(2026, 10, 22, 14, 40).timestamp()

    def test_the_time_said_last_is_a_reminder_with_no_model(self):
        for said, when in (("remind me to call mum at 6 pm", "at 6 pm"), ("Remind me to call Mum tomorrow at 9.",
                                                                          "tomorrow at 9"),
                           ("remind me to wish rahul tonight at 12", "tonight at 12")):
            step = siri.quick(said)["steps"][0]
            self.assertEqual((step["do"], step["when"], step["task"]["kind"]), ("schedule", when, "reminder"), said)
        self.assertEqual(siri.quick("remind me to call mum at 6 pm")["steps"][0]["task"]["text"], "call mum")
        self.assertEqual(siri.quick("remind me to drink water every day at 9")["steps"][0]["repeat"],
                         "every day at 9")  # a repeat, as before

    def test_a_bare_hour_is_the_one_still_to_come(self):
        four_am, eight_pm = at(22, 4), at(22, 20)
        for now, when, got in ((self.T240PM, "at 6", "at 6 pm"), (four_am, "at 6", "at 6 am"),
                               (eight_pm, "at 6", "at 6 am"), (self.T240PM, "at 6:30", "at 6:30 pm"),
                               (self.T240PM, "at 3", "at 3 pm"), (self.T240PM, "today at 9", "today at 9 pm")):
            self.assertEqual(siri.upcoming(when, now), got, (when, now))
        for when in ("at 6 pm", "tonight at 8", "tomorrow at 9", "at 14", "at noon", "at 12"):
            self.assertEqual(siri.upcoming(when, self.T240PM), when)
        # the model's own sum, near enough, picks which 6
        self.assertEqual(siri.upcoming("at 6", self.T240PM, near=self.T240PM + 12600), "at 6 pm")
        self.assertEqual(siri.upcoming("at 6", self.T240PM, near=self.T240PM + 55000), "at 6 am")
        with mock.patch.object(siri.time, "time", return_value=self.T240PM):
            step = siri.quick("remind me at 6 to call mum")["steps"][0]
        self.assertEqual(tasks.normalize_schedule(step["when"], "", self.T240PM)[0], at(22, 18))

    def test_a_timer_for_a_time_of_day_is_a_reminder_then(self):
        with mock.patch.object(siri.time, "time", return_value=self.T240PM):
            for said, timer, when, text in (
                    ("remind me to call mum at 6 pm, Jev", {"seconds": 12600, "label": "Call Mum"}, "at 6 pm",
                     "call Mum"),
                    ("can you remind me to call mum at 6", {"seconds": 0, "label": "Call Mum"}, "at 6 pm", "call Mum"),
                    ("wake me up at 7 a.m.", {"seconds": 59000, "label": "Wake up"}, "at 7 am", "wake up"),
                    ("set an alarm for 6:30 am", {"seconds": 57000}, "at 6:30 am", "your reminder"),
                    ("And I need to go outside at uh five pm. Remind me okay", {"seconds": 8000, "label": "Go outside"},
                     "at 5 pm", "go outside")):
                step = siri.clock_timer({"do": "timer", **timer}, said)
                self.assertEqual((step["do"], step["when"], step["task"]), ("schedule", when,
                                                                           {"kind": "reminder", "text": text}), said)
        self.assertEqual(tasks.normalize_schedule("at 5 pm", "", self.T240PM)[0], at(22, 17))
        for said, step in (("set a timer for 20 minutes", {"do": "timer", "seconds": 1200}),
                           ("remind me to stretch for 10 minutes in 1 hour", {"do": "timer", "seconds": 3600}),
                           ("open notepad at 6 pm", {"do": "open", "app": "Notepad"})):
            self.assertEqual(siri.clock_timer(dict(step), said), step, said)


class Repeating(unittest.TestCase):
    """P3: 'remind me every hour to drink water' was lost, and 'every one hour' made a one-off reminder."""

    def test_every_hour(self):
        for repeat in ("every hour", "hourly", "every one hour", "every 1 hour"):
            self.assertEqual(tasks.normalize_schedule("", repeat, WED_7PM)[1], {"kind": "interval", "seconds": 3600},
                             repeat)
        self.assertEqual(tasks.normalize_schedule("", "every half an hour", WED_7PM)[1],
                         {"kind": "interval", "seconds": 1800})
        with self.assertRaises(ValueError):
            tasks.normalize_schedule("", "every second", WED_7PM)  # under a minute: refused, as before

    def test_said_locally_and_repeats(self):
        for said in ("remind me every hour to drink water", "remind me every one hour to drink water",
                     "Remind me every one hour, to drink water.", "remind me to drink water every hour",
                     "every hour remind me to drink water", "hourly remind me to drink water"):
            plan = siri.quick(said)
            self.assertIsNotNone(plan, said)
            step = plan["steps"][0]
            self.assertEqual(step["do"], "schedule", said)
            self.assertEqual(step["task"], {"kind": "reminder", "text": "drink water"}, said)
            self.assertEqual(tasks.normalize_schedule(step["when"], step["repeat"], WED_7PM)[1],
                             {"kind": "interval", "seconds": 3600}, said)

    def test_daily_reminder_said_first(self):
        step = siri.quick("remind me every day at 9 to take my tablets")["steps"][0]
        self.assertEqual(step["task"]["text"], "take my tablets")
        self.assertEqual(tasks.normalize_schedule(step["when"], step["repeat"], WED_7PM)[1],
                         {"kind": "daily", "hour": 9, "minute": 0})
        step = siri.quick("every day at 9 remind me to take my tablets")["steps"][0]  # as before
        self.assertEqual(step["repeat"], "every day at 9")

    def test_repeat_said_first_with_a_comma(self):
        """Nemotron puts the comma in: "Every hour, remind me to drink water." went to the model."""
        for said in ("Every hour, remind me to drink water.", "Every day at 9, remind me to take my tablets."):
            step = siri.quick(said)["steps"][0]
            self.assertEqual((step["do"], step["task"]["kind"]), ("schedule", "reminder"), said)
            self.assertIsNotNone(tasks.normalize_schedule(step["when"], step["repeat"], WED_7PM)[1], said)


class WithStore(unittest.TestCase):
    """A fresh task database and no timers for each test."""

    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="heyjev-timers-")
        self.store = tasks.Store(os.path.join(self.dir, "tasks.db"))
        patcher = mock.patch.object(siri, "TASK_STORE", self.store)
        patcher.start()
        self.addCleanup(patcher.stop)
        with siri.TIMERS_LOCK:
            siri.TIMERS.clear()
        self.addCleanup(siri.TIMERS.clear)
        reminders = getattr(siri, "_reminders_read", None)
        if reminders:
            reminders[0] = 0.0  # read the reminders again, from this test's store

    def reminder(self, text, due, repeat=None):
        return self.store.create(f"Remind me to {text}", "reminder", {"text": text}, due=due, repeat=repeat)

    def run_plan(self, plan):
        plan = siri.prepare_task_steps(plan)
        for step in plan["steps"]:
            siri.do_step(step)
        return plan


class CancelTimer(WithStore):
    """A13: 'cancel the 5 minute timer' set a new timer. A14, A26, A42: 'cancel the timer' also cancelled every
    reminder, daily ones too, while she said there was no timer running."""

    def test_named_timer_is_cancelled_not_set(self):
        five, ten = siri.add_timer(300), siri.add_timer(600)
        for said in ("cancel the 5 minute timer", "stop my 5 minute timer", "delete the five minute timer"):
            plan = siri.quick(said)
            self.assertEqual([s["do"] for s in plan["steps"]], ["cancel_timers"], said)
        siri.do_step(siri.quick("cancel the 5 minute timer")["steps"][0])
        self.assertEqual(siri.TIMERS, [ten])
        self.assertNotIn(five, siri.TIMERS)

    def test_time_left_on_a_named_timer(self):
        siri.add_timer(300)
        siri.add_timer(600)
        plan = siri.quick("how much time is left on the 10 minute timer")
        self.assertEqual(plan["steps"], [])
        self.assertRegex(plan["say"], r"(?:9|10) minutes")
        self.assertEqual(len(siri.TIMERS), 2)

    def test_time_left_on_a_labelled_timer(self):
        """The model's timers have a label: "on my tea timer" answered with the soonest timer instead."""
        siri.add_timer(300)
        siri.add_timer(600, "Tea")
        self.assertRegex(siri.quick("how long is left on my tea timer")["say"], r"(?:9|10) minutes")

    def test_more_than_a_timer_goes_to_the_model(self):
        """The duration slot took any words, so these cancelled the timers only and said it was done."""
        siri.add_timer(300)
        self.reminder("call mum", time.time() + 600)
        for said in ("stop the music and the timer", "clear my reminders and timers", "cancel the timer and the reminder"):
            self.assertIsNone(siri.quick(said), said)
        self.assertEqual(siri.quick("cancel the one and a half hour timer")["steps"][0]["seconds"], 5400)

    def test_stop_reminding_me(self):
        """The model's cancel_timers doesn't touch reminders now, so this one has to be local."""
        water = self.reminder("drink water", time.time() + 1800, {"kind": "interval", "seconds": 3600})
        mum = self.reminder("call mum", time.time() + 600)
        for said in ("stop reminding me to drink water", "Stop reminding me to drink water anymore."):
            plan = siri.quick(said)
            self.assertIn("drink water", plan["say"], said)
            self.assertNotIn("mum", plan["say"], said)
        self.run_plan(plan["confirm"])
        self.assertEqual(self.store.get(water)["status"], "cancelled")
        self.assertEqual(self.store.get(mum)["status"], "queued")

    def test_plain_cancel_still_cancels_every_timer(self):
        siri.add_timer(300)
        siri.add_timer(600)
        plan = siri.quick("cancel the timer")
        self.assertIn(plan["say"], siri.REPLIES["timers_cancel"])
        siri.do_step(plan["steps"][0])
        self.assertEqual(siri.TIMERS, [])

    def test_cancel_timer_leaves_reminders(self):
        daily = self.reminder("take my tablets", time.time() + 50000, {"kind": "daily", "hour": 9, "minute": 0})
        tomorrow = self.reminder("call the bank", time.time() + 80000)
        soon = self.reminder("check the oven", time.time() + 600)
        siri.add_timer(300)
        for said in ("cancel the timer", "stop the timer", "cancel the alarm"):
            self.run_plan(siri.quick(said))
            for task_id in (daily, tomorrow, soon):
                self.assertEqual(self.store.get(task_id)["status"], "queued", said)
        self.assertEqual(siri.TIMERS, [])
        self.assertEqual(siri.quick("cancel the timer")["say"], "There's no timer running.")

    def test_model_cancel_timers_leaves_reminders(self):
        task_id = self.reminder("call mum", time.time() + 600)
        siri.do_step({"do": "cancel_timers"})
        self.assertEqual(self.store.get(task_id)["status"], "queued")

    def test_cancel_reminders_asks_and_names_them(self):
        daily = self.reminder("take my tablets", time.time() + 50000, {"kind": "daily", "hour": 9, "minute": 0})
        once = self.reminder("call the bank", time.time() + 80000)
        plan = siri.quick("cancel my reminders")
        self.assertEqual(plan["steps"], [])
        self.assertTrue(plan["say"].endswith("?"))
        self.assertIn("take my tablets", plan["say"])
        self.assertIn("call the bank", plan["say"])
        self.assertEqual(self.store.get(daily)["status"], "queued")  # nothing yet, she asked
        done = self.run_plan(plan["confirm"])  # the yes
        self.assertEqual(self.store.get(daily)["status"], "cancelled")
        self.assertEqual(self.store.get(once)["status"], "cancelled")
        self.assertIn(f"Task {daily} cancelled", done["say"])

    def test_cancel_a_named_reminder(self):
        mum = self.reminder("call mum", time.time() + 600)
        bank = self.reminder("call the bank", time.time() + 80000)
        plan = siri.quick("cancel my reminder to call mum")
        self.assertIn("call mum", plan["say"])
        self.assertNotIn("bank", plan["say"])
        self.run_plan(plan["confirm"])
        self.assertEqual(self.store.get(mum)["status"], "cancelled")
        self.assertEqual(self.store.get(bank)["status"], "queued")

    def test_no_reminders(self):
        plan = siri.quick("cancel my reminders")
        self.assertEqual(plan["steps"], [])
        self.assertNotIn("confirm", plan)


class RemindersCountDown(WithStore):
    """A42: a reminder due in 10 minutes was invisible to 'how long is left?' and the window."""

    def test_reminder_due_soon_shows_with_the_timers(self):
        self.reminder("call mum", time.time() + 600)
        self.reminder("call the bank", time.time() + 3 * 86400)  # days away: a schedule, not a countdown
        self.reminder("drink water", time.time() + 1800, {"kind": "interval", "seconds": 3600})  # repeats
        siri.add_timer(60, "Tea")
        names = [name for name, _ in siri.timer_snapshot()]
        self.assertEqual(names, ["Tea", "Call mum"])
        self.assertAlmostEqual(siri.timer_snapshot()[1][1], 600, delta=5)

    def test_how_long_is_left_sees_a_reminder(self):
        self.reminder("call mum", time.time() + 600)
        plan = siri.quick("how long is left")
        self.assertNotIn(plan["say"], siri.REPLIES["timer_none"])
        self.assertRegex(plan["say"], r"(?:9|10) minutes")

    def test_broken_store_never_breaks_the_window(self):
        with mock.patch.object(self.store, "list", side_effect=OSError("disk gone")):
            siri.add_timer(60)
            self.assertEqual(len(siri.timer_snapshot()), 1)


class StopsWorker(tasks.Store):
    """A store whose claim_due ends task_worker's loop once the test is over."""
    stopped = False

    def claim_due(self, *args, **kwargs):
        if self.stopped:
            raise SystemExit
        return super().claim_due(*args, **kwargs)


class Worker(unittest.TestCase):
    """A44: a reminder due during a 30 minute install was said only after the install finished."""

    def test_reminder_is_said_during_a_long_install(self):
        store = StopsWorker(os.path.join(tempfile.mkdtemp(prefix="heyjev-worker-"), "tasks.db"))
        said, release, started = queue.Queue(), threading.Event(), threading.Event()

        def slow_install(payload, cancelled):
            started.set()
            release.wait(10)
            return True, "VLC is installed.", ""

        with mock.patch.object(siri, "TASK_STORE", store), mock.patch.object(siri, "ANNOUNCE", said), \
                mock.patch.object(installer, "install", slow_install):
            store.create("Install VLC", "install", {"id": "VideoLAN.VLC", "approved": True})
            worker = threading.Thread(target=siri.task_worker, daemon=True)
            worker.start()
            try:
                self.assertTrue(started.wait(5))
                store.create("Remind me to take the pizza out", "reminder", {"text": "take the pizza out"})
                self.assertEqual(said.get(timeout=5), "Reminder: take the pizza out.")
                release.set()
                self.assertEqual(said.get(timeout=5), "VLC is installed.")
            finally:
                release.set()
                store.stopped = True
                tasks.WAKE.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())

    def test_a_repeat_long_missed_while_the_pc_was_off_isnt_said_hours_late(self):
        """24 October, on waking at 9: "Reminder from Friday 23 October at 9:35 PM: drink water.", an hourly one."""
        store = StopsWorker(os.path.join(tempfile.mkdtemp(prefix="heyjev-worker-"), "tasks.db"))
        said, now = queue.Queue(), time.time()
        an_hour_ago = dt.datetime.fromtimestamp(now - 3600)
        with mock.patch.object(siri, "TASK_STORE", store), mock.patch.object(siri, "ANNOUNCE", said):
            hourly = store.create("Drink water", "reminder", {"text": "drink water"}, due=now - 11.5 * 3600,
                                  repeat={"kind": "interval", "seconds": 3600})
            store.create("Call Ravi", "reminder", {"text": "call Ravi"}, due=now - 2 * 3600)
            store.create("Take the tablet", "reminder", {"text": "take the tablet"}, due=now - 3600,
                         repeat={"kind": "daily", "hour": an_hour_ago.hour, "minute": an_hour_ago.minute})
            worker = threading.Thread(target=siri.task_worker, daemon=True)
            worker.start()
            try:
                lines = [said.get(timeout=5), said.get(timeout=5)]
                time.sleep(0.5)  # time enough for the hourly one too, if it were said
                self.assertTrue(said.empty(), said.queue)
            finally:
                store.stopped = True
                tasks.WAKE.set()
                worker.join(5)
        self.assertTrue(lines[0].startswith("Reminder from ") and lines[0].endswith(": call Ravi."), lines)
        self.assertTrue(lines[1].endswith(": take the tablet."), lines)  # a daily one an hour late still is
        self.assertGreater(store.get(hourly)["due"], now)  # the next one comes round as ever

    def test_long_tasks_still_go_one_at_a_time(self):
        store = StopsWorker(os.path.join(tempfile.mkdtemp(prefix="heyjev-worker-"), "tasks.db"))
        said, release, started, running = queue.Queue(), threading.Event(), threading.Event(), []
        overlap = []

        def slow_install(payload, cancelled):
            running.append(payload["id"])
            overlap.append(len(running))
            started.set()
            release.wait(10)
            running.remove(payload["id"])
            return True, f"{payload['id']} is installed.", ""

        with mock.patch.object(siri, "TASK_STORE", store), mock.patch.object(siri, "ANNOUNCE", said), \
                mock.patch.object(installer, "install", slow_install):
            store.create("Install VLC", "install", {"id": "VLC", "approved": True})
            store.create("Install Git", "install", {"id": "Git", "approved": True})
            worker = threading.Thread(target=siri.task_worker, daemon=True)
            worker.start()
            try:
                self.assertTrue(started.wait(5))
                time.sleep(0.5)  # time enough for the worker to start Git too, if it would
                self.assertEqual(running, ["VLC"])
                release.set()
                self.assertEqual({said.get(timeout=5), said.get(timeout=5)}, {"VLC is installed.", "Git is installed."})
                self.assertEqual(overlap, [1, 1])
            finally:
                release.set()
                store.stopped = True
                tasks.WAKE.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
