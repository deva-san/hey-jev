"""Talking over her: a request, her name or "stop" stops her mid-line, other words turn her down a moment, and once
she's stopped the rest of her turn isn't said. Nothing here plays a sound."""
import queue
import time
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
                mock.patch.object(siri, "drop_staged", lambda: None):
            siri.handle("send hi to mum on whatsapp", "send hi to mum on whatsapp")
        self.assertIsNone(siri.PENDING["plan"])


if __name__ == "__main__":
    unittest.main()
