"""Carrying things out and confirming them: keys, media, the yes or no to her questions, what she says about what she
did. Nothing here acts on the PC: tests.support turns that into tripwires, and each test patches what it needs."""
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.support import TRIPPED, siri, winplatform


def original(name):
    """One of siri's functions as written, which tests.support swapped for a tripwire, run in siri's own globals so
    what a test patches on siri still applies."""
    import ast
    with open(siri.__file__, encoding="utf-8") as f:
        node = next(n for n in ast.parse(f.read()).body if isinstance(n, ast.FunctionDef) and n.name == name)
    found = {}
    exec(compile(ast.Module([node], []), siri.__file__, "exec"), vars(siri), found)
    return found[name]


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


class RamFigures(unittest.TestCase):
    def test_an_apps_ram_is_its_private_working_set(self):
        """"Chrome uses the most, 4.1 GB" against Task Manager's 2.65: shared pages were counted in every process.
        Reads the process list only. This process's own figure should be its private set (psutil's USS), not all of
        its working set (RSS), which counts the DLLs it shares."""
        import os
        import psutil
        import sysinfo
        ram = sysinfo._snapshot()[os.getpid()][2]
        mem = psutil.Process().memory_full_info()
        self.assertGreater(mem.rss - mem.uss, 4 * 2 ** 20)  # enough shared pages here to tell them apart
        self.assertLess(abs(ram - mem.uss), (mem.rss - mem.uss) / 2)


class Voice(unittest.TestCase):
    def test_a_line_she_says_now_waits_seconds_for_fish_not_a_minute(self):
        """The mic is paused while she talks, and Fish once took 17 s to start: with 60 s she was silent and deaf."""
        asked = {}
        with mock.patch.object(siri, "FISH", SimpleNamespace(post=lambda url, **kw: asked.update(kw) or
                                                             SimpleNamespace(ok=True))):
            original("fish")("A new line.", "pcm", stream=True)
        connect, read = asked["timeout"]
        self.assertLessEqual(connect, 5)
        self.assertLessEqual(read, 5)

    def test_slow_fish_gets_windows_own_voice(self):
        import requests
        native = []

        def post(url, **kw):
            raise requests.ReadTimeout("read timed out")
        with mock.patch.object(siri, "FISH", SimpleNamespace(post=post)), \
                mock.patch.object(siri, "fish", original("fish")), \
                mock.patch.object(siri.win, "speak_native", lambda text, **kw: native.append(text)):
            original("speak")("A line nobody has cached, 1729.")
        self.assertEqual(native, ["A line nobody has cached, 1729."])


if __name__ == "__main__":
    unittest.main()
