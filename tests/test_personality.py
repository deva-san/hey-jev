"""28 October 2026, Atticus's way of answering in Jev's voice: answer first, a done task in one sentence of what's now
true, and a failure that says what to do (siri.fail_line). An untouched SOUL.md moves to the new default; one you
edited stays yours. No model, voice or network."""
import os
import tempfile
import unittest
from unittest import mock

from tests.support import siri

import requests


class Soul(unittest.TestCase):
    def setUp(self):
        folder = tempfile.mkdtemp(prefix="heyjev-soul-")
        self.path = os.path.join(folder, "SOUL.md")
        p = mock.patch.object(siri, "SOUL_PATH", self.path)
        p.start()
        self.addCleanup(p.stop)

    def write(self, text):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write(text + "\n")

    def read(self):
        with open(self.path, encoding="utf-8") as f:
            return f.read().strip()

    def test_the_new_default_answers_first(self):
        self.assertIn("Answer first", siri.DEFAULT_SOUL)
        self.assertIn("Never say it's done unless you saw it", siri.DEFAULT_SOUL)
        self.assertIn("JARVIS", siri.DEFAULT_SOUL)  # still her

    def test_an_untouched_old_default_moves_to_the_new_one(self):
        self.write(siri.OLD_SOULS[0])
        with mock.patch("builtins.print"):
            self.assertEqual(siri.soul(), siri.DEFAULT_SOUL)
        self.assertEqual(self.read(), siri.DEFAULT_SOUL)

    def test_one_you_edited_stays_yours(self):
        mine = siri.OLD_SOULS[0] + "\nCall me boss."
        self.write(mine)
        self.assertEqual(siri.soul(), mine)
        self.assertEqual(self.read(), mine)


class FailLines(unittest.TestCase):
    def line(self, exc, slow=False, model="openai/gpt-6.1"):
        with mock.patch.object(siri.settings, "get", lambda key, *a: model if key == "llm_model" else None):
            return siri.fail_line(exc, slow)

    def test_each_failure_says_what_to_do(self):
        for exc, slow, want in (
                (RuntimeError("Add your OpenAI key in Settings > Answer model"), False, "I need an OpenAI key"),
                (RuntimeError("OpenAI (openai/gpt-6.1) 401 Unauthorized: bad key"), False, "key isn't working"),
                (RuntimeError("OpenAI (openai/gpt-6.1) 404 Not Found: no such model"), False, "That model's gone"),
                (RuntimeError("OpenCode (kilo/x:free) 429 Too Many Requests"), False, "busy right now"),
                (TimeoutError("no answer in 12 s"), True, "taking too long"),
                (requests.ConnectionError("Max retries exceeded"), False, "can't reach the internet")):
            with self.subTest(want=want):
                self.assertIn(want, self.line(exc, slow))

    def test_a_local_model_that_isnt_running(self):
        line = self.line(RuntimeError("Ollama (ollama/llama3) isn't running on this PC, start it first"),
                         model="ollama/llama3")
        self.assertEqual(line, "Ollama isn't running on this PC. Start it, or pick another model in Settings.")

    def test_anything_else_is_her_old_line(self):
        self.assertIn(self.line(RuntimeError("something odd")), siri.REPLIES["llm_error"])


if __name__ == "__main__":
    unittest.main()


class StepLabels(unittest.TestCase):
    """Her card's step rows, in plain words from the step's own fields (siri.step_label)."""

    def test_plain_words(self):
        for step, want in (({"do": "open", "app": "Notepad"}, "Opening Notepad"),
                           ({"do": "website", "url": "https://www.youtube.com/watch?v=1"}, "Opening youtube.com"),
                           ({"do": "youtube", "query": "lofi", "play": True}, "Playing lofi on YouTube"),
                           ({"do": "web", "query": "Iron Man 2 cast"}, "Searching the web: Iron Man 2 cast"),
                           ({"do": "keys", "keys": "ctrl+w"}, "Pressing Ctrl+W"),
                           ({"do": "volume", "to": "30"}, "Volume to 30%"),
                           ({"do": "message", "contact": "Mum"}, "Opening Mum’s chat"),
                           ({"do": "night_light", "on": False}, "Night light off")):
            with self.subTest(step=step):
                self.assertEqual(siri.step_label(step), want)

    def test_never_long(self):
        self.assertLessEqual(len(siri.step_label({"do": "web", "query": "x " * 200})), 70)


class OnlyWhatSheSaw(unittest.TestCase):
    """28 October 2026, Atticus's rule: a step that left nothing to see fails, said so, and is never learned."""

    def test_an_app_whose_window_never_came_isnt_called_open(self):
        app = mock.Mock()
        app.name = "Spotify"
        with mock.patch.object(siri, "find_app", lambda name: app), \
                mock.patch.object(siri.win, "open_app", lambda a: False), \
                mock.patch.object(siri.win, "windows_page", lambda name: None), mock.patch("builtins.print"):
            with self.assertRaisesRegex(RuntimeError, "I couldn't see Spotify open"):
                siri.do_step({"do": "open", "app": "Spotify"})

    def test_one_that_came_is(self):
        app = mock.Mock()
        app.name = "Spotify"
        with mock.patch.object(siri, "find_app", lambda name: app), \
                mock.patch.object(siri.win, "open_app", lambda a: True), \
                mock.patch.object(siri.win, "windows_page", lambda name: None):
            self.assertEqual(siri.do_step({"do": "open", "app": "Spotify"}), "Spotify")

    def test_dark_mode_is_read_back(self):
        with mock.patch.object(siri.win, "set_dark_mode", lambda on: None), \
                mock.patch.object(siri.win, "dark_mode", lambda: False):
            with self.assertRaisesRegex(RuntimeError, "didn't switch to dark mode"):
                siri.do_step({"do": "dark_mode", "on": True})


class Windows(unittest.TestCase):
    """28 October 2026, as Atticus places them: a named app's window on a side or a screen, with no model."""
    MONS = [{"name": "Built-in Display", "x": 0, "y": 0, "w": 1920, "h": 1200, "work": (0, 0, 1920, 1152),
             "built_in": True, "primary": True},
            {"name": "DELL U2720Q", "x": 1920, "y": 0, "w": 2560, "h": 1440, "work": (1920, 0, 2560, 1400),
             "built_in": False, "primary": False}]

    def test_said_plainly_it_needs_no_model(self):
        with mock.patch("builtins.print"):
            plan = siri.placed(siri.plain("Chrome on the left, Notepad on the right"))
        self.assertEqual([(s["app"], s["where"], s["screen"]) for s in plan["steps"]],
                         [("Google Chrome", "left", "current"), ("Notepad", "right", "current")])
        self.assertEqual(plan["say"], "Google Chrome’s on the left and Notepad’s on the right.")
        for said, step, line in (
                ("put VS Code on my big screen", ("full", "monitor"), "VS Code’s on the big screen."),
                ("Spotify full screen on the laptop", ("full", "laptop"), "Spotify’s full screen on the laptop."),
                ("Chrome on the left side of the screen", ("left", "current"), "Google Chrome’s on the left."),
                ("put Notepad in the middle", ("center", "current"), "Notepad’s in the middle."),
                ("Chrome on the right of the TV", ("right", "monitor"), "Google Chrome’s on the right of the TV."),
                ("Chrome on the left please", ("left", "current"), "Google Chrome’s on the left.")):
            with self.subTest(said=said), mock.patch("builtins.print"):
                plan = siri.placed(siri.plain(said))
                self.assertEqual((plan["steps"][0]["where"], plan["steps"][0]["screen"]), step)
                self.assertEqual(plan["say"], line)

    def test_anything_else_goes_to_the_model(self):
        for said in ("open chrome", "turn on the left light", "flurble on the left", "chrome on the left and close it",
                     "scroll to the bottom", "whats on the left", "play it on the tv"):
            with self.subTest(said=said):
                self.assertIsNone(siri.placed(siri.plain(said)))
        self.assertIsNone(siri.placed("chrome on the left", gate="cold"))  # not from across the room

    def test_which_screen(self):
        here = (500, 500)  # the window's middle, on the laptop's panel
        pick = lambda screen: siri.win.pick_monitor(self.MONS, screen, here)["name"]
        self.assertEqual(pick("laptop"), "Built-in Display")
        self.assertEqual(pick("monitor"), "DELL U2720Q")
        self.assertEqual(pick("other"), "DELL U2720Q")
        self.assertEqual(pick("current"), "Built-in Display")
        self.assertEqual(pick("dell"), "DELL U2720Q")

    def test_where_on_it(self):
        work = self.MONS[1]["work"]
        self.assertEqual(siri.win.rect_for("left", work, (800, 600)), (1920, 0, 1280, 1400))
        self.assertEqual(siri.win.rect_for("right", work, (800, 600)), (3200, 0, 1280, 1400))
        self.assertEqual(siri.win.rect_for("center", work, (800, 600)), (2800, 400, 800, 600))

    def test_the_step_puts_it_there(self):
        app = mock.Mock()
        app.name = "Notepad"
        with mock.patch.object(siri, "find_app", lambda name: app), \
                mock.patch.object(siri.win, "place_window", lambda a, where, screen: f"{a.name} {where} {screen}"):
            self.assertEqual(siri.do_step({"do": "place", "app": "Notepad", "where": "maximise"}),
                             "Notepad full current")
        self.assertEqual(siri.step_label({"do": "place", "app": "Notepad", "where": "left"}),
                         "Putting Notepad on the left")
