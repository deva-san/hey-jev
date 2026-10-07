"""The ears (speech.Listener) and the listening loop in siri.run_voice_assistant, with no mic, models, speakers or
keyboard hook. run_voice_assistant runs on fakes until its control loop has nothing left to do, and its inner
functions are then driven directly, through the variables they share."""
import collections
import contextlib
import io
import queue
import time
import types
import unittest
from unittest import mock

import numpy as np

from tests.support import siri

import speech

RATE, BLOCK = speech.RATE, siri.Recorder.BLOCK


class Stop(BaseException):
    """Ends a loop that would otherwise wait forever."""


def blocks(secs, value):
    """secs of mic audio in 32 ms blocks: value 1.0 is speech to the fake voice detector, 0.0 quiet."""
    return [np.full(BLOCK, value, np.float32) for _ in range(int(round(secs * RATE / BLOCK)))]


class FakeVAD:
    """Silero's stand-in: the chance of speech in a block is its first sample."""

    def __call__(self, audio):
        return [float(audio[0])] if len(audio) else []

    def reset(self):
        pass


def segments(audio):
    """How many stretches of speech the audio has, apart by at least a block of quiet."""
    voiced = np.asarray(audio)[::BLOCK] > 0.5  # a block's samples are all the same
    return int(np.sum(voiced[1:] & ~voiced[:-1]) + (1 if len(voiced) and voiced[0] else 0))


class FakeLive:
    """Nemotron's stand-in: words as they come, from what the ears say each stretch of speech is."""
    live = True

    def __init__(self, ears):
        self.ears, self.parts = ears, []

    def feed(self, audio):
        self.parts.append(np.asarray(audio, np.float32))

    def text(self):
        return self.ears.write(np.concatenate(self.parts)) if self.parts else ""

    def finish(self, quiet=0.2):
        self.ears.finished += 1
        return speech.heard(self.text()), 5


class FakeEars:
    """speech.Ears with no model: write(audio) gives the words, by default one word per stretch of speech."""

    def __init__(self, live=False, write=None):
        self.engine, self.live, self.finished, self.calls = ("nemotron" if live else "parakeet"), live, 0, 0
        self.write = write or (lambda audio: " ".join(["word"] * segments(audio)))

    def transcribe(self, audio):
        self.calls += 1
        return speech.heard(self.write(audio)), 5

    def session(self):
        return FakeLive(self) if self.live else speech.Whole(self.transcribe)


def listener(ears, **kw):
    """A real speech.Listener on the fake voice detector, keeping every phrase it makes."""
    phrases = []
    ear = speech.Listener(FakeVAD(), ears, lambda audio, kind, text, ms: phrases.append((len(audio), kind, str(text),
                                                                                          ear.pos)), **kw)
    return ear, phrases


class FakeStream:
    """A sounddevice stream: like the real one, a closed stream can't be asked if it's running."""

    def __init__(self):
        self._active, self.closed = False, False

    @property
    def active(self):
        if self.closed:
            raise RuntimeError("Error querying stream: Invalid stream pointer")
        return self._active

    def start(self):
        if self.closed:
            raise RuntimeError("Error starting stream: Invalid stream pointer")
        self._active = True

    def stop(self):
        self._active = False

    def close(self):
        self._active, self.closed = False, True


class Blocks(queue.Queue):
    """The mic queue. What's in .coming arrives a block at a time as the loop takes it, the way the mic hands it over
    when she keeps up; what's put() straight in piled up while she was busy. Once both are empty the next of .then
    runs, and with nothing left get() ends the listening loop."""

    def __init__(self, gen):
        super().__init__()
        self.coming, self.then, self.gen = collections.deque(), [], gen

    def get(self, block=True, timeout=None):
        if not block:  # get_nowait(), as when she skips to now
            return super().get(block=False)
        while self.empty() and not self.coming and self.then:
            self.then.pop(0)()
        if self.empty() and self.coming:
            self.put((self.gen(), self.coming.popleft()))
        try:
            return super().get(block=False)
        except queue.Empty:
            raise Stop from None


class Controls:
    """The window's control queue: these commands, then Stop."""

    def __init__(self, commands=()):
        self.commands = list(commands)

    def get(self, timeout=None):
        if self.commands:
            return self.commands.pop(0)
        raise Stop


class Assistant:
    """siri.run_voice_assistant on fakes, run until its control loop is out of commands. var(name) and put(name,
    value) read and change the variables its inner functions share, threads[name] is what each thread would run."""

    def __init__(self, ears=None, mode="wake", commands=(), unplugged=()):
        self.ears, self.threads, self.streams, self.timer_done, self.back = ears or FakeEars(), {}, [], None, None
        self.unplugged, self.out = set(unplugged), io.StringIO()  # mics that won't open, and what it printed
        assistant = self

        class Thread:
            def __init__(self, target=None, args=(), daemon=None, **_):
                self.target, self.args = target, args

            def start(self):
                assistant.threads[getattr(self.target, "__name__", "?")] = self.target

        def open_stream(rec, mic):
            if mic in assistant.unplugged:
                raise RuntimeError(f"{mic} isn't there")
            assistant.streams.append(FakeStream())
            return assistant.streams[-1]

        with contextlib.ExitStack() as stack:
            for target, name, value in (
                    (speech, "Ears", lambda engine, notify=None: self.ears),
                    (speech, "Turn", mock.Mock(side_effect=RuntimeError("no Smart Turn in tests"))),
                    (speech, "end_of_speech", lambda notify=None: FakeVAD()),
                    (siri.Recorder, "_open", open_stream),
                    (siri.win, "warm_start_apps", lambda: None),
                    (siri.win, "start_ptt_listener", lambda press, release: None),
                    (siri.watch, "Watcher", lambda: types.SimpleNamespace(messages=lambda front: None,
                                                                          check=lambda *a: [])),
                    (siri, "start_timer_loop", lambda on_done: setattr(self, "timer_done", on_done)),
                    (siri, "watch_return", lambda on_back: setattr(self, "back", on_back)),
                    (siri, "warm", lambda: None),
                    (siri.threading, "Thread", Thread)):
                stack.enter_context(mock.patch.object(target, name, value))
            stack.enter_context(contextlib.redirect_stdout(self.out))
            self.open_stream = open_stream
            try:
                siri.run_voice_assistant(controls=Controls(commands), mode=mode)
            except Stop:
                pass
        self.cells = {}
        todo, seen = [f for f in (*self.threads.values(), self.timer_done, self.back) if f], set()
        while todo:
            f = todo.pop()
            if id(f) in seen or not getattr(f, "__closure__", None):
                continue
            seen.add(id(f))
            for name, cell in zip(f.__code__.co_freevars, f.__closure__):
                self.cells.setdefault(name, cell)
                try:
                    value = cell.cell_contents
                except ValueError:
                    continue
                if isinstance(value, types.FunctionType) and "run_voice_assistant" in value.__qualname__:
                    todo.append(value)
        self.rec, self.listener = self.var("rec"), self.var("listener")
        self.rec._open = lambda mic: open_stream(self.rec, mic)  # never the real mic, also after the patches end
        self.rec.blocks = Blocks(lambda: self.rec.gen)
        self.put("partials", types.SimpleNamespace(submit=lambda fn, *args: fn(*args)))  # at once, not on a thread

    def var(self, name):
        return self.cells[name].cell_contents

    def put(self, name, value):
        self.cells[name].cell_contents = value

    def speak(self, audio):
        """Audio the mic hands over as she keeps up."""
        self.rec.blocks.coming.extend(audio)

    def then(self, step):
        """step() once what's been said so far has been heard, in the same run of the listening loop."""
        self.rec.blocks.then.append(step)

    def queue(self, audio):
        """Audio that piled up in the mic queue, while she was busy."""
        for block in audio:
            self.rec.blocks.put((self.rec.gen, block))

    def listen(self):
        """The listening loop, until the mic queue is empty."""
        with contextlib.redirect_stdout(self.out):
            try:
                self.threads["listen_loop"]()
            except Stop:
                pass

    def close(self):
        siri.MIC[0] = None


class FakeListener:
    """speech.Listener's stand-in for the loop around it: on_feed(n) runs as the nth block goes in."""

    def __init__(self, on_feed=None):
        self.fed, self.resets, self.on_feed = 0, [], on_feed or (lambda n: None)
        self.talking, self.session, self.speech_start, self.ended = False, None, None, (None, 0.6)

    def feed(self, block, dictating=False):
        self.fed += 1
        self.on_feed(self.fed)

    def reset(self, window=0.0):
        self.resets.append(self.fed)

    def end(self):
        pass

    def open(self, secs):
        pass

    def talking_for(self):
        return 0.0

    def state(self):
        return None


class Case(unittest.TestCase):
    """Nothing a test does may reach a tripwire."""

    def setUp(self):
        from tests.support import TRIPPED
        self.tripped = len(TRIPPED)
        self.addCleanup(lambda: self.assertEqual(TRIPPED[self.tripped:], []))
        calls = mock.patch.object(siri.win, "call_apps", lambda *args, **kw: ())  # no call going on
        calls.start()
        self.addCleanup(calls.stop)
        self.addCleanup(siri.ROOM.clear)

    def assistant(self, **kw):
        a = Assistant(**kw)
        self.addCleanup(a.close)
        return a


class Harness(Case):
    def test_runs_on_fakes(self):
        a = self.assistant()
        self.assertTrue(a.rec.wake)
        self.assertIn("listen_loop", a.threads)
        self.assertTrue(a.streams[-1].active)


# --------------------------------------------------------------------------- A1: a turn cut at MAX_TURN
class MaxTurn(Case):
    def test_continuous_speech_makes_one_turn_per_max_turn(self):
        """A TV that never pauses: one turn each 15 s, not a new 15 s turn on every block after the first (the
        log had 102 in a row of the same words)."""
        for live in (False, True):
            with self.subTest(live=live):
                ear, phrases = listener(FakeEars(live))
                for block in blocks(31, 1.0):
                    ear.feed(block)
                self.assertEqual(len(phrases), 2)
                first, second = phrases
                self.assertAlmostEqual(first[0] / RATE, speech.Listener.MAX_TURN, delta=0.05)
                # the second turn starts where the first was cut: none of the first's audio again
                self.assertEqual(second[3] - second[0], first[3])

    def test_later_turns_still_get_the_moment_before_their_speech(self):
        ear, phrases = listener(FakeEars())
        for block in blocks(16, 1.0) + blocks(1, 0.0) + blocks(1, 1.0) + blocks(2, 0.0):
            ear.feed(block)
        self.assertEqual(len(phrases), 3)  # the cut, what was left of that speech, and the next
        self.assertGreater(phrases[2][0] / RATE, 1.0 + speech.Listener.PRE_ROLL)  # its pre-roll, for a soft "H"


# --------------------------------------------------------------------------- A9: her long instruction, Parakeet
class LongInstruction(Case):
    def run_speech(self, words):
        a = self.assistant(ears=FakeEars(write=lambda audio: words))
        phrases = []
        a.listener.on_phrase = lambda audio, kind, text, ms: phrases.append(len(audio) / RATE)
        a.speak(blocks(0.5, 0.0) + blocks(20, 1.0))
        a.listen()
        return phrases

    def test_named_instruction_isnt_cut_at_max_turn_with_parakeet(self):
        """Her name at the start, heard early on the first seconds (check_partial): let run to MAX_TURN_HERS."""
        self.assertEqual(self.run_speech("Hey Jev, open Notepad and write the whole plan for Monday"), [])

    def test_room_talk_is_still_cut_at_max_turn(self):
        phrases = self.run_speech("so the match yesterday went on and on and on")
        self.assertEqual(len(phrases), 1)
        self.assertLess(phrases[0], 15.5)


# --------------------------------------------------------------------------- T1: "Hello [700 ms] Jev" with Parakeet
class BareGreeting(Case):
    @staticmethod
    def hello_jev(audio):
        return "Hello Jev." if segments(audio) > 1 else "Hello."

    def test_hello_then_her_name_after_a_breath_is_one_turn_with_parakeet(self):
        ear, phrases = listener(FakeEars(write=self.hello_jev), hold_for=siri.wait_for_rest)
        for block in blocks(0.5, 0.0) + blocks(0.4, 1.0) + blocks(0.7, 0.0) + blocks(0.3, 1.0) + blocks(1.5, 0.0):
            ear.feed(block)
        self.assertEqual([p[2] for p in phrases], ["Hello Jev."])

    def test_a_bare_greeting_ends_after_the_longest_wait_written_once(self):
        ears = FakeEars(write=self.hello_jev)
        ear, phrases = listener(ears, hold_for=siri.wait_for_rest)
        for block in blocks(0.5, 0.0) + blocks(0.4, 1.0) + blocks(2.0, 0.0):
            ear.feed(block)
        self.assertEqual([p[2] for p in phrases], ["Hello."])
        quiet = (phrases[0][3] - int(round(0.9 * RATE / BLOCK)) * BLOCK) / RATE
        self.assertAlmostEqual(quiet, speech.Listener.LONGEST, delta=0.05)
        self.assertEqual(ears.calls, 1)

    def test_other_short_turns_end_as_soon_as_before(self):
        """The hold costs nothing for anything but a bare greeting: same end, one transcription."""
        ends = []
        for hold in (None, siri.wait_for_rest):
            ears = FakeEars(write=lambda audio: "Louder.")
            ear, phrases = listener(ears, hold_for=hold)
            for block in blocks(0.5, 0.0) + blocks(0.5, 1.0) + blocks(2.0, 0.0):
                ear.feed(block)
            self.assertEqual(len(phrases), 1)
            self.assertEqual(ears.calls, 1)
            ends.append(phrases[0][3])
        self.assertEqual(ends[0], ends[1])


# --------------------------------------------------------------------------- A2: how far behind she may fall
class CatchUp(Case):
    def test_a_slow_moment_without_a_turn_doesnt_excuse_the_backlog(self):
        """Slow speech-to-text alone: what piled up counts, and over LAG she skips to now. Before, any feed over
        0.5 s excused the whole queue, and she fell 771 s behind."""
        a = self.assistant()

        def slow(n):
            if n == 1:
                time.sleep(0.6)
                a.queue(blocks(1.3, 0.0))
        fake = FakeListener(slow)
        a.put("listener", fake)
        a.queue(blocks(1.3, 0.0))
        a.listen()
        self.assertEqual(fake.fed, 1)
        self.assertIn("skipped", a.out.getvalue())

    def turn_that_takes(self, secs):
        a = self.assistant()
        ran = []

        def run_turn(text, words, ms, gate=False):  # she thinks for secs, and the mic keeps going meanwhile
            ran.append(words)
            a.queue(blocks(secs, 0.0))
        a.put("run_turn", run_turn)
        fake = FakeListener(lambda n: n == 1 and a.var("act_on")("Hey Jev, what time is it?", "other", 100))
        a.put("listener", fake)
        a.queue(blocks(0.1, 0.0))
        a.listen()
        return a, fake, ran

    def test_what_came_in_while_she_worked_is_caught_up_on(self):
        a, fake, ran = self.turn_that_takes(3.0)
        self.assertEqual(len(ran), 1)
        self.assertEqual(fake.fed, len(blocks(0.1, 0.0)) + len(blocks(3.0, 0.0)))
        self.assertNotIn("skipped", a.out.getvalue())

    def test_but_never_more_than_catch_up(self):
        a, fake, ran = self.turn_that_takes(siri.CATCH_UP + 5)
        self.assertLess(fake.fed, 10)
        self.assertIn("skipped", a.out.getvalue())


# --------------------------------------------------------------------------- A4: said while she was thinking
class WhileSheThinks(Case):
    def test_blocks_from_before_she_talked_are_heard_then_the_listener_starts_over(self):
        a = self.assistant()
        fake = FakeListener()
        a.put("listener", fake)
        a.queue(blocks(0.5, 0.0))
        a.rec.paused = True  # she talks, so the mic is off for a moment
        a.rec.paused = False
        a.queue(blocks(0.5, 0.0))
        a.listen()
        n = len(blocks(0.5, 0.0))
        self.assertEqual(fake.fed, 2 * n)
        self.assertEqual(fake.resets, [0, n])  # at the start, and at the break while she talked

    FIRST, SECOND = "Hey Jev, who directed Iron Man?", "Hey Jev, also set a timer for five minutes."

    def two_requests(self, said_meanwhile):
        """'Hey Jev, who directed Iron Man?', and while the model thinks, said_meanwhile is queued (0.8 for the second
        request's speech), then she answers. What reached handle()."""
        a = self.assistant(ears=FakeEars(write=lambda audio: self.SECOND if np.any(np.isclose(audio, 0.8))
                                         else self.FIRST))
        handled = []

        def handle(text, words, stt_ms=None, notify=None, gate=False):
            handled.append(str(text))
            if len(handled) == 1:
                a.queue(said_meanwhile)
                siri.say("Jon Favreau directed it.", None)
            return True
        with mock.patch.object(siri, "handle", handle), mock.patch.object(siri, "speak", lambda line: 0):
            a.speak(blocks(0.5, 0.0) + blocks(2.0, 0.9) + blocks(1.5, 0.0))
            a.listen()
        return handled

    def test_a_second_request_said_while_she_thinks_is_acted_on(self):
        """'Hey Jev, also set a timer for five minutes.' said while she thought: her answer to the first used to throw
        it away."""
        handled = self.two_requests(blocks(0.5, 0.0) + blocks(2.0, 0.8) + blocks(1.5, 0.0))
        self.assertEqual(handled, [self.FIRST, self.SECOND])

    def test_one_she_started_talking_just_after_counts_as_finished(self):
        """Only 0.3 s after you stopped, too soon for the turn to have ended: it ends at the break, not lost."""
        handled = self.two_requests(blocks(0.5, 0.0) + blocks(2.0, 0.8) + blocks(0.3, 0.0))
        self.assertEqual(handled, [self.FIRST, self.SECOND])

    def test_one_she_talked_over_is_let_go(self):
        """Still talking when she started: the rest was never heard, so it isn't acted on half said."""
        handled = self.two_requests(blocks(0.5, 0.0) + blocks(2.0, 0.8))
        self.assertEqual(handled, [self.FIRST])


# --------------------------------------------------------------------------- A7: the rest of a held phrase
class HeldPhrase(Case):
    def test_held_phrase_waits_while_its_continuation_is_still_going(self):
        """'Hey Jev, search [pause] for flights to Delhi [0.4 s] next Friday': one request, not 'search' alone."""
        def write(audio):
            parts = (["Hey Jev, search."] if np.any(np.isclose(audio, 0.9)) else []) + \
                (["for flights to Delhi next Friday."] if np.any(np.isclose(audio, 0.8)) else [])
            return " ".join(parts)
        a = self.assistant(ears=FakeEars(write=write))
        acted = []
        a.put("act_on", lambda text, kind, ms: acted.append(str(text)))
        held, waited = a.var("held"), []

        def expire():  # the rest has begun, and the 1.8 s it had run out while it goes on
            held[0] = (*held[0][:3], time.time() - 1)

        def the_rest():
            waited.append(held[0] and held[0][0])
            a.listener.on_speech = expire
            a.speak(blocks(1.5, 0.8) + blocks(0.4, 0.0) + blocks(1.0, 0.8) + blocks(1.5, 0.0))
        a.speak(blocks(0.5, 0.0) + blocks(0.6, 0.9) + blocks(0.6, 0.0))
        a.then(the_rest)
        a.listen()
        self.assertEqual(waited, ["Hey Jev, search."])
        self.assertEqual(acted, ["Hey Jev, search. for flights to Delhi next Friday."])


# --------------------------------------------------------------------------- A5: she doesn't talk over you
class NotOverYou(Case):
    def wait_then_talk(self, start):
        """start() in a thread while a turn is open: nothing said until it's over."""
        a = self.assistant()
        said = []
        a.listener.session = object()  # you're half way through a sentence
        with mock.patch.object(siri, "say", lambda line, notify: said.append(line)), \
                mock.patch.object(siri.history, "add", lambda *args: None), \
                mock.patch.object(siri.win, "chime", lambda name: None):
            import threading
            t = threading.Thread(target=start, args=(a,), daemon=True)
            t.start()
            time.sleep(0.4)
            self.assertEqual(said, [])
            self.assertFalse(a.rec.paused)
            a.listener.session = None  # you've finished
            t.join(5)
        self.assertFalse(t.is_alive())
        self.assertEqual(len(said), 1)

    def test_a_heads_up_waits_till_you_finish(self):
        self.wait_then_talk(lambda a: a.var("tell")("New message from Mum on WhatsApp.", "heads-up"))

    def test_a_timer_waits_till_you_finish(self):
        self.wait_then_talk(lambda a: a.timer_done({"label": "", "line": "Your pasta is ready.", "secs": 60}))

    def test_a_timer_kept_till_a_dictation_stops_doesnt_hold_up_listening(self):
        """finish_dictation runs on the listening thread, where a turn can't move on while it waits."""
        a = self.assistant()
        said = []
        a.var("late_timers").append({"label": "", "line": "Your pasta is ready.", "secs": 60})
        a.listener.session = object()
        a.rec.dictating = True
        no_sleep = types.SimpleNamespace(time=time.time, sleep=lambda secs: None, strftime=time.strftime)
        with mock.patch.object(siri, "say", lambda line, notify: said.append(line)), \
                mock.patch.object(siri.win, "chime", lambda name: None), \
                mock.patch.object(siri.win, "paste", lambda text: None), \
                mock.patch.object(a.var("dictation"), "finish", lambda: "Hello there."), \
                mock.patch.object(siri, "time", no_sleep), contextlib.redirect_stdout(a.out):
            start = time.time()
            a.var("finish_dictation")()
        self.assertLess(time.time() - start, 1.0)
        self.assertEqual(said, ["Your pasta is ready."])


if __name__ == "__main__":
    unittest.main()
