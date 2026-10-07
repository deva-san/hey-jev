"""Carrying things out and confirming them: keys, media, the yes or no to her questions, what she says about what she
did. Nothing here acts on the PC: tests.support turns that into tripwires, and each test patches what it needs."""
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.support import TRIPPED, siri, winplatform


def original(name):
    """One of siri's functions as written, which tests.support swapped for a tripwire, run in siri's own globals so
    what a test patches on siri still applies."""
    import ast
    with open(siri.__file__, encoding="utf-8") as f:
        node = next(n for n in ast.parse(f.read()).body if isinstance(n, ast.FunctionDef) and n.name == name)
    found = {}
    exec(compile(ast.Module([node], []), siri.__file__, "exec"), vars(siri), found)
    return found[name]


class Keys(unittest.TestCase):
    def test_zoom_in_and_out_press_real_keys(self):
        """"Zoom in" planned ctrl+plus and she said "There's no plus key": pynput has no such key."""
        pressed = []
        with mock.patch.object(siri.win, "press", lambda *keys: pressed.append(keys)), \
                mock.patch.object(siri, "not_into_shell", lambda: None):
            siri.press_keys(siri.quick("zoom in")["steps"][0]["keys"])
            siri.press_keys(siri.quick("zoom out")["steps"][0]["keys"])
        self.assertEqual(pressed, [("ctrl", "="), ("ctrl", "-")])

    def test_zoom_stays_a_safe_shortcut(self):
        for keys in ("ctrl+plus", "ctrl+minus", "ctrl + =", "ctrl+0"):
            self.assertIn(siri.combo(keys), siri.SAFE_KEYS, keys)


def session(app, position):
    return SimpleNamespace(source_app_user_model_id=app, position=position)


class Media(unittest.TestCase):
    def previous(self, app, position):
        sent = []
        with mock.patch.object(siri.win, "media_session", lambda hint=None: session(app, position)), \
                mock.patch.object(siri.win, "media_position", lambda s: s.position), \
                mock.patch.object(siri.win, "media_command", lambda s, action: sent.append(action) or True), \
                mock.patch.object(siri.time, "sleep", lambda secs: None):
            siri.media("previous")
        return sent

    def test_previous_on_spotify_mid_song_goes_back_a_song(self):
        """One "previous" 40 s into a Spotify song only started it again."""
        self.assertEqual(self.previous("Spotify.exe", 40.0), ["previous", "previous"])

    def test_previous_at_the_start_of_a_song_is_one_press(self):
        self.assertEqual(self.previous("Spotify.exe", 1.0), ["previous"])

    def test_previous_elsewhere_is_one_press(self):
        """YouTube's previous goes back a video straight away, two would skip one."""
        self.assertEqual(self.previous("Chrome", 40.0), ["previous"])


class RamFigures(unittest.TestCase):
    def test_an_apps_ram_is_its_private_working_set(self):
        """"Chrome uses the most, 4.1 GB" against Task Manager's 2.65: shared pages were counted in every process.
        Reads the process list only. This process's own figure should be its private set (psutil's USS), not all of
        its working set (RSS), which counts the DLLs it shares."""
        import os
        import psutil
        import sysinfo
        ram = sysinfo._snapshot()[os.getpid()][2]
        mem = psutil.Process().memory_full_info()
        self.assertGreater(mem.rss - mem.uss, 4 * 2 ** 20)  # enough shared pages here to tell them apart
        self.assertLess(abs(ram - mem.uss), (mem.rss - mem.uss) / 2)


class Folders(unittest.TestCase):
    def opened(self, step):
        folders = []
        with mock.patch.object(siri.win, "open_folder", folders.append):
            siri.do_step(step)
        return folders

    def test_open_recycle_bin_planned_as_an_app_opens_it(self):
        """The model planned {"do": "open", "app": "Recycle Bin"}: "I couldn't find an app called Recycle Bin"."""
        self.assertEqual(self.opened({"do": "open", "app": "Recycle Bin"}), ["shell:RecycleBinFolder"])
        self.assertEqual(self.opened({"do": "open", "app": "the Downloads folder"}), ["shell:Downloads"])
        for uri in winplatform.SHELL_NAMES.values():
            self.assertIn(uri, winplatform.SHELL_FOLDERS)  # open_folder only opens those

    def test_recycle_bin_as_a_website_opens_the_recycle_bin(self):
        """Next it planned the website https://C:/$Recycle.Bin/, and she opened that in Chrome."""
        self.assertEqual(self.opened({"do": "website", "url": "https://C:/$Recycle.Bin/"}), ["shell:RecycleBinFolder"])

    def test_a_path_on_this_pc_is_no_website(self):
        before = len(TRIPPED)
        with self.assertRaisesRegex(RuntimeError, "on this PC"):
            siri.do_step({"do": "website", "url": "C:\\Users\\Public"})
        with self.assertRaisesRegex(RuntimeError, "on this PC"):
            siri.do_step({"do": "website", "url": "file:///D:/films"})
        self.assertEqual(len(TRIPPED), before)

    def test_an_app_is_still_an_app(self):
        with self.assertRaisesRegex(RuntimeError, "tripwire: win.open_app"):
            siri.do_step({"do": "open", "app": "Notepad"})


class SaysWhatHappened(unittest.TestCase):
    """She says a send, an install or closing an app worked once it has, and never when it didn't."""
    def setUp(self):
        patcher = mock.patch.object(siri, "say", lambda line, notify: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def send(self, send):
        siri.STAGED.update(ready={"app": "whatsapp", "contact": "Ravi", "text": "hi"}, until=time.time() + 60)
        with mock.patch.object(siri.messaging, "send", send):
            return siri.run_plan({"steps": [{"do": "message_send"}], "say": ""}, None)

    def test_a_send_says_what_this_send_did(self):
        """She said "Sent to Mum." for a message to Ravi: the last send's line, said before this one ran."""
        siri.SENT_LINE[0] = "Sent to Mum."
        failed, _, _, spoken = self.send(lambda ready: (True, f"Sent to {ready['contact']}."))
        self.assertEqual((failed, spoken), ([], ["Sent to Ravi."]))

    def test_a_refused_send_is_never_said_to_have_gone(self):
        def refuse(ready):
            raise RuntimeError("WhatsApp isn't in front, so I've not sent it")
        siri.SENT_LINE[0] = ""
        failed, _, _, spoken = self.send(refuse)
        self.assertEqual(failed, ["WhatsApp isn't in front, so I've not sent it"])
        self.assertEqual(len(spoken), 1)
        self.assertIn("so I've not sent it", spoken[0])

    def test_an_install_after_a_message_says_the_install(self):
        siri.SENT_LINE[0] = "Sent to Mum."
        siri.STAGED_INSTALL.update(ready={"action": "install", "name": "VLC", "version": "3.0.24", "id": "VideoLAN.VLC"},
                                   until=time.time() + 60)
        with mock.patch.object(siri.TASK_STORE, "create", lambda *a, **kw: 12):
            failed, _, _, spoken = siri.run_plan({"steps": [{"do": "install_run"}], "say": ""}, None)
        self.assertEqual(failed, [])
        self.assertEqual(len(spoken), 1)
        self.assertTrue(spoken[0].startswith("Installing VLC in the background, as task 12."), spoken)

    def close(self, quit_app):
        with mock.patch.object(siri.win, "quit_app", quit_app):
            return siri.run_plan({"steps": [{"do": "close", "app": "Messages"}], "say": "Closed Messages."}, None)

    def test_closing_an_app_that_isnt_running_isnt_said_to_be_done(self):
        """"Closed Messages.", then "Hmm, that didn't work. Messages isn't running." (log, 12:10)"""
        def not_running(app):
            raise RuntimeError(f"{app.name} isn't running")
        failed, _, _, spoken = self.close(not_running)
        self.assertEqual(failed, ["Messages isn't running"])
        self.assertNotIn("Closed Messages.", spoken)
        self.assertEqual(len(spoken), 1)

    def test_closing_is_said_once_it_has_closed(self):
        order = []
        with mock.patch.object(siri, "say", lambda line, notify: order.append(line)):
            failed, _, _, spoken = self.close(lambda app: time.sleep(0.2) or order.append("closed"))
        self.assertEqual(order, ["closed", "Closed Messages."])

    def test_opening_is_still_said_while_it_opens(self):
        order = []
        with mock.patch.object(siri, "say", lambda line, notify: order.append(line)), \
                mock.patch.object(siri.win, "open_app", lambda app: time.sleep(0.2) or order.append("opened")):
            siri.run_plan({"steps": [{"do": "open", "app": "Notepad"}], "say": "Opening it now."}, None)
        self.assertEqual(order, ["Opening it now.", "opened"])


class Turn(unittest.TestCase):
    """Whole turns through handle(): what she said and pressed, with the model, her voice and the learning loop
    stubbed. A test patches siri.think for what the model would plan."""
    def setUp(self):
        self.said, self.pressed = [], []
        for target, name, value in ((siri, "say", lambda line, notify: self.said.append(line)),
                                    (siri, "learn_later", lambda *a: None), (siri, "media_playing", lambda: False),
                                    (siri, "asked_last", lambda within=0: False), (siri, "not_into_shell", lambda: None),
                                    (siri.win, "press", lambda *keys: self.pressed.append(keys))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        siri.PENDING.update(plan=None, until=0.0)
        siri.STAGED.update(ready=None, until=0.0)
        siri.STAGED_INSTALL.update(ready=None, until=0.0)

    def model(self, plan):
        return mock.patch.object(siri, "think", lambda *a, **kw: plan)


class CloseTab(Turn):
    def test_close_this_tab_planned_as_closing_chrome_closes_the_tab(self):
        """Log, 11:08: the model planned closing Google Chrome, she asked, "Yeah, right", and all of Chrome went."""
        plan = {"steps": [], "say": "Should I close Google Chrome?",
                "confirm": {"steps": [{"do": "close", "app": "Google Chrome"}], "say": "Closed the tab for you, Hari."}}
        with self.model(plan), mock.patch.object(siri.win, "quit_app", tripwire_quit):
            siri.handle("England does not okay close this tab", gate="cold")
        self.assertEqual(self.pressed, [("ctrl", "w")])
        self.assertEqual(self.said, ["Closed the tab for you, Hari."])
        self.assertIsNone(siri.PENDING["plan"])

    def test_tab_closed_said_for_closing_chrome_closes_the_tab(self):
        """Log, 11:35: "Okay close the" -> "Tab closed." as she closed all of Chrome."""
        with self.model({"steps": [{"do": "close", "app": "Google Chrome"}], "say": "Tab closed."}), \
                mock.patch.object(siri.win, "quit_app", tripwire_quit):
            siri.handle("Okay close the", gate="cold")
        self.assertEqual(self.pressed, [("ctrl", "w")])

    def test_close_chrome_still_closes_chrome(self):
        closed = []
        with self.model({"steps": [{"do": "close", "app": "Google Chrome"}], "say": "Closing Chrome and its tabs."}), \
                mock.patch.object(siri.win, "quit_app", lambda app: closed.append(app.name)):
            siri.handle("close chrome and everything in it")
        self.assertEqual((closed, self.pressed), (["Google Chrome"], []))


LONG = ("The train from Bengaluru is running very late again tonight because of the rain near Hosur. "
        "I'll be home after ten, so please don't wait up for me or keep the gate locked. "
        "Keep some dinner aside, the chapati and dal are fine, nothing fried please. "
        "Tell Appa I've got the medicines from the shop near the station and the receipt too. "
        "Put the inverter on charge if the power goes again. Call me if anything comes up.")  # 400 and more read back


def staged(app, contact, text):
    """What messaging.prepare hands back once the chat is open with the words typed in."""
    return {"app": app, "contact": contact, "text": text, "checked": True, "say": "WhatsApp"}


class Readback(Turn):
    def test_a_long_message_is_read_back_whole_with_who_and_the_question(self):
        """tidy kept three sentences of a line over 400 characters: she never said who it was to, or "Send it?"."""
        with mock.patch.object(siri.messaging, "prepare", staged):
            siri.handle(f"Message Mum on WhatsApp: {LONG}")
        self.assertEqual(len(self.said), 1)
        self.assertTrue(self.said[0].endswith("” to Mum on WhatsApp. Send it?"), self.said[0])
        self.assertIn("Call me if anything comes up", self.said[0])

    def test_a_chatty_model_is_still_cut_short(self):
        with self.model({"steps": [], "say": LONG}):
            siri.handle("tell me a story")
        self.assertEqual(self.said, [LONG[:LONG.index(" Tell Appa")]])


def tripwire_quit(app):
    raise AssertionError(f"quit {app.name}")


class Voice(unittest.TestCase):
    def test_a_line_she_says_now_waits_seconds_for_fish_not_a_minute(self):
        """The mic is paused while she talks, and Fish once took 17 s to start: with 60 s she was silent and deaf."""
        asked = {}
        with mock.patch.object(siri, "FISH", SimpleNamespace(post=lambda url, **kw: asked.update(kw) or
                                                             SimpleNamespace(ok=True))):
            original("fish")("A new line.", "pcm", stream=True)
        connect, read = asked["timeout"]
        self.assertLessEqual(connect, 5)
        self.assertLessEqual(read, 5)

    def test_slow_fish_gets_windows_own_voice(self):
        import requests
        native = []

        def post(url, **kw):
            raise requests.ReadTimeout("read timed out")
        with mock.patch.object(siri, "FISH", SimpleNamespace(post=post)), \
                mock.patch.object(siri, "fish", original("fish")), \
                mock.patch.object(siri.win, "speak_native", lambda text, **kw: native.append(text)):
            original("speak")("A line nobody has cached, 1729.")
        self.assertEqual(native, ["A line nobody has cached, 1729."])


if __name__ == "__main__":
    unittest.main()
