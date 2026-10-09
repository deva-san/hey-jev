"""The decider (decider.py): its heads, its levels, its Jev-shaped answers, and in act_on only ever letting plain room
talk go, and only when it's on. A fake encoder stands in for the model."""
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
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


class SureNo:
    """A head sure nothing is for her."""

    def for_me(self, words, kind):
        return 0.01, "no"


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

    def test_follow_ups_written_down_as_true_train_as_follow_ups(self):
        """The shadow log wrote a follow-up's kind as "True" (16 of the 88 rows on this PC), which features() saw as
        no kind at all, while she asks it with "follow_up" for the same turns."""
        where = tempfile.mkdtemp()
        with open(os.path.join(where, "shadow.jsonl"), "w", encoding="utf-8") as f:
            f.write('{"said": "and tomorrow", "kind": "True", "label": "U"}\n'
                    '{"said": "pass the salt", "kind": "cold", "label": "N"}\n'
                    '{"said": "not labelled", "kind": "True"}\n')
        with mock.patch.object(decider, "folder", lambda: where):
            turns = train_decider.labelled_turns()
        self.assertEqual([(w, kind) for w, kind, *_ in turns],
                         [("and tomorrow", "follow_up"), ("pass the salt", "cold")])


class Cost(unittest.TestCase):
    def test_a_turns_words_go_through_the_encoder_once(self):
        """Without her name a turn's words were worked out twice, about 15 ms each: is it for her (act_on), then
        which skills fit it (skills_block)."""
        seen = []

        class Counting(FakeEncoder):
            def __call__(self, text):
                seen.append(text)
                return super().__call__(text)
        d = trained()
        d.encoder = Counting()
        skill = {"dir": "work-folder", "description": "Opens the work folder", "triggers": []}
        with mock.patch.object(decider, "available", lambda: True), mock.patch.object(decider, "get", lambda: d):
            d.for_me("open the work folder", "cold")
            siri.relevant_skills("open the work folder", [skill])
        self.assertEqual(seen.count("open the work folder"), 1)

    def test_its_words_get_no_pool_of_threads(self):
        """tokenizers started a thread for every CPU thread, 12 more idling in her process for one sentence at a
        time."""
        seen = []
        tokenizers = SimpleNamespace(Tokenizer=SimpleNamespace(
            from_file=lambda path: seen.append(os.environ.get("TOKENIZERS_PARALLELISM")) or mock.Mock()))
        with mock.patch.dict(sys.modules, {"tokenizers": tokenizers}), mock.patch.dict(os.environ), \
                mock.patch("onnxruntime.InferenceSession") as session:
            os.environ.pop("TOKENIZERS_PARALLELISM", None)
            decider.Encoder()
        self.assertEqual(seen, ["false"])
        self.assertFalse(session.call_args.kwargs["sess_options"].enable_cpu_mem_arena)  # P6: 3 MB less


class InHerEars(unittest.TestCase):
    def assistant(self):
        a = Assistant(ears=FakeEars())
        self.addCleanup(a.close)
        return a

    def run_cold(self, a, words, setting, head=trained, kind="other"):
        handled, logged = [], []
        text = speech.heard(words)
        with mock.patch.object(siri, "handle", lambda text, *args, **kw: handled.append(str(text)) or False), \
                mock.patch.dict(siri.settings._load(), {"decider": setting, "no_name": True, "voice_id": "off"}), \
                mock.patch.object(decider, "get", head), \
                mock.patch.object(decider, "available", lambda: True), \
                mock.patch.object(decider, "log", logged.append), \
                mock.patch.object(siri, "asked_last", lambda *a: False):  # a "...?" another test left in history
            a.var("act_on")(text, kind, 100)
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

    def test_it_never_lets_go_a_follow_up_or_words_with_an_unsure_name(self):
        """On by default, sure "no" let these go with no model call right after her answer ("It's 32 degrees in
        Delhi."): none ask about anything once plain() has taken the "?" off. Only words said cold are its to let go."""
        a = self.assistant()
        for words in ("And tomorrow?", "Say that again", "Translate that to Hindi", "Try again", "Is it done?",
                      "the second one", "aur kal?", "phir se bolo", "awaaz badhao"):
            handled, logged = self.run_cold(a, words, "on", SureNo, kind="follow_up")
            self.assertEqual((handled, logged[0]["verdict"]), ([words], "no"), words)
        handled, _ = self.run_cold(a, "say that again, Jev", "on", SureNo)  # her name, not sure of it
        self.assertEqual(handled, ["say that again, Jev"])

    def test_a_question_another_test_left_in_history_changes_nothing_here(self):
        """run_cold read asked_last from the shared test history: a "...?" reply any other test wrote within 28 s
        turned on waiting, the decider was never asked, and room talk went on to the model."""
        a = self.assistant()
        with mock.patch.object(siri, "asked_last", lambda *a: True):
            handled, _ = self.run_cold(a, "what are you doing tonight", "on", SureNo)
        self.assertEqual(handled, [])

    def test_nor_an_order_after_a_word_or_two_or_said_in_hinglish(self):
        """LEADS only looked first, and plain() leaves "actually", "wait", "accha" and "bhai" on: a sure decider let
        "Actually, cancel that" and "Bhai, refresh karo" go, and Hinglish says the order last ("page reload karo")."""
        a = self.assistant()
        for words in ("Actually, cancel that", "Wait, go back", "Oh, refresh the page", "Accha, read my messages",
                      "Right, run it", "Bhai, refresh karo", "Sorry, wait, go back", "page reload karo",
                      "window chhota karo", "song lagao", "music chala do", "screen pe dikhao"):
            handled, logged = self.run_cold(a, words, "on", SureNo)
            self.assertEqual((handled, logged[0]["verdict"]), ([words], "no"), words)
        self.assertEqual(self.run_cold(a, "what are you doing tonight, bhai", "on", SureNo)[0], [])

    def test_in_shadow_it_only_writes_down_what_it_would_have_done(self):
        a = self.assistant()
        with mock.patch.object(siri, "could_be_request", lambda text: True):
            handled, logged = self.run_cold(a, "please pass the salt, I said", "shadow")
        self.assertEqual(handled, ["please pass the salt, I said"])
        self.assertEqual([e["verdict"] for e in logged], ["no"])
        self.assertEqual(logged[0]["result"], "False")

    def test_a_follow_up_is_written_down_the_way_it_was_asked(self):
        """Written down as str(gate), a follow-up's kind was "True", and a head trained on it lost what it was."""
        a = self.assistant()
        with mock.patch.object(siri, "asked_last", lambda *a: False):
            handled, logged = self.run_cold(a, "and what about tomorrow", "shadow", kind="follow_up")
            _, cold = self.run_cold(a, "what time does the match start", "shadow")
        self.assertEqual(handled, ["and what about tomorrow"])
        self.assertEqual([e["kind"] for e in logged + cold], ["follow_up", "cold"])


if __name__ == "__main__":
    unittest.main()
