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

    def test_reminder_in_still_works(self):
        for said in ("remind me in 5 min to call mum", "remind me to call mum in 5 minutes"):
            step = siri.quick(said)["steps"][0]
            self.assertEqual((step["when"], step["task"]["text"]), ("in 300 seconds", "call mum"), said)


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

    def test_reminder_tonight_is_local(self):
        plan = siri.quick("remind me tonight at 8 to call mum")
        step = plan["steps"][0]
        self.assertEqual((step["do"], step["task"]["text"]), ("schedule", "call mum"))
        self.assertEqual(self.due(step["when"])[0], at(7, 20))


if __name__ == "__main__":
    unittest.main()
