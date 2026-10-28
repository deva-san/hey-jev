"""What the review of sharing files found: nothing goes without a fresh yes to her own question, the share rule only
takes what's a share, a slow album stays one message, and File Explorer's tab in front is the one read."""
import asyncio
import json
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.support import WIN_ORIGINAL, siri

import telegram_bot


class OnlyAfterAYes(unittest.TestCase):
    def test_a_model_never_plans_a_send_or_an_install(self):
        plan = {"steps": [{"do": "message_send"}, {"do": "install_run"}, {"do": "open", "app": "Notepad"}], "say": ""}
        with mock.patch.object(siri, "ask_plan", return_value=(json.dumps(plan), dict(plan), {}, "test")), \
                mock.patch.object(siri, "context", return_value=""):
            got = siri.think("yes send it", False)
        self.assertEqual([s["do"] for s in got["steps"]], ["open"])

    def test_a_send_without_the_yes_is_refused_and_nothing_goes(self):
        sent = []
        siri.SEND_OK["until"] = 0.0
        siri.STAGED.update(ready={"app": "whatsapp", "contact": "Amma", "files": ["a.jpg"]}, until=time.time() + 60)
        self.addCleanup(siri.STAGED.update, ready=None, until=0.0)
        with mock.patch.object(siri.messaging, "send", lambda ready: sent.append(ready)):
            with self.assertRaises(RuntimeError):
                siri.do_step({"do": "message_send"})
        self.assertEqual(sent, [])

    def test_one_yes_one_send(self):
        sent = []
        siri.SEND_OK["until"] = time.time() + 30
        for _ in range(2):
            siri.STAGED.update(ready={"app": "whatsapp", "contact": "Amma", "text": "hi"}, until=time.time() + 60)
            with mock.patch.object(siri.messaging, "send", lambda ready: sent.append(ready) or (True, "Sent.")):
                try:
                    siri.do_step({"do": "message_send"})
                except RuntimeError:
                    pass
        self.assertEqual(len(sent), 1)
        siri.STAGED.update(ready=None, until=0.0)


    def test_files_whose_question_ran_out_are_taken_out_of_the_preview(self):
        """"Send report.pdf to Amma?" and nobody answered: the question ran out, but the file stayed in WhatsApp's
        preview with the keyboard in its caption box, and the next Enter there sent it."""
        cleared = []
        self.addCleanup(siri.STAGED.update, ready=None, until=0.0)
        with mock.patch.object(siri.messaging, "discard", lambda ready: cleared.append(ready["contact"]) or True):
            for ready in ({"app": "whatsapp", "contact": "Amma", "files": ["report.pdf"]},
                          {"app": "whatsapp", "contact": "Ravi", "text": "hi"}):  # words stay, as a draft would
                siri.STAGED.update(ready=ready, until=time.time() + 60)
                siri.drop_expired()
                self.assertIs(siri.STAGED["ready"], ready)  # still waiting for its yes: left alone
                siri.STAGED["until"] = time.time() - 1
                siri.drop_expired()
            self.assertEqual(cleared, ["Amma"])
            self.assertEqual(siri.STAGED["ready"]["contact"], "Ravi")


class ShareWords(unittest.TestCase):
    def setUp(self):
        self.staged = []
        for target, name, value in (
                (siri, "stage_files", lambda app, who, paths, caption="": self.staged.append(who) or siri.make_plan()),
                (siri, "given_files", lambda: ["C:/x/photo.jpg"])):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_to_your_own_phone_isnt_a_share(self):
        for words in ("send this to my phone", "send it to me", "send the screenshot to my phone"):
            self.assertIsNone(siri.direct_share(words), words)

    def test_two_requests_go_to_the_model(self):
        self.assertIsNone(siri.direct_share("send this to amma and lock the pc"))
        self.assertEqual(self.staged, [])

    def test_please_isnt_part_of_who(self):
        siri.direct_share("send this to amma please")
        self.assertEqual(self.staged, ["amma"])

    def test_only_on_whatsapp(self):
        plan = siri.direct_share("send this to ravi on telegram")
        self.assertIn("only send files on WhatsApp", plan["say"])
        self.assertEqual(self.staged, [])


class Albums(unittest.TestCase):
    def test_a_slow_album_is_still_one_message(self):
        seen = []
        bot = telegram_bot.Bot(on_message=lambda *a: seen.append(a), on_tap=None)

        def item(caption):
            async def download():
                await asyncio.sleep(0.15)  # longer than the album's wait
                return bytearray(b"jpeg")

            async def get_file():
                return SimpleNamespace(download_as_bytearray=download)
            sizes = [SimpleNamespace(width=800, height=600, file_size=900, get_file=get_file)]

            async def reply_text(t, **kw):
                pass
            msg = SimpleNamespace(text=None, caption=caption, voice=None, audio=None, reply_text=reply_text,
                                  photo=sizes, document=None, media_group_id="g1",
                                  date=__import__("datetime").datetime.now(__import__("datetime").timezone.utc))
            return SimpleNamespace(effective_message=msg, effective_user=SimpleNamespace(id=7, first_name="H",
                                                                                         last_name=None, username=None),
                                   effective_chat=SimpleNamespace(type="private", id=7))

        async def run():
            for caption in ("send these to amma", None, None):
                await bot._message(item(caption), None)
            await asyncio.sleep(0.2)
        with mock.patch.dict(siri.settings._load(), {"telegram_owner": 7}), \
                mock.patch.object(telegram_bot, "ALBUM_WAIT", 0.05):
            asyncio.run(run())
        self.assertEqual(len(seen), 1)
        self.assertEqual((seen[0][0], len(seen[0][3])), ("send these to amma", 3))


class ExplorerTabs(unittest.TestCase):
    def tabs(self, title, names):
        items = [SimpleNamespace(HWND=5, LocationName=n, Document=SimpleNamespace(
            SelectedItems=lambda n=n: SimpleNamespace(Count=1, Item=lambda j, n=n: SimpleNamespace(Path=f"C:/{n}/a.pdf"))))
            for n in names]
        shell = SimpleNamespace(Windows=lambda: SimpleNamespace(Count=len(items), Item=lambda i: items[i]))
        win = siri.win
        with mock.patch.object(win.user32, "GetForegroundWindow", lambda: 5), \
                mock.patch.object(win, "_class_name", lambda h: "CabinetWClass"), \
                mock.patch.object(win, "window_title", lambda h: title), \
                mock.patch.object(win, "_com", lambda: None), \
                mock.patch("comtypes.client.CreateObject", lambda *a, **k: shell), \
                mock.patch.object(win.os.path, "isfile", lambda p: True):
            return WIN_ORIGINAL["selected_files"]()  # the real one, with what it calls patched above

    def test_the_tab_in_front(self):
        self.assertEqual(self.tabs("Downloads - File Explorer", ["Documents", "Downloads"]), ["C:/Downloads/a.pdf"])

    def test_two_tabs_on_the_same_name_are_asked_about(self):
        with self.assertRaises(RuntimeError):
            self.tabs("Downloads - File Explorer", ["Downloads", "Downloads"])


if __name__ == "__main__":
    unittest.main()
