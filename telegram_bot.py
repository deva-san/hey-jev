"""Jev on your phone, through a Telegram bot of your own: make one with @BotFather, paste its token in Keys, then
Settings > Phone > Pair.

Only your Telegram account can use it, and it fails closed: until you've paired it doesn't listen at all, except
for the 10 minutes a pairing is open; after, everyone else is ignored (and you're told once about each). Pairing is
Hermes Agent's (gateway/pairing.py, see hermes_memory/gateway_bits.py): you send /start, the bot answers with an
8-letter code, and you type that into Jev's window on the PC, which proves you have both. The code is kept only
hashed, runs out after an hour, and 5 wrong ones lock pairing for an hour.

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
for _name in ("httpx", "httpcore", "telegram", "telegram.ext"):
    logging.getLogger(_name).setLevel(logging.WARNING)  # httpx logs every URL, and the token is in them


class _HideToken(logging.Filter):
    """Hermes' token redaction: the bot's token never reaches the log, not even inside an error the library logs
    ("The token `...` was rejected by the server")."""

    def __init__(self, secret):
        super().__init__()
        self.secret = secret

    def filter(self, record):
        if not self.secret:
            return True
        if record.exc_info:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_info = None
        record.msg, record.args = record.getMessage().replace(self.secret, "<token>"), ()
        if record.exc_text:
            record.exc_text = record.exc_text.replace(self.secret, "<token>")
        return True


def _hide_token(secret):
    """On every place a log line can end up: the root logger's handlers, and Python's last-resort one."""
    hide = _HideToken(secret)
    for handler in [*logging.getLogger().handlers, logging.lastResort]:
        if handler is not None and not any(isinstance(f, _HideToken) for f in handler.filters):
            handler.addFilter(hide)


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


class Pairing:
    """One pairing at a time, Hermes' rules: the code from its alphabet (no 0/O, 1/I), kept as a salted hash, an hour
    to use it, and after 5 wrong codes no pairing for an hour."""

    def __init__(self):
        self.until, self.pending, self.fails, self.locked_until = 0.0, None, 0, 0.0

    @property
    def open(self):
        return time.time() < self.until and time.time() >= self.locked_until

    def start(self):
        self.until, self.pending = time.time() + PAIR_FOR, None

    def request(self, user_id, name):
        """A /start while pairing is open: the code to send back, or None."""
        if not self.open:
            return None
        code = "".join(secrets.choice(ALPHABET) for _ in range(CODE_LENGTH))
        salt = os.urandom(16)
        self.pending = {"hash": _hash_code(code, salt), "salt": salt, "user_id": int(user_id), "name": name,
                        "at": time.time()}
        return code

    def confirm(self, code):
        """(the account paired, or None, why): "ok", "wrong", "locked" or "none"."""
        if time.time() < self.locked_until:
            return None, "locked"
        p = self.pending
        if not p or time.time() - p["at"] > CODE_TTL_SECONDS:
            return None, "none"
        code = "".join(str(code or "").upper().split())  # spaces between letters are fine
        if secrets.compare_digest(_hash_code(code, p["salt"]), p["hash"]):
            self.pending, self.until, self.fails = None, 0.0, 0
            return p, "ok"
        self.fails += 1
        if self.fails >= MAX_FAILED_ATTEMPTS:
            self.locked_until, self.pending, self.fails = time.time() + LOCKOUT_SECONDS, None, 0
            return None, "locked"
        return None, "wrong"


class Bot:
    def __init__(self, on_message, on_tap, transcribe=None, on_pair=None):
        """on_message(text, chat): a message from you, to run as a turn (on Jev's side, not this thread).
        on_tap(yes, ask, chat, message): you tapped Yes or No on her question ask. transcribe(16 kHz audio) ->
        (text, ms), for voice notes. on_pair(name): someone sent /start while pairing was open."""
        self.on_message, self.on_tap, self.transcribe, self.on_pair = on_message, on_tap, transcribe, on_pair
        self.pairing, self.strangers, self.name = Pairing(), set(), ""
        self.loop, self.app, self.thread = None, None, None

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def start(self):
        """Starts listening, if there's a token and you've paired or a pairing is open. True if it's running."""
        if self.running:
            return True
        if not get_secret(TOKEN) or not (owner() or self.pairing.open):
            return False
        self.thread = threading.Thread(target=self._run, name="telegram", daemon=True)
        self.thread.start()
        return True

    def stop(self):
        loop, app = self.loop, self.app
        if loop is not None and app is not None:
            loop.call_soon_threadsafe(app.stop_running)

    def _run(self):
        from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self.loop = loop
        token = get_secret(TOKEN)
        _hide_token(token)
        try:
            self.app = Application.builder().token(token).post_init(self._ready).build()
            self.app.add_handler(MessageHandler(filters.ChatType.PRIVATE, self._message))
            self.app.add_handler(CallbackQueryHandler(self._tap))
            print("[phone: listening on Telegram]")
            # what came in while she was off is dropped by Telegram itself (drop_pending_updates), the rest by OLDEST
            self.app.run_polling(allowed_updates=["message", "callback_query"], drop_pending_updates=True,
                                 stop_signals=None, close_loop=False)
        except Exception as exc:
            print(f"[phone: Telegram stopped: {type(exc).__name__}]")  # never the message: it can hold the token
        finally:
            self.loop, self.app = None, None
            print("[phone: stopped]")

    async def _ready(self, app):
        me = await app.bot.get_me()
        self.name = me.first_name or me.username or ""
        settings.put("telegram_bot_name", self.name)  # so her heads-ups don't read out her own replies (watch.py)

    async def _message(self, update, context):
        msg, user, chat = update.effective_message, update.effective_user, update.effective_chat
        if msg is None or user is None or chat is None or chat.type != "private":
            return
        if msg.date and time.time() - msg.date.timestamp() > OLDEST:
            return  # sent while the PC was off or asleep: never run late
        me = owner()
        text = (msg.text or msg.caption or "").strip()
        if me is None:  # not paired: only a /start while pairing is open, nothing else at all
            if text.startswith("/start") and self.pairing.open:
                code = self.pairing.request(user.id, who(user))
                if code:
                    await msg.reply_text(f"Your code is {code}. Type it into Jev's window on your PC, in Settings > "
                                         f"Phone, to pair. It works once, for the next hour.")
                    if self.on_pair:
                        self.on_pair(who(user))
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
        if answer in ("yes", "no"):
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

    def settle(self, chat, message, note):
        """Her question's buttons taken off once answered, with what happened: "Yes.", "Expired, not run."."""
        async def go():
            await self.app.bot.edit_message_reply_markup(chat, message, reply_markup=None)
            await self.app.bot.send_message(chat, note, reply_to_message_id=message)
        return self._call(go)
