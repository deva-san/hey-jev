"""Carrying things out and confirming them: keys, media, the yes or no to her questions, what she says about what she
did. Nothing here acts on the PC: tests.support turns that into tripwires, and each test patches what it needs."""
import json
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


class NightLight(unittest.TestCase):
    """22 October: Night light took the model and a walk through Settings (and with Haiku's thinking off it turned on
    dark mode instead). It's switched in the registry now, the way Quick Settings does it."""
    # this PC's state value that day: off, last changed by hand (Windows 11 25H2, build 26200)
    OFF = bytes.fromhex("43 42 01 00 0a 02 01 00 2a 06 cc f1 ab d6 06 2a 2b 0e 13 43 42 01 00 d0 0a 02 c6 14 f8 f7 c2 "
                        "8f ae a5 d6 ee 01 00 00 00 00")
    # on, as the scheduler leaves it (no cause field), from nathanbabcock/nightlight-cli issue 2
    SCHEDULED_ON = bytes.fromhex("43 42 01 00 0a 02 01 00 2a 06 cd 8b 80 cd 06 2a 2b 0e 12 43 42 01 00 10 00 c6 14 e5 c6 "
                                 "b2 82 fe ad c1 ed 01 00 00 00 00")
    NOW = 1792000000.0

    def fields(self, value):
        return winplatform._night_fields(winplatform._night_split(value)[1])

    def test_on_and_off_are_what_windows_writes(self):
        on = winplatform.night_light_value(self.OFF, True, self.NOW)
        stamp, inner = winplatform._night_split(on)
        filetime = winplatform._varint(int((self.NOW + winplatform.FILETIME_1970) * 10_000_000))
        self.assertEqual(inner, bytes.fromhex("43 42 01 00 10 00 d0 0a 02 c6 14") + filetime + b"\x00")
        self.assertEqual(stamp, int(self.NOW))
        self.assertEqual(on[:19], self.OFF[:10] + winplatform._varint(int(self.NOW)) + bytes.fromhex("2a 2b 0e 15"))
        off = winplatform.night_light_value(on, False, self.NOW)
        self.assertNotIn(0, self.fields(off))
        self.assertEqual(winplatform._night_split(off)[0], int(self.NOW) + 2)  # never one Windows has seen go by
        self.assertEqual(len(off), len(self.OFF))

    def test_on_and_off_from_the_schedule_too(self):
        self.assertIn(0, self.fields(self.SCHEDULED_ON))
        off = winplatform.night_light_value(self.SCHEDULED_ON, False, self.NOW)
        self.assertEqual(sorted(self.fields(off)), [10, 20])  # turned off by hand

    def test_a_value_laid_out_otherwise_is_left_alone(self):
        for bad in (b"", self.OFF[:-1], self.OFF + b"\x00", self.OFF.replace(b"\x2b\x0e", b"\x2b\x10"),
                    self.OFF[:18] + bytes([10]) + b"\x43\x42\x01\x00\x09\x03abc\x00" + b"\x00" * 3):  # a string
            with self.assertRaises(ValueError):
                winplatform.night_light_value(bad, True, self.NOW)
        unusable = bytes.fromhex("43 42 01 00 0a 02 01 00 2a 06 cc f1 ab d6 06 2a 2b 0e 08 43 42 01 00 c2 1e 00 00 "
                                 "00 00 00")
        with self.assertRaises(RuntimeError):
            winplatform.night_light_value(unusable, True, self.NOW)

    def test_said_it_switches_at_once_and_night_mode_is_dark_mode(self):
        for said, step in (("turn on night light", {"do": "night_light", "on": True}),
                           ("Night light on", {"do": "night_light", "on": True}),
                           ("enable nightlight", {"do": "night_light", "on": True}),
                           ("turn off night light", {"do": "night_light", "on": False}),
                           ("night light off", {"do": "night_light", "on": False}),
                           ("turn on night mode", {"do": "dark_mode", "on": True}),
                           ("night mode", {"do": "dark_mode", "on": True}),
                           ("turn off night mode", {"do": "dark_mode", "on": False}),
                           ("turn on dark mode", {"do": "dark_mode", "on": True}),
                           # as speech-to-text heard them on 22 October, both done by the model, slowly or not at all
                           ("Turn on light night", {"do": "night_light", "on": True}),
                           ("Hey turn on light mode", {"do": "dark_mode", "on": False}),
                           ("start night light", {"do": "night_light", "on": True}),
                           ("Back to light mode", {"do": "dark_mode", "on": False}),
                           ("switch to light mode", {"do": "dark_mode", "on": False}),
                           ("light mode", {"do": "dark_mode", "on": False}),
                           ("turn off light mode", {"do": "dark_mode", "on": True})):
            self.assertEqual(siri.quick(said)["steps"], [step], said)
        self.assertIn(siri.quick("turn on light mode")["say"], siri.REPLIES["light_on"])
        switched = []
        with mock.patch.object(siri.win, "set_night_light", lambda on: switched.append(on) or True), \
                mock.patch.object(siri.win, "night_light", lambda: True):
            for on in (True, False, None):
                siri.do_step({"do": "night_light", "on": on})
        self.assertEqual(switched, [True, False, False])  # None: the other way from now
        self.assertEqual(siri.confirm_question({"do": "night_light", "on": True}), "Should I turn night light on?")
        self.assertEqual(siri.confirm_question({"do": "dark_mode", "on": False}), "Should I turn dark mode off?")
        self.assertIn('{"do":"night_light","on":true}', siri.PROMPT)


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
        with mock.patch.object(siri.win, "close_site_tab", mock.Mock(side_effect=LookupError("no tab shows it"))):
            failed, _, _, spoken = self.close(not_running)
        self.assertEqual(failed, ["Messages isn't open"])  # in an app or a tab
        self.assertNotIn("Closed Messages.", spoken)
        self.assertEqual(len(spoken), 1)

    def test_a_site_isnt_an_app_its_tab_is_closed(self):
        """"Close the YouTube" on 22 October: "Sorry, that didn't work. YouTube isn't running." """
        def not_running(app):
            raise RuntimeError(f"{app.name} isn't running")
        closed = mock.Mock(return_value="Akka Official Trailer - YouTube - Google Chrome")
        with mock.patch.object(siri.win, "quit_app", not_running), mock.patch.object(siri.win, "close_site_tab", closed):
            failed, _, _, spoken = siri.run_plan({"steps": [{"do": "close", "app": "YouTube"}], "say": "Closed it."},
                                                 None)
        self.assertEqual((failed, spoken), ([], ["Closed it."]))
        closed.assert_called_once_with(("YouTube",))
        self.assertEqual(siri.quick("Close the YouTube")["steps"], [{"do": "close", "app": "YouTube"}])
        self.assertEqual(siri.quick("close youtube tab")["steps"], [{"do": "close", "app": "YouTube"}])

    def test_a_sites_own_titles_are_its_tabs(self):
        for title, names, shows in (("Akka Official Trailer | Keerthy Suresh - YouTube - Google Chrome", "YouTube", True),
                                    ("(3) YouTube - Google Chrome", "YouTube", True),
                                    ("YouTube", "YouTube", True),  # its app, installed from Chrome
                                    ("Inbox (12) - hari@gmail.com - Gmail - Google Chrome", "Gmail", True),
                                    ("(2) Feed | LinkedIn - Personal - Microsoft\u200b Edge", "LinkedIn", True),
                                    ("Home / X - Google Chrome", "X", True),
                                    ("akka trailer - Google Search - Google Chrome", ("Google", "Google Search"), True),
                                    ("download youtube videos - Google Search - Google Chrome", "YouTube", False),
                                    ("YouTube Music - Google Chrome", "YouTube", False),
                                    ("Max - Google Chrome", "X", False)):
            self.assertEqual(winplatform.shows_site(title, names), shows, title)

    def test_close_it_right_after_she_played_one_is_her_tab(self):
        """22 October: "Close it", twice, 17 s after she played a trailer, went to the model as room talk."""
        front = "Akka Official Trailer | Keerthy Suresh - YouTube - Google Chrome"
        with mock.patch.object(siri.win, "front_title", lambda: front), \
                mock.patch.dict(siri.FOCUS, app="youtube", at=time.monotonic() - 17):
            self.assertEqual(siri.quick("Close it")["steps"], [{"do": "close", "app": "YouTube", "tab": True}])
            self.assertEqual(siri.quick("close this video")["steps"], [{"do": "close", "app": "YouTube", "tab": True}])
            self.assertIsNone(siri.let_go({"steps": [{"do": "close", "app": "YouTube", "tab": True}], "say": "Done."}))
        with mock.patch.object(siri.win, "front_title", lambda: "Inbox - Outlook"), \
                mock.patch.dict(siri.FOCUS, app="youtube", at=time.monotonic() - 17):
            self.assertIsNone(siri.quick("Close it"))  # you've gone to something else: the model works it out
        with mock.patch.object(siri.win, "front_title", lambda: front), \
                mock.patch.dict(siri.FOCUS, app="youtube", at=time.monotonic() - 300):
            self.assertIsNone(siri.quick("Close it"))  # long ago

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
                                    (siri, "offered", lambda within=0: ""),
                                    (siri.win, "press", lambda *keys: self.pressed.append(keys))):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        siri.PENDING.update(plan=None, until=0.0)
        siri.STAGED.update(ready=None, until=0.0)
        siri.STAGED_INSTALL.update(ready=None, until=0.0)

    def model(self, plan):
        return mock.patch.object(siri, "think", lambda *a, **kw: plan)


class NowPlaying(unittest.TestCase):
    """22 October, 17:25: "What's the video", without her name. The model looked at the screen for it, and that was
    let go as room talk: "I wasn't sure that was for me"."""
    TRAILER = ("Akka Official Trailer | Keerthy Suresh | Radhika Apte", "Netflix India")

    def ask(self, words, props=("", ""), page=""):
        with mock.patch.object(siri.win, "media_session", lambda app_hint=None: object()), \
                mock.patch.object(siri.win, "media_props", lambda session: props), \
                mock.patch.object(siri, "youtube_title", lambda: page):
            return siri.quick(words)

    def test_whats_playing_is_said_from_the_media_controls(self):
        for words in ("What's the video", "what's playing", "what song is this", "what video is this"):
            self.assertEqual(self.ask(words, self.TRAILER),
                             {"steps": [], "say": "It's Akka Official Trailer, Keerthy Suresh, Radhika Apte, from "
                                                  "Netflix India."}, words)
        self.assertEqual(self.ask("what's the video", page="Lofi beats to study to")["say"],
                         "It's Lofi beats to study to.")  # paused, nothing in the media controls: the page in front
        self.assertIsNone(self.ask("what's playing"))  # nothing says: the model looks

    def test_what_a_video_is_about_is_a_look_at_the_screen_said_plainly(self):
        screen = [{"do": "screen", "task": "say what the video on the screen is about"}]
        for words in ("what is this video about", "What's the video", "what's this page about", "what song is this"):
            self.assertIsNone(siri.unasked(screen, words, "cold"), words)
        self.assertEqual(siri.unasked(screen, "what was that about", "cold"), screen[0])  # room talk


OFFER = "There's a WhatsApp message on your screen, Hari. Want me to read it or open the chat?"


class AnswerToHer(Turn):
    def test_a_mumbled_yes_to_what_she_offered_answers_it(self):
        """22 October, 15:08: she offered "Want me to read it or open the chat?", and "Yes", 46% sure, was let go."""
        asked = []
        with mock.patch.object(siri, "offered", lambda within=0: OFFER), \
                mock.patch.object(siri, "think", lambda *a, **kw: asked.append(str(a[0])) or
                                  {"steps": [], "say": "Ravi says he's on his way."}):
            siri.handle(siri.speech.heard("Yes", 0.46), gate=True)
        self.assertEqual((asked, self.said), (["Yes"], ["Ravi says he's on his way."]))

    def test_a_mumble_after_nothing_offered_or_said_cold_is_still_let_go(self):
        with mock.patch.object(siri, "think", lambda *a, **kw: self.fail("asked the model")):
            siri.handle(siri.speech.heard("Yes", 0.46), gate=True)  # nothing offered (setUp)
            with mock.patch.object(siri, "offered", lambda within=0: OFFER):
                siri.handle(siri.speech.heard("Yes", 0.46), gate="cold")
                siri.handle(siri.speech.heard("and then we went to the market", 0.46), gate=True)
        self.assertEqual(self.said, [])


class ToSomeoneElse(Turn):
    def test_where_are_you_without_her_name_is_to_a_person(self):
        """22 October, 21:26: "Where are you" got "I'm right here on Hari's laptop, Jev."."""
        with mock.patch.object(siri, "think", lambda *a, **kw: self.fail("asked the model")):
            for words in ("Where are you?", "when are you coming home", "did you eat", "Are you coming?"):
                self.assertFalse(siri.handle(words, gate="cold"), words)
        self.assertEqual(self.said, [])

    def test_she_never_calls_you_by_her_own_name(self):
        self.assertEqual(siri.tidy("I'm right here on Hari's laptop, Jev."), "I'm right here on Hari's laptop.")
        self.assertEqual(siri.tidy("Jev, it's five o'clock."), "It's five o'clock.")
        for line in ("Hey, I'm Jev, what can I do for you?", 'Just say "Hey, Jev."', "I'm Jev."):
            self.assertEqual(siri.tidy(line), line)


class Offered(unittest.TestCase):
    def offered(self, line):
        recent = [(time.time(), "what's on my screen", json.dumps({"steps": [], "say": line}))]
        with mock.patch.object(siri.history, "recent", lambda n, within: recent):
            return siri.offered()

    def test_what_she_offered_and_what_she_left_to_you(self):
        self.assertEqual(self.offered(OFFER), OFFER)
        self.assertEqual(self.offered("Should I look it up?"), "Should I look it up?")
        for line in ("Done. Anything else?", "Hi! What can I do for you?", "Is there anything you'd like me to do?",
                     "It's 32 degrees in Delhi.", ""):
            self.assertEqual(self.offered(line), "", line)


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

    def test_close_it_without_her_name_closes_the_video_she_just_played(self):
        """22 October, 15:10: the trailer she'd played 17 s before was playing, and "Close it" was let go twice."""
        def not_running(app):
            raise RuntimeError(f"{app.name} isn't running")
        tab = mock.Mock(return_value="Akka Official Trailer - YouTube - Google Chrome")
        with mock.patch.object(siri.win, "front_title", lambda: "Akka Official Trailer - YouTube - Google Chrome"), \
                mock.patch.dict(siri.FOCUS, app="youtube", at=time.monotonic() - 17), \
                mock.patch.object(siri, "media_playing", lambda: True), \
                mock.patch.object(siri.win, "quit_app", not_running), \
                mock.patch.object(siri.win, "close_site_tab", tab), \
                mock.patch.object(siri, "think", lambda *a, **kw: self.fail("asked the model")):
            siri.handle("Close it", gate="cold")
        tab.assert_called_once_with(("YouTube",))
        self.assertEqual(len(self.said), 1)
        asked = []
        with mock.patch.object(siri.win, "front_title", lambda: "Inbox - Outlook"), \
                mock.patch.dict(siri.FOCUS, app="youtube", at=time.monotonic() - 17), \
                mock.patch.object(siri, "think", lambda *a, **kw: asked.append(a[0]) or None):
            siri.handle("Close it", gate="cold")  # not what you're looking at now: the model decides
        self.assertEqual(asked, ["Close it"])


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

    def test_a_yes_or_no_you_never_said_isnt_the_message(self):
        """"You not sent the message", and the model planned the message again with "yes" for its words: "yes" was
        typed in Mum's chat, asked about as the message to send."""
        typed = []
        with self.model({"steps": [{"do": "message", "app": "whatsapp", "contact": "Mum", "text": "Yes."}],
                         "say": ""}), \
                mock.patch.object(siri.messaging, "prepare", lambda app, contact, text: typed.append(text) or
                                  staged(app, contact, text)):
            siri.handle("You not sent the message")
        self.assertEqual(typed, [])
        self.assertEqual(self.said, ["What should the message say?"])
        self.assertFalse(siri.bare_answer("No, I can't make it", "let ravi know i'm busy"))  # a message, that one
        self.assertFalse(siri.bare_answer("yes", "reply yes"))


class Short(unittest.TestCase):
    """Out loud, an answer is a few sentences at most, without markdown or list numbers; on the phone it's read whole.
    The model gave spoken answers of 374 letters, with ** and numbered lists."""
    ANSWER = ("Here are three good phones under 20,000:\n1. **Pixel 9a** at 19,999\n2. Galaxy A55, the best screen\n"
              "3. Nothing Phone 3a for the looks\nAll three take good photos, and the Pixel gets updates the longest. "
              "If you mostly watch videos, the Galaxy's screen is the one to pick, and it charges fastest too.")

    def test_said_short_without_the_list_numbers(self):
        said = siri.tidy(self.ANSWER)
        self.assertTrue(said.startswith("Here are three good phones under 20,000: Pixel 9a at 19,999. Galaxy A55, the "
                                        "best screen. Nothing Phone 3a for the looks."), said)
        self.assertLessEqual(len(said), siri.SAY_MOST)
        self.assertNotIn("1.", said)

    def test_read_whole_on_the_phone(self):
        to = siri.REPLY_TO.set([])
        try:
            self.assertEqual(siri.tidy(f"{self.ANSWER}\n{LONG}"), f"{self.ANSWER}\n{LONG}".replace("**", ""))
        finally:
            siri.REPLY_TO.reset(to)

    def test_said_as_its_written_it_stops_there_too(self):
        """Most answers are said as the model writes them (LiveSay), a sentence at a time, so tidy alone cut nothing."""
        live, chunker = siri.LiveSay(None, make=lambda line: None), siri.SentenceChunker()
        for sentence in chunker.feed(self.ANSWER) + chunker.flush():
            live._queue(sentence)
        said = []
        while not live.lines.empty():
            said.append(live.lines.get()[0])
        self.assertEqual(said[:2], ["Here are three good phones under 20,000:", "Pixel 9a at 19,999"])
        self.assertLessEqual(len(" ".join(said)), siri.SAY_MOST)
        self.assertNotIn("If you mostly watch videos", " ".join(said))  # nor anything after where it stopped
        self.assertNotRegex(" ".join(said), r"\b\d\.")

    def test_only_the_name_in_settings(self):
        """The model called him Harish, where Settings say Hari."""
        with mock.patch.dict(siri.settings._load(), {"name": "Hari"}):
            self.assertIn("Their name is Hari, never any other.", siri.context())


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

    def test_a_message_she_couldnt_clear_is_said_to_be_still_there(self):
        """A no clears only what she typed, in the chat she typed it in: with another chat open, it's left, and she
        says so, rather than "Okay, I won't." with "hi" still in Mum's box."""
        self.ask()
        with mock.patch.object(siri.messaging, "discard", lambda ready: False):
            siri.handle("No.", gate=True)
        self.assertEqual(self.said, ["Okay, I won't send it. It's still typed in WhatsApp, so clear it there."])
        self.assertIsNone(siri.STAGED["ready"])

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
        found = [{"name": "Buntyyy \U0001f43c", "number": "915555501234", "shown": "+91 55555 01234"},
                 {"name": "Bunty K", "number": "915550005678", "shown": "+91 55500 05678"}]
        for target, name, value in ((m, "prepare", prepare), (m, "whatsapp_people", lambda name, **kw: list(found)),
                                    (m, "send", lambda ready: self.sent.append(ready["contact"]) or (True, "Sent.")),
                                    (m, "discard", lambda ready: True)):
            patcher = mock.patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(lambda: (siri.FOUND.update(people=[], until=0.0), siri.ASKED.update(alias="", until=0.0),
                                 m._write_json(m.CONTACTS_PATH, {}, emptying=True)))

    def test_yes_to_them_then_yes_to_the_message_sends_it(self):
        siri.handle("message buntyy on whatsapp: hi")
        self.assertEqual(self.said[0], "Let me look for buntyy in your WhatsApp.")
        self.assertTrue(self.said[-1].endswith("The first is Buntyyy, number plus 9 1, 5 5 5 5 5, 0 1 2 3 4. "
                                               "Is that them?"), self.said)
        siri.handle("Yes, that's him.", gate=True)
        self.assertEqual(self.said[-1], "“hi” to buntyy on WhatsApp. Send it? The chat open is Buntyyy.")
        self.assertEqual(self.sent, [])  # saved, and asked about: not sent
        siri.handle("Yes, send it.", gate=True)
        self.assertEqual(self.sent, ["buntyy"])
        self.assertEqual(siri.messaging.read_contacts()["buntyy"]["whatsapp"], "915555501234")

    def test_no_then_the_next_one(self):
        siri.handle("message buntyy on whatsapp: hi")
        siri.handle("No.", gate=True)
        self.assertEqual(self.said[-1], "Then is it Bunty K, number plus 9 1, 5 5 5 0 0, 0 5 6 7 8?")
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
            siri.messaging._write_json(siri.messaging.CONTACTS_PATH, {}, emptying=True)
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
        with mock.patch.object(siri.history, "add", lambda *a, **k: kept.append((a, k))):  # with where and how
            siri.handle("message buntyy on whatsapp: hi")
        self.assertIn("5 5 5 5 5", self.said[-1])
        self.assertTrue(kept)
        self.assertNotIn("5 5 5 5 5", repr(kept))


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
