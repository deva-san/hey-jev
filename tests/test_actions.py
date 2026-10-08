"""Carrying things out and confirming them: keys, media, the yes or no to her questions, what she says about what she
did. Nothing here acts on the PC: tests.support turns that into tripwires, and each test patches what it needs."""
import time
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.support import ORIGINAL, TRIPPED, needs_windows, siri, winplatform


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
                mock.patch.object(siri, "not_into_shell", lambda *a: None):
            siri.press_keys(siri.quick("zoom in")["steps"][0]["keys"])
            siri.press_keys(siri.quick("zoom out")["steps"][0]["keys"])
        self.assertEqual(pressed, [("ctrl", "="), ("ctrl", "-")])

    def test_zoom_stays_a_safe_shortcut(self):
        for keys in ("ctrl+plus", "ctrl+minus", "ctrl + =", "ctrl+0"):
            self.assertIn(siri.combo(keys), siri.SAFE_KEYS, keys)


def session(app, position=0.0, playing=True):
    return SimpleNamespace(source_app_user_model_id=app, position=position, playing=playing)


VLC_EXE = r"C:\Program Files\VideoLAN\VLC\vlc.exe"


class Media(unittest.TestCase):
    def media(self, action, now=None, vlc=(), front=VLC_EXE, sounding=True):
        """What media(action) did, with now as Windows' media controls' session, vlc as VLC's windows and sounding
        whether VLC is making sound."""
        done = []
        with mock.patch.object(siri.win, "media_session", lambda hint=None: now), \
                mock.patch.object(siri.win, "app_sounding", lambda app: sounding and app is siri.VLC), \
                mock.patch.object(siri.win, "media_playing", lambda s: s.playing), \
                mock.patch.object(siri.win, "media_position", lambda s: s.position), \
                mock.patch.object(siri.win, "media_command", lambda s, action: done.append(action) or True), \
                mock.patch.object(siri.win, "app_windows", lambda app: list(vlc) if app is siri.VLC else []), \
                mock.patch.object(siri.win, "bring_to_front", lambda hwnd: done.append(f"front {hwnd}")), \
                mock.patch.object(siri.win, "foreground_exe", lambda: front), \
                mock.patch.object(siri.win, "press", lambda *keys: done.append(keys)), \
                mock.patch.object(siri.time, "sleep", lambda secs: None):
            siri.media(action)
        return done

    def test_previous_on_spotify_mid_song_goes_back_a_song(self):
        """One "previous" 40 s into a Spotify song only started it again."""
        self.assertEqual(self.media("previous", session("Spotify.exe", 40.0)), ["previous", "previous"])

    def test_previous_at_the_start_of_a_song_is_one_press(self):
        self.assertEqual(self.media("previous", session("Spotify.exe", 1.0)), ["previous"])

    def test_previous_elsewhere_is_one_press(self):
        """YouTube's previous goes back a video straight away, two would skip one."""
        self.assertEqual(self.media("previous", session("Chrome", 40.0)), ["previous"])

    def test_vlc_gets_its_own_keys(self):
        """VLC 3.0.16 isn't in Windows' media controls: "pause" said nothing was playing, or paused something else."""
        self.assertEqual(self.media("pause", None, vlc=[42]), ["front 42", ("space",)])
        self.assertEqual(self.media("next", session("Chrome", playing=False), vlc=[42]), ["front 42", ("n",)])
        self.assertEqual(self.media("previous", session("Chrome", playing=False), vlc=[42]), ["front 42", ("p",)])

    def test_what_is_playing_in_the_media_controls_comes_first(self):
        self.assertEqual(self.media("pause", session("Spotify.exe"), vlc=[42]), ["pause"])
        self.assertEqual(self.media("play", session("Spotify.exe", playing=False), vlc=[42]), ["play"])

    def test_an_idle_vlc_leaves_a_paused_spotify_alone(self):
        """With Spotify paused and VLC open but not playing, "previous" went to VLC and "pause" started it playing."""
        paused = session("Spotify.exe", 40.0, playing=False)
        self.assertEqual(self.media("previous", paused, vlc=[42], sounding=False), ["previous", "previous"])
        self.assertEqual(self.media("next", paused, vlc=[42], sounding=False), ["next"])
        self.assertEqual(self.media("pause", paused, vlc=[42], sounding=False), ["pause"])
        with self.assertRaisesRegex(RuntimeError, "Nothing's playing"):
            self.media("pause", None, vlc=[42], sounding=False)
        self.assertEqual(self.media("play", None, vlc=[42], sounding=False), ["front 42", ("space",)])

    def test_vlc_that_wont_come_to_the_front_gets_no_keys(self):
        with self.assertRaisesRegex(RuntimeError, "Nothing's playing"):
            self.media("pause", None, vlc=[42], front=r"C:\Windows\explorer.exe")

    def test_nothing_playing_and_no_vlc(self):
        with self.assertRaisesRegex(RuntimeError, "Nothing's playing"):
            self.media("pause", None)


class RamFigures(unittest.TestCase):
    @needs_windows  # sysinfo reads Windows' process list
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
        siri.SEND_OK["until"] = time.time() + 30  # as the yes to her question does
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
        siri.SEND_OK["until"] = time.time() + 30
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
                                    (siri, "asked_last", lambda within=0: False), (siri, "not_into_shell", lambda *a: None),
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


SEND = {"steps": [{"do": "message_send"}], "say": ""}
SCREEN = {"steps": [{"do": "screen", "task": "open the Recycle Bin on the desktop"}], "say": ""}
SHUTDOWN = {"steps": [{"do": "shutdown"}], "say": ""}
CLOSE = {"steps": [{"do": "close", "app": "Google Chrome"}], "say": ""}


class YesOrNo(Turn):
    """The yes or no to her question, said the way people say it."""
    def setUp(self):
        super().setUp()
        self.sent, self.cleared = [], []
        for name, value in (("send", lambda ready: self.sent.append(ready["contact"]) or (True, "Sent to Mum.")),
                            ("discard", lambda ready: self.cleared.append(ready["contact"]) or True)):
            patcher = mock.patch.object(siri.messaging, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def ask(self, plan=SEND, ago=0.0):
        """She asked about plan ago seconds back, "'hi' to Mum on WhatsApp. Send it?" by default."""
        asked = time.time() - ago
        siri.STAGED.update(ready={"app": "whatsapp", "contact": "Mum", "text": "hi"}, until=asked + 90)
        siri.PENDING.update(plan=plan, soon=asked + 16, until=asked + (90 if plan is SEND else 16))

    def test_natural_yeses(self):
        for words, plan in (("Yes, send it.", SEND), ("Okay, send it.", SEND), ("Sure, send it", SEND),
                            ("Yes please.", SEND), ("Yes, do it.", SEND), ("Go for it.", SEND), ("Send.", SEND),
                            ("Yes, install it.", {"steps": [{"do": "install_run"}]}),
                            ("Yes, shut it down.", SHUTDOWN), ("Yes, restart.", {"steps": [{"do": "restart"}]}),
                            ("Yes, close it.", CLOSE), ("Okay, close Chrome.", CLOSE),
                            ("Sure sure you can", SCREEN), ("Yeah, sure, sure. Yeah, you can", SCREEN),
                            ("Sure you want", SCREEN), ("Ha.", CLOSE), ("Right.", SCREEN), ("Okay.", SEND)):
            self.assertTrue(siri.said_yes(words, plan), words)

    def test_not_a_yes(self):
        for words, plan in (("Ha.", SEND), ("Right.", SEND), ("Ya", SEND), ("Please", SEND), ("Ha ha", SHUTDOWN),
                            ("Yes, close it.", SEND), ("Don't send it.", SEND), ("No, send it to Ravi", SEND),
                            ("Yes, send it to Ravi instead", SEND), ("Okay, open Notepad", SCREEN), ("", SEND)):
            self.assertFalse(siri.said_yes(words, plan), words)

    def test_um_yes_and_go_ahead_and_send_it(self):
        """Speech-to-text often starts "Uh," or "Um,". plain() took that off, so "Um, yes." was a yes, and read as said
        it wasn't, nor "Go ahead and send it", "Go on" or "Correct". "Thank you." alone is no yes to anything."""
        for words, plan in (("Um, yes.", SEND), ("Uh, yeah.", SHUTDOWN), ("Hmm, okay.", CLOSE), ("So yes", SEND),
                            ("Go ahead and send it.", SEND), ("Yeah, just send it", SEND), ("Go on.", SEND),
                            ("Correct.", SEND), ("Uh, close it", CLOSE), ("Yes, thank you.", SEND), ("Yes now", SEND)):
            self.assertTrue(siri.said_yes(words, plan), words)
        for words, plan in (("Um.", SEND), ("Thank you.", CLOSE), ("Thanks.", SCREEN), ("Now.", CLOSE),
                            ("So, no.", SEND), ("Uh-huh.", SEND)):
            self.assertFalse(siri.said_yes(words, plan), words)
        self.ask()
        siri.handle("Um, yes.", gate=True)
        self.assertEqual(self.sent, ["Mum"])

    def test_yes_send_it_sends(self):
        """"Yes, send it." became "send it" after plain(), was no yes, and the message was never sent."""
        self.ask()
        siri.handle("Yes, send it.", gate=True)
        self.assertEqual(self.sent, ["Mum"])
        self.assertEqual(self.said, ["Sent to Mum."])

    def test_a_laugh_doesnt_send_and_the_yes_can_still_follow(self):
        self.ask()
        siri.handle("Ha.", gate=True)
        siri.handle("Hmm.", gate=True)
        self.assertEqual((self.sent, self.said), ([], []))
        siri.handle("Yes.", gate=True)
        self.assertEqual(self.sent, ["Mum"])

    def test_not_now_and_forget_it_clear_the_typed_message(self):
        """"Forget it" got "Sure." and "not now" went to the model: the text stayed typed in the chat."""
        for words in ("Not now.", "Forget it.", "Never mind."):
            self.cleared.clear()
            self.ask()
            siri.handle(words, gate=True)
            self.assertEqual(self.cleared, ["Mum"], words)
            self.assertIsNone(siri.PENDING["plan"])
        self.assertEqual(self.sent, [])

    def test_a_command_once_the_first_seconds_are_gone_is_no_no(self):
        """"Jev, stop the music" 40 s after "Send it?" was taken as a no to the message, and the music played on."""
        paused = []
        with mock.patch.object(siri, "media", paused.append):
            self.ask(ago=40)
            siri.handle("stop the music")
            self.assertEqual((paused, self.cleared, self.sent), (["pause"], [], []))
            self.ask(ago=40)
            siri.handle("Not now.")  # still a no, with her name
            self.ask()
            siri.handle("Stop.", gate=True)  # and straight after she asked
        self.assertEqual((paused, self.cleared, self.sent), (["pause"], ["Mum", "Mum"], []))

    def test_a_laugh_never_shuts_down(self):
        shut = []
        self.ask(SHUTDOWN)
        with mock.patch.object(siri.win, "shutdown", lambda: shut.append("down")):
            siri.handle("Ha.", gate=True)
            siri.handle("Right.", gate=True)
        self.assertEqual(shut, [])

    def test_sure_you_can_lets_her_look(self):
        """Real log: "Sure sure you can" to "Should I look at your screen for that?" wasn't a yes, she asked again."""
        looked = []
        self.ask(SCREEN)
        with mock.patch.object(siri, "see", lambda task, notify=None: looked.append(task) or ("It's open.", [])):
            siri.handle("Sure sure you can", gate=True)
        self.assertEqual(looked, ["open the Recycle Bin on the desktop"])

    def test_the_window_for_a_yes_opens_once_she_has_asked(self):
        """It was 16 s from before the readback: a long one used it up, and the yes came too late."""
        with mock.patch.object(siri, "say", lambda line, notify: time.sleep(0.5)), self.model(
                {"steps": [], "say": "Should I close Google Chrome?", "confirm": CLOSE}):
            siri.handle("close it")
        self.assertGreater(siri.PENDING["until"] - time.time(), siri.FOLLOW_UP + 8 - 0.2)

    def test_a_message_waits_for_its_yes_as_long_as_it_is_typed_in(self):
        """README: saying nothing for 90 seconds leaves the message unsent, so a yes inside 90 s sends it."""
        with mock.patch.object(siri.messaging, "prepare", staged):
            siri.handle("Message Mum on WhatsApp: hi")
        self.assertEqual(siri.PENDING["plan"], SEND)
        self.assertAlmostEqual(siri.PENDING["until"], siri.STAGED["until"], delta=1)
        self.assertGreater(siri.PENDING["until"] - time.time(), 80)

    def test_a_question_that_ends_with_a_note_keeps_the_window_open(self):
        """"... Send it? I can't read Telegram back, so check it on screen." ends in a full stop, so a message asked for
        without her name came back as just a chat: no window for the yes, and a yes without her name was let go."""
        unread = lambda app, contact, text: {**staged(app, contact, text), "checked": False, "say": "Telegram"}
        # without her name the model decides it was for her and plans the message (quick no longer stages it cold)
        planned = {"steps": [{"do": "message", "app": "telegram", "contact": "Mum", "text": "hi"}], "say": ""}
        with mock.patch.object(siri.messaging, "prepare", unread), \
                mock.patch.object(siri, "think", lambda *a, **k: planned):
            self.assertIs(siri.handle("Message Mum on Telegram: hi", gate="cold"), True)
        self.assertTrue(self.said[0].endswith("so check it on screen."), self.said)


class FoundInWhatsApp(Turn):
    """"Message Buntyy": she looks in WhatsApp, asks if who she found is them, and the message waits for its own yes."""
    def setUp(self):
        super().setUp()
        m, self.sent = siri.messaging, []

        def prepare(app, contact, text):
            if not m.read_contacts().get(m.alias_key(contact), {}).get("whatsapp"):
                raise m.NeedContact(f"I don't know {contact} on WhatsApp yet.")
            return {**staged(app, contact, text), "to": "Buntyyy"}
        found = [{"name": "Buntyyy \U0001f43c", "number": "919573309199", "shown": "+91 95733 09199"},
                 {"name": "Bunty K", "number": "918888802607", "shown": "+91 88888 02607"}]
        for target, name, value in ((m, "prepare", prepare), (m, "whatsapp_people", lambda name, **kw: list(found)),
                                    (m, "send", lambda ready: self.sent.append(ready["contact"]) or (True, "Sent.")),
                                    (m, "discard", lambda ready: True)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(lambda: (siri.FOUND.update(people=[], until=0.0), siri.ASKED.update(alias="", until=0.0),
                                 m._write_json(m.CONTACTS_PATH, {})))

    def test_yes_to_them_then_yes_to_the_message_sends_it(self):
        siri.handle("message buntyy on whatsapp: hi")
        self.assertEqual(self.said[0], "Let me look for buntyy in your WhatsApp.")
        self.assertTrue(self.said[-1].endswith("The first is Buntyyy, number plus 9 1, 9 5 7 3 3, 0 9 1 9 9. "
                                               "Is that them?"), self.said)
        siri.handle("Yes, that's him.", gate=True)
        self.assertEqual(self.said[-1], "“hi” to buntyy on WhatsApp. Send it? The chat open is Buntyyy.")
        self.assertEqual(self.sent, [])  # saved, and asked about: not sent
        siri.handle("Yes, send it.", gate=True)
        self.assertEqual(self.sent, ["buntyy"])
        self.assertEqual(siri.messaging.read_contacts()["buntyy"]["whatsapp"], "919573309199")

    def test_no_then_the_next_one(self):
        siri.handle("message buntyy on whatsapp: hi")
        siri.handle("No.", gate=True)
        self.assertEqual(self.said[-1], "Then is it Bunty K, number plus 9 1, 8 8 8 8 8, 0 2 6 0 7?")
        siri.handle("No.", gate=True)
        self.assertEqual(self.said[-1], "Okay. What's their phone number, with the country code?")
        self.assertEqual((siri.messaging.read_contacts(), self.sent), ({}, []))

    def test_a_laugh_saves_nobody(self):
        siri.handle("message buntyy on whatsapp: hi")
        siri.handle("Ha.", gate=True)
        siri.handle("Right.", gate=True)
        self.assertEqual(siri.messaging.read_contacts(), {})

    def test_yes_send_it_and_yes_thats_them_by_name(self):
        """Review: "Yes, send it" and "Yes, that's Bunty" weren't a yes, and the question went to the model."""
        for words in ("Yes, send it.", "Yes, that's buntyy."):
            siri.messaging._write_json(siri.messaging.CONTACTS_PATH, {})
            siri.handle("message buntyy on whatsapp: hi")
            siri.handle(words, gate=True)
            self.assertEqual(self.said[-1], "“hi” to buntyy on WhatsApp. Send it? The chat open is Buntyyy.",
                             words)
            self.assertEqual(self.sent, [], words)

    def test_cancel_ends_the_lookup(self):
        """Review: "Cancel" moved on to the next one she found, then asked for the number."""
        siri.handle("message buntyy on whatsapp: hi")
        siri.handle("Cancel.", gate=True)
        self.assertIn(self.said[-1], siri.REPLIES["confirm_no"])
        self.assertEqual((siri.FOUND["people"], siri.ASKED["alias"], siri.messaging.read_contacts()), ([], "", {}))

    def test_the_number_she_read_isnt_kept(self):
        """Review: a number read off WhatsApp went into history, and from there to the model."""
        kept = []
        with mock.patch.object(siri.history, "add", lambda *a: kept.append(a)):
            siri.handle("message buntyy on whatsapp: hi")
        self.assertIn("9 5 7 3 3", self.said[-1])
        self.assertTrue(kept)
        self.assertNotIn("9 5 7 3 3", repr(kept))


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
                mock.patch.object(siri, "fish", original("fish")), mock.patch.object(siri, "Line", ORIGINAL["Line"]), \
                mock.patch.object(siri.pocket, "available", lambda voice=None: False), \
                mock.patch.object(siri.win, "speak_native", lambda text, **kw: native.append(text)):
            original("speak")("A line nobody has cached, 1729.")
        self.assertEqual(native, ["A line nobody has cached, 1729."])

    def test_slow_fish_gets_her_voice_on_this_pc_when_it_is_there(self):
        import requests
        made = []

        def post(url, **kw):
            raise requests.ReadTimeout("read timed out")

        def stream(text, voice, **kw):
            made.append((text, voice))
            q = __import__("queue").Queue()
            q.put(None)  # nothing to play, so no sound in a test
            return q
        with mock.patch.object(siri, "FISH", SimpleNamespace(post=post)), \
                mock.patch.object(siri, "fish", original("fish")), mock.patch.object(siri, "Line", ORIGINAL["Line"]), \
                mock.patch.object(siri.pocket, "available", lambda voice=None: True), \
                mock.patch.object(siri.pocket, "stream", stream), \
                mock.patch.object(siri.win, "speak_native", lambda text, **kw: self.fail("Windows' voice")):
            original("speak")("A line nobody has cached, 1729.", "9a9cf47702da476aa4629e2506d4a857")
        self.assertEqual(made, [("A line nobody has cached, 1729.", "p248")])


if __name__ == "__main__":
    unittest.main()
