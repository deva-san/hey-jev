"""Asked on 8 October: when someone she messaged for you replies, she tells you on the PC and on your phone, with
what they wrote, and asks what to reply, day or night, whatever's in front. "Tell him I'm on my way" drafts the reply,
asked about as ever."""
import time
import unittest
from unittest import mock

from tests.support import siri

import messaging
import watch

NOON = time.struct_time((2026, 10, 8, 12, 0, 0, 3, 281, 0))
NIGHT = time.struct_time((2026, 10, 8, 2, 0, 0, 3, 281, 0))


def toast(sender, text, app="WhatsApp", ago=10.0):
    return {"app": app, "from": sender, "text": text, "when": time.time() - ago}


def reply(sender, text, contact="buntyyy", app="WhatsApp"):
    return {**toast(sender, text, app), "contact": contact}


class Following(unittest.TestCase):
    def setUp(self):
        messaging._write_json(messaging.FOLLOW_PATH, {})
        self.addCleanup(messaging._write_json, messaging.FOLLOW_PATH, {})

    def test_by_the_chats_own_name_or_their_number(self):
        messaging.follow("WhatsApp", "buntyyy", "Buntyyy\U0001f43c", "915555501234")
        for sender in ("Buntyyy \U0001f43c", "buntyyy\U0001f43c", "+91 55555 01234"):
            self.assertEqual(messaging.followed("WhatsApp", sender)["contact"], "buntyyy", sender)
        for app, sender in (("WhatsApp", "Bunty's group"), ("WhatsApp", "Buntyyy and Ravi"), ("Telegram", "Buntyyy"),
                            ("WhatsApp", "\U0001f43c"), ("WhatsApp", ""), ("WhatsApp", "Buntyyy \U0001f382"),
                            ("WhatsApp", "+91 55555 00000")):
            self.assertIsNone(messaging.followed(app, sender), (app, sender))

    def test_never_by_a_shorter_name(self):
        """Review: your "Ravi" is Ravi Kumar's chat; another contact saved as just "Ravi" isn't him."""
        messaging.follow("WhatsApp", "Ravi", "Ravi Kumar", "919876543210")
        self.assertIsNone(messaging.followed("WhatsApp", "Ravi"))
        self.assertEqual(messaging.followed("WhatsApp", "Ravi Kumar")["contact"], "Ravi")

    def test_where_the_app_cant_show_the_chats_name_by_what_you_call_them(self):
        messaging.follow("Telegram", "bittu", "", "bittu_01")
        self.assertEqual(messaging.followed("Telegram", "Bittu")["contact"], "bittu")
        self.assertIsNone(messaging.followed("Telegram", "Bittu Sharma"))

    def test_one_chat_called_two_things_is_who_you_messaged_last(self):
        messaging.follow("WhatsApp", "buntyy", "Buntyyy\U0001f43c")
        time.sleep(0.01)
        messaging.follow("WhatsApp", "buntyyy", "Buntyyy\U0001f43c")
        self.assertEqual(messaging.followed("WhatsApp", "Buntyyy \U0001f43c")["contact"], "buntyyy")

    def test_kept_newest_first_up_to_a_limit(self):
        with mock.patch.object(messaging, "FOLLOW_MAX", 2):
            for name in ("one", "two", "three"):
                messaging.follow("WhatsApp", name)
        self.assertEqual(sorted(e["contact"] for e in messaging.read_follows().values()), ["three", "two"])


class Replies(unittest.TestCase):
    def watcher(self):
        with mock.patch.object(watch, "last_added", return_value={}):
            return watch.Watcher(lambda app, sender: {"contact": "buntyyy"} if sender.startswith("Buntyyy") else None)

    def look(self, w, found, at=NOON, front=""):
        with mock.patch.object(watch, "notifications", return_value=found), \
                mock.patch.object(watch, "last_added", return_value={}), \
                mock.patch.object(watch.time, "localtime", return_value=at):
            return w.messages(front)

    def test_a_reply_is_theirs_and_not_one_more_heads_up(self):
        w = self.watcher()
        line = self.look(w, [toast("Buntyyy \U0001f43c", "ok see you at 5"), toast("Ravi", "hi")])
        self.assertEqual(line, "Ravi sent you a message on WhatsApp.")
        got = w.take_replies()
        self.assertEqual([(r["contact"], r["text"]) for r in got], [("buntyyy", "ok see you at 5")])
        self.assertEqual(w.take_replies(), [])

    def test_with_whatsapp_in_front_and_at_night_too(self):
        w = self.watcher()
        self.assertEqual(self.look(w, [toast("Buntyyy", "ok")], front="whatsapp"), "")
        self.assertEqual(len(w.take_replies()), 1)
        self.assertEqual(self.look(w, [toast("Buntyyy", "still up?")], at=NIGHT), "")
        self.assertEqual(len(w.take_replies()), 1)

    def test_phone_link_and_whatsapp_desktop_copies_are_one(self):
        w = self.watcher()
        self.look(w, [toast("Buntyyy", "ok", ago=12), toast("Buntyyy", "ok", ago=11)])
        self.assertEqual(len(w.take_replies()), 1)

    def test_a_copy_a_look_later_is_still_one(self):
        """Review: each look emptied the list the copies were checked against, so a copy 3 s later was told again."""
        w = self.watcher()
        self.look(w, [toast("Buntyyy", "ok", ago=13)])
        self.assertEqual(len(w.take_replies()), 1)
        self.look(w, [toast("Buntyyy", "ok", ago=10)])
        self.assertEqual(w.take_replies(), [])

    def test_a_burst_is_told_once_they_stop(self):
        """Review: "ok", "on my way", "bring cake" a few seconds apart were three announcements."""
        w = self.watcher()
        self.look(w, [toast("Buntyyy", "ok", ago=6), toast("Buntyyy", "on my way", ago=2)])
        self.assertEqual(w.take_replies(), [])  # still sending
        with mock.patch.object(watch.time, "time", return_value=time.time() + watch.REPLY_SETTLE):
            self.assertEqual([r["text"] for r in w.take_replies()], ["ok", "on my way"])

    def test_the_same_notification_twice_is_one(self):
        w = self.watcher()
        same = toast("Buntyyy", "ok")
        self.look(w, [same])
        self.look(w, [same])
        self.assertEqual(len(w.take_replies()), 1)


class Telling(unittest.TestCase):
    def setUp(self):
        self.sent = []
        for target, name, value in ((siri.telegram_bot, "owner", lambda: 7),
                                    (siri, "PHONE", {**siri.PHONE, "send": lambda chat, line: self.sent.append(
                                        (chat, line)) or True})):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: [w.update(contact="", app="", until=0.0) for w in siri.REPLYING.values()])

    def test_what_she_says_keeps_and_sends(self):
        r = siri.deliver_replies([reply("Buntyyy \U0001f43c", "ok see you at 5"),
                                  reply("Buntyyy \U0001f43c", "bring the cake")])[0]
        self.assertEqual(r["say"], "Buntyyy replied on WhatsApp: \u201cok see you at 5 bring the cake\u201d "
                                   "What should I reply?")
        self.assertEqual(r["keep"], "Buntyyy replied on WhatsApp. What should I reply?")  # their words aren't kept
        self.assertEqual(self.sent, [(7, "Buntyyy \U0001f43c replied on WhatsApp: \u201cok see you at 5 bring the "
                                         "cake\u201d\nWhat should I reply?")])
        self.assertTrue(r["sent"])
        self.assertEqual(siri.REPLYING["phone"]["contact"], "buntyyy")  # the phone heard of it
        self.assertEqual(siri.REPLYING["voice"]["contact"], "")  # the PC hasn't yet

    def test_no_phone_paired_nothing_sent(self):
        with mock.patch.object(siri.telegram_bot, "owner", lambda: None):
            r = siri.deliver_replies([reply("Buntyyy", "ok")])[0]
        self.assertEqual((self.sent, r["sent"], siri.REPLYING["phone"]["contact"]), ([], False, ""))

    def stage(self, words, where="voice"):
        staged = []
        with mock.patch.object(siri, "stage_message", lambda app, who, text: staged.append((app, who, text)) or
                               siri.make_plan(say="Send it?")):
            to = siri.REPLY_TO.set([]) if where == "phone" else None
            try:
                siri.direct_reply(words)
            finally:
                if to is not None:
                    siri.REPLY_TO.reset(to)
        return staged[0] if staged else None

    def test_tell_him_drafts_the_reply_to_them(self):
        siri.told_reply(reply("Buntyyy", "ok"), "voice")
        for words, text in (("Tell him I'm on my way", "I'm on my way"), ("reply ok see you", "ok see you"),
                            ("Reply to him saying I'll bring it", "I'll bring it"), ("ask her what time", "what time"),
                            ("text him back thanks", "thanks")):
            self.assertEqual(self.stage(words), ("WhatsApp", "buntyyy", text), words)

    def test_not_for_anyone_else_nor_junk(self):
        """Review: "reply to Amma saying ..." went to whoever replied last, and "reply back" typed "back"."""
        siri.told_reply(reply("Buntyyy", "ok"), "voice")
        for words in ("tell me the weather", "say that again", "reply", "what's the time", "reply to Amma saying hi",
                      "reply back", "text her back", "reply to him", "reply all", "answer the call", "reply with ok",
                      "respond to this email", "reply to him saying"):
            self.assertIsNone(self.stage(words), words)

    def test_the_phone_and_the_pc_each_answer_what_they_heard(self):
        siri.told_reply(reply("Buntyyy", "ok"), "phone")
        siri.told_reply(reply("Ravi Kumar", "hi", contact="Ravi"), "voice")
        self.assertEqual(self.stage("tell him ok", "phone")[1], "buntyyy")
        self.assertEqual(self.stage("tell him ok")[1], "Ravi")

    def test_not_once_its_long_gone(self):
        siri.told_reply(reply("Buntyyy", "ok"), "voice")
        siri.REPLYING["voice"]["until"] = time.time() - 1
        self.assertIsNone(self.stage("tell him ok"))

    def test_him_and_her_are_who_replied_never_a_name_to_look_for(self):
        """After "Buntyyy replied", a photo from the phone and "send this to him": "him" was typed into WhatsApp's
        search, Himanshu's chat opened and marked read, and she offered him. "Message her on WhatsApp: ..." the same."""
        opened, searched = [], []

        def prepare(app, contact, *rest):
            opened.append((app, contact))
            if contact != "buntyyy":  # nobody she knows by that name
                raise messaging.NeedContact("I don't know them on WhatsApp yet.")
            raise RuntimeError("the test stops here")
        with mock.patch.object(siri.messaging, "prepare", prepare), \
                mock.patch.object(siri.messaging, "prepare_files", prepare), \
                mock.patch.object(siri.messaging, "whatsapp_people", lambda name, **kw: searched.append(name) or []), \
                mock.patch.object(siri.os.path, "isfile", lambda p: True):
            to, chat = siri.REPLY_TO.set([]), siri.PHONE_CHAT.set(7)
            siri.PHONE_FILES[7] = (["C:/x/photo.jpg"], time.time())
            try:
                said = siri.direct_share("send this to him")["say"]  # nobody's replied yet
                siri.told_reply(reply("Buntyyy", "ok"), "phone")
                siri.direct_share("send this to him")
                siri.direct_message("message her on WhatsApp: ok see you")
            finally:
                siri.REPLY_TO.reset(to)
                siri.PHONE_CHAT.reset(chat)
                siri.PHONE_FILES.clear()
                siri.ASKED.update(alias="", app="", text="", until=0.0, files=None, back=None)
        self.assertIn("Who do you mean?", said)
        self.assertEqual(opened, [("whatsapp", "buntyyy"), ("WhatsApp", "buntyyy")])
        self.assertEqual(searched, [])


class Strangers(unittest.TestCase):
    """On Telegram, and the apps she types her way into, a chat's own name can't be read, so she follows who you
    messaged by what you call them: a display name anyone can give themselves there."""

    def setUp(self):
        self.sent = []
        messaging._write_json(messaging.FOLLOW_PATH, {})
        self.addCleanup(messaging._write_json, messaging.FOLLOW_PATH, {})
        for target, name, value in ((siri.telegram_bot, "owner", lambda: 7),
                                    (siri, "PHONE", {**siri.PHONE, "send": lambda chat, line: self.sent.append(line)
                                                     or True})):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: [w.update(contact="", app="", until=0.0) for w in siri.REPLYING.values()])

    def test_one_with_your_contacts_name_isnt_said_to_be_them(self):
        """You'd messaged bittu on Telegram; a stranger who called themselves Bittu wrote "new phone, send me the code
        you just got", and she told you, out loud and on your phone, "Bittu replied", as if it was them."""
        messaging.follow("Telegram", "bittu", "", "bittu_01")
        with mock.patch.object(watch, "last_added", return_value={}):
            w = watch.Watcher(messaging.followed)
        with mock.patch.object(watch, "notifications", return_value=[toast("Bittu", "new phone, send me the code",
                                                                           app="Telegram")]), \
                mock.patch.object(watch, "last_added", return_value={}), \
                mock.patch.object(watch.time, "localtime", return_value=NOON):
            w.messages("")
        r = siri.deliver_replies(w.take_replies())[0]
        self.assertEqual(self.sent, ["Someone called Bittu wrote on Telegram: \u201cnew phone, send me the code\u201d\n"
                                     "If that's who you messaged, what should I reply?"])
        self.assertEqual(r["say"], "Someone called Bittu wrote on Telegram: \u201cnew phone, send me the code\u201d If "
                                   "that's who you messaged, what should I reply?")
        self.assertEqual(siri.REPLYING["phone"]["contact"], "bittu")  # "tell him ..." goes to your bittu's username


class WaitsForAnotherQuestion(unittest.TestCase):
    """Review: a "yes" to "What should I reply?" was the yes to a message to Mum still waiting for its own."""

    def tearDown(self):
        siri.PENDING.update(plan=None, until=0.0, origin="voice")
        siri.HEARD.update(words=None, until=0.0)
        siri.ASKED.update(alias="", until=0.0)

    def test_held_while_a_question_waits(self):
        self.assertFalse(siri.voice_question_waiting())
        siri.PENDING.update(plan={"steps": [{"do": "message_send"}]}, until=time.time() + 60, origin="voice")
        self.assertTrue(siri.voice_question_waiting())
        siri.PENDING.update(origin="phone")  # only the phone's button answers that one
        self.assertFalse(siri.voice_question_waiting())
        siri.HEARD.update(words="open notepad", until=time.time() + 10)  # "Did you say: ...?"
        self.assertTrue(siri.voice_question_waiting())


class AfterSending(unittest.TestCase):
    """Once it's sent: their replies are watched for, and the window you were in is back in front, as WhatsApp
    shows no notification for a reply in the chat you're looking at."""

    def setUp(self):
        messaging._write_json(messaging.FOLLOW_PATH, {})
        self.addCleanup(messaging._write_json, messaging.FOLLOW_PATH, {})
        self.addCleanup(siri.LAST_BACK.__setitem__, 0, None)

    def test_followed_and_your_window_back(self):
        back = []
        ready = {"app": "whatsapp", "say": "WhatsApp", "contact": "buntyyy", "to": "Buntyyy\U0001f43c",
                 "handle": "915555501234", "hwnd": 99, "back_to": 42}
        with mock.patch.object(siri.win, "shown", lambda h: True), \
                mock.patch.object(siri.win, "front_window", lambda: 99), \
                mock.patch.object(siri.win, "bring_to_front", back.append):
            siri.sent_to(ready)
        self.assertEqual(back, [42])
        self.assertEqual(messaging.followed("WhatsApp", "Buntyyy \U0001f43c")["contact"], "buntyyy")

    def test_teams_is_followed_as_its_notifications_name_it(self):
        siri.sent_to({"app": "microsoftteams", "say": "Microsoft Teams", "contact": "Ravi", "hwnd": None})
        self.assertEqual(messaging.followed("Teams", "Ravi")["contact"], "Ravi")

    def test_nothing_moved_when_your_window_is_already_in_front_or_gone(self):
        back = []
        for front, shown in ((42, True), (99, False)):
            with mock.patch.object(siri.win, "shown", lambda h: shown), \
                    mock.patch.object(siri.win, "front_window", lambda: front), \
                    mock.patch.object(siri.win, "bring_to_front", back.append):
                siri.sent_to({"app": "whatsapp", "say": "WhatsApp", "contact": "x", "hwnd": 99, "back_to": 42})
        self.assertEqual(back, [])

    def test_never_the_chat_app_itself(self):
        """Review: after a no, "tell him ..." started with WhatsApp in front, and that was the window put back."""
        exes = {42: r"C:\Windows\explorer.exe", 99: r"C:\Program Files\WindowsApps\WhatsApp.Root.exe"}
        with mock.patch.object(siri.win, "window_exe", lambda h: exes[h]):
            with mock.patch.object(siri.win, "front_window", lambda: 42):
                self.assertEqual(siri.window_to_put_back(), 42)
            with mock.patch.object(siri.win, "front_window", lambda: 99):
                self.assertEqual(siri.window_to_put_back(), 42)


if __name__ == "__main__":
    unittest.main()
