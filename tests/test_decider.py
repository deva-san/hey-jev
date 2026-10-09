"""The decider (decider.py): its heads, its levels, its Jev-shaped answers, and in act_on only ever letting plain room
talk go, and only when it's on. A fake encoder stands in for the model."""
import os
import tempfile
import unittest
from unittest import mock

import numpy as np

from tests.support import siri
from tests.test_listening import Assistant, FakeEars

import decider
import speech
import train_decider


class FakeEncoder:
    """Room talk points one way, requests the other."""

    def __call__(self, text):
        v = np.zeros(decider.DIM, np.float32)
        v[0 if any(w in str(text).lower() for w in ("open", "play", "what", "set")) else 1] = 1.0
        return v


def trained(hi=0.8, lo=0.2):
    d = decider.Decider.__new__(decider.Decider)
    d.encoder, d.lock = FakeEncoder(), __import__("threading").Lock()
    x = np.stack([decider.features(FakeEncoder()(t), "cold") for t in ("open chrome", "pass the salt")] * 20)
    y = np.array([1, 0] * 20, np.float32)
    w, b = decider.train_head(x, y)
    d.heads = {"for_me": {"w": w, "b": b, "hi": hi, "lo": lo}}
    return d


class Heads(unittest.TestCase):
    def test_it_learns_requests_from_room_talk_and_answers_like_jev(self):
        d = trained()
        with mock.patch.object(decider, "available", lambda: True):
            out = d.decide({"said": "open chrome", "kind": "cold"}, {"for_me": {"type": "noul"}, "nope": {}})
            self.assertEqual(set(out["answers"]), {"for_me"})
            self.assertGreater(out["answers"]["for_me"]["noul"], 0.8)
            self.assertEqual(d.for_me("play some music", "cold")[1], "yes")
            self.assertEqual(d.for_me("pass the salt please", "cold")[1], "no")

    def test_without_a_trained_head_it_has_no_view(self):
        d = decider.Decider.__new__(decider.Decider)
        d.heads, d.encoder = {}, None
        self.assertEqual(d.for_me("open chrome", "cold"), (None, None))

    def test_levels_are_where_it_was_right_95_percent_of_the_time(self):
        p = np.linspace(0, 1, 100)
        y = (p > 0.5).astype(np.float32)
        hi, lo = train_decider.levels(p, y)
        self.assertTrue(0.45 <= hi <= 0.55 and 0.45 <= lo <= 0.55)
        self.assertEqual(train_decider.levels(p, np.zeros(100, np.float32))[0], 1.01)  # never sure it's for her

    def test_it_saves_and_loads(self):
        d = trained()
        where = tempfile.mkdtemp()
        with mock.patch.object(decider, "folder", lambda: where):
            h = d.heads["for_me"]
            np.savez(os.path.join(decider.folder(), "heads.npz"), for_me__w=h["w"], for_me__b=h["b"],
                     for_me__hi=h["hi"], for_me__lo=h["lo"])
            again = decider.Decider()
        self.assertTrue(np.allclose(again.heads["for_me"]["w"], h["w"]))
        self.assertEqual(again.heads["for_me"]["lo"], 0.2)


class InHerEars(unittest.TestCase):
    def assistant(self):
        a = Assistant(ears=FakeEars())
        self.addCleanup(a.close)
        return a

    def run_cold(self, a, words, setting, head=trained):
        handled, logged = [], []
        text = speech.heard(words)
        with mock.patch.object(siri, "handle", lambda text, *args, **kw: handled.append(str(text)) or False), \
                mock.patch.dict(siri.settings._load(), {"decider": setting, "no_name": True, "voice_id": "off"}), \
                mock.patch.object(decider, "get", head), \
                mock.patch.object(decider, "available", lambda: True), \
                mock.patch.object(decider, "log", logged.append):
            a.var("act_on")(text, "other", 100)
        return handled, logged

    def test_on_it_lets_plain_room_talk_go_without_asking_the_model(self):
        a = self.assistant()
        handled, logged = self.run_cold(a, "what time does the match start, pass the salt", "on")
        handled2, _ = self.run_cold(a, "please pass the salt, I said", "on")
        self.assertEqual(handled, ["what time does the match start, pass the salt"])  # not sure: the model decides
        self.assertEqual(handled2, [])
        self.assertEqual(logged[0]["verdict"], "yes")  # sure it's for her: the model still decides

    def test_on_by_default_it_never_lets_go_words_that_ask_for_something(self):
        """Left in shadow mode, it changed nothing while she spoke or acted on 22 of 88 room-talk turns on 8 October,
        and its "sure it isn't for her" was right 16 times in 18. The 2 it got wrong asked for something: let go,
        the model would never have seen them. Words that ask for something, or name an app or a site, go on."""
        with mock.patch.dict(siri.settings._load(), clear=True):
            self.assertEqual(decider.mode(), "on")
        a = self.assistant()
        for words in ("A turn of nightlight", "check for Realme P3 in stock", "and Notepad, I said", "Click chat messages"):
            handled, logged = self.run_cold(a, words, "on")
            self.assertEqual((handled, logged[0]["verdict"]), ([words], "no"), words)

    def test_nor_commands_or_questions_it_is_sure_of(self):
        """On by default, its "sure it isn't for her" was only kept from the two kinds of words it got wrong on 8
        October: "Shut down the computer", "what time is it", or "how about tomorrow" right after her answer, would
        have been let go with no model call."""
        class SureNo:
            def for_me(self, words, kind):
                return 0.01, "no"
        a = self.assistant()
        for words in ("Shut down the computer", "Okay, copy that link", "Take a screenshot", "what time is it",
                      "What's the weather tomorrow", "Go back", "Refresh the page", "Read my messages", "Cancel that",
                      "Hey, what's the time", "Run it", "Approve it", "Switch to the other window"):
            handled, logged = self.run_cold(a, words, "on", SureNo)
            self.assertEqual((handled, logged[0]["verdict"]), ([words], "no"), words)
        self.assertEqual(self.run_cold(a, "pass the salt please", "on", SureNo)[0], [])  # room talk still goes
        self.assertTrue(siri.asks_something("how about tomorrow", True))  # right after her answer: to her
        self.assertTrue(siri.asks_something("Send a message to Bunty saying I'm late", True))
        self.assertFalse(siri.asks_something("what are you doing tonight", "cold"))  # said cold: room talk
        # her things to do only count first: said in the middle they're as often room talk, for it to judge
        for words in ("we should go back home", "I read that in the paper", "they cancelled it, run along"):
            self.assertFalse(siri.asks_something(words, "cold"), words)

    def test_in_shadow_it_only_writes_down_what_it_would_have_done(self):
        a = self.assistant()
        with mock.patch.object(siri, "could_be_request", lambda text: True):
            handled, logged = self.run_cold(a, "please pass the salt, I said", "shadow")
        self.assertEqual(handled, ["please pass the salt, I said"])
        self.assertEqual([e["verdict"] for e in logged], ["no"])
        self.assertEqual(logged[0]["result"], "False")


if __name__ == "__main__":
    unittest.main()
