"""The local fast path: what quick() and fast_intent plan on this PC, and what they leave to the model."""
import contextlib
import io
import threading
import time
import unittest
from unittest import mock

from tests.support import siri, winplatform

import fast_intent


class Routing(unittest.TestCase):
    """quick() and handle() with nothing to find: no Start menu apps, nothing in front, no last YouTube search, no
    routines. Installs, messages and PC lookups are recorded instead of done."""

    def setUp(self):
        self.installs, self.messages = [], []
        for patch in (
                mock.patch.object(siri.win, "loaded_start_apps", lambda: []),
                mock.patch.object(siri, "focused_on", lambda app: False),
                mock.patch.object(siri, "youtube_title", lambda: ""),
                mock.patch.object(siri, "LAST_QUERY", [""]),
                mock.patch.object(siri, "routines", lambda: []),
                mock.patch.object(siri.web, "weather", side_effect=RuntimeError("offline")),
                mock.patch.object(siri.sysinfo, "lookup", lambda what: {}),
                mock.patch.object(siri.sysinfo, "describe", lambda what, data, drive=None: f"lookup {what}"),
                mock.patch.object(siri, "stage_install",
                                  lambda name: self.installs.append(name) or {"steps": [], "say": "Install it?"}),
                mock.patch.object(siri, "stage_message", lambda app, who, text:
                                  self.messages.append((app, who, text)) or {"steps": [], "say": "Send it?"})):
            patch.start()
            self.addCleanup(patch.stop)

    def quick(self, words, gate=None):
        with contextlib.redirect_stdout(io.StringIO()):
            return siri.quick(words) if gate is None else siri.quick(words, gate)

    def steps(self, words):
        plan = self.quick(words)
        return plan and plan["steps"]

    def handle(self, words, gate):
        """One turn, with the model, the steps and her voice stubbed: (whether the model was asked, the plan she ran,
        the plan waiting on a yes)."""
        ran = []
        with mock.patch.object(siri, "think", return_value=None) as think, \
                mock.patch.object(siri, "run_plan", lambda plan, notify: ran.append(plan) or ([], False, None, [])), \
                mock.patch.object(siri, "media_playing", return_value=False), \
                mock.patch.object(siri, "learn_later"), mock.patch.object(siri.history, "add"), \
                mock.patch.dict(siri.PENDING, {"plan": None, "until": 0.0}), contextlib.redirect_stdout(io.StringIO()):
            siri.handle(words, gate=gate)
            return think.called, ran[0] if ran else None, siri.PENDING["plan"]


class Writing(Routing):
    """A12: type/write/enter take the words as said only when they are the text, not a request to write something."""

    def test_compose_and_fill_in_requests_go_to_the_model(self):
        for words in ("write a short email saying I'll be late", "open Notepad and write today's date",
                      "write down what I say", "type my email address", "write me a poem about rain", "type the date",
                      "enter my password"):
            with self.subTest(words=words):
                self.assertIsNone(self.quick(words))

    def test_enter_full_screen_is_the_shortcut(self):
        self.assertEqual(self.steps("enter full screen"), [{"do": "keys", "keys": "f11"}])

    def test_typed_text_keeps_its_own_then(self):
        self.assertEqual(self.steps("open notepad and type salt then pepper"),
                         [{"do": "open", "app": "Notepad"}, {"do": "type", "text": "salt then pepper"}])

    def test_then_press_enter_still_presses_it(self):
        typed = [{"do": "type", "text": "hello"}, {"do": "keys", "keys": "enter"}]
        for words, steps in (("type hello then press enter", typed), ("type hello and then press enter", typed),
                             ("open notepad and type hello then press enter", [{"do": "open", "app": "Notepad"}, *typed])):
            with self.subTest(words=words):
                self.assertEqual(self.steps(words), steps)

    def test_literal_text_is_still_typed(self):
        self.assertEqual(self.steps("type Hello, World! and press enter"),
                         [{"do": "type", "text": "Hello, World!"}, {"do": "keys", "keys": "enter"}])
        self.assertEqual(self.steps("write I'll be late"), [{"do": "type", "text": "I'll be late"}])
        self.assertEqual(self.steps("open notepad and type hello"),
                         [{"do": "open", "app": "Notepad"}, {"do": "type", "text": "hello"}])


class Play(Routing):
    """A17, R8: what QUICK leaves to the model isn't played by fast_intent as a YouTube search for those words."""

    def test_what_siri_leaves_to_the_model_isnt_searched(self):
        for words in ("play shape of you on Spotify", "play the second song", "play the same song again",
                      "play the top result", "play the second video", "play the third video"):
            with self.subTest(words=words):
                self.assertIsNone(self.quick(words))
                self.assertIsNone(fast_intent.FastIntentMatcher(siri).match(words))

    def test_a_song_still_plays(self):
        self.assertEqual(self.steps("play Arijit Singh songs"),
                         [{"do": "youtube", "query": "arijit singh songs", "play": True}])
        self.assertEqual(self.steps("play It's My Life"), [{"do": "youtube", "query": "it's my life", "play": True}])


class RoomTalk(Routing):
    """R5: talk about playing or looking up isn't a YouTube or Google search, and "let's play" isn't a direct ask."""

    def test_talk_isnt_a_search(self):
        for words in ("let's play cricket tomorrow", "play with the dog", "look up, there's a bird on the roof"):
            with self.subTest(words=words):
                self.assertIsNone(self.quick(words))

    def test_lets_play_goes_to_the_model_without_her_name(self):
        asked, _, _ = self.handle("let's play some music", "cold")
        self.assertTrue(asked)
        self.assertEqual(self.steps("let's play some music"), [{"do": "youtube", "query": "some music", "play": True}])


class Installs(Routing):
    """A18, A41: only an install word looks an app up in winget."""

    def test_everyday_asks_arent_installs(self):
        for words in ("get me the weather", "get me the latest news", "Get me the weather in Delhi",
                      "set up dark mode", "download the youtube video", "download the report"):
            self.quick(words)
        self.assertEqual(self.installs, [])

    def test_get_me_the_weather_is_the_weather(self):
        with mock.patch.object(siri.web, "weather", return_value={}) as weather, \
                mock.patch.object(siri, "weather_line", lambda w, day=None: "Sunny."):
            self.assertEqual(self.quick("Get me the weather in Delhi")["say"], "Sunny.")
        weather.assert_called_once_with("delhi")

    def test_for_tomorrow_is_a_day_not_a_place(self):
        got = []
        with mock.patch.object(siri.web, "weather", lambda where=None: {"where": where}), \
                mock.patch.object(siri, "weather_line", lambda w, day=None: got.append((w["where"], day)) or "Sunny."):
            for words in ("get me the weather for tomorrow", "what's the weather for the day after tomorrow",
                          "weather in Delhi for tomorrow", "weather for tomorrow in Mumbai", "weather in Tomorrowland"):
                self.quick(words)
        self.assertEqual(got, [(None, "tomorrow"), (None, "the day after tomorrow"), ("delhi", "tomorrow"),
                               ("mumbai", "tomorrow"), ("tomorrowland", None)])

    def test_install_words_still_install(self):
        for words in ("download and install VLC", "install Zoom on this PC", "update Git"):
            self.quick(words)
        self.assertEqual(self.installs, ["VLC", "Zoom", "Git"])


class Routines(Routing):
    """A19: a routine she was taught runs before the message, install, typing and compound shortcuts."""

    def test_routines_come_first(self):
        routine = {"dir": "focus", "plan": {"steps": [{"do": "volume", "to": "mute"}], "say": "Focus time."}}
        phrases = ("enter focus mode", "write my status", "get me ready for work", "install the usual apps")
        with mock.patch.object(siri, "routines", lambda: [(p, routine) for p in phrases]):
            for words in ("Enter focus mode.", "write my status", "get me ready for work", "install the usual apps"):
                with self.subTest(words=words):
                    self.assertEqual(self.quick(words), {"steps": [{"do": "volume", "to": "mute"}], "say": "Focus time."})
        self.assertEqual(self.installs, [])

    def test_a_routine_doesnt_wait_for_the_skill_bookkeeping(self):
        """"Work mode" waited 18-26 ms inside quick() while Hermes' usage tracking locked, read and wrote its file,
        before anything happened. It's kept all the same, just not on the turn."""
        routine = {"dir": "focus", "plan": {"steps": [{"do": "volume", "to": "mute"}], "say": "Focus time."}}
        kept = threading.Event()

        def used(name):
            time.sleep(0.3)  # the file lock held by the curator a moment
            kept.set()
        with mock.patch.object(siri, "routines", lambda: [("enter focus mode", routine)]), \
                mock.patch.object(siri.skills, "used", used):
            t = time.time()
            self.assertEqual(self.quick("enter focus mode")["steps"], [{"do": "volume", "to": "mute"}])
            self.assertLess(time.time() - t, 0.2)
            self.assertTrue(kept.wait(2))


class Messages(Routing):
    """A21: the message is the words after "saying" or "that"."""

    def test_saying_and_that_arent_part_of_the_message(self):
        self.quick("message Mum on WhatsApp saying I'm running late")
        self.quick("text Dad on Telegram that I'll call later")
        self.quick("Message Mum on WhatsApp: that was fun")
        self.assertEqual(self.messages, [("WhatsApp", "Mum", "I'm running late"), ("Telegram", "Dad", "I'll call later"),
                                         ("WhatsApp", "Mum", "that was fun")])

    def test_a_comma_after_saying_and_that_twice(self):
        self.quick("Message Mum on WhatsApp saying, I'm running late.")  # how speech-to-text writes it
        self.quick("Message Mum on WhatsApp, saying I'm running late.")
        self.quick("text Dad on Telegram that that was fun")
        self.quick("text Dad on Telegram, that was fun")
        self.assertEqual(self.messages, [("WhatsApp", "Mum", "I'm running late"), ("WhatsApp", "Mum", "I'm running late"),
                                         ("Telegram", "Dad", "that was fun"), ("Telegram", "Dad", "that was fun")])


class UnnamedMessages(Routing):
    """R6: without her name no chat opens before the model decides it was for her, and there are no messages later."""

    def test_no_chat_opens_or_install_is_looked_up_without_her_name(self):
        for words in ("WhatsApp Mum: running late", "install VLC"):
            with self.subTest(words=words):
                self.assertIsNone(self.quick(words, "cold"))
                asked, _, _ = self.handle(words, "cold")
                self.assertTrue(asked)
        self.assertEqual((self.messages, self.installs), ([], []))
        self.quick("WhatsApp Mum: running late", True)  # just after she answered: as with her name
        self.assertEqual(self.messages, [("WhatsApp", "Mum", "running late")])

    def test_a_message_for_later_is_refused(self):
        plan = self.quick("text Mum on WhatsApp tomorrow at 9 saying hi")
        self.assertEqual(self.messages, [])
        self.assertEqual(plan["steps"], [])
        self.assertIn("not later", plan["say"])
        self.quick("Message Mum on WhatsApp: tomorrow I'm coming home")
        self.quick("Message Mum on WhatsApp, tonight that's fine")
        self.assertEqual(self.messages, [("WhatsApp", "Mum", "tomorrow I'm coming home"),
                                         ("WhatsApp", "Mum", "tonight that's fine")])


class HeardAs(Routing):
    """A24: heard_as puts an app's name right where an app is named, and leaves everyone's words alone."""

    def test_the_app_name_is_put_right(self):
        self.assertEqual(siri.fix_names("open prone"), "open Google Chrome")
        self.assertEqual(siri.fix_names("Prone."), "Google Chrome.")
        self.assertEqual(siri.fix_names("Jeff, switch to this code"), "Jeff, switch to VS Code")
        self.assertEqual(siri.fix_names("open my files and close keto"), "open File Explorer and close Kiro")
        self.assertEqual(self.steps(siri.fix_names("Prone.")), [{"do": "open", "app": "Google Chrome"}])
        self.assertEqual(self.steps("google search"), [{"do": "google", "query": "search", "play": False}])

    def test_words_are_left_alone(self):
        for words in ("Message Mum on WhatsApp: starting keto from Monday", "Type I'm prone to typos",
                      "Play keto recipes on YouTube", "Search for this code of conduct on Google",
                      "Google cloud code pricing", "explain this code", "run this code"):
            with self.subTest(words=words):
                self.assertEqual(siri.fix_names(words), words)
        self.assertEqual(self.steps(siri.fix_names("Play keto recipes on YouTube")),
                         [{"do": "youtube", "query": "keto recipes", "play": True}])


class Folders(Routing):
    """A29: Downloads, Documents and Pictures open where Windows keeps them, which needn't be under the user folder."""

    def test_known_folders(self):
        for words, path in (("open downloads", "shell:Downloads"), ("open my downloads", "shell:Downloads"),
                            ("show my downloads", "shell:Downloads"), ("open pictures", "shell:My Pictures"),
                            ("show my pictures", "shell:My Pictures"), ("open documents", "shell:Personal")):
            with self.subTest(words=words):
                self.assertEqual(self.steps(words), [{"do": "open_folder", "path": path}])
                self.assertIn(path, winplatform.SHELL_FOLDERS)


class Asking(Routing):
    """R1: commands the real log dropped as room talk could be requests; room talk still isn't."""

    def test_commands_from_the_log(self):
        for words in ("Hey Zoe, shut down the computer", "Download and install VLC", "Okay, copy that link",
                      "Clear notification", "Clear that notification", "I take a screenshot", "J restart the laptop",
                      "Update", "am I online", "maximise the window"):
            with self.subTest(words=words):
                self.assertTrue(siri.could_be_request(words))

    def test_room_talk_still_isnt(self):
        for words in ("Are you coming for dinner?", "pass me the water", "Okay, so it is gonna rain later",
                      "Is that clear?", "Thank you very much.", "It installs everything and gets it running for you."):
            with self.subTest(words=words):
                self.assertFalse(siri.could_be_request(words))


class Power(Routing):
    """R2: shutting down and restarting the PC are planned on the PC, and always asked about first."""

    def test_planned_locally(self):
        for words, do in (("shut down the computer", "shutdown"), ("Shut down the PC.", "shutdown"),
                          ("shut the laptop down", "shutdown"), ("switch off the computer", "shutdown"),
                          ("shut down the system", "shutdown"), ("restart the computer", "restart"),
                          ("restart my laptop", "restart"), ("reboot the system", "restart")):
            with self.subTest(words=words):
                self.assertEqual(self.steps(words), [{"do": do}])

    def test_without_her_name_she_asks(self):
        asked, ran, pending = self.handle("Shut down the computer", "cold")
        self.assertFalse(asked)
        self.assertEqual(ran["say"], "Should I shut down the computer?")
        self.assertEqual(pending["steps"], [{"do": "shutdown"}])


class Numbers(Routing):
    """R3: a volume level and a number of scrolls said in words, as well as in digits."""

    def test_number_words(self):
        self.assertEqual(self.steps("set the volume to thirty"), [{"do": "volume", "to": 30}])
        self.assertEqual(self.steps("volume fifty percent"), [{"do": "volume", "to": 50}])
        self.assertEqual(self.steps("set volume to twenty five"), [{"do": "volume", "to": 25}])
        self.assertEqual(self.steps("volume 40"), [{"do": "volume", "to": 40}])
        self.assertEqual(self.steps("scroll down three times"), [{"do": "scroll", "direction": "down", "times": 3}])
        self.assertEqual(self.steps("scroll up 2 times"), [{"do": "scroll", "direction": "up", "times": 2}])


class PcQuestions(Routing):
    """R4, R7: "am I online?" is answered on the PC; a check with a schedule in it is left to the model."""

    def test_am_i_online(self):
        for words in ("am I online", "Am I connected?", "is the internet working"):
            with self.subTest(words=words):
                self.assertEqual(siri.sys_intent(siri.plain(words)), ("network", None))
                self.assertEqual(self.quick(words)["say"], "lookup network")

    def test_a_scheduled_check_isnt_answered_now(self):
        for words in ("check my C drive space every Monday at 9 AM", "tell me the battery every morning",
                      "tell me the battery at 10", "how much space is left on the C drive at 11:30"):
            with self.subTest(words=words):
                self.assertIsNone(siri.sys_intent(siri.plain(words)))
                self.assertIsNone(self.quick(words))
        self.assertEqual(siri.sys_intent("check the storage of c drive"), ("disk", "c"))
        for words in ("is my battery at 5%", "is my battery at 50 percent"):  # a level, not a time
            with self.subTest(words=words):
                self.assertEqual(siri.sys_intent(siri.plain(words)), ("battery", None))


if __name__ == "__main__":
    unittest.main()


class HeardNames(unittest.TestCase):
    def test_jet_and_jeth_are_her_name_after_hey(self):
        """README Troubleshooting's own miss, "Hey Jet, open Spotify", and Parakeet's "Hey Jeth" in checks/listen.py."""
        self.assertEqual(siri.find_name("Hey Jet open Spotify"), (True, "open Spotify"))
        self.assertEqual(siri.find_name("Hey Jeth, check the space of the C drive")[0], True)

    def test_a_jet_in_a_sentence_isnt_her(self):
        for t in ("Jet lag is terrible", "I took a jet to Delhi", "The jet engine is loud"):
            self.assertIsNone(siri.find_name(t), t)
