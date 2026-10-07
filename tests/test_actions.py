"""Carrying things out and confirming them: keys, media, the yes or no to her questions, what she says about what she
did. Nothing here acts on the PC: tests.support turns that into tripwires, and each test patches what it needs."""
import unittest
from types import SimpleNamespace
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


def session(app, position):
    return SimpleNamespace(source_app_user_model_id=app, position=position)


class Media(unittest.TestCase):
    def previous(self, app, position):
        sent = []
        with mock.patch.object(siri.win, "media_session", lambda hint=None: session(app, position)), \
                mock.patch.object(siri.win, "media_position", lambda s: s.position), \
                mock.patch.object(siri.win, "media_command", lambda s, action: sent.append(action) or True), \
                mock.patch.object(siri.time, "sleep", lambda secs: None):
            siri.media("previous")
        return sent

    def test_previous_on_spotify_mid_song_goes_back_a_song(self):
        """One "previous" 40 s into a Spotify song only started it again."""
        self.assertEqual(self.previous("Spotify.exe", 40.0), ["previous", "previous"])

    def test_previous_at_the_start_of_a_song_is_one_press(self):
        self.assertEqual(self.previous("Spotify.exe", 1.0), ["previous"])

    def test_previous_elsewhere_is_one_press(self):
        """YouTube's previous goes back a video straight away, two would skip one."""
        self.assertEqual(self.previous("Chrome", 40.0), ["previous"])


if __name__ == "__main__":
    unittest.main()
