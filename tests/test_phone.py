"""Jev on your phone (telegram_bot.py and the phone turns in siri): pairing, only your account, nothing late, her
questions answered only by a tap there, and a yes at the PC never answering a phone question. Telegram is faked."""
import asyncio
import datetime
import json
import os
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
    msg = SimpleNamespace(text=text, caption=None, voice=voice, audio=None, reply_text=reply_text, photo=(),
                          document=None,
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

    def test_a_send_from_the_bots_own_loop_doesnt_freeze_it(self):
        """"stop" from your phone during a task in an app: "Stopping." was sent from the message's own handler, which
        waited 30 s for the loop it was holding. No message or tap was taken meanwhile, and "Stopping." came late."""
        bot, sent = telegram_bot.Bot(on_message=None, on_tap=None), []

        async def send_message(chat, text, **kw):
            sent.append((chat, text))
        bot.app = SimpleNamespace(bot=SimpleNamespace(send_message=send_message))
        bot.loop = loop = asyncio.new_event_loop()

        async def handler():  # as phone_message runs, inside Bot._message
            start = time.time()
            ok = bot.send(7, "Stopping.")
            took = time.time() - start
            await asyncio.sleep(0.05)  # the loop free again: the send goes
            return ok, took
        try:
            ok, took = loop.run_until_complete(handler())
        finally:
            loop.close()
        self.assertTrue(ok)
        self.assertLess(took, 1.0)
        self.assertEqual(sent, [(7, "Stopping.")])

    def test_a_bad_token_is_said_once_and_it_stops(self):
        stops = []
        bot = telegram_bot.Bot(on_message=None, on_tap=None, on_stop=stops.append)
        with mock.patch.object(telegram_bot, "get_secret", lambda k: "t"),                 mock.patch.object(telegram_bot.Bot, "_poll", lambda self: "InvalidToken"):
            bot.start()
            bot.thread.join(5)
        self.assertEqual(stops, ["InvalidToken"])
        self.assertFalse(bot.running)


class Pictures(unittest.TestCase):
    """A photo you send her: downloaded on this PC, and what your words with it (or a moment after) are about."""

    def photo_update(self, caption=None, size=900):
        upd, replies = update(None)
        got = []

        async def download():
            return bytearray(b"jpeg picture")

        async def get_file():
            return SimpleNamespace(download_as_bytearray=download)
        sizes = [SimpleNamespace(width=w, height=w * 3 // 4, file_size=w * 100,
                                 get_file=(lambda w=w: (got.append(w), get_file())[1])) for w in (90, 320, size, 2560)]
        upd.effective_message.photo, upd.effective_message.document = sizes, None
        upd.effective_message.caption, upd.effective_message.media_group_id = caption, None
        return upd, replies, got

    def send_in(self, bot, upd):
        with mock.patch.dict(siri.settings._load(), {"telegram_owner": 7}):
            asyncio.run(bot._message(upd, Context()))

    def test_a_photo_goes_through_with_its_caption_at_a_readable_size(self):
        seen = []
        bot = telegram_bot.Bot(on_message=lambda *a: seen.append(a), on_tap=None)
        upd, _, got = self.photo_update("which is cheaper")
        with mock.patch.dict(siri.settings._load(), {"telegram_owner": 7}):
            asyncio.run(bot._message(upd, Context()))
        (text, chat, pictures, files), = seen
        self.assertEqual((text, chat, pictures), ("which is cheaper", 7, [(b"jpeg picture", "image/jpeg")]))
        self.assertEqual(got, [2560, 900])  # kept at its biggest to send on, looked at up to PICTURE_SIDE
        self.assertTrue(files[0].startswith(telegram_bot.files_dir()) and files[0].endswith(".jpg"))
        with open(files[0], "rb") as f:
            self.assertEqual(f.read(), b"jpeg picture")

    def test_a_stranger_s_photo_is_never_downloaded(self):
        bot = telegram_bot.Bot(on_message=lambda *a: None, on_tap=None)
        upd, _, got = self.photo_update("hi")
        upd.effective_user.id = 99
        with mock.patch.dict(siri.settings._load(), {"telegram_owner": 7}):
            asyncio.run(bot._message(upd, Context()))
        self.assertEqual(got, [])

    def test_an_album_is_one_message_with_its_caption(self):
        seen = []
        bot = telegram_bot.Bot(on_message=lambda *a: seen.append(a), on_tap=None)

        async def album():
            for caption in ("which is cheaper", None, None):
                upd, _, _ = self.photo_update(caption)
                upd.effective_message.media_group_id = "g1"
                await bot._message(upd, Context())
            await asyncio.sleep(telegram_bot.ALBUM_WAIT + 0.3)
        with mock.patch.dict(siri.settings._load(), {"telegram_owner": 7}),                 mock.patch.object(telegram_bot, "ALBUM_WAIT", 0.05):
            asyncio.run(album())
        self.assertEqual(len(seen), 1)
        self.assertEqual((seen[0][0], len(seen[0][2])), ("which is cheaper", 3))

    def test_gifs_and_stickers_are_said_so_never_answered_as_text(self):
        for field in ("animation", "sticker", "video_note"):
            seen = []
            bot = telegram_bot.Bot(on_message=lambda *a: seen.append(a), on_tap=None)
            upd, replies = update("and what about this one?")
            setattr(upd.effective_message, field, object())
            self.send_in(bot, upd)
            self.assertEqual(seen, [], field)
            self.assertIn("not GIFs or stickers", replies[0], field)

    @staticmethod
    def file(name, kind, size):
        async def download():
            return bytearray(b"the file")

        async def get_file():
            return SimpleNamespace(download_as_bytearray=download)
        return SimpleNamespace(file_name=name, mime_type=kind, file_size=size, get_file=get_file)

    def test_files_and_videos_are_kept_to_send_on_but_not_looked_at(self):
        for field, item in (("document", self.file("report.pdf", "application/pdf", 2000)),
                            ("document", self.file("big photo.jpg", "image/jpeg", 6 * 1024 * 1024)),
                            ("document", self.file("x.heic", "image/heic", 10)),
                            ("video", self.file(None, "video/mp4", 5000))):
            seen = []
            bot = telegram_bot.Bot(on_message=lambda *a: seen.append(a), on_tap=None)
            upd, _ = update("send this to amma")
            setattr(upd.effective_message, field, item)
            self.send_in(bot, upd)
            (text, chat, pictures, files), = seen
            self.assertEqual((text, pictures), ("send this to amma", []), item.file_name)
            self.assertTrue(os.path.isfile(files[0]), item.file_name)
            if item.file_name:
                self.assertEqual(os.path.basename(files[0]), item.file_name)

    def test_over_twenty_mb_is_said_so(self):
        seen = []
        bot = telegram_bot.Bot(on_message=lambda *a: seen.append(a), on_tap=None)
        upd, replies = update("send this to amma")
        upd.effective_message.document = self.file("film.mp4", "video/mp4", 30 * 1024 * 1024)
        self.send_in(bot, upd)
        self.assertEqual(seen, [])
        self.assertIn("over 20 MB", replies[0])

    def test_the_model_sees_it_on_the_phone_only(self):
        siri.PHONE_PICTURES[7] = ([siri.picture_url(b"x")], time.time())
        self.addCleanup(siri.PHONE_PICTURES.clear)
        sent = []
        plan = {"steps": [], "say": "The left one."}

        def ask(messages, **kw):
            sent.append(messages[-1]["content"])
            return json.dumps(plan), dict(plan), {}, "test"
        with mock.patch.object(siri, "ask_plan", ask), mock.patch.object(siri, "context", return_value=""):
            to, chat = siri.REPLY_TO.set([]), siri.PHONE_CHAT.set(7)
            try:
                siri.think("which is cheaper", False)
            finally:
                siri.REPLY_TO.reset(to)
                siri.PHONE_CHAT.reset(chat)
            siri.think("which is cheaper", False)  # at the PC
        self.assertEqual(sent[0][1]["image_url"]["url"], "data:image/jpeg;base64,eA==")
        self.assertIn("which is cheaper", sent[0][0]["text"])
        self.assertEqual(sent[1], "which is cheaper")

    def test_an_old_picture_is_forgotten(self):
        siri.PHONE_PICTURES[7] = ([siri.picture_url(b"x")], time.time() - siri.PICTURE_FOR - 1)
        self.addCleanup(siri.PHONE_PICTURES.clear)
        to, chat = siri.REPLY_TO.set([]), siri.PHONE_CHAT.set(7)
        try:
            self.assertIsNone(siri.phone_picture())
        finally:
            siri.REPLY_TO.reset(to)
            siri.PHONE_CHAT.reset(chat)
        self.assertNotIn(7, siri.PHONE_PICTURES)  # and let go of

    def phone_turn(self, words, plan):
        """handle() on the phone with a picture sent a minute ago: (her lines, whether it looked at the screen)."""
        siri.PHONE_PICTURES[7] = ([siri.picture_url(b"x")], time.time() - 60)
        self.addCleanup(siri.PHONE_PICTURES.clear)
        lines, looked = [], []
        with mock.patch.object(siri, "ask_plan", return_value=(json.dumps(plan), dict(plan), {}, "test")),                 mock.patch.object(siri, "context", return_value=""),                 mock.patch.object(siri, "learn_later", lambda *a, **k: None),                 mock.patch.object(siri, "see", lambda task, notify=None: looked.append(task) or ("Done.", [])):
            to, chat = siri.REPLY_TO.set(lines), siri.PHONE_CHAT.set(7)
            try:
                siri.handle(words, words)
            finally:
                siri.REPLY_TO.reset(to)
                siri.PHONE_CHAT.reset(chat)
        return lines, looked

    def test_the_pc_screen_is_still_the_pc_screen(self):
        _, looked = self.phone_turn("what's on my screen", {"steps": [], "say": "A phone."})
        self.assertTrue(looked)

    def test_what_a_picture_says_cant_change_things_without_a_yes(self):
        lines, _ = self.phone_turn("what should I do about this", {"steps": [{"do": "lock"}], "say": "Locking."})
        self.assertTrue(lines and lines[-1].endswith("?"), lines)  # asked first, with the phone's buttons
        siri.PENDING.update(plan=None, until=0.0, origin="voice")


class Answers(unittest.TestCase):
    """A question that needs looking up gets an answer, never "say that again"; typed, nothing was misheard."""

    def test_after_the_last_look_it_answers(self):
        looks, asked = [], []

        def ask(messages, **kw):
            asked.append(messages[-1]["content"])
            p = {"steps": [{"do": "web", "query": f"phones {len(asked)}"}], "say": ""}
            return json.dumps(p), p, {}, "test"
        with mock.patch.object(siri, "ask_plan", ask), mock.patch.object(siri, "context", return_value=""),                 mock.patch.object(siri, "run_info", lambda info, *a: looks.append(info) or "[]"):
            plan = siri.think("best phone under 20000", False)
        self.assertEqual(len(looks), siri.ROUNDS)
        self.assertIn("last look-up", asked[-1])  # told before its last go
        self.assertNotIn("last look-up", asked[-2])
        self.assertIn(plan["say"], siri.REPLIES["looked_no_answer"])  # and if it still wants more, says so
        self.assertEqual(plan["steps"], [])

    def test_without_her_name_she_stays_quiet_instead(self):
        def ask(messages, **kw):
            p = {"steps": [{"do": "web", "query": "match"}], "say": ""}
            return json.dumps(p), p, {}, "test"
        with mock.patch.object(siri, "ask_plan", ask), mock.patch.object(siri, "context", return_value=""),                 mock.patch.object(siri, "run_info", lambda info, *a: "[]"):
            for gate in (True, "cold"):
                plan = siri.think("who won the match yesterday", gate)
                self.assertEqual((plan["steps"], plan["say"]), ([], ""), gate)
                self.assertIsNotNone(siri.let_go(plan), gate)

    def test_on_the_phone_nothing_was_misheard(self):
        plan = {"steps": [], "say": ""}
        lines = []
        with mock.patch.object(siri, "ask_plan", return_value=(json.dumps(plan), plan, {}, "test")),                 mock.patch.object(siri, "context", return_value=""),                 mock.patch.object(siri, "learn_later", lambda *a, **k: None):
            to = siri.REPLY_TO.set(lines)
            try:
                siri.handle("M17 e or M17", "M17 e or M17")
            finally:
                siri.REPLY_TO.reset(to)
        self.assertIn(lines[0], siri.REPLIES["not_worked_out"])


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
