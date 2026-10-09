"""Talking over her: a request, her name or "stop" stops her mid-line, other words turn her down a moment, and once
she's stopped the rest of her turn isn't said. Nothing here plays a sound."""
import queue
import random
import sys
import threading
import time
import types
import unittest
from unittest import mock

import numpy as np

from tests.support import ORIGINAL, siri
from hermes_memory import voice_bits


class Verdicts(unittest.TestCase):
    """siri.barge: what words heard over her do."""

    def test_a_request_stops_her_once_it_is_said(self):
        self.assertEqual(siri.barge("okay now open notepad", True), "cut")
        self.assertEqual(siri.barge("open Chrome", True), "cut")
        self.assertEqual(siri.barge("okay now open", False), "duck")  # while it's still being said: turned down

    def test_her_name_stops_her_at_once(self):
        self.assertEqual(siri.barge("Hey Jev", False), "cut")

    def test_stop_only_once_it_is_all_that_was_said(self):
        self.assertEqual(siri.barge("Stop.", True), "cut")
        self.assertEqual(siri.barge("stop", False), "duck")
        self.assertEqual(siri.barge("stop the music", True), "cut")  # a request too: stop, then it's done

    def test_talk_nods_and_questions_dont(self):
        for words in ("okay", "mm hmm", "yeah", "and then we went to the market", "what are you doing",
                      "Wait, someone's at the door"):
            self.assertIsNone(siri.barge(words, True), words)

    def test_only_the_words_that_stopped_her_are_taken_as_said_to_her(self):
        """She asked "Should I turn on night light?", a TV's "play the next episode" didn't stop her (she was asking),
        your "stop" did. Any phrase that would stop her counted as the one that had: the TV's, heard first once she was
        done, was taken as said to her, and your "stop" as overheard."""
        self.addCleanup(setattr, siri.HER, "cut_by", "")
        siri.HER.cut_by = "stop"
        self.assertFalse(siri.said_to_her("play the next episode"))
        self.assertEqual(siri.HER.cut_by, "stop")  # still there for the stop itself
        self.assertTrue(siri.said_to_her("Stop."))
        siri.HER.cut_by = "okay now open note pad"  # written a little differently over her
        self.assertTrue(siri.said_to_her("open notepad"))

    def test_unsure_words_dont(self):
        self.assertIsNone(siri.barge("open notepad", True, sure=0.5))

    def test_while_she_asks_only_stop_or_her_name_do(self):
        self.assertIsNone(siri.barge("no cancel it", True, asking=True))
        self.assertIsNone(siri.barge("open notepad", True, asking=True))
        self.assertEqual(siri.barge("stop", True, asking=True), "cut")

    def test_her_own_words_never_do(self):
        siri.HER_SAID.append((time.time(), "Opening Notepad for you now and closing Chrome as well."))
        self.addCleanup(siri.HER_SAID.clear)
        self.assertIsNone(siri.barge("opening notepad for you now and closing chrome", True))


LINES = ["Tokyo is the capital of Japan, and with about fourteen million people it is also the biggest city there.",
         "Here's what Ravi said on WhatsApp: he'll be at the station by six, and asks if you could pick up some milk.",
         "The weather in Hyderabad today is thirty one degrees and sunny, with a light breeze in the evening.",
         "The top stories: the monsoon has reached Kerala early this year, markets closed higher, and India won.",
         "Should I send it to Mum on WhatsApp? It says: running late, will be home by eight, don't wait for dinner.",
         "Iron Man 2 came out in 2010, with Robert Downey Junior, Gwyneth Paltrow, Don Cheadle and Scarlett Johansson.",
         "Here's a short summary of the page: it explains how to set up a Python virtual environment on Windows.",
         "That's the second video on the page, a review of the new phone, about twelve minutes long."]


class Echo(unittest.TestCase):
    """echo_of: her own voice heard back, told apart from you without a difflib match for every letter she said."""

    def setUp(self):
        siri.HER_SAID.clear()
        self.addCleanup(siri.HER_SAID.clear)
        for line in LINES:
            siri.HER_SAID.append((time.time(), line))

    def test_a_few_words_after_a_long_answer_are_quick_to_tell_apart(self):
        """After a long answer, six words over her slid a SequenceMatcher across all she'd said a letter at a time:
        90-120 ms on every word update while she talked (barge), and twice more before the turn (act_on)."""
        made = []

        class Counted(siri.difflib.SequenceMatcher):
            def __init__(self, *args, **kw):
                made.append(1)
                super().__init__(*args, **kw)
        with mock.patch.object(siri.difflib, "SequenceMatcher", Counted):
            self.assertFalse(siri.echo_of("okay now open notepad and write hello please"))
            self.assertFalse(siri.echo_of("okay now open notepad and write hello please"))  # act_on's second look
            self.assertTrue(siri.echo_of("The weather in Hyderabad today is thirty one degrees."))
            self.assertTrue(siri.echo_of("send it to mum on whatsapp it says running late"))
        self.assertLess(len(made), 30)  # it was 2,126 for these four

    def test_the_answers_are_hermes_own(self):
        rnd, words = random.Random(7), siri.words_of(" ".join(LINES)).split()
        for _ in range(300):
            st, k = rnd.randrange(len(words) - 12), rnd.randint(2, 12)
            frag = words[st:st + k]
            for _ in range(rnd.randint(0, 3)):  # a word or two misheard
                frag[rnd.randrange(len(frag))] = rnd.choice(words)
            a, b = " ".join(frag), " ".join(words[max(0, st - rnd.randint(0, 20)):][:rnd.randint(4, 30)])
            with self.subTest(a=a, b=b):
                self.assertEqual(siri.tts_echo(a, b), voice_bits.is_tts_echo(a, b, threshold=siri.ECHO_SURE))


class Stopping(unittest.TestCase):
    def setUp(self):
        siri.HER.begin()
        self.addCleanup(siri.HER.begin)

    def test_a_late_verdict_never_stops_the_next_turn(self):
        turn = siri.HER.turn
        siri.HER.begin()
        self.assertFalse(siri.HER.cut("late", turn))
        self.assertFalse(siri.HER.stop.is_set())
        self.assertTrue(siri.HER.cut("now", siri.HER.turn))

    def test_the_model_hears_she_was_cut_off_once(self):
        voice_bits.take_speech_interrupted()
        siri.HER.cut("test")
        self.assertTrue(voice_bits.take_speech_interrupted())
        self.assertFalse(voice_bits.take_speech_interrupted())

    def test_a_stopped_answers_queued_lines_arent_made_in_her_voice_on_this_pc(self):
        """Her voice on this PC (Pocket): a streamed answer had three sentences queued, each line's voice already
        on its way, and you talked over her with a new request. Playing them was skipped, but end() cleared stop, so
        they were made in full anyway, one after another under the engine's one lock, and the next answer's first
        word came 3 to 10 s late."""
        made = []

        class TTS:
            def generate(self, text, config, callback):
                time.sleep(0.15)  # about 0.5 s a sentence on the PC
                made.append(text)
                callback(np.zeros(100, np.float32), 1.0)
                return types.SimpleNamespace(samples=np.zeros(100, np.float32))
        engine = siri.pocket.Engine.__new__(siri.pocket.Engine)
        engine.tts, engine.refs, engine.used, engine.lock = TTS(), {"p248": np.zeros(10, np.float32)}, 0.0, \
            threading.Lock()
        fake = types.SimpleNamespace(GenerationConfig=types.SimpleNamespace)
        line = ORIGINAL["Line"]
        with mock.patch.dict(sys.modules, {"sherpa_onnx": fake}), \
                mock.patch.object(siri.pocket, "engine", lambda: engine):
            queued = [line(f"Sentence number {i} of the answer.", "pocket:p248") for i in range(3)]
            time.sleep(0.05)  # the first is being made
            siri.HER.cut("a new request")
            siri.HER.end()
            t = time.time()
            nxt = line("The next answer.", "pocket:p248")
            while nxt.audio.get(timeout=2) is not None:
                pass
            waited = time.time() - t
        self.assertEqual(made, ["Sentence number 0 of the answer.", "The next answer."])
        self.assertLess(waited, 0.3)  # the one already being made, then this one
        self.assertTrue(all(q.audio.get(timeout=1) is None for q in queued[1:]))

    def test_playing_stops_between_slices(self):
        written = []
        out = mock.Mock(write=lambda piece: (written.append(len(piece)), len(written) == 3 and siri.HER.stop.set()))
        self.assertFalse(siri._write(out, np.zeros(16000, np.float32), 16000))
        self.assertEqual(len(written), 3)  # stopped within a slice, not at the end of the line

    def test_turned_down_she_eases_to_a_third(self):
        got = []
        out = mock.Mock(write=lambda piece: got.append(piece.copy()))
        siri.HER.duck()
        siri.HER.level = 1.0
        self.assertTrue(siri._write(out, np.full(4410, 10000, np.int16), 44100))
        self.assertEqual(got[0].dtype, np.int16)
        self.assertEqual(int(got[0][0]), 10000)  # from where she was
        self.assertAlmostEqual(int(got[-1][-1]), 3000, delta=5)  # to a third, without a click

    def test_a_fish_line_stopped_mid_way_isnt_said_again_in_another_voice(self):
        line = ORIGINAL["Line"].__new__(ORIGINAL["Line"])
        line.text, line.v, line.t = "A long line.", "fish", time.time()
        line.path, line.audio = "x.wav", queue.Queue()
        for _ in range(20):
            line.audio.put(b"\x00\x10" * 4410)
        line.audio.put(None)
        outs = []

        class Out:
            def __init__(self, **kw):
                self.aborted, self.writes = False, 0
                outs.append(self)

            def start(self):
                pass

            def write(self, data):
                self.writes += 1
                if self.writes == 5:
                    siri.HER.cut("test")

            def abort(self):
                self.aborted = True

            def stop(self):
                raise AssertionError("played on to the end")

            def close(self):
                pass
        with mock.patch.object(siri.sd, "RawOutputStream", Out), \
                mock.patch.object(siri.pocket, "available", lambda voice=None: self.fail("another voice")), \
                mock.patch.object(siri.win, "speak_native", lambda *a, **k: self.fail("Windows' voice")):
            line._play()
        self.assertTrue(outs[0].aborted)

    def test_once_stopped_the_rest_of_her_turn_isnt_said(self):
        siri.HER.cut("test")
        with mock.patch.object(siri, "speak", lambda line: self.fail("said")):
            self.assertIsNone(siri.say("And another thing.", None))

    def test_a_question_she_was_stopped_in_isnt_waiting_for_a_yes(self):
        plan = {"steps": [], "say": "Send hi to Mum on WhatsApp?", "confirm": {"steps": [{"do": "message_send"}]}}

        def run_plan(p, notify):
            siri.HER.cut("test")
            return [], False, None, []
        siri.PENDING.update(plan=None, until=0.0, origin="voice")
        self.addCleanup(siri.PENDING.update, plan=None, until=0.0, origin="voice")
        with mock.patch.object(siri, "run_plan", run_plan), mock.patch.object(siri, "quick", lambda *a: plan), \
                mock.patch.object(siri, "learn_later", lambda *a, **k: None), \
                mock.patch.object(siri, "drop_staged", lambda: None), \
                mock.patch.object(siri.history, "add", lambda *a, **k: None):  # her "...?" would be asked_last() after
            siri.handle("send hi to mum on whatsapp", "send hi to mum on whatsapp")
        self.assertIsNone(siri.PENDING["plan"])


if __name__ == "__main__":
    unittest.main()
