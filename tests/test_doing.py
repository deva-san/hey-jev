"""25 October: Hari said she cut his sentences off, didn't do what he said and couldn't use his laptop. What changed,
from his log and from OpenLive (github.com/katipally/openlive): her name as it was misheard, a greeting with a request
after it, plans Haiku made that were let go as not asked for, Windows' own tools and Settings pages, light mode that
was Night light, what apps are installed, and her prompt read back from Haiku's cache."""
import contextlib
import io
import json
import unittest
from unittest import mock

from tests.support import WIN_ORIGINAL, siri, winplatform
from tests.test_routing import Routing

import opencode
import speech


class Names(unittest.TestCase):
    def test_her_name_as_it_was_misheard(self):
        for said in ("Hey Zoe, shut down the computer", "Hey Jevon, open Notepad", "Jevan, what time is it?"):
            with self.subTest(said=said):
                self.assertTrue(siri.find_name(said))

    def test_not_job_or_a_name_said_about_someone(self):
        for said in ("Okay, job done", "Zoe said she'd come", "Jevon's coming tomorrow"):
            with self.subTest(said=said):
                self.assertFalse(siri.find_name(said))


class Greeting(unittest.TestCase):
    """"Hey, can you fill all the details here" and "Hey, they mind me at five PM" were let go as room talk, her name
    lost, before the model saw them. With Answer without her name on, a greeting and two words or more go to it cold,
    and it decides who they were said to (COLD_NOTE)."""

    def setUp(self):
        calls = mock.patch.object(siri.win, "call_apps", lambda *args, **kw: ())  # no call going on
        calls.start()
        self.addCleanup(calls.stop)

    def route(self, words, open_mic=True):
        return siri.route(speech.heard(words, 0.9), "other", open_mic=open_mic)

    def test_a_greeting_and_more_goes_to_the_model_said_cold(self):
        for words in ("Hey, they mind me at five PM", "Hello, the blue one please", "Hey, the details here"):
            with self.subTest(words=words):
                self.assertEqual(self.route(words)[2], "cold")
                self.assertIsNone(self.route(words, open_mic=False))

    def test_not_a_bare_greeting_a_name_or_an_okay(self):
        for words in ("Hey Ravi", "Hello?", "Okay so much", "Okay, but India is"):
            with self.subTest(words=words):
                self.assertIsNone(self.route(words))


class AboutHer(unittest.TestCase):
    """"Hey, can you see me?" and "Hello, can you see me?", 25 October: Haiku took both for a video call's words and
    she said nothing, and "can you hear me" without the hey never reached it."""

    def setUp(self):
        self.calls = []  # no call going on
        calls = mock.patch.object(siri.win, "call_apps", lambda *args, **kw: self.calls)
        calls.start()
        self.addCleanup(calls.stop)

    def route(self, words):
        return siri.route(speech.heard(words, 0.9), "other", open_mic=True)

    def test_it_reaches_the_model_and_the_decider_keeps_it(self):
        for words in ("Can you see me?", "can you hear me", "Are you there?", "Hey, can you see me",
                      "Hey why you are not replying", "why don't you answer me"):
            with self.subTest(words=words):
                self.assertEqual(self.route(words)[2], "cold")
                self.assertTrue(siri.asks_something(words, "cold"))
        for words in ("pass the salt please", "did you see me on TV"):
            with self.subTest(words=words):
                self.assertIsNone(self.route(words))

    def told(self, words, gate):
        """What the model was sent with words, said with gate."""
        seen, plan = [], {"to": "you", "steps": [], "say": "I can't see you."}

        def ask_plan(messages, **kw):
            seen.append(messages)
            return json.dumps(plan), dict(plan), {}, "test"
        with mock.patch.object(siri, "ask_plan", ask_plan), mock.patch.object(siri, "STREAM_SAY", False), \
                mock.patch.object(siri, "context", return_value="Now: Sunday."), \
                contextlib.redirect_stdout(io.StringIO()):
            siri.think(words, gate)
        return seen[0][-1]["content"]

    def test_she_is_told_its_to_her_and_that_she_cant_see_them(self):
        said = self.told("Hey, can you see me", "cold")
        self.assertIn("no call is going on at this PC, so it's to you", said)
        self.assertIn("you can't see them", said)
        self.assertIn("so it's to you", self.told("Hey why you are not replying", "cold"))
        self.assertNotIn("can't see them", self.told("Can you hear me?", "cold"))
        named = self.told("Jev, can you see me?", False)  # to her anyway: only what's true of her
        self.assertIn("you can't see them", named)
        self.assertNotIn("no call", named)

    def test_on_a_call_its_left_to_the_model(self):
        self.calls = [("zoom.exe", "Zoom")]
        self.assertNotIn("asks about you", self.told("Hey, can you see me", "cold"))


class TrustingHaiku(unittest.TestCase):
    """All 13 plans let go as "not asked for" from 21 to 25 October, after Haiku had planned them as said to her, were
    Hari's own: "Open settings and Windows update", "Can you summarize that", "Open the apply link"."""

    def setUp(self):
        siri.LAST_SCREEN[0] = 0.0  # she hasn't looked lately

    def test_a_task_on_the_screen_haiku_planned_goes_ahead(self):
        screen = {"do": "screen", "task": "open Windows Update in Settings"}
        for step in (screen, {"do": "procedure", "name": "windows-update"}):
            with self.subTest(step=step["do"]):
                self.assertIs(siri.unasked([step], "and windows update", "cold"), step)  # a quick plan: as before
                self.assertIsNone(siri.unasked([step], "and windows update", "cold", planned=True))

    def test_closing_needs_words_about_it_and_typing_its_own_words(self):
        close = {"do": "close", "app": "Google Chrome"}
        self.assertIs(siri.unasked([close], "the other one, close that", "cold"), close)
        self.assertIsNone(siri.unasked([close], "the other one, close that", "cold", planned=True))
        self.assertIs(siri.unasked([close], "No, it is already opened", "cold", planned=True), close)
        typing = {"do": "type", "text": "meeting at five"}
        self.assertIs(siri.unasked([typing], "I told him the meeting is at five", "cold", planned=True), typing)
        lock = {"do": "lock"}
        self.assertIs(siri.unasked([lock], "I'm going to bed now", "cold", planned=True), lock)


class WindowsPages(unittest.TestCase):
    """"Open device manager" searched Google on 25 October, Device Manager not being in the Start menu, and a task in
    Settings went to https://display for ms-settings:display."""

    def test_by_what_people_call_them(self):
        for name, target in (("Device Manager", "devmgmt.msc"), ("the Windows Update page", "ms-settings:windowsupdate"),
                             ("Wi-Fi settings", "ms-settings:network-wifi"), ("camera settings", "ms-settings:privacy-webcam"),
                             ("Control Panel", "control.exe"), ("open bluetooth", "ms-settings:bluetooth"),
                             ("installed apps", "ms-settings:appsfeatures")):
            with self.subTest(name=name):
                self.assertEqual(winplatform.windows_page(name), target)
        for name in ("Notepad", "Run", "Registry Editor", "cmd", "Task Scheduler", "Services", ""):
            with self.subTest(name=name):
                self.assertIsNone(winplatform.windows_page(name))

    def test_only_those_and_settings_pages_are_opened(self):
        real, opened = WIN_ORIGINAL["open_windows_page"], []
        with mock.patch.object(winplatform.os, "startfile", opened.append):
            for target in ("ms-settings:display", "devmgmt.msc", "ms-settings:privacy-webcam"):
                real(target)
            for target in ("cmd.exe", "regedit.exe", "ms-settings:display & calc", "https://evil.example", ""):
                with self.subTest(target=target), self.assertRaises(RuntimeError):
                    real(target)
        self.assertEqual(opened, ["ms-settings:display", "devmgmt.msc", "ms-settings:privacy-webcam"])

    def test_open_and_website_steps_go_there(self):
        opened, pages = [], []
        with mock.patch.object(siri.win, "open_windows_page", opened.append), \
                mock.patch.object(siri, "open_page", lambda url, *a, **k: pages.append(url)), \
                contextlib.redirect_stdout(io.StringIO()):
            siri.do_step({"do": "open", "app": "Device Manager"})
            siri.do_step({"do": "website", "url": "ms-settings:display"})
            siri.do_step({"do": "website", "url": "https://example.com"})
        self.assertEqual(opened, ["devmgmt.msc", "ms-settings:display"])
        self.assertEqual(pages, ["https://example.com"])

    def test_the_planner_knows_them(self):
        self.assertIn("Device Manager", siri.PROMPT)
        self.assertTrue(siri.could_be_request("windows update"))
        self.assertTrue(siri.could_be_request("device manager"))


class WindowSteps(unittest.TestCase):
    """27 October, found while mapping: a window step with an action do_step doesn't have did nothing and was counted
    as done, so her line said it was."""

    def test_one_it_cant_do_is_said_not_done(self):
        for step, why in (({"do": "window", "action": "snap_left"}, "I can't snap left a window"),
                          ({"do": "window"}, "I didn't catch what to do with the window")):
            with self.subTest(step=step), self.assertRaisesRegex(RuntimeError, why):
                siri.do_step(step)
        done = []
        with mock.patch.object(siri.win, "maximize_foreground_window", lambda: done.append("max")), \
                mock.patch.object(siri.win, "minimize_foreground_window", lambda: done.append("min")):
            for action in ("maximize", "maximise", "minimise"):
                siri.do_step({"do": "window", "action": action})
        self.assertEqual(done, ["max", "max", "min"])


class Switching(unittest.TestCase):
    """25 October, from OpenLive: a window that's already open is switched to, opening nothing. Every plan she read
    left the step out ("no such steps, left out: switch"), the model's replies in an app included."""

    def test_a_switch_step_is_kept_and_brings_that_window_up(self):
        fronted = []
        windows = {"excel": {"hwnd": 7, "exe": "excel.exe", "title": "Q3 report - Excel", "name": "Excel"}}

        def named_window(name, kind):
            if name.lower() not in windows:
                raise siri.NotAWindow(f"I couldn't find an open window called {name}.")
            return windows[name.lower()]
        with mock.patch.object(siri, "named_window", named_window), \
                mock.patch.object(siri.win, "bring_to_front", fronted.append), \
                contextlib.redirect_stdout(io.StringIO()):
            plan = siri.parse_plan('{"steps": [{"do": "switch", "to": "Excel"}], "say": "Switching."}')
            self.assertEqual(plan["steps"], [{"do": "switch", "to": "Excel"}])
            self.assertEqual(siri.do_step(plan["steps"][0]), "Excel")
            with self.assertRaisesRegex(RuntimeError, "couldn't find an open window called Word"):
                siri.do_step({"do": "switch", "to": "Word"})
        self.assertEqual(fronted, [7])


class CheckedInApps(unittest.TestCase):
    """26 October: "open recorder and record my voice" was planned as Recorder and Ctrl+R, pressed blind, and she
    said she'd started recording when nothing had. Keys a model chose in an app are a task on the screen now, which
    sees the window and checks it's done before she says so."""

    def setUp(self):
        self.front = ("soundrec.exe", "Sound Recorder")
        front = mock.patch.object(siri.win, "foreground", lambda: (1, *self.front))
        front.start()
        self.addCleanup(front.stop)

    def check(self, steps, words, say=""):
        with contextlib.redirect_stdout(io.StringIO()):
            return siri.checked_in_app({"steps": steps, "say": say}, words)["steps"]

    def test_keys_in_an_app_are_done_and_checked_on_the_screen(self):
        steps = self.check([{"do": "open", "app": "Sound Recorder"}, {"do": "keys", "keys": "ctrl+r"}],
                           "But open recorder and record my voice.", "I've started recording your voice.")
        self.assertEqual(steps[0], {"do": "open", "app": "Sound Recorder"})
        self.assertEqual((steps[1]["do"], steps[1]["task"]), ("screen", "open recorder and record my voice"))
        self.assertIn("press Control R", steps[1]["hint"])
        self.assertEqual(len(steps), 2)
        alone = self.check([{"do": "keys", "keys": "ctrl+r"}], "Recorder is not started. Please start it")
        self.assertEqual(alone[0]["task"], "recorder is not started. Please start it")  # the app in front

    def test_keys_you_said_in_a_browser_or_with_vision_off_are_pressed_as_planned(self):
        keys = [{"do": "keys", "keys": "ctrl+s"}]
        self.assertEqual(self.check(keys, "press control s"), keys)
        self.assertEqual(self.check([{"do": "open", "app": "Chrome"}, *keys], "open chrome and save it")[1], keys[0])
        self.assertEqual(self.check([{"do": "website", "url": "https://x.com"}, *keys], "save the page")[1], keys[0])
        self.front = ("chrome.exe", "YouTube")
        self.assertEqual(self.check(keys, "save it"), keys)
        self.front = ("soundrec.exe", "Sound Recorder")
        with mock.patch.dict(siri.settings._load(), {"vision": False}):
            self.assertEqual(self.check(keys, "save it"), keys)
        with mock.patch.object(siri.win, "foreground", side_effect=RuntimeError("can't tell")):
            self.assertEqual(self.check(keys, "save it"), keys)


class Installed(unittest.TestCase):
    def test_what_apps_she_has_comes_from_the_start_menu(self):
        apps = [("Zoom Workplace", "z"), ("Excel", "e"), ("Zoom Workplace", "z2"), ("calculator", "c")]
        with mock.patch.object(siri.win, "start_apps", lambda refresh=False: apps), \
                contextlib.redirect_stdout(io.StringIO()):
            out = json.loads(siri.run_info([{"do": "lookup", "what": "installed apps"}]))
        self.assertEqual(out, [{"lookup": "installed apps",
                                "result": {"count": 3, "apps": ["calculator", "Excel", "Zoom Workplace"]}}])
        self.assertIn("installed", siri.PROMPT)


class LightMode(unittest.TestCase):
    """25 October: "light mode", said four times, changed nothing you could see. Windows was in light mode already,
    and what looked dark was Night light's warm screen, on since "turn on light night"."""

    def mended(self, steps, say="", light=True, warm=True):
        with mock.patch.object(siri.win, "light_mode", lambda: light), \
                mock.patch.object(siri.win, "night_light", lambda: warm), contextlib.redirect_stdout(io.StringIO()):
            return siri.mend_modes({"steps": steps, "say": say})

    def test_light_mode_when_its_light_already_turns_night_light_off(self):
        plan = self.mended([{"do": "dark_mode", "on": False}], "Light mode's on.")
        self.assertEqual(plan["steps"], [{"do": "night_light", "on": False}])
        self.assertEqual(plan["say"], "Night light's off, so the screen's back to normal.")

    def test_with_night_light_off_too_she_says_its_light_already(self):
        plan = self.mended([{"do": "dark_mode", "on": False}], "Light mode's on.", warm=False)
        self.assertEqual(plan["steps"], [{"do": "dark_mode", "on": False}])
        self.assertTrue(plan["say"].startswith("It's already in light mode."), plan["say"])

    def test_in_dark_mode_light_mode_is_light_mode(self):
        for warm in (True, False, None):
            plan = self.mended([{"do": "dark_mode", "on": False}], "Light mode's on.", light=False, warm=warm)
            self.assertEqual(plan, {"steps": [{"do": "dark_mode", "on": False}], "say": "Light mode's on."})

    def test_unread_it_does_as_asked(self):
        def unreadable():
            raise OSError("no key")
        with mock.patch.object(siri.win, "light_mode", unreadable), contextlib.redirect_stdout(io.StringIO()):
            plan = siri.mend_modes({"steps": [{"do": "dark_mode", "on": False}], "say": "Light mode's on."})
        self.assertEqual(plan["steps"], [{"do": "dark_mode", "on": False}])

    def test_a_step_with_no_line_gets_one_and_other_plans_are_left_alone(self):
        self.assertIn(self.mended([{"do": "night_light", "on": True}])["say"], siri.REPLIES["night_on"])
        self.assertIn(self.mended([{"do": "dark_mode", "on": True}])["say"], siri.REPLIES["dark_on"])
        mixed = {"steps": [{"do": "dark_mode", "on": False}, {"do": "open", "app": "Notepad"}], "say": ""}
        self.assertEqual(siri.mend_modes(mixed), mixed)
        self.assertEqual(siri.mend_modes({"steps": [], "say": "Hi."}), {"steps": [], "say": "Hi."})


class SaidCold(Routing):
    def test_night_light_and_dark_mode_said_cold_go_straight(self):
        """Sent to the model said cold they came back as not for her ("Nightlight") or with no line ("Light mode")."""
        for words, step in (("Nightlight", {"do": "night_light", "on": True}),
                            ("turn on night light", {"do": "night_light", "on": True}),
                            ("dark mode", {"do": "dark_mode", "on": True}),
                            ("light mode", {"do": "dark_mode", "on": False})):
            with self.subTest(words=words), mock.patch.object(siri.win, "light_mode", lambda: False):
                asked, ran, _ = self.handle(words, "cold")
                self.assertFalse(asked)
                self.assertEqual(ran["steps"], [step])
                self.assertTrue(ran["say"])

    def test_light_mode_said_cold_with_windows_light_turns_night_light_off(self):
        with mock.patch.object(siri.win, "light_mode", lambda: True), \
                mock.patch.object(siri.win, "night_light", lambda: True):
            asked, ran, _ = self.handle("Back to light mode", "cold")
        self.assertEqual((asked, ran["steps"]), (False, [{"do": "night_light", "on": False}]))


class Caching(unittest.TestCase):
    """Her prompt, the same turn after turn, is read back from Haiku's cache: a tenth of the price and sooner."""

    class Reply:
        status_code, ok, reason, text = 200, True, "OK", ""

        def json(self):
            return {"content": [{"type": "text", "text": '{"steps": [], "say": "Hi."}'}],
                    "usage": {"input_tokens": 40, "output_tokens": 9, "cache_read_input_tokens": 2400,
                              "cache_creation_input_tokens": 0}}

        def close(self):
            pass

    def test_the_fixed_start_is_marked_for_the_cache(self):
        system = opencode.Cached("SOUL\n\nPROMPT" + "Now: Sunday.", len("SOUL\n\nPROMPT"))
        joined, _ = opencode._anthropic_messages([{"role": "system", "content": system},
                                                  {"role": "user", "content": "hi"}])
        self.assertEqual(opencode._system(joined), [
            {"type": "text", "text": "SOUL\n\nPROMPT", "cache_control": {"type": "ephemeral"}},
            {"type": "text", "text": "Now: Sunday."}])
        self.assertEqual(opencode._system(opencode.Cached("all of it")),
                         [{"type": "text", "text": "all of it", "cache_control": {"type": "ephemeral"}}])
        self.assertEqual(opencode._system("plain"), "plain")
        self.assertIsInstance(system, str)

    def test_a_later_system_note_keeps_the_mark_where_it_was(self):
        joined, _ = opencode._anthropic_messages([{"role": "system", "content": opencode.Cached("FIXEDrest", 5)},
                                                  {"role": "system", "content": "note"},
                                                  {"role": "user", "content": "hi"}])
        self.assertEqual((str(joined), joined.cache_at), ("FIXEDrest\n\nnote", 5))
        plain, _ = opencode._anthropic_messages([{"role": "system", "content": "a"}, {"role": "user", "content": "b"}])
        self.assertFalse(getattr(plain, "cache_at", 0))

    def test_whats_read_from_the_cache_is_counted(self):
        bodies = []

        def post(url, json=None, **kw):
            bodies.append(json)
            return self.Reply()
        with mock.patch.object(opencode.SESSION, "post", post), \
                mock.patch("secrets_store.get_secret", return_value="key"):
            _, usage, _ = opencode._anthropic([{"role": "system", "content": opencode.Cached("x" * 40, 30)},
                                               {"role": "user", "content": "hi"}], 400, 10, opencode.HAIKU)
        self.assertEqual(bodies[0]["system"][0], {"type": "text", "text": "x" * 30,
                                                   "cache_control": {"type": "ephemeral"}})
        self.assertEqual((usage["prompt_tokens"], usage["completion_tokens"], usage["cache_read"]), (40, 9, 2400))

    def test_her_prompt_is_cached_up_to_what_changes_each_turn(self):
        seen, plan = [], {"steps": [], "say": "Hi."}

        def ask_plan(messages, **kw):
            seen.append(messages)
            return json.dumps(plan), dict(plan), {"cache_read": 2400}, "test"
        with mock.patch.object(siri, "ask_plan", ask_plan), \
                mock.patch.object(siri, "context", return_value="Now: Sunday."), \
                contextlib.redirect_stdout(io.StringIO()) as out:
            siri.think("hello there", False)
        system = seen[0][0]["content"]
        self.assertEqual(system[:system.cache_at], siri.soul() + "\n\n" + siri.PROMPT)
        self.assertIn("Now: Sunday.", system[system.cache_at:])
        self.assertIn("2400 cached", out.getvalue())


if __name__ == "__main__":
    unittest.main()
