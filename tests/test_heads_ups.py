"""Heads-ups and apps: Telegram on this PC showing what her own bot just sent your phone isn't news, and a Store app
whose .exe has Windows or Microsoft in front of its name (WindowsCamera.exe) is still that app."""
import collections
import time
import unittest
from unittest import mock

from tests.support import siri

import telegram_bot
import watch

TELEGRAM_ID = "TelegramMessengerLLP.TelegramDesktop_t4vj0pshhgkwm!Telegram.TelegramDesktop.Store"


class OwnReplies(unittest.TestCase):
    def watcher(self):
        with mock.patch.object(watch, "last_added", return_value={}):
            w = watch.Watcher()
        return w

    def nameless(self, sent_ago, decided_after=2):
        """What she says when Telegram here noted a message (5 s ago) that the list no longer has: sent_ago seconds
        after the bot sent your phone something, decided on decided_after seconds after she noticed it."""
        w = self.watcher()
        noted = time.time() - 5
        sends = collections.deque([[noted - sent_ago - 1, noted - sent_ago]])
        with mock.patch.object(watch, "notifications", return_value=[]),                 mock.patch.object(watch, "last_added", return_value={TELEGRAM_ID: noted}),                 mock.patch.object(watch.time, "localtime", return_value=time.struct_time((2026, 10, 8, 12, 0, 0, 3, 281, 0))),                 mock.patch.object(telegram_bot, "SENDS", sends):
            w.messages("")  # noticed
            w.waiting = {k: (when, time.time() - decided_after) for k, (when, _) in w.waiting.items()}
            return w.messages("")

    def test_her_own_reply_isnt_a_heads_up(self):
        self.assertEqual(watch._app(TELEGRAM_ID)[0].lower(), "telegram")
        self.assertEqual(self.nameless(sent_ago=1), "")
        self.assertEqual(self.nameless(sent_ago=1, decided_after=8 * 3600), "")  # however late she looks

    def test_a_friends_message_a_little_later_still_is(self):
        self.assertIn("Telegram", self.nameless(sent_ago=25))
        self.assertIn("Telegram", self.nameless(sent_ago=600))

    def test_welcome_back_doesnt_count_it_either(self):
        noted = time.time() - 30
        with mock.patch.object(watch, "last_added", return_value={TELEGRAM_ID: noted}),                 mock.patch.object(telegram_bot, "SENDS", collections.deque([[noted - 1.5, noted - 0.5]])):
            self.assertEqual(watch.vanished(noted - 60, []), [])
        with mock.patch.object(watch, "last_added", return_value={TELEGRAM_ID: noted}),                 mock.patch.object(telegram_bot, "SENDS", collections.deque()):
            self.assertEqual(watch.vanished(noted - 60, []), ["Telegram"])


class StoreApps(unittest.TestCase):
    def test_windows_camera_is_camera(self):
        cam = siri.win.App("Camera")
        with mock.patch.object(siri.win, "file_description", return_value=""):
            self.assertTrue(cam.matches(r"C:\Program Files\WindowsApps\Microsoft.WindowsCamera\WindowsCamera.exe"))
            self.assertTrue(siri.win.App("Terminal").matches("WindowsTerminal.exe"))
            self.assertFalse(cam.matches("WindowsTerminal.exe"))
            self.assertFalse(siri.win.App("Windows").matches("explorer.exe"))
            self.assertFalse(siri.win.App("Camera Hub").matches("WindowsCamera.exe"))  # one shared word
            self.assertTrue(siri.win.App("Photos").matches("Microsoft.Photos.exe"))


if __name__ == "__main__":
    unittest.main()
