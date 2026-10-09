"""Faster answers: a plain answer said as the model writes it (LiveSay), the streamed reply (opencode._streamed), a
second try only when the first hasn't started writing (ask_model), a "One moment" when she's slow (fill_silence),
and the prompt kept small. No model, voice or network: fakes throughout."""
import ast
import contextlib
import io
import json
import os
import threading
import time
import unittest
from unittest import mock

from tests.support import ROOT, siri

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
                      '{"say": "Said before the steps. Not this.", "steps": []}',
                      'Sure. {"steps": [{"do": "open", "app": "Notepad"}], "say": "Opening Notepad for you now."}'):
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

    def test_plain_words_that_turn_into_a_plan_leave_the_answer_to_another_try(self):
        live = siri.LiveSay(None, make=FakeLine)
        self.run_reply('Sure. {"steps": [{"do": "open", "app": "Notepad"}], "say": "Opening it."}', key=0, live=live)
        self.run_reply("Tokyo is the capital of Japan. It is also the biggest city there.", key=1, live=live)
        self.assertEqual(live.finish(), ["Tokyo is the capital of Japan.", "It is also the biggest city there."])


class Unnamed(unittest.TestCase):
    """P1: with Answer without her name on, 149 of 150 voice turns had no name, and not one of 113 was said as it was
    written or got a "One moment": think streamed only with her name, and only a reply that began {"steps": [],
    "say": ", where the answer model answered 18 of 89 questions in plain words. Never said over people talking in the
    room."""

    def setUp(self):
        FakeLine.said = []
        for target, name, value in ((siri, "skills_block", lambda *a: ""), (siri, "memory_block", lambda: ""),
                                    (siri, "context", lambda: ""), (siri, "soul", lambda: "You are Jev."),
                                    (siri, "Line", FakeLine), (siri, "MIC", [None]), (siri, "STREAM_SAY", True),
                                    (siri, "media_playing", lambda: False),
                                    (siri.history, "recent", lambda *a, **k: [])):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        siri.TURN_SPOKE.clear()
        siri.FOR_HER.clear()
        self.addCleanup(siri.FOR_HER.set)
        self.addCleanup(siri.TURN_SPOKE.set)

    def think(self, words, gate, reply):
        """(the plan, sentences she'd begun saying as each piece of the reply came)."""
        heard = []

        def chat(key, messages, model=None, on_text=None, stop=None, **kw):
            for so_far in stream_of(reply):
                on_text(so_far)
                time.sleep(0.01)
                heard.append(len(FakeLine.said))
            return reply, {}, model
        with mock.patch.object(siri.opencode, "chat", chat), contextlib.redirect_stdout(io.StringIO()):
            return siri.think(words, gate), heard

    def test_an_answer_to_her_without_her_name_is_said_as_it_comes(self):
        for gate, reply in (("cold", '{"to": "you", "steps": [], "say": "Tokyo is the capital of Japan. It is also '
                                     'the biggest city there, with about fourteen million people."}'),
                            (True, '{"steps": [], "say": "Tokyo is the capital of Japan. It is also the biggest city '
                                   'there, with about fourteen million people."}')):
            with self.subTest(gate=gate):
                FakeLine.said = []
                plan, heard = self.think("what's the capital of Japan", gate, reply)
                self.assertGreater(heard[-5], 0)  # before the reply was all in
                self.assertEqual(plan["said"], ["Tokyo is the capital of Japan.",
                                                "It is also the biggest city there, with about fourteen million people."])
                self.assertTrue(siri.FOR_HER.is_set())

    def test_plain_words_are_said_as_they_come(self):
        plan, heard = self.think("what's the capital of Japan", False,
                                 "Tokyo is the capital of Japan. It is also the biggest city there, with about "
                                 "fourteen million people.")
        self.assertGreater(heard[-5], 0)
        self.assertEqual(len(plan["said"]), 2)

    def test_talk_to_others_and_what_she_would_let_go_are_never_said(self):
        for gate, reply in (("cold", '{"to": "others"}'), (True, '{"ignore": true}'),
                            ("cold", "Sorry, I didn't catch that. Could you say it again for me?"),
                            ("cold", '{"to": "you", "steps": [], "say": "That sounded like it was meant for someone '
                                     'else in the room. Carry on."}'),
                            # words before the JSON, or "to" put last: said over the room before the reply was in
                            ("cold", 'He is asking someone in the room why they are late today.\n{"to": "others"}'),
                            ("cold", 'This sounds like a chat between people in the room, not a request. I will stay '
                                     'out of it. {"to": "others"}'),
                            (True, 'This sounds like part of a conversation in the room, so I will ignore it.\n'
                                   '{"ignore": true}'),
                            ("cold", '{"steps": [], "say": "Traffic was bad, sorry about that. It took an hour.", '
                                     '"to": "others"}')):
            with self.subTest(gate=gate, reply=reply):
                siri.FOR_HER.clear()
                self.think("why are you so late today", gate, reply)
                self.assertEqual(FakeLine.said, [])
                self.assertEqual(siri.FOR_HER.is_set(), reply.startswith('{"to": "you"'))  # else no "One moment"

    def test_not_while_something_plays_that_the_mic_hears(self):
        with mock.patch.object(siri, "media_playing", lambda: True):
            plan, _ = self.think("what's the capital of Japan", "cold",
                                 '{"to": "you", "steps": [], "say": "Tokyo is the capital of Japan. It is big."}')
        self.assertEqual(FakeLine.said, [])
        self.assertNotIn("said", plan)

    def test_plain_words_then_a_plan_still_say_the_plans_line(self):
        plan, _ = self.think("open notepad", False, 'Here is what I will do now. I will open it for you right now. '
                                                    '{"steps": [], "say": "Notepad is open."}')
        self.assertEqual(FakeLine.said, ["Here is what I will do now."])
        self.assertNotIn("said", plan)  # so run_plan says "Notepad is open." too
        self.assertEqual(plan["say"], "Notepad is open.")

    def test_a_promise_just_ahead_of_its_plan_is_not_said(self):
        """Said before the message was staged and read back for a yes: what the plan does is said once it's done."""
        plan, _ = self.think("message mum on whatsapp i'm late", False,
                             'Sure, I will send that message to Mum right now.\n{"steps": [{"do": "message", "app": '
                             '"whatsapp", "contact": "Mum", "text": "I\'m late"}], "say": ""}')
        self.assertEqual(FakeLine.said, [])
        self.assertEqual(plan["steps"][0]["do"], "message")

    def test_a_long_plain_answer_is_cut_as_tidy_cuts_it(self):
        reply = " ".join(f"The Mughal empire did a notable thing number {n} in its long history." for n in range(8))
        plan, _ = self.think("tell me about the mughal empire", False, reply)
        self.assertEqual(" ".join(FakeLine.said), siri.tidy(reply))
        self.assertEqual(len(plan["said"]), 3)
        FakeLine.said = []
        short = "One. Two is here. Three is here too. Four is here as well. Five, and that is all of it."
        plan, _ = self.think("count to five", False, short)
        self.assertEqual(" ".join(FakeLine.said), siri.tidy(short))  # all of it, as tidy keeps a short one

    def test_a_model_that_runs_out_of_time_leaves_no_half_sentence(self):
        for gate, reply in ((False, "Tokyo is the cap"), ("cold", '{"to": "you", "steps": [], "say": "He is asking '
                                                                   'his fri'),
                            (False, '{"steps": [], "say": "Tokyo is the capital of Japan. It is also the bigg')):
            with self.subTest(reply=reply):
                FakeLine.said = []

                def ask_plan(messages, live=None, **kw):
                    for so_far in stream_of(reply):
                        live.feed(0, so_far)
                    raise TimeoutError("the model took too long")
                with mock.patch.object(siri, "ask_plan", ask_plan), contextlib.redirect_stdout(io.StringIO()), \
                        self.assertRaises(TimeoutError):
                    siri.think("what's the capital of Japan", gate)
                self.assertEqual(FakeLine.said, ["Tokyo is the capital of Japan."] if "bigg" in reply else [])

    def test_a_question_back_after_not_for_me_is_said_in_full(self):
        """As let_go has it: "I thought you were talking to someone else" with a question is to you."""
        plan, _ = self.think("can you help", "cold", '{"to": "you", "steps": [], "say": "Sure, I can help with that '
                                                     'one. I thought you were talking to someone else at first. What '
                                                     'do you need?"}')
        self.assertEqual(len(plan["said"]), 3)

    def test_what_plays_is_asked_about_alongside_the_request_not_ahead_of_it(self):
        sent = threading.Event()
        before = []

        def playing():
            before.append(sent.wait(1))  # Windows' media controls, slow to answer
            return False

        def chat(key, messages, model=None, on_text=None, stop=None, **kw):
            sent.set()
            reply = '{"to": "you", "steps": [], "say": "Tokyo is the capital of Japan. It is big."}'
            for so_far in stream_of(reply):
                on_text(so_far)
            return reply, {}, model
        with mock.patch.object(siri, "media_playing", playing), mock.patch.object(siri.opencode, "chat", chat), \
                contextlib.redirect_stdout(io.StringIO()):
            plan = siri.think("what's the capital of Japan", "cold")
        self.assertEqual(before, [True])  # the request had gone out
        self.assertEqual(len(plan["said"]), 2)

    def test_one_moment_without_her_name_only_once_the_reply_shows_its_for_her(self):
        said = []
        with mock.patch.object(siri, "say", lambda line, notify: said.append(line)), \
                mock.patch.object(siri, "FILLER_AFTER", 0.05):
            for reply, after in (('{"to": "others"}', 0), ('{"to": "you", "steps": [{"do": "web"', 1)):
                siri.TURN_SPOKE.clear()
                siri.FOR_HER.clear()
                said.clear()
                filler = threading.Thread(target=siri.fill_silence, args=("what's the capital of Japan", None))
                filler.start()
                time.sleep(0.15)  # slow to answer, but it may be someone else's conversation
                self.assertEqual(said, [])
                siri.LiveSay(None, make=FakeLine, gate="cold").feed(0, reply)
                time.sleep(0.05)
                siri.TURN_SPOKE.set()  # the turn is over (handle)
                siri.FOR_HER.set()
                filler.join(1)
                self.assertEqual(len(said), after)
                self.assertTrue(all(line in siri.REPLIES["filler_ask"] for line in said))

    def test_a_turn_without_her_name_gets_one_too(self):
        said = []

        def think(words, gate, notify=None, sure=1.0, reply='{"to": "you", "steps": [{"do": "web"'):
            siri.LiveSay(None, make=FakeLine, gate=gate).feed(0, reply)  # her model, slow to look it up
            time.sleep(0.2)
            return siri.make_plan(say="Tokyo.") if "you" in reply else None
        for gate, reply, after in (("cold", '{"to": "you", "steps": [{"do": "web"', 1), ("cold", '{"to": "others"}', 0),
                                   (False, "", 1)):
            with self.subTest(gate=gate, reply=reply), \
                    mock.patch.object(siri, "think", lambda w, g, n=None, s=1.0: think(w, g, n, s, reply)), \
                    mock.patch.object(siri, "say", lambda line, notify: said.append(line)), \
                    mock.patch.object(siri, "FILLER_AFTER", 0.05), \
                    mock.patch.object(siri, "run_plan", lambda plan, notify: ([], False, None, [])), \
                    mock.patch.object(siri, "learn_later"), mock.patch.object(siri.history, "add"), \
                    mock.patch.dict(siri.PENDING, {"plan": None, "until": 0.0}), \
                    contextlib.redirect_stdout(io.StringIO()):
                said.clear()
                siri.handle("what's the capital of Japan", gate=gate)
                time.sleep(0.05)
                self.assertEqual(len(said), after)


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


class Startup(unittest.TestCase):
    def test_her_compiled_code_is_kept_whatever_python_was_told(self):
        """Her modules' cached bytecode was found stale, as if she ran with PYTHONDONTWRITEBYTECODE or -B: each start
        compiled her 24k lines again. app.py turns writing it back on before it imports any of them."""
        with open(os.path.join(ROOT, "app.py"), encoding="utf-8") as f:
            tree = ast.parse(f.read())
        before = []
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) or (isinstance(node, ast.Import) and
                                                    any(a.name not in ("os", "sys") for a in node.names)):
                break  # the first of her own modules
            before.append(ast.unparse(node))
        self.assertIn("sys.dont_write_bytecode = False", before)


class PromptSize(unittest.TestCase):
    def test_the_fixed_part_of_her_prompt_stays_under_3000_tokens(self):
        """About 4 characters a token. Today's step list is most of it; memory and skills come on top (phase 4)."""
        fixed = siri.DEFAULT_SOUL + "\n\n" + siri.PROMPT
        self.assertLess(len(fixed) + 700, 12000)  # + the PC's context, about 630 characters


if __name__ == "__main__":
    unittest.main()
