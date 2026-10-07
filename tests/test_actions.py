"""Carrying things out and confirming them: keys, media, the yes or no to her questions, what she says about what she
did. Nothing here acts on the PC: tests.support turns that into tripwires, and each test patches what it needs."""
import unittest
from unittest import mock

from tests.support import TRIPPED, siri, winplatform


class Keys(unittest.TestCase):
    def test_zoom_in_and_out_press_real_keys(self):
        """"Zoom in" planned ctrl+plus and she said "There's no plus key": pynput has no such key."""
        pressed = []
        with mock.patch.object(siri.win, "press", lambda *keys: pressed.append(keys)), \
                mock.patch.object(siri, "not_into_shell", lambda: None):
            siri.press_keys(siri.quick("zoom in")["steps"][0]["keys"])
            siri.press_keys(siri.quick("zoom out")["steps"][0]["keys"])
        self.assertEqual(pressed, [("ctrl", "="), ("ctrl", "-")])

    def test_zoom_stays_a_safe_shortcut(self):
        for keys in ("ctrl+plus", "ctrl+minus", "ctrl + =", "ctrl+0"):
            self.assertIn(siri.combo(keys), siri.SAFE_KEYS, keys)


if __name__ == "__main__":
    unittest.main()
