"""Jev on your phone (telegram_bot.py and the phone turns in siri): pairing, only your account, nothing late, her
questions answered only by a tap there, and a yes at the PC never answering a phone question. Telegram is faked."""
import asyncio
import datetime
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.support import siri

import telegram_bot


def update(text="hi", user_id=7, chat_type="private", ago=0, voice=None):
    replies = []

    async def reply_text(t, **kw):
        replies.append(t)
    msg = SimpleNamespace(text=text, caption=None, voice=voice, audio=None, reply_text=reply_text,
                          date=datetime.datetime.fromtimestamp(time.time() - ago, datetime.timezone.utc))
    u = SimpleNamespace(effective_message=msg, effective_user=SimpleNamespace(id=user_id, first_name="Hari",
                                                                              last_name=None, username="hari"),
                        effective_chat=SimpleNamespace(type=chat_type, id=user_id))
    return u, replies


class Context:
    def __init__(self):
        self.sent = []

        async def send_message(chat, text, **kw):
            self.sent.append((chat, text))
        self.bot = SimpleNamespace(send_message=send_message)


class Pairing(unittest.TestCase):
    def test_the_right_code_pairs_once(self):
        p = telegram_bot.Pairing()
        self.assertIsNone(p.request(7, "Hari"))  # not open: no code
        p.start()
        code = p.request(7, "Hari")
        self.assertEqual(len(code), 8)
        self.assertNotIn(code, str(p.pending))  # only its hash is kept
        self.assertEqual(p.confirm("WRONG123"), (None, "wrong"))
        paired, why = p.confirm(" ".join(code.lower()))  # spaces between letters, small letters: still fine
        self.assertEqual((paired["user_id"], why), (7, "ok"))
        self.assertEqual(p.confirm(code), (None, "none"))  # used up

    def test_a_strangers_start_doesnt_knock_out_your_code(self):
        p = telegram_bot.Pairing()
        p.start()
        yours = p.request(7, "Hari")
        p.request(99, "someone")
        paired, why = p.confirm(yours)
        self.assertEqual((paired["user_id"], why), (7, "ok"))

    def test_no_more_than_three_waiting(self):
        p = telegram_bot.Pairing()
        p.start()
        self.assertTrue(all(p.request(u, "x") for u in (1, 2, 3)))
        self.assertIsNone(p.request(4, "x"))
        self.assertTrue(p.request(2, "x"))  # one already waiting may ask again

    def test_five_wrong_codes_lock_it(self):
        p = telegram_bot.Pairing()
        p.start()
        p.request(7, "Hari")
        for _ in range(telegram_bot.MAX_FAILED_ATTEMPTS - 1):
            self.assertEqual(p.confirm("AAAAAAAA")[1], "wrong")
        self.assertEqual(p.confirm("AAAAAAAA")[1], "locked")
        self.assertFalse(p.open)


class Messages(unittest.TestCase):
    def bot(self):
        got, pairs = [], []
        bot = telegram_bot.Bot(on_message=lambda text, chat: got.append((text, chat)), on_tap=lambda *a: got.append(a),
                               on_pair=pairs.append)
        return bot, got, pairs

    def run_message(self, bot, upd, owner=None):
        ctx = Context()
        with mock.patch.dict(siri.settings._load(), {"telegram_owner": owner}):
            asyncio.run(bot._message(upd, ctx))
        return ctx

    def test_before_pairing_a_start_gets_how_to_pair_or_a_code_and_nothing_else_runs(self):
        bot, got, pairs = self.bot()
        upd, replies = update("/start")
        self.run_message(bot, upd)
        self.assertIn("press Pair", replies[0])  # pairing not open: how to open it, never silence
        upd, replies = update("/start")
        self.run_message(bot, upd)
        self.assertEqual(replies, [])  # and only once
        self.run_message(bot, update("shut down the pc")[0])
        bot.pairing.start()
        self.run_message(bot, update("shut down the pc")[0])
        self.assertEqual(got, [])  # nothing but /start, ever, before pairing
        upd, replies = update("/start")
        self.run_message(bot, upd)
        self.assertIn("Your code is", replies[0])
        self.assertEqual(pairs, ["Hari (@hari)"])

    def test_once_paired_only_you_and_strangers_are_told_about_once(self):
        bot, got, _ = self.bot()
        self.run_message(bot, update("what's the weather")[0], owner=7)
        self.assertEqual(got, [("what's the weather", 7)])
        ctx1 = self.run_message(bot, update("hello", user_id=99)[0], owner=7)
        ctx2 = self.run_message(bot, update("hello again", user_id=99)[0], owner=7)
        self.assertEqual(len(got), 1)
        self.assertEqual([c for c, _ in ctx1.sent], [7])  # you hear about it, once
        self.assertEqual(ctx2.sent, [])

    def test_late_messages_and_group_chats_are_dropped(self):
        bot, got, _ = self.bot()
        self.run_message(bot, update("shut down the pc", ago=8 * 3600)[0], owner=7)
        self.run_message(bot, update("open notepad", chat_type="group")[0], owner=7)
        self.assertEqual(got, [])

    def test_only_your_taps_count(self):
        bot, got, _ = self.bot()
        answered = []

        async def answer():
            answered.append(1)
        for user_id in (99, 7):
            q = SimpleNamespace(data="yes:4", answer=answer, message=SimpleNamespace(chat_id=7, message_id=50))
            with mock.patch.dict(siri.settings._load(), {"telegram_owner": 7}):
                asyncio.run(bot._tap(SimpleNamespace(callback_query=q,
                                                     effective_user=SimpleNamespace(id=user_id)), None))
        self.assertEqual(got, [(True, "4", 7, 50)])
        self.assertEqual(len(answered), 2)  # every tap gets its spinner stopped


class Fixes(unittest.TestCase):
    """What the check of the fix found: a restart that was lost, a revoked token going unnoticed, strangers' codes
    keeping yours out, a second tap, and right Alt over the sentence you're reading."""

    def test_pressing_pair_again_clears_strangers_codes_and_a_closed_pairing_takes_none(self):
        p = telegram_bot.Pairing()
        p.start()
        for u in (1, 2, 3):
            p.request(u, "stranger")
        self.assertIsNone(p.request(7, "Hari"))  # busy
        p.start()  # Pair again
        code = p.request(7, "Hari")
        self.assertTrue(code)
        p.until = time.time() - 1  # the 10 minutes are up
        self.assertEqual(p.confirm(code), (None, "none"))

    def test_locked_pairing_doesnt_open(self):
        p = telegram_bot.Pairing()
        p.locked_until = time.time() + 3000
        self.assertFalse(p.start())
        self.assertGreaterEqual(p.minutes_left, 49)

    def test_a_busy_pairing_is_said_on_both_ends(self):
        pairs = []
        bot = telegram_bot.Bot(on_message=None, on_tap=None, on_pair=pairs.append)
        bot.pairing.start()
        for u in (1, 2, 3):
            bot.pairing.request(u, "stranger")
        upd, replies = update("/start")
        with mock.patch.dict(siri.settings._load(), {"telegram_owner": None}):
            asyncio.run(bot._message(upd, Context()))
        self.assertIn("press Pair again", replies[0])
        self.assertEqual(pairs, [None])

    def test_a_second_tap_on_the_same_question_does_nothing(self):
        got = []
        bot = telegram_bot.Bot(on_message=None, on_tap=lambda *a: got.append(a))

        async def answer():
            pass
        for _ in range(2):
            q = SimpleNamespace(data="yes:4", answer=answer, message=SimpleNamespace(chat_id=7, message_id=50))
            with mock.patch.dict(siri.settings._load(), {"telegram_owner": 7}):
                asyncio.run(bot._tap(SimpleNamespace(callback_query=q, effective_user=SimpleNamespace(id=7)), None))
        self.assertEqual(len(got), 1)

    def test_a_token_revoked_while_listening_stops_it_with_why(self):
        from telegram.error import InvalidToken
        bot = telegram_bot.Bot(on_message=None, on_tap=None)
        loop = asyncio.new_event_loop()

        async def polling():
            await asyncio.sleep(0.05)
            raise InvalidToken()
        try:
            loop.create_task(polling(), name=telegram_bot.POLLING)
            loop.create_task(bot._watch())
            loop.call_later(5, loop.stop)  # a backstop: the test fails rather than hangs
            loop.run_forever()
        finally:
            loop.close()
        self.assertEqual(bot.why, "InvalidToken")

    def test_restart_while_stopping_starts_again_and_stop_ends_a_stuck_start(self):
        """Telegram unreachable as it starts (the library retries for ever): a new token still gets used."""
        polls, gate = [], __import__("threading").Event()

        def poll(bot):
            polls.append(1)
            loop = asyncio.new_event_loop()
            with bot.lock:
                if bot.stopping:
                    loop.close()
                    return ""
                bot.loop = loop
            try:  # stands in for run_polling stuck getting going: run_until_complete on what never finishes
                gate.set()
                loop.run_until_complete(asyncio.sleep(3600))
            except RuntimeError:
                return "RuntimeError"
            finally:
                bot.loop = None
                loop.close()
            return ""
        bot = telegram_bot.Bot(on_message=None, on_tap=None)
        with mock.patch.object(telegram_bot, "get_secret", lambda k: "t"),                 mock.patch.object(telegram_bot.Bot, "_poll", poll):
            self.assertTrue(bot.start())
            self.assertTrue(gate.wait(5))
            gate.clear()
            self.assertTrue(bot.restart())  # doesn't wait: stops the stuck one, then starts again
            self.assertTrue(gate.wait(5))
            self.assertEqual(len(polls), 2)
            bot.stop()
            self.assertFalse(bot.running)
            self.assertTrue(bot.start())  # and a start after a stop starts afresh
            self.assertTrue(gate.wait(5))
            bot.stop()
        self.assertEqual(len(polls), 3)

    def test_a_bad_token_is_said_once_and_it_stops(self):
        stops = []
        bot = telegram_bot.Bot(on_message=None, on_tap=None, on_stop=stops.append)
        with mock.patch.object(telegram_bot, "get_secret", lambda k: "t"),                 mock.patch.object(telegram_bot.Bot, "_poll", lambda self: "InvalidToken"):
            bot.start()
            bot.thread.join(5)
        self.assertEqual(stops, ["InvalidToken"])
        self.assertFalse(bot.running)


class Questions(unittest.TestCase):
    """A question asked on the phone waits for its tap; a yes said at the PC, or typed, doesn't answer it."""

    def setUp(self):
        self.ran = []
        def run_plan(plan, notify):
            self.ran.append(plan)
            if plan.get("say"):
                siri.say(plan["say"], notify)
            return [], False, None, [plan.get("say") or ""]
        for name, value in (("run_plan", run_plan), ("learn_later", lambda *a, **k: None)):
            p = mock.patch.object(siri, name, value)
            p.start()
            self.addCleanup(p.stop)
        siri.PENDING.update(plan={"steps": [{"do": "shutdown"}], "say": ""}, until=time.time() + 60,
                            soon=time.time() + 60, origin="phone", id=4)
        self.addCleanup(siri.PENDING.update, plan=None, until=0.0, origin="voice")

    def turn(self, text, phone=False, tapped=False):
        lines = []
        to = siri.REPLY_TO.set(lines if phone else None)
        tap = siri.TAPPED.set(tapped)
        try:
            with mock.patch.object(siri, "think", lambda *a, **k: siri.make_plan(say="Okay.")):
                siri.handle(text, text)
        finally:
            siri.REPLY_TO.reset(to)
            siri.TAPPED.reset(tap)
        return lines

    def ran_shutdown(self):
        return any(s.get("do") == "shutdown" for p in self.ran for s in p.get("steps") or [])

    def test_a_yes_at_the_pc_doesnt_answer_the_phone(self):
        self.turn("yes")
        self.assertFalse(self.ran_shutdown())
        self.assertIsNotNone(siri.PENDING["plan"])  # still waiting for the phone

    def test_a_typed_yes_doesnt_either_only_the_tap(self):
        self.turn("yes", phone=True)
        self.assertFalse(self.ran_shutdown())
        self.turn("yes", phone=True, tapped=True)
        self.assertTrue(self.ran_shutdown())

    def test_on_the_phone_her_lines_go_back_to_the_chat(self):
        siri.PENDING.update(plan=None)
        lines = self.turn("what's the capital of Japan", phone=True)
        self.assertEqual(lines, ["Okay."])


if __name__ == "__main__":
    unittest.main()
