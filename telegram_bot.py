"""Jev on your phone, through a Telegram bot of your own: make one with @BotFather, paste its token in Keys, then
Settings > Phone > Pair.

Only your Telegram account can use it, and it fails closed: until you've paired, all it answers is /start, with a
code while a pairing is open (10 minutes from pressing Pair), else with how to open one, and nothing else ever runs;
after, everyone else is ignored (and you're told once about each). Pairing is Hermes Agent's (gateway/pairing.py, see
hermes_memory/gateway_bits.py): you send /start, the bot answers with an 8-letter code, and you type that into Jev's
window on the PC, which proves you have both. The code is kept only hashed, works only while its pairing is open,
and 5 wrong ones lock pairing for an hour.

It asks Telegram for new messages (long polling): nothing on this PC is open to the internet. Only private chats,
only messages and button taps; anything sent while the PC was off or asleep, or more than 2 minutes ago, is dropped,
never run late: a "shut down" from last night must not run this morning. Risky steps come back as a question with
Yes and No buttons, and only a tap answers it. A voice note is written out by the speech-to-text on this PC, never
a cloud service (it does pass through Telegram's servers, as every Telegram voice note does). Long replies are split
the way Hermes splits them. Runs on its own thread, so voice turns aren't held up.
"""
import asyncio
import io
import logging
import os
import secrets
import threading
import time

import numpy as np

import settings
from hermes_memory.gateway_bits import (ALPHABET, CODE_LENGTH, CODE_TTL_SECONDS, LOCKOUT_SECONDS, MAX_FAILED_ATTEMPTS,
                                        _hash_code, truncate_message, utf16_len)
from secrets_store import get_secret

TOKEN = "TELEGRAM_BOT_TOKEN"
OLDEST = 120  # seconds: a message older than this is dropped
PAIR_FOR = 600  # seconds a pairing stays open after you press Pair
POLLING = "Updater:start_polling:polling_task"  # python-telegram-bot's name for the task asking for messages (22.8)
for _name in ("httpx", "httpcore", "telegram", "telegram.ext"):
    logging.getLogger(_name).setLevel(logging.WARNING)  # httpx logs every URL, and the token is in them


class _HideToken(logging.Filter):
    """Hermes' token redaction: the bot's token never reaches the log, not even inside an error the library logs
    ("The token `...` was rejected by the server")."""

    secrets = set()  # every token used this session: a new one pasted in Keys is hidden too, the old one still

    def filter(self, record):
        if not self.secrets:
            return True
        if record.exc_info:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
        msg = record.getMessage()
        for secret in self.secrets:
            msg = msg.replace(secret, "<token>")
            if record.exc_text:
                record.exc_text = record.exc_text.replace(secret, "<token>")
        record.msg, record.args = msg, ()
        return True


def _hide_token(secret):
    """On every place a log line can end up: the root logger's handlers, and Python's last-resort one."""
    if secret:
        _HideToken.secrets.add(secret)
    for handler in [*logging.getLogger().handlers, logging.lastResort]:
        if handler is not None and not any(isinstance(f, _HideToken) for f in handler.filters):
            handler.addFilter(_HideToken())


def owner():
    """Your Telegram user ID once paired, else None."""
    try:
        return int(settings.get("telegram_owner") or 0) or None
    except (TypeError, ValueError):
        return None


def who(user):
    """A person as Telegram shows them: their name and @username."""
    name = " ".join(x for x in (user.first_name, user.last_name) if x) or "someone"
    return f"{name} (@{user.username})" if user.username else name


MAX_PENDING = 3  # Hermes' MAX_PENDING_PER_PLATFORM: codes waiting at once, one per account


class Pairing:
    """Hermes' pairing rules: the code from its alphabet (no 0/O, 1/I), kept as a salted hash, one waiting code per
    account and 3 at most, and after 5 wrong codes no pairing for an hour. A code is only given, and only works,
    while a pairing is open, PAIR_FOR seconds from pressing Pair; pressing it again starts afresh, so codes strangers
    asked for can't hold the places and keep yours out."""

    def __init__(self):
        self.until, self.pending, self.fails, self.locked_until = 0.0, {}, 0, 0.0

    @property
    def open(self):
        return time.time() < self.until and not self.locked

    @property
    def locked(self):
        return time.time() < self.locked_until

    @property
    def minutes_left(self):
        """Of the pairing open now, or of the lock after too many wrong codes."""
        return max(1, round(((self.locked_until if self.locked else self.until) - time.time()) / 60))

    def start(self):
        """Opens pairing for PAIR_FOR seconds, every code given before gone. False while it's locked."""
        if self.locked:
            return False
        self.until, self.pending = time.time() + PAIR_FOR, {}
        return True

    def _fresh(self):
        now = time.time()
        self.pending = {u: p for u, p in self.pending.items() if now - p["at"] <= CODE_TTL_SECONDS} if self.open \
            else {}

    def request(self, user_id, name):
        """A /start: the code to send back, or None: pairing isn't open, or 3 others are waiting (busy)."""
        self._fresh()
        if not self.open or (len(self.pending) >= MAX_PENDING and int(user_id) not in self.pending):
            return None
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        salt = os.urandom(16)
        self.pending[int(user_id)] = {"hash": _hash_code(code, salt), "salt": salt, "user_id": int(user_id),
                                      "name": name, "at": time.time()}
        return code

    def confirm(self, code):
        """(the account paired, or None, why): "ok", "wrong", "locked" or "none" (no code waiting)."""
        if self.locked:
            return None, "locked"
        self._fresh()
        if not self.pending:
            return None, "none"
        code = "".join(str(code or "").upper().split())  # spaces between letters are fine
        for p in self.pending.values():
            if secrets.compare_digest(_hash_code(code, p["salt"]), p["hash"]):
                self.pending, self.until, self.fails = {}, 0.0, 0
                return p, "ok"
        self.fails += 1
        if self.fails >= MAX_FAILED_ATTEMPTS:
            self.locked_until, self.pending, self.fails = time.time() + LOCKOUT_SECONDS, {}, 0
            return None, "locked"
        return None, "wrong"


class Bot:
    def __init__(self, on_message, on_tap, transcribe=None, on_pair=None, on_stop=None):
        """on_message(text, chat): a message from you, to run as a turn (on Jev's side, not this thread).
        on_tap(yes, ask, chat, message): you tapped Yes or No on her question ask. transcribe(16 kHz audio) ->
        (text, ms), for voice notes. on_pair(name): someone sent /start while pairing was open and got a code, or
        None: they didn't, 3 others had asked first. on_stop(why): it gave up, by the error's class name
        ("InvalidToken"), never its message, which can hold the token."""
        self.on_message, self.on_tap, self.transcribe, self.on_pair = on_message, on_tap, transcribe, on_pair
        self.on_stop = on_stop
        self.pairing, self.strangers, self.told, self.name = Pairing(), set(), set(), ""
        self.answered = {}  # her questions already answered with a tap: (chat, message) -> when
        self.loop, self.app, self.thread, self.why = None, None, None, ""
        self.stopping, self.again = False, False  # stop() asked for, and start() asked for again meanwhile
        self.lock = threading.Lock()

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        """Starts listening whenever a bot token is saved, paired or not: unpaired, it only ever answers /start (with
        a code while a pairing is open, else how to open one), so it's never silent and never takes an order. True if
        it's running, or will be in a moment: while a stop() is still under way, it starts again once that's done."""
        if not get_secret(TOKEN):
            return False
        with self.lock:
            if self.running:
                if self.stopping:
                    self.again = True
                return True
            self.stopping, self.again = False, False
            self.thread = threading.Thread(target=self._run, name="telegram", daemon=True)
            self.thread.start()
        return True

    def stop(self, wait=5.0):
        """Stops listening, at once: while it's getting going, or waiting for Telegram to answer, too. wait: seconds
        to wait for it to have stopped."""
        with self.lock:
            self.stopping, self.again = True, False
            loop, thread = self.loop, self.thread
        if loop is not None:
            try:  # ends run_forever as the library's stop_running does, and its getting going (run_until_complete)
                loop.call_soon_threadsafe(loop.stop)
            except RuntimeError:  # the loop had just closed
                pass
        if wait and thread is not None and thread is not threading.current_thread():
            thread.join(wait)

    def restart(self):
        """After a new token: starts again with it, as soon as the old one has stopped. Doesn't wait for that."""
        self.stop(wait=0)
        return self.start()

    def open_pairing(self):
        """Pair pressed: a pairing opens for PAIR_FOR seconds, and it listens. "open", "locked" (too many wrong
        codes, see pairing.minutes_left) or "no token"."""
        if not self.pairing.start():
            return "locked"
        self.told.clear()  # told how to pair before: told again, once the pairing's over
        return "open" if self.start() else "no token"

    def _run(self):
        """Keeps it listening: Telegram not reachable as it starts is retried by the library (bootstrap_retries=-1);
        if it stops on anything but a bad token or stop(), it starts again after a pause, longer each time."""
        pause = 5.0
        while True:
            began = time.time()
            why = "" if self.stopping else self._poll()
            if why in ("InvalidToken", "ImportError"):
                with self.lock:
                    gave_up, self.stopping = not self.stopping, True
                if gave_up and self.on_stop:  # or the window would still say "send /start" with nothing listening
                    self.on_stop(why)
            if self.stopping:
                with self.lock:
                    if not self.again:
                        self.thread = None
                        break
                    self.stopping, self.again, pause = False, False, 5.0  # restart(): the new token
                continue
            if time.time() - began > 600:  # it had been going a while: a hiccup, not a pattern
                pause = 5.0
            print(f"[phone: Telegram stopped ({why or 'no reason given'}), trying again in {pause:.0f} s]")
            for _ in range(int(pause * 10)):
                if self.stopping:
                    break
                time.sleep(0.1)
            pause = min(pause * 2, 300.0)
        print("[phone: stopped]")

    def _poll(self):
        """Listens until stopped. Returns why it stopped: the error's class name, or "" for a stop()."""
        try:
            from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters
        except ImportError:
            print("[phone: python-telegram-bot isn't installed]")
            return "ImportError"
        token = get_secret(TOKEN)
        _hide_token(token)
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.why = ""
        with self.lock:  # stop() either sees this loop and stops it, or this sees it was asked to stop
            if self.stopping:
                loop.close()
                return ""
            self.loop = loop
        try:
            self.app = Application.builder().token(token).post_init(self._ready).build()
            self.app.add_handler(MessageHandler(filters.ChatType.PRIVATE, self._message))
            self.app.add_handler(CallbackQueryHandler(self._tap))
            print("[phone: listening on Telegram" + ("" if owner() else ", not paired yet: only /start is answered")
                  + "]")
            # Paired: what came in while she was off is dropped (drop_pending_updates), the rest by OLDEST. Not
            # paired: kept, so a /start sent just before you pressed Pair still gets its code (OLDEST still applies)
            self.app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=bool(owner()),
                                 stop_signals=None, close_loop=False, bootstrap_retries=-1)
            return self.why
        except Exception as exc:
            print(f"[phone: Telegram stopped: {type(exc).__name__}]")  # never the message: it can hold the token
            return type(exc).__name__
        finally:
            with self.lock:
                self.loop, self.app = None, None
            try:  # what was left going when the loop stopped mid-way, so it isn't torn down half done
                left = [t for t in asyncio.all_tasks(loop) if not t.done()]
                for t in left:
                    t.cancel()
                if left:
                    loop.run_until_complete(asyncio.wait(left, timeout=5))
            except Exception:
                pass
            try:
                loop.close()
            except Exception:
                pass

    async def _ready(self, app):
        me = await app.bot.get_me()
        self.name = me.first_name or me.username or ""
        settings.put("telegram_bot_name", self.name)  # so her heads-ups don't read out her own replies (watch.py)
        asyncio.get_running_loop().create_task(self._watch(), name="jev:watch")

    async def _watch(self):
        """A token revoked while it listens ends the library's asking for messages there and then (it doesn't retry
        InvalidToken), and the rest would carry on, deaf, saying nothing: this stops it then, so _run hears why."""
        while True:  # the task starts once Telegram has answered, however long that takes
            task = next((t for t in asyncio.all_tasks() if t.get_name() == POLLING), None)
            if task is not None:
                break
            await asyncio.sleep(0.5)

        def ended(t):
            if not t.cancelled() and t.exception() is not None:
                self.why = type(t.exception()).__name__
                t.get_loop().stop()
        task.add_done_callback(ended)

    async def _message(self, update, context):
        msg, user, chat = update.effective_message, update.effective_user, update.effective_chat
        if msg is None or user is None or chat is None or chat.type != "private":
            return
        if msg.date and time.time() - msg.date.timestamp() > OLDEST:
            return  # sent while the PC was off or asleep: never run late
        me = owner()
        text = (msg.text or msg.caption or "").strip()
        if me is None:  # not paired: a /start gets a code while pairing is open, else how to open it; nothing else
            if not text.startswith("/start"):
                return
            if self.pairing.open:
                code = self.pairing.request(user.id, who(user))
                minutes = self.pairing.minutes_left
                await msg.reply_text(f"Your code is {code}. Type it into Jev's window on your PC, in Settings > Phone, "
                                     f"and press Pair. It works once, in the next {minutes} minute"
                                     f"{'s' if minutes != 1 else ''}." if code else
                                     "Others asked to pair first. On your PC, press Pair again in Jev's Settings > "
                                     "Phone, then send /start here again.")
                if self.on_pair:
                    self.on_pair(who(user) if code else None)
            elif user.id not in self.told:  # once each: anyone can find a bot, and it only says how to pair
                self.told.add(user.id)
                await msg.reply_text("I'm not paired yet. On your PC, in Jev's Settings > Phone, press Pair with the "
                                     "box empty, then send /start here again.")
            return
        if user.id != me:
            if user.id not in self.strangers:  # once each, so you know, and nothing else
                self.strangers.add(user.id)
                await context.bot.send_message(me, f"{who(user)} messaged me on Telegram. I didn't answer, I only "
                                                   f"talk to you here.")
            return
        if msg.voice or msg.audio:
            text = await self._hear(msg)
            if not text:
                await msg.reply_text("I couldn't make out that voice note.")
                return
            await msg.reply_text(f"\U0001f3a4 {text}")
        if text == "/start":
            await msg.reply_text("I'm here. Ask me anything, or tell me what to do on the PC.")
        elif text:
            self.on_message(text, chat.id)

    async def _hear(self, msg):
        """A voice note in words, written on this PC."""
        if self.transcribe is None:
            return ""
        import soundfile as sf
        note = msg.voice or msg.audio
        if (note.file_size or 0) > 20 * 1024 * 1024:  # Telegram's own limit for a bot downloading a file
            return ""
        data = await (await note.get_file()).download_as_bytearray()

        def write():
            audio, rate = sf.read(io.BytesIO(bytes(data)), dtype="float32", always_2d=True)
            audio = audio.mean(axis=1)
            if rate != 16000:
                n = int(len(audio) * 16000 / rate)
                audio = np.interp(np.linspace(0, len(audio) - 1, n), np.arange(len(audio)), audio).astype(np.float32)
            return str(self.transcribe(audio)[0]).strip()
        try:
            return await asyncio.get_running_loop().run_in_executor(None, write)
        except Exception as exc:
            print(f"  voice note failed: {exc!r}")
            return ""

    async def _tap(self, update, context):
        q, user = update.callback_query, update.effective_user
        if q is None:
            return
        await q.answer()  # stops the button spinning, whoever tapped
        if user is None or user.id != owner() or q.message is None:
            return  # a tap from anyone else does nothing
        answer, _, ask = str(q.data or "").partition(":")
        key = (q.message.chat_id, q.message.message_id)
        if answer in ("yes", "no") and key not in self.answered:  # a second tap, before the buttons came off: no
            self.answered[key] = time.time()
            while len(self.answered) > 200:
                self.answered.pop(next(iter(self.answered)))
            self.on_tap(answer == "yes", ask, q.message.chat_id, q.message.message_id)

    def _call(self, coro_fn):
        """Runs a send on the bot's own loop, from Jev's side. False if it couldn't."""
        loop = self.loop
        if loop is None:
            return False
        try:
            asyncio.run_coroutine_threadsafe(coro_fn(), loop).result(30)
            return True
        except Exception as exc:  # including Telegram's flood control: a failed send, not a long sleep
            print(f"  telegram send failed: {type(exc).__name__}")
            return False

    def send(self, chat, text, ask=None):
        """Her reply, split Hermes' way if it's long. ask: Yes and No buttons on it, for her question ask."""
        async def go():
            from telegram import InlineKeyboardButton, InlineKeyboardMarkup
            parts = truncate_message(text, 4096, utf16_len)
            for i, part in enumerate(parts):
                buttons = InlineKeyboardMarkup([[InlineKeyboardButton("Yes", callback_data=f"yes:{ask}"),
                                                 InlineKeyboardButton("No", callback_data=f"no:{ask}")]]) \
                    if ask is not None and i == len(parts) - 1 else None
                await self.app.bot.send_message(chat, part, reply_markup=buttons)
        return self._call(go)

    def send_photo(self, chat, picture, caption=""):
        """A picture to the chat: a screenshot she was asked for, PNG bytes. False if it couldn't."""
        async def go():
            await self.app.bot.send_photo(chat, photo=io.BytesIO(picture), caption=caption[:1024] or None)
        return self._call(go)

    def settle(self, chat, message, note):
        """Her question's buttons taken off once answered, with what happened: "Yes.", "Expired, not run."."""
        async def go():
            try:  # a second tap finds the buttons already gone: the note still goes
                await self.app.bot.edit_message_reply_markup(chat, message, reply_markup=None)
            except Exception as exc:
                print(f"  telegram: buttons already off ({type(exc).__name__})")
            await self.app.bot.send_message(chat, note, reply_to_message_id=message)
        return self._call(go)
