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


def logged(p, yours, room, level="strict"):
    """Scores in the log as after_turn writes them while learning: turns she acted on, and phrases she let go. Also
    "checked", as the log had them before, so the old way of setting the levels reads them too."""
    for who, scores in (("you", yours), ("room", room)):
        for s in scores:
            p.log({"score": float(s), "level": level, "secs": 2.0, "checked": True, "who": who})


class Learning(unittest.TestCase):
    def test_after_enough_of_your_turns_she_sets_the_levels_from_them_and_switches_on(self):
        p = profile()
        with mock.patch.dict(siri.settings._load(), {"voice_id": "learning"}):
            for s in np.linspace(0.06, 0.39, voiceid.CALIBRATE_AFTER):  # let go: Windows' voices scored this on 7 Oct
                self.assertIsNone(voiceid.after_turn(p, SOMEONE, float(s), 2.0, False, "other", True, False))
            scores = np.linspace(0.55, 0.9, voiceid.CALIBRATE_AFTER)
            switched = [voiceid.after_turn(p, YOU, float(s), 2.0, False, "other", True, True) for s in scores]
            self.assertEqual(switched, [None] * (len(scores) - 1) + ["on"])
            self.assertEqual(siri.settings.get("voice_id"), "on")
        self.assertTrue(p.calibrated)
        lo, hi = voiceid.LEVELS["strict"]
        self.assertTrue(lo <= p.strict <= hi and p.strict < 0.55)
        self.assertGreater(p.strict, p.named)
        again = voiceid.Profile(p.path)  # kept on disk
        self.assertEqual((again.named, again.strict, again.calibrated), (p.named, p.strict, True))

    def test_room_talk_short_turns_and_chat_arent_taken_for_yours(self):
        p = profile()
        with mock.patch.dict(siri.settings._load(), {"voice_id": "learning"}):
            for _ in range(voiceid.CALIBRATE_AFTER):
                voiceid.after_turn(p, SOMEONE, 0.1, 2.0, False, "other", True, False)  # let go
                voiceid.after_turn(p, YOU, 0.9, 0.5, True, "other", True, True)  # under a second: the words match
                voiceid.after_turn(p, YOU, 0.9, 2.0, False, "other", True, "chat")  # just talked: maybe the TV
        self.assertFalse(p.calibrated)
        self.assertEqual({e["who"] for e in p.scores()}, {"room"})

    def test_the_level_without_her_name_is_set_from_your_turns_without_it(self):
        """On 8 Oct your "A turn of nightlight" scored 0.41, under the starting 0.50 without her name, and the levels
        were only ever set from turns with her name, which you hardly say."""
        p = profile()
        logged(p, np.linspace(0.42, 0.8, 40), np.linspace(0.06, 0.39, 40))  # yours, and Windows' voices on 7 Oct
        self.assertEqual(p.calibrate(), "on")
        with mock.patch.dict(siri.settings._load(), {"voice_id": "on"}):
            self.assertTrue(voiceid.judge(p, 0.41, 2.0, False, "follow_up")[0])
            self.assertFalse(voiceid.judge(p, 0.39, 2.0, False, "other")[0])

    def test_a_few_turns_unlike_yours_dont_drag_the_levels_down(self):
        """While learning everyone counts, so a guest's or the TV's turns can be acted on and taken for yours: three
        low ones out of 30 put the level with her name at its 0.30 floor, where Windows' voices (up to 0.39) pass."""
        p = profile()
        logged(p, [0.1, 0.12, 0.15, *np.linspace(0.6, 0.85, 30)], np.linspace(0.06, 0.39, 30), level="named")
        p.calibrate()
        self.assertTrue(p.calibrated)
        self.assertGreater(p.named, 0.39)
        self.assertGreater(p.strict, 0.55)

    def test_she_switches_on_only_if_she_can_tell_you_apart_and_says_so_once(self):
        """On 8 Oct a video she let go scored 0.70 to 0.84 against your voice, and your own commands 0.33 to 0.54:
        switched on then, she'd have turned you away and answered the video."""
        p = profile()
        said = []
        with mock.patch.dict(siri.settings._load(), {"voice_id": "learning"}):
            for i in range(voiceid.CALIBRATE_AFTER + 10):
                said.append(voiceid.after_turn(p, SOMEONE, 0.7 + i / 300, 2.0, False, "other", True, False))
                said.append(voiceid.after_turn(p, YOU, 0.4 + i / 300, 2.0, False, "other", True, True))
            self.assertEqual(siri.settings.get("voice_id"), "learning")
        self.assertEqual([s for s in said if s], ["unsure"])
        self.assertTrue(p.calibrated)  # the levels are there for "only answer me"
        self.assertTrue(voiceid.Profile(p.path).told)  # and she won't say it again after a restart

    def test_four_in_a_hundred_of_yours_failing_is_too_many_to_switch_on(self):
        p = profile()
        logged(p, [0.1] * 4 + [0.7] * 96, [0.1] * 40)
        self.assertEqual(p.calibrate(), "unsure")
        logged(p, [0.7] * 100, [])  # 4 in 200
        self.assertEqual(p.calibrate(), "on")

    def test_the_score_log_is_read_from_the_file_once(self):
        """Read again on every phrase, on the listening thread before the turn ran, it took 25 ms at 166 lines and
        48 ms at 14,000, and nothing ever cut it back."""
        p = profile()
        reads = []

        def spy(path, mode="r", *args, **kw):
            if "r" in mode:
                reads.append(path)
            return open(path, mode, *args, **kw)

        with mock.patch.object(voiceid, "open", spy, create=True):
            for i in range(50):
                p.log({"when": i, "score": 0.7, "level": "strict", "who": "you"})
                p.scores()
        self.assertEqual(reads, [])
        self.assertEqual(len(voiceid.Profile(p.path).scores()), 50)  # and it's on the file for next time

    def test_the_log_keeps_the_latest_of_each(self):
        p = profile()
        logged(p, [], [0.2] * 10)
        logged(p, np.linspace(0, 1, 3 * voiceid.KEEP - 9), [])  # the line that makes it 3 * KEEP + 1: cut back
        again = voiceid.Profile(p.path).scores()
        self.assertEqual(len(again), voiceid.KEEP + 10)
        self.assertEqual(again[-1]["score"], 1.0)
        self.assertEqual(sum(e["who"] == "room" for e in again), 10)

    def test_plainly_you_adds_to_her_picture_of_your_voice_up_to_a_limit(self):
        p = profile(calibrated=True)
        with mock.patch.dict(siri.settings._load(), {"voice_id": "on"}):
            for _ in range(50):  # with her name or without: you hardly say it
                voiceid.after_turn(p, YOU, 0.95, 2.0, False, "other", True, True)
            voiceid.after_turn(p, SOMEONE, 0.95, 2.0, True, "other", True, True)  # unlike the sentences you read
            voiceid.after_turn(p, YOU, 0.95, 2.0, True, "other", True, False)  # or let go: never
        self.assertEqual(len(p.read) + len(p.grown), voiceid.MOST)
        self.assertTrue(all(float(g @ YOU) > 0.99 for g in p.grown))

    def test_her_picture_of_your_voice_cant_be_walked_over_to_someone_elses(self):
        """PLAN promised a guard against drift and there was none: each turn added was checked against the picture
        it was moving, and they could make up 30 of its 40 prints. A voice a little further from yours each time took
        it all the way."""
        p = profile(calibrated=True)
        with mock.patch.dict(siri.settings._load(), {"voice_id": "on"}):
            for angle in np.linspace(0.1, 1.47, 60):  # from yours to someone else's
                v = unit(np.cos(angle), np.sin(angle))
                s = p.score(v)
                voiceid.after_turn(p, v, s, 2.0, True, "other", voiceid.judge(p, s, 2.0, True, "other")[0], True)
        self.assertGreater(len(p.grown), 0)
        self.assertGreater(p.score(YOU), 0.9)
        self.assertLess(p.score(SOMEONE), 0.5)

    def test_one_print_added_barely_moves_her_picture_of_your_voice(self):
        """The first one added counted for half, as much as all the sentences you read, so a turn that only just
        passed (with the TV on behind you, say) moved every score away from the ones the levels were set from."""
        p = profile(calibrated=True)
        edge = unit(np.cos(0.8), np.sin(0.8))  # just over the level it takes to be added
        self.assertGreater(p.score(edge, read_only=True), p.strict + voiceid.GROW_ABOVE)
        with mock.patch.dict(siri.settings._load(), {"voice_id": "on"}):
            voiceid.after_turn(p, edge, p.score(edge), 2.0, False, "other", True, True)
        self.assertEqual(len(p.grown), 1)
        self.assertLess(abs(p.score(YOU) - p.score(YOU, read_only=True)), 0.01)
        for _ in range(len(p.read) * 2):  # and however many are added, never more than half
            p.grow(edge)
        half = unit(*(np.array(p.centre(read_only=True)[:2]) + edge[:2]))
        self.assertAlmostEqual(p.score(half), 1.0, places=4)

    def test_nothing_is_added_while_learning_or_before_the_levels_are_set(self):
        for setting, calibrated in (("learning", True), ("on", False)):
            p = profile(calibrated=calibrated)
            with self.subTest(setting=setting), mock.patch.dict(siri.settings._load(), {"voice_id": setting}):
                voiceid.after_turn(p, YOU, 0.95, 2.0, True, "other", True, True)
                self.assertEqual(len(p.grown), 0)

    def test_the_least_alike_go_first_and_enough_are_always_kept(self):
        rng = np.random.default_rng(1)
        near = [unit(1, *rng.normal(0, 0.15, 3)) for _ in range(18)]
        kept = voiceid.keep_alike(near[:5] + [SOMEONE] + near[5:12] + [unit(0.5, 0, 0, 1)] + near[12:])
        self.assertEqual(len(kept), 18)
        self.assertNotIn(5, kept)
        self.assertNotIn(13, kept)
        noisy = [unit(*rng.normal(0, 1, 8)) for _ in range(20)]  # nothing alike: the most alike are kept, never none
        self.assertEqual(len(voiceid.keep_alike(noisy)), voiceid.ENROL_KEEP)

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
        self.assertTrue(all(len(s) <= 50 for s in voiceid.SENTENCES))

    def test_there_are_enough_sentences_and_most_without_her_name_the_way_you_talk_to_her(self):
        """10 sentences, 7 starting with "Hey Jev": two unlike the rest left 8, and with "Answer without her name" on
        you hardly say it."""
        self.assertGreaterEqual(len(voiceid.SENTENCES), 20)
        self.assertGreaterEqual(sum(not s.startswith("Hey Jev") for s in voiceid.SENTENCES), len(voiceid.SENTENCES) / 2)


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
        self.assertEqual(len(a.var("profile").read), len(voiceid.SENTENCES))

    def test_a_sentence_unlike_the_rest_is_left_out_of_your_voice(self):
        """On 8 Oct two of the ten sentences scored 0.37 and 0.43 against the other eight (the rest 0.54 to 0.80) and
        were kept, and against that picture of your voice your own commands scored 0.33 to 0.54."""
        a = self.assistant()
        a.put("profile", voiceid.Profile(tempfile.mkdtemp(prefix="heyjev-voice-")))
        a.var("enrolling")[0] = {"i": 0, "prints": [], "until": 1e12}
        a.put("tell", lambda line, said_for: None)
        where, audio = tempfile.mkdtemp(), np.zeros(16000, np.float32)
        odd = (1, 7)
        with mock.patch.dict(siri.settings._load(), {"voice_id": "off"}), \
                mock.patch.object(voiceid, "folder", lambda: where):
            for i, sentence in enumerate(voiceid.SENTENCES):
                a.listener.on_phrase(audio, "other", turn(sentence, SOMEONE if i in odd else YOU), 100)
        read = a.var("profile").read
        self.assertEqual(len(read), len(voiceid.SENTENCES) - len(odd))
        self.assertTrue(all(float(p @ YOU) > 0.99 for p in read))
        clips = sorted(os.listdir(os.path.join(where, "clips")))  # what's kept is what her picture is made of
        self.assertEqual(len(clips), len(read))
        self.assertNotIn("sentence-2.wav", clips)

    def learning(self, a, voices):
        """act_on for each (words, voice), with voice ID learning and "Answer without her name" on: "open notepad
        please" is done, "pass me the water please" let go as room talk."""
        with mock.patch.object(siri, "handle", lambda *args, **kw: True), \
                mock.patch.dict(siri.settings._load(), {"voice_id": "learning", "no_name": True}):
            for words, voice in voices:
                a.var("act_on")(turn(words, voice), "other", 100)
            setting = siri.settings.get("voice_id")
        siri.ROOM.clear()
        said = []
        while not siri.ANNOUNCE.empty():
            said.append(siri.ANNOUNCE.get_nowait())
        return setting, said

    def test_learning_ends_from_your_turns_without_her_name(self):
        """With "Answer without her name" on, her name was in 1 of 150 turns and none of the 166 scores logged since
        19:25 was at the named level, so learning, which waited for 30 named turns, never ended."""
        a = self.assistant()
        siri.ANNOUNCE.queue.clear()
        setting, said = self.learning(a, [pair for i in range(voiceid.CALIBRATE_AFTER) for pair in (
            ("pass me the water please", unit(0.1 + i / 100, 1)), ("open notepad please", unit(1, 0.3 + i / 100)))])
        self.assertEqual(setting, "on")
        self.assertEqual(len(said), 1)
        self.assertIn("only answer you", said[0])
        self.assertEqual(len(a.var("profile").scores()), 2 * voiceid.CALIBRATE_AFTER)

    def test_when_what_she_let_go_sounds_like_you_she_keeps_answering_everyone_and_says_so(self):
        a = self.assistant()
        siri.ANNOUNCE.queue.clear()
        setting, said = self.learning(a, [("pass me the water please", YOU), ("open notepad please", YOU)] *
                                      (voiceid.CALIBRATE_AFTER + 5))
        self.assertEqual(setting, "learning")
        self.assertEqual(len(said), 1)
        self.assertIn("answering everyone", said[0])

    def test_a_turn_is_logged_once_its_over_and_empty_words_never(self):
        """Logged before the turn ran she couldn't know whose it was, and 71 of the 84 short ones let go on 8 Oct had
        no words at all."""
        a = self.assistant()
        p, seen = a.var("profile"), []
        with mock.patch.object(siri, "handle", lambda *args, **kw: seen.append(len(p.scores())) or True), \
                mock.patch.dict(siri.settings._load(), {"voice_id": "learning", "no_name": True}):
            a.var("act_on")(turn("", YOU), "other", 100)
            a.var("act_on")(turn(" . ", YOU), "other", 100)
            a.var("act_on")(turn("open notepad please", YOU), "other", 100)
        self.assertEqual(seen, [0])
        self.assertEqual([e["who"] for e in p.scores()], ["you"])

    def test_a_phrase_held_for_the_rest_keeps_its_voice(self):
        """"Hey Jev, open [pause] YouTube" in someone else's voice was joined as new words with no voice print, so it
        passed as too short to check, her name being in it; and yours, "open [pause] recycle bin" without her name,
        was let go as too short however long it was. Then the parts' own prints were averaged, each from under a
        second of speech, which can't tell voices apart (voiceid.py): yours, split, could be let go. So the joined
        audio gets one print of its own."""
        a = self.assistant()
        handled = []
        voices = {1.0: YOU, 2.0: SOMEONE}
        # a print of the audio as heard: whose by what it's filled with, as long as it is
        a.var("speaker")[0] = mock.Mock(print=lambda audio: (voices[float(np.max(audio))], len(audio) / 16000))
        said = lambda words, who, secs: a.listener.on_phrase(  # noqa: E731
            np.full(int(secs * 16000), 1.0 if who is YOU else 2.0, np.float32), "other",
            turn(words, unit(0.3, 1), spoke=secs), 100)  # under a second the print can be far off yours, 0.38 here
        with mock.patch.object(siri, "handle", lambda text, *args, **kw: handled.append(str(text))), \
                mock.patch.dict(siri.settings._load(), {"voice_id": "on", "no_name": True}):
            for who in (SOMEONE, YOU):
                said("Hey Jev, open", who, 0.7)
                said("YouTube", who, 0.5)
            said("open", YOU, 0.5)
            said("recycle bin", YOU, 0.7)
        self.assertEqual(handled, ["Hey Jev, open YouTube", "open recycle bin"])

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
