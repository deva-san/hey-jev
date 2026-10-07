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


if __name__ == "__main__":
    unittest.main()
