"""The local fast path: what quick() and fast_intent plan on this PC, and what they leave to the model."""
import contextlib
import io
import unittest
from unittest import mock

from tests.support import siri, winplatform

import fast_intent


class Routing(unittest.TestCase):
    """quick() and handle() with nothing to find: no Start menu apps, nothing in front, no last YouTube search, no
    routines. Installs, messages and PC lookups are recorded instead of done."""

    def setUp(self):
        self.installs, self.messages = [], []
        for patch in (
                mock.patch.object(siri.win, "loaded_start_apps", lambda: []),
                mock.patch.object(siri, "focused_on", lambda app: False),
                mock.patch.object(siri, "youtube_title", lambda: ""),
                mock.patch.object(siri, "LAST_QUERY", [""]),
                mock.patch.object(siri, "routines", lambda: []),
                mock.patch.object(siri.web, "weather", side_effect=RuntimeError("offline")),
                mock.patch.object(siri.sysinfo, "lookup", lambda what: {}),
                mock.patch.object(siri.sysinfo, "describe", lambda what, data, drive=None: f"lookup {what}"),
                mock.patch.object(siri, "stage_install",
                                  lambda name: self.installs.append(name) or {"steps": [], "say": "Install it?"}),
                mock.patch.object(siri, "stage_message", lambda app, who, text:
                                  self.messages.append((app, who, text)) or {"steps": [], "say": "Send it?"})):
            patch.start()
            self.addCleanup(patch.stop)

    def quick(self, words, gate=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return siri.quick(words) if gate is None else siri.quick(words, gate)

    def steps(self, words):
        plan = self.quick(words)
        return plan and plan["steps"]

    def handle(self, words, gate):
        """One turn, with the model, the steps and her voice stubbed: (whether the model was asked, the plan she ran,
        the plan waiting on a yes)."""
        ran = []
        with mock.patch.object(siri, "think", return_value=None) as think, \
                mock.patch.object(siri, "run_plan", lambda plan, notify: ran.append(plan) or ([], False, None, [])), \
                mock.patch.object(siri, "media_playing", return_value=False), \
                mock.patch.object(siri, "learn_later"), mock.patch.object(siri.history, "add"), \
                mock.patch.dict(siri.PENDING, {"plan": None, "until": 0.0}), contextlib.redirect_stdout(io.StringIO()):
            siri.handle(words, gate=gate)
            return think.called, ran[0] if ran else None, siri.PENDING["plan"]


class Writing(Routing):
    """A12: type/write/enter take the words as said only when they are the text, not a request to write something."""

    def test_compose_and_fill_in_requests_go_to_the_model(self):
        for words in ("write a short email saying I'll be late", "open Notepad and write today's date",
                      "write down what I say", "type my email address", "write me a poem about rain", "type the date",
                      "enter my password"):
            with self.subTest(words=words):
                self.assertIsNone(self.quick(words))

    def test_enter_full_screen_is_the_shortcut(self):
        self.assertEqual(self.steps("enter full screen"), [{"do": "keys", "keys": "f11"}])

    def test_typed_text_keeps_its_own_then(self):
        self.assertEqual(self.steps("open notepad and type salt then pepper"),
                         [{"do": "open", "app": "Notepad"}, {"do": "type", "text": "salt then pepper"}])

    def test_literal_text_is_still_typed(self):
        self.assertEqual(self.steps("type Hello, World! and press enter"),
                         [{"do": "type", "text": "Hello, World!"}, {"do": "keys", "keys": "enter"}])
        self.assertEqual(self.steps("write I'll be late"), [{"do": "type", "text": "I'll be late"}])
        self.assertEqual(self.steps("open notepad and type hello"),
                         [{"do": "open", "app": "Notepad"}, {"do": "type", "text": "hello"}])


if __name__ == "__main__":
    unittest.main()
