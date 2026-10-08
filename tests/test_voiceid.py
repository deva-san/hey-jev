"""Only your voice (voiceid.py): who counts at each level, learning then switching on, and her turning away a voice
that isn't yours without a sound, on made-up voice prints (the real model is checked by hand, see voiceid.py)."""
import os
import tempfile
import unittest
from unittest import mock

import numpy as np

from tests.support import siri
from tests.test_listening import Assistant, FakeEars

import speech
import voiceid


def unit(*xs):
    v = np.zeros(8, np.float32)
    v[:len(xs)] = xs
    return v / np.linalg.norm(v)


YOU, SOMEONE = unit(1, 0.1), unit(0.1, 1)  # cosine about 0.2 between them, 1 with yourself


def profile(**kw):
    p = voiceid.Profile(tempfile.mkdtemp(prefix="heyjev-voice-"))
    p.enrol([unit(1, 0.1 * i % 0.3) for i in range(10)])
    for k, v in kw.items():
        setattr(p, k, v)
    return p


def turn(text, voice, spoke=2.0):
    t = speech.heard(text)
    t.voice, t.spoke = voice, spoke
    return t


class Levels(unittest.TestCase):
    def setUp(self):
        patch = mock.patch.dict(siri.settings._load(), {"voice_id": "on"})
        patch.start()
        self.addCleanup(patch.stop)
        self.p = profile()

    def test_your_voice_counts_and_someone_elses_doesnt_with_or_without_her_name(self):
        for named, kind in ((True, "other"), (False, "other"), (False, "follow_up"), (False, "armed")):
            with self.subTest(named=named, kind=kind):
                self.assertTrue(voiceid.judge(self.p, self.p.score(YOU), 2.0, named, kind)[0])
                self.assertFalse(voiceid.judge(self.p, self.p.score(SOMEONE), 2.0, named, kind)[0])

    def test_her_name_gets_the_lower_level(self):
        between = (voiceid.NAMED + voiceid.STRICT) / 2
        self.assertTrue(voiceid.judge(self.p, between, 2.0, True, "other")[0])
        self.assertTrue(voiceid.judge(self.p, between, 2.0, False, "armed")[0])  # just after a bare "Hey Jev"
        self.assertFalse(voiceid.judge(self.p, between, 2.0, False, "other")[0])
        self.assertFalse(voiceid.judge(self.p, between, 2.0, False, "follow_up")[0])

    def test_too_short_to_tell_counts_only_with_her_name_or_just_after_she_spoke(self):
        """Under a second, voice prints match on the words, not the voice: a bare "Hey Jev" in Windows' voices
        scored 0.84 to 0.97 against Hari's."""
        for named, kind, counts in ((True, "other", True), (False, "armed", True), (False, "follow_up", True),
                                    (False, "other", False)):
            with self.subTest(named=named, kind=kind):
                self.assertIs(voiceid.judge(self.p, self.p.score(SOMEONE), 0.6, named, kind)[0], counts)
                self.assertIs(voiceid.judge(self.p, None, 2.0, named, kind)[0], counts)

    def test_off_learning_or_without_your_voice_everyone_counts(self):
        for setting, p in (("off", self.p), ("learning", self.p), ("on", voiceid.Profile(tempfile.mkdtemp()))):
            with self.subTest(setting=setting), mock.patch.dict(siri.settings._load(), {"voice_id": setting}):
                self.assertTrue(voiceid.judge(p, 0.0, 2.0, False, "other")[0])
                self.assertTrue(voiceid.judge(p, None, 0.5, False, "other")[0])


class Learning(unittest.TestCase):
    def test_after_enough_named_turns_she_sets_the_levels_from_yours_and_switches_on(self):
        p = profile()
        with mock.patch.dict(siri.settings._load(), {"voice_id": "learning"}):
            scores = np.linspace(0.55, 0.9, voiceid.CALIBRATE_AFTER)
            switched = [voiceid.after_turn(p, YOU, float(s), 2.0, True, "other", True) for s in scores]
            self.assertEqual(switched, [False] * (len(scores) - 1) + [True])
            self.assertEqual(siri.settings.get("voice_id"), "on")
        self.assertTrue(p.calibrated)
        lo, hi = voiceid.LEVELS["named"]
        self.assertTrue(lo <= p.named <= hi and p.named < 0.55)
        self.assertGreater(p.strict, p.named)
        again = voiceid.Profile(p.path)  # kept on disk
        self.assertEqual((again.named, again.strict, again.calibrated), (p.named, p.strict, True))

    def test_room_talk_and_short_turns_dont_set_the_levels(self):
        p = profile()
        with mock.patch.dict(siri.settings._load(), {"voice_id": "learning"}):
            for _ in range(voiceid.CALIBRATE_AFTER):
                voiceid.after_turn(p, SOMEONE, 0.1, 2.0, False, "other", True)
                voiceid.after_turn(p, YOU, 0.9, 0.5, True, "other", True)
        self.assertFalse(p.calibrated)

    def test_plainly_you_adds_to_her_picture_of_your_voice_up_to_a_limit(self):
        p = profile()
        with mock.patch.dict(siri.settings._load(), {"voice_id": "on"}):
            for _ in range(50):
                voiceid.after_turn(p, YOU, 0.95, 2.0, True, "other", True)
            voiceid.after_turn(p, SOMEONE, 0.95, 2.0, False, "other", True)  # without her name: never
        self.assertEqual(len(p.read) + len(p.grown), voiceid.MOST)

    def test_learning_your_voice_again_starts_the_levels_over(self):
        p = profile(named=0.5, strict=0.6, calibrated=True)
        p.log({"score": 0.9, "level": "named", "checked": True})
        p.enrol([YOU] * 10)
        self.assertEqual((p.named, p.strict, p.calibrated, p.scores()), (voiceid.NAMED, voiceid.STRICT, False, []))


class Words(unittest.TestCase):
    def test_what_you_say_to_her_about_your_voice(self):
        for said, which in (("learn my voice", siri.VOICE_LEARN), ("Teach you my voice again.", siri.VOICE_LEARN),
                            ("only listen to me", siri.VOICE_ONLY), ("Just answer me from now on", siri.VOICE_ONLY),
                            ("answer everyone again", siri.VOICE_ALL), ("Listen to everybody.", siri.VOICE_ALL)):
            with self.subTest(said=said):
                self.assertTrue(which.fullmatch(said))
        self.assertFalse(siri.VOICE_LEARN.fullmatch("I can't remember my voice notes"))

    def test_a_sentence_read_out_counts_when_most_of_its_words_are_there(self):
        want = voiceid.SENTENCES[0]
        self.assertTrue(siri.voice_like("Hey Jeff open Chrome and play some music", want))
        self.assertTrue(siri.voice_like("open from and play music", want))
        self.assertFalse(siri.voice_like("pass me the water", want))

    def test_the_sentences_fit_the_popup(self):
        self.assertEqual(len(voiceid.SENTENCES), 10)
        self.assertTrue(all(len(s) <= 50 for s in voiceid.SENTENCES))


class InHerEars(unittest.TestCase):
    """Through run_voice_assistant's act_on and on_phrase, on the listening tests' fakes."""

    def assistant(self):
        a = Assistant(ears=FakeEars())
        self.addCleanup(a.close)
        a.put("profile", profile())
        return a

    def test_she_lets_someone_elses_voice_go_without_a_word(self):
        a = self.assistant()
        handled = []
        with mock.patch.object(siri, "handle", lambda text, *args, **kw: handled.append(str(text))), \
                mock.patch.dict(siri.settings._load(), {"voice_id": "on", "no_name": True}):
            a.var("act_on")(turn("Hey Jev, what time is it?", SOMEONE), "other", 100)
            a.var("act_on")(turn("what's the weather like today", SOMEONE), "other", 100)
            a.var("act_on")(turn("Hey Jev, what time is it?", YOU), "other", 100)
        self.assertEqual(handled, ["Hey Jev, what time is it?"])

    def test_someone_elses_words_never_go_to_the_model_as_room_talk(self):
        a = self.assistant()
        siri.ROOM.clear()
        with mock.patch.dict(siri.settings._load(), {"voice_id": "on", "no_name": True}):
            a.var("act_on")(turn("pass me the water please", SOMEONE), "other", 100)
            self.assertEqual(list(siri.ROOM), [])
            a.var("act_on")(turn("pass me the water please", YOU), "other", 100)
        self.assertEqual([w for _, w in siri.ROOM], ["pass me the water please"])
        siri.ROOM.clear()

    def test_reading_the_sentences_learns_your_voice_then_she_starts_learning(self):
        a = self.assistant()
        a.put("profile", voiceid.Profile(tempfile.mkdtemp(prefix="heyjev-voice-")))
        a.var("enrolling")[0] = {"i": 0, "prints": [], "until": 1e12}
        told = []
        a.put("tell", lambda line, said_for: told.append(said_for))
        audio = np.zeros(16000, np.float32)
        with mock.patch.dict(siri.settings._load(), {"voice_id": "off"}), \
                mock.patch.object(voiceid, "folder", lambda: tempfile.mkdtemp()), \
                mock.patch.object(siri.threading, "Thread", lambda target, args=(), daemon=None: mock.Mock(
                    start=lambda: target(*args))):
            on_phrase = a.listener.on_phrase
            on_phrase(audio, "other", turn("pass me the water", YOU), 100)  # not the sentence: asked again
            self.assertEqual(a.var("enrolling")[0]["i"], 0)
            on_phrase(audio, "other", turn(voiceid.SENTENCES[0], YOU, spoke=0.5), 100)  # too short
            self.assertEqual(a.var("enrolling")[0]["i"], 0)
            for sentence in voiceid.SENTENCES:
                on_phrase(audio, "other", turn(sentence, YOU), 100)
            self.assertIsNone(a.var("enrolling")[0])
            self.assertEqual(siri.settings.get("voice_id"), "learning")
            self.assertEqual(told, ["voice learned"])
        self.assertEqual(len(a.var("profile").read), 10)

    def test_a_phrase_held_for_the_rest_keeps_its_voice(self):
        """"Hey Jev, open [pause] YouTube" in someone else's voice was joined as new words with no voice print, so it
        passed as too short to check, her name being in it; and yours, "open [pause] recycle bin" without her name,
        was let go as too short however long it was."""
        a = self.assistant()
        handled = []
        audio = np.zeros(16000, np.float32)
        with mock.patch.object(siri, "handle", lambda text, *args, **kw: handled.append(str(text))), \
                mock.patch.dict(siri.settings._load(), {"voice_id": "on", "no_name": True}):
            for voice in (SOMEONE, YOU):
                a.listener.on_phrase(audio, "other", turn("Hey Jev, open", voice, spoke=0.8), 100)
                a.listener.on_phrase(audio, "other", turn("YouTube", voice, spoke=0.7), 100)
            a.listener.on_phrase(audio, "other", turn("open", YOU, spoke=0.5), 100)
            a.listener.on_phrase(audio, "other", turn("recycle bin", YOU, spoke=0.7), 100)
        self.assertEqual(handled, ["Hey Jev, open YouTube", "open recycle bin"])

    def test_a_joined_phrase_has_its_parts_voices_by_how_long_each_spoke(self):
        """Only the parts with a print count: one too short for a print (under 0.3 s) adds no seconds."""
        held, rest = turn("open", None, spoke=0.2), turn("the downloads folder", YOU, spoke=1.3)
        voice, spoke = voiceid.joined(held, rest)
        self.assertAlmostEqual(float(voice @ YOU), 1.0, places=5)
        self.assertEqual(spoke, 1.3)
        voice, spoke = voiceid.joined(turn("open the", SOMEONE, spoke=0.5), rest)
        self.assertGreater(float(voice @ YOU), float(voice @ SOMEONE))
        self.assertEqual(spoke, 1.8)
        self.assertEqual(voiceid.joined(held, turn("bin", None, spoke=0.1)), (None, 0.0))

    def test_saying_stop_stops_learning_your_voice(self):
        a = self.assistant()
        a.var("enrolling")[0] = {"i": 3, "prints": [YOU] * 3, "until": 1e12}
        a.listener.on_phrase(np.zeros(8000, np.float32), "other", turn("stop", YOU, spoke=0.4), 100)
        self.assertIsNone(a.var("enrolling")[0])


class Listener(unittest.TestCase):
    def test_the_voice_print_is_worked_out_beside_speech_to_text_and_put_on_the_words(self):
        from tests.test_listening import blocks, listener
        prints = []
        ear, phrases = listener(FakeEars(), speaker=lambda audio: prints.append(len(audio)) or (YOU, 1.5))
        seen = []
        ear.on_phrase = lambda audio, kind, text, ms: seen.append((text.voice, text.spoke))
        for block in blocks(0.3, 0.0) + blocks(1.5, 0.9) + blocks(1.5, 0.0):
            ear.feed(block)
        self.assertEqual(len(prints), 1)
        self.assertEqual(len(seen), 1)
        self.assertIs(seen[0][0], YOU)
        self.assertEqual(seen[0][1], 1.5)


if __name__ == "__main__":
    unittest.main()
