"""A screenshot sent to your phone: only to your own paired Telegram, only when asked, the picture made on this PC with
her popup left out, and on the phone "screenshot" means that rather than the snipping tool."""
import unittest
from unittest import mock

import numpy as np

from tests.support import siri


class Step(unittest.TestCase):
    def setUp(self):
        self.sent = []
        for target, name, value in ((siri.win, "screenshot", lambda: (np.zeros((1080, 2560, 3), np.uint8),
                                                                        (0, 0, 2560, 1080))),):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_it_goes_only_to_the_paired_account(self):
        with mock.patch.dict(siri.PHONE, {"photo": lambda chat, png, caption: self.sent.append((chat, png[:8],
                                                                                                caption)) or True}), \
                mock.patch.dict(siri.settings._load(), {"telegram_owner": 7}):
            siri.do_step({"do": "send_screenshot"})
        chat, head, caption = self.sent[0]
        self.assertEqual((chat, head), (7, b"\x89PNG\r\n\x1a\n"))
        self.assertTrue(caption.startswith("Your screen at"))

    def test_not_paired_it_says_so_and_sends_nothing(self):
        with mock.patch.dict(siri.PHONE, {"photo": lambda *a: self.sent.append(a) or True}), \
                mock.patch.dict(siri.settings._load(), {"telegram_owner": None}):
            with self.assertRaises(RuntimeError) as err:
                siri.do_step({"do": "send_screenshot"})
        self.assertIn("Pair your phone", str(err.exception))
        self.assertEqual(self.sent, [])

    def test_the_picture_is_phone_sized(self):
        sizes = []
        real = siri.vision.png
        with mock.patch.object(siri.vision, "png", lambda rgb: sizes.append(rgb.shape) or real(rgb[:2, :2])), \
                mock.patch.dict(siri.PHONE, {"photo": lambda *a: True}), \
                mock.patch.dict(siri.settings._load(), {"telegram_owner": 7}):
            siri.do_step({"do": "send_screenshot"})
        self.assertEqual(sizes[0][1], siri.SCREENSHOT_WIDTH)


class TaskScreenshots(unittest.TestCase):
    """A task in an app (agent.capture): the picture that goes to the model."""

    def capture(self, area):
        screen = np.zeros((1080, 2560, 3), np.uint8)
        screen[:, 1600:] = 200  # WhatsApp, open beside Settings: its messages
        with mock.patch.object(siri.win, "screenshot", lambda: (screen, (0, 0, 2560, 1080))), \
                mock.patch.object(siri.win, "front_area", lambda: area, create=True):
            return siri.vision.capture()

    def test_only_the_window_in_front_goes(self):
        """It was the whole screen: WhatsApp's messages, or a bank's page, beside Settings went to the model with
        "turn on night light", when only the window in front had been judged."""
        shot = self.capture((100, 50, 1100, 750))  # Settings, with a list dropped down from it
        self.assertEqual((shot.rect, (shot.w, shot.h)), ((100, 50, 1100, 750), (1000, 700)))
        self.assertEqual(int(shot.small.max()), 0)  # none of WhatsApp
        self.assertEqual(shot.to_screen(10, 20), (110, 70))  # a point in it is a point on the screen still
        self.assertEqual(self.capture((2000, -10, 3000, 900)).rect, (2000, 0, 2560, 900))  # cut to its screen

    def test_with_no_window_in_front_nothing_goes(self):
        for area in (None, (3000, 0, 3500, 500)):  # nothing in front, or it's on another screen
            with self.assertRaises(RuntimeError):
                self.capture(area)


class Words(unittest.TestCase):
    def plan(self, said, phone=False):
        to = siri.REPLY_TO.set([] if phone else None)
        try:
            p = siri.phone_screenshot(said)
        finally:
            siri.REPLY_TO.reset(to)
        return [s["do"] for s in p["steps"]] if p else None

    def test_asked_for_in_so_many_words_anywhere(self):
        for said in ("send me a screenshot", "Send a screenshot to my phone", "share my screen to telegram",
                     "take a screenshot and send it to my phone"):
            self.assertEqual(self.plan(said), ["send_screenshot"], said)

    def test_on_the_phone_just_screenshot_will_do(self):
        for said in ("screenshot", "take a screenshot", "my screen"):
            self.assertEqual(self.plan(said, phone=True), ["send_screenshot"], said)
            self.assertIsNone(self.plan(said), said)  # at the PC, the snipping tool as before

    def test_after_reading_the_web_it_asks_first(self):
        self.assertNotIn("send_screenshot", siri.READ_SAFE)
        self.assertIn("send_screenshot", siri.KNOWN_STEPS)
        self.assertIn("send_screenshot", siri.SAY_AFTER)


if __name__ == "__main__":
    unittest.main()
