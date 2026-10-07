"""Faster answers: a plain answer said as the model writes it (LiveSay), the streamed reply (opencode._streamed), a
second try only when the first hasn't started writing (ask_model), a "One moment" when she's slow (fill_silence),
and the prompt kept small. No model, voice or network: fakes throughout."""
import json
import threading
import time
import unittest
from unittest import mock

from tests.support import siri

import opencode


class FakeLine:
    """A Line that only records what it would say."""
    said = []

    def __init__(self, text, voice=None):
        self.text, self.t = text, time.time()

    def play(self):
        FakeLine.said.append(self.text)
        return 5


def stream_of(text, step=7):
    """A reply as it would stream: longer and longer starts of it."""
    return [text[:i] for i in range(step, len(text) + step, step)]


class JsonSoFar(unittest.TestCase):
    def test_a_string_still_being_written(self):
        self.assertEqual(siri.json_string_so_far('Tokyo is the capital."}'), "Tokyo is the capital.")
        self.assertEqual(siri.json_string_so_far('He said \\"hi\\" and'), 'He said "hi" and')
        self.assertEqual(siri.json_string_so_far('Line one\\nline two'), "Line one\nline two")
        self.assertEqual(siri.json_string_so_far('caf\\u00e9 and'), "café and")
        self.assertEqual(siri.json_string_so_far('half an escape \\'), "half an escape ")
        self.assertEqual(siri.json_string_so_far('half a \\u00e'), "half a ")
        self.assertEqual(siri.json_string_so_far('smile \\ud83d\\ude00 ok'), "smile \U0001f600 ok")
        self.assertEqual(siri.json_string_so_far('smile \\ud83d'), "smile ")  # half an emoji waits for the rest


class Live(unittest.TestCase):
    def setUp(self):
        FakeLine.said = []
        p = mock.patch.object(siri, "MIC", [None])
        p.start()
        self.addCleanup(p.stop)

    def run_reply(self, reply, key=0, live=None):
        live = live or siri.LiveSay(None, make=FakeLine)
        for so_far in stream_of(reply):
            live.feed(key, so_far)
        return live

    def test_a_plain_answer_is_said_a_sentence_at_a_time_as_it_comes(self):
        reply = ('{"steps": [], "say": "Tokyo is the capital of Japan. It is also the biggest city there, '
                 'with about fourteen million people."}')
        live = siri.LiveSay(None, make=FakeLine)
        heard = []
        for so_far in stream_of(reply):
            live.feed(0, so_far)
            heard.append(len(FakeLine.said))
        time.sleep(0.1)  # the player thread
        self.assertEqual(FakeLine.said, ["Tokyo is the capital of Japan."])  # before the reply was all in
        self.assertEqual(live.finish(), ["Tokyo is the capital of Japan.",
                                         "It is also the biggest city there, with about fourteen million people."])

    def test_anything_to_do_waits_for_the_whole_plan(self):
        for reply in ('{"steps": [{"do": "open", "app": "Notepad"}], "say": "Opening Notepad for you now. Done."}',
                      '{"to": "you", "steps": [], "say": "Sure, here it is. And more."}',
                      '{"say": "Said before the steps. Not this.", "steps": []}'):
            with self.subTest(reply=reply):
                live = self.run_reply(reply)
                self.assertIsNone(live.finish())
                self.assertFalse(live.talking)
        self.assertEqual(FakeLine.said, [])

    def test_only_the_first_try_to_start_is_said(self):
        live = siri.LiveSay(None, make=FakeLine)
        self.run_reply('{"steps": [], "say": "The first answer to come in. Said in full."}', key=0, live=live)
        self.run_reply('{"steps": [], "say": "A second try, a moment later. Never said."}', key=1, live=live)
        self.assertTrue(live.claim(0))
        self.assertFalse(live.claim(1))
        self.assertEqual(live.finish(), ["The first answer to come in.", "Said in full."])


class Streamed(unittest.TestCase):
    def test_the_words_come_out_and_the_thinking_stays_in(self):
        events = [{"choices": [{"delta": {"role": "assistant"}}]},
                  {"choices": [{"delta": {"reasoning": "Let me think about Japan"}}]},
                  {"choices": [{"delta": {"content": '{"steps": [], '}}]},
                  {"choices": [{"delta": {"content": '"say": "Tokyo."}'}}]},
                  {"choices": [], "usage": {"completion_tokens": 12}}]
        lines = [b"data: " + json.dumps(e).encode() for e in events] + [b"", b"data: [DONE]"]
        r = mock.Mock(iter_lines=lambda: iter(lines))
        seen = []
        text, usage, model = opencode._streamed(r, "m", seen.append, None)
        self.assertEqual(text, '{"steps": [], "say": "Tokyo."}')
        self.assertEqual(seen, ['{"steps": [], ', '{"steps": [], "say": "Tokyo."}'])
        self.assertEqual(usage, {"completion_tokens": 12})
        r.close.assert_called()

    def test_stop_ends_it_early(self):
        stop = threading.Event()
        lines = [b'data: {"choices": [{"delta": {"content": "a"}}]}'] * 5
        seen = []

        def on_text(text):
            seen.append(text)
            stop.set()
        opencode._streamed(mock.Mock(iter_lines=lambda: iter(lines)), "m", on_text, stop)
        self.assertEqual(seen, ["a"])

    def test_an_error_in_the_stream_is_an_error(self):
        lines = [b'data: {"error": {"message": "overloaded"}}']
        with self.assertRaises(RuntimeError):
            opencode._streamed(mock.Mock(iter_lines=lambda: iter(lines)), "m", lambda t: None, None)


class Tries(unittest.TestCase):
    """ask_model with opencode.chat faked: each fake try streams its reply, slowly or quickly."""

    def chat(self, behaviour):
        calls = []

        def chat(key, messages, model=None, on_text=None, stop=None, **kw):
            calls.append(model)
            delay, reply = behaviour[len(calls) - 1]
            time.sleep(delay)
            for so_far in stream_of(reply):
                if stop is not None and stop.is_set():
                    break
                on_text(so_far)
                time.sleep(0.01)
            return reply, {}, model
        return chat, calls

    def test_a_try_that_has_started_writing_gets_no_second_request(self):
        chat, calls = self.chat([(0.05, '{"steps": [], "say": "' + "word " * 40 + '"}')] * 3)
        with mock.patch.object(siri.opencode, "chat", chat):
            raw, _, _ = siri.ask_model([{"role": "user", "content": "hi"}], hedge_after=0.2)
        self.assertEqual(len(calls), 1)
        self.assertIn("word", raw)

    def test_one_that_hasnt_started_gets_a_second_and_the_first_to_answer_wins(self):
        chat, calls = self.chat([(1.0, '{"steps": [], "say": "slow"}'), (0.0, '{"steps": [], "say": "quick"}')])
        with mock.patch.object(siri.opencode, "chat", chat):
            raw, _, _ = siri.ask_model([{"role": "user", "content": "hi"}], hedge_after=0.2)
        self.assertEqual(len(calls), 2)
        self.assertIn("quick", raw)

    def test_the_answer_returned_is_the_one_she_is_saying(self):
        FakeLine.said = []
        said = '{"steps": [], "say": "The one being said aloud right now. Yes."}'
        other = '{"steps": [{"do": "open", "app": "Notepad"}], "say": ""}'
        chat, calls = self.chat([(0.0, said), (0.0, other)])
        live = siri.LiveSay(None, make=FakeLine)
        with mock.patch.object(siri.opencode, "chat", chat), mock.patch.object(siri, "MIC", [None]):
            raw, _, _ = siri.ask_model([{"role": "user", "content": "hi"}], hedge_after=0.01, live=live)
            self.assertEqual(raw, said)
            self.assertEqual(live.finish(), ["The one being said aloud right now.", "Yes."])


class Filler(unittest.TestCase):
    def test_a_slow_answer_gets_one_short_filler_and_a_quick_one_none(self):
        said = []
        with mock.patch.object(siri, "say", lambda line, notify: said.append(line)), \
                mock.patch.object(siri, "FILLER_AFTER", 0.05):
            siri.TURN_SPOKE.clear()
            siri.fill_silence("what's the capital of Japan", None)
            siri.fill_silence("what's the capital of Japan", None)  # never twice in a turn
            self.assertEqual(len(said), 1)
            self.assertIn(said[0], siri.REPLIES["filler_ask"])
            siri.TURN_SPOKE.clear()
            threading.Timer(0.01, siri.TURN_SPOKE.set).start()  # the answer came first
            siri.fill_silence("open notepad and write a poem", None)
            self.assertEqual(len(said), 1)


class PromptSize(unittest.TestCase):
    def test_the_fixed_part_of_her_prompt_stays_under_3000_tokens(self):
        """About 4 characters a token. Today's step list is most of it; memory and skills come on top (phase 4)."""
        fixed = siri.DEFAULT_SOUL + "\n\n" + siri.PROMPT
        self.assertLess(len(fixed) + 700, 12000)  # + the PC's context, about 630 characters


if __name__ == "__main__":
    unittest.main()
