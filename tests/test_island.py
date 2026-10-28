"""Her island (island.py): what dictation strikes out, her eyes, the plugins' rules, which scene shows, the drawing
shortcuts that must give the same picture as the long way round, and what she's working on: the Tasks plugin, read
from memory only, its card with Stop and Deny, and the guards on a careful button."""
import contextlib
import io
import os
import shutil
import tempfile
import threading
import sys
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from tests.support import needs_windows, siri  # temp APPDATA and the tripwires, before anything else
from tests.test_watchers import until

import activity
import agent
import askbox
import dictation
import island
import island_face as face
import island_plugins as plugins
import settings
import tasks


class Dictation(unittest.TestCase):
    """What you said, tidied the way Nixi shows it: the fillers and the words you put right are left out."""
    CASES = (
        ("Anyone up for a game tonight? Um, I'm free after seven, actually eight.",
         "Anyone up for a game tonight? I'm free after eight."),
        ("Meet me at 5, no, 6 pm.", "Meet me at 6 pm."),
        ("Tell John, actually tell Mary.", "Tell Mary."),
        ("I want the blue one, no wait, the red one.", "I want the red one."),
        ("Let's meet on Monday, actually, make it Tuesday.", "Let's meet on Tuesday."),
        ("Send it to Ravi, sorry, I mean Priya.", "Send it to Priya."),
        ("I'm at home, no, at the office.", "I'm at the office."),
        ("Buy apples, actually oranges.", "Buy oranges."),
        ("I I think we should go.", "I think we should go."),
        ("um so we went to the the market", "So we went to the market"),
        ("I'm free, um.", "I'm free."),
        ("The meeting is at seven actually eight", "The meeting is at eight"),
        ("Call Ravi actually Priya tomorrow", "Call Priya tomorrow"),
        ("Hello there. This is wrong. Scratch that. This is right.", "Hello there. This is right."),
        ("We need twenty-five, no, thirty chairs.", "We need thirty chairs."),
        ("Order the iPhone. uh, and the case.", "Order the iPhone. And the case."),
        ("Invite Ravi Kumar, sorry, Priya Shah to the call.", "Invite Priya Shah to the call."),
        ("Book it for 3 pm, actually 4 pm.", "Book it for 4 pm."),
    )
    KEPT = (  # what only looks like a correction stays as it was said
        "I actually like it.", "It's fine, actually.", "No, I don't think so.", "I said no to him.",
        "Wait, what time is it?",
    )

    def test_fillers_and_corrections_are_left_out(self):
        for said, want in self.CASES:
            self.assertEqual(dictation.clean(said), want, said)

    def test_what_isnt_a_correction_stays(self):
        for said in self.KEPT:
            self.assertEqual(dictation.clean(said), said)

    def test_the_struck_words_are_shown_in_place(self):
        said = "Anyone up for a game tonight? Um, I'm free after seven, actually eight."
        segs = dictation.segments(said)
        self.assertEqual(" ".join(w for w, _ in segs), said)  # every word, in order, for the bar
        self.assertEqual([w for w, kept in segs if not kept], ["Um,", "seven,", "actually"])


class Apps(unittest.TestCase):
    """Which apps' notifications pop up, and what they're called there."""

    def setUp(self):
        settings.put("island_apps", {})

    def test_the_apps_people_message_you_in_are_on_until_picked(self):
        self.assertTrue(plugins.app_on("WhatsApp", True))
        self.assertFalse(plugins.app_on("Cursor", False))
        settings.put("island_apps", {"WhatsApp": False, "Cursor": True})
        self.assertFalse(plugins.app_on("WhatsApp", True))
        self.assertTrue(plugins.app_on("Cursor", False))

    def test_names_from_windows_app_ids(self):
        start = [("Feedback Hub", "Microsoft.WindowsFeedbackHub_8wekyb3d8bbwe!App")]
        with mock.patch.object(plugins.win, "loaded_start_apps", return_value=start):
            for app_id, name in (
                    ("Microsoft.WindowsFeedbackHub_8wekyb3d8bbwe!app", "Feedback Hub"),  # the Start menu's, any case
                    ("5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App", "WhatsApp"),
                    ("Microsoft.VisualStudioCode", "Visual Studio Code"), ("ByteDance.TraeSolo", "Trae Solo"),
                    ("electron.app.ZCode", "ZCode"), ("ai.opencode.desktop", "Opencode"),
                    ("Microsoft.MicrosoftEdge.Stable_8wekyb3d8bbwe!https://unstop.com/", "Unstop"),
                    ("Microsoft.YourPhone_8wekyb3d8bbwe!YourPhoneNotifications_com.ubercab", "Uber"),
                    ("Microsoft.YourPhone_8wekyb3d8bbwe!YourPhoneNotifications_com.gapseat.app", "Gapseat"),
                    ("Microsoft.YourPhone_8wekyb3d8bbwe!YourPhoneCalling", "Phone calls"),
                    # Windows' own notices, a code and a browser extension have no name to show
                    ("Windows.SystemToast.LowDisk", ""), ("Chrome.EIU4AE6L7WCI5APAXN3P24FYCY", ""),
                    ("Microsoft.MicrosoftEdge.Stable_8wekyb3d8bbwe!chrome-extension://hgeljhfekpckiiplhkig/", "")):
                self.assertEqual(plugins.app_label(app_id), name, app_id)


class Battery(unittest.TestCase):
    """When the battery shows: plugging in and out, full, and low at 20 and 10 percent, once each."""

    def shown(self, readings):
        host = mock.Mock()
        battery = plugins.Battery(host)
        with mock.patch.object(plugins, "win_battery", side_effect=list(readings)):
            battery.start()
            for _ in readings[1:]:
                battery.poll(time.time())
        return [(c.args[0][1].data["event"], c.args[0][1].data["percent"]) for c in host.post.call_args_list
                if c.args[0][0] == "show"]

    def test_plugging_in_and_out(self):
        self.assertEqual(self.shown([(50, False), (50, True), (51, True), (51, False)]),
                         [("plugged", 50), ("unplugged", 51)])

    def test_low_once_at_20_and_once_at_10(self):
        self.assertEqual(self.shown([(25, False), (20, False), (19, False), (10, False), (9, False)]),
                         [("low", 20), ("low", 10)])

    def test_full(self):
        self.assertEqual(self.shown([(98, True), (99, True), (100, True), (100, True)]), [("full", 100)])


class Eyes(unittest.TestCase):
    def test_awake_from_the_start(self):
        eyes = face.Eyes()  # her five quiet minutes count from now, not from 1970
        self.assertEqual(eyes.update(time.time(), 0.016, "open")[0], "open")

    def test_sleepy_after_five_quiet_minutes(self):
        now = time.time()
        eyes = face.Eyes(now)
        self.assertEqual(eyes.update(now + 301, 0.016, "open")[0], "sleepy")
        eyes.wake(now + 302)
        self.assertEqual(eyes.update(now + 302, 0.016, "open")[0], "open")

    def test_a_reaction_lasts_a_moment(self):
        now = time.time()
        eyes = face.Eyes(now)
        eyes.react("love", now)
        self.assertEqual(eyes.update(now + 0.5, 0.016, "open")[0], "love")
        self.assertEqual(eyes.update(now + face.REACT_FOR["love"] + 0.1, 0.016, "open")[0], "open")
        eyes.react("no such mood", now)
        self.assertIsNone(eyes.mood)

    def test_a_blink_closes_them_for_a_moment(self):
        now = time.time()
        eyes = face.Eyes(now)
        opens = [eyes.update(now + 2.0 + i * 0.016, 0.016, "open")[1] for i in range(14)]
        self.assertLess(min(opens), 0.3)
        self.assertEqual(opens[-1], 1.0)

    def test_a_shape_is_the_same_either_way_round(self):
        pts = [(0.0, 0.0), (10.0, 0.0), (5.0, 8.0)]
        xs, ys = np.array([5.0, 20.0]), np.array([[3.0]])
        a, b = face.polygon(xs, ys, pts), face.polygon(xs, ys, pts[::-1])
        self.assertTrue(np.allclose(a, b))
        self.assertLess(a[0, 0], 0)  # inside
        self.assertGreater(a[0, 1], 0)  # outside


def bare(**kw):
    """An island with no window: enough for its rules."""
    isl = object.__new__(island.DynamicIsland)
    isl.jev, isl.enabled, isl.busy, isl.hide_full = None, True, False, True
    isl.popups, isl.popup, isl.hover, isl.auto_hide = [], None, False, 5.0
    isl.lives, isl.always, isl.face_style = {}, True, "eyes"
    isl.k, isl.cw, isl.ch, isl.border, isl.theme_name, isl.light, isl.shapes = 1.5, 1200, 300, False, "amoled", False, {}
    isl.eyes = face.Eyes()
    isl.pinned, isl.rest_pos, isl.rest_at = None, None, 0.0
    # the black pill: what these tests were written for, drawn as it always was. The capsule's own are below (Capsule)
    isl.style, isl.face_at, isl.patch_at, isl.level = "pill", None, (0, 0), 0.0
    isl.look_at, isl.pointer, isl.pointer_at = None, None, 0.0
    for name, value in kw.items():
        setattr(isl, name, value)
    return isl


FONTS = (("f_compact", 13.5, 600), ("f_label", 12, 600), ("f_main", 15, 500), ("f_title", 14.5, 700),
         ("f_small", 11.5, 600))


def fonted(test, **kw):
    """bare(), with the island's words (bubble.Text, which Windows' GDI draws) and its window as tall as _build has
    it, enough for a layout to be made and drawn."""
    isl = bare(**kw)
    for name, px, weight in FONTS:
        setattr(isl, name, island.Text(round(px * isl.k), weight))
        test.addCleanup(getattr(isl, name).close)
    isl.corner, isl.t0, isl.texts, isl.eye = 22, time.time(), {}, ("open", 1.0, 0.0, 0.0, False)
    isl.island_max_h = max(140 * isl.k, isl._tallest_card())
    return isl


def tasks_card(rows, more=0, short=None, badge=0):
    return plugins.Activity("tasks", "card", {"rows": rows, "more": more, "short": short, "badge": badge}, live=True)


def drawn(lay):
    """lay drawn on a black patch its size: the patch, which must have something on it."""
    col = np.zeros((int(lay.h) + 4, int(lay.w) + 4, 3), np.float32)
    lay.draw(face.Canvas(col), 2, 2, lay.w, lay.h, 1.0, time.time())
    return col


class Scenes(unittest.TestCase):
    """What the island shows: her turn, then a popup, then what lasts (a timer before music), then her eyes."""

    def note(self):
        return plugins.Activity("notifications", "notification", {"app": "WhatsApp", "app_id": "", "title": "Mum",
                                                                  "text": "Home by eight", "phone": False})

    def test_her_turn_comes_first(self):
        isl = bare(jev={"state": "listening", "text": ""}, popups=[self.note()], busy=True)
        self.assertEqual(isl._scene(time.time()), ("jev",))

    def test_a_popup_then_what_lasts_then_her_eyes(self):
        now = time.time()
        timer = plugins.Activity("timers", "timer", {"label": "Tea", "end": now + 60, "total": 60.0}, live=True)
        music = plugins.Activity("media", "media", {"title": "Song", "playing": True}, live=True)
        isl = bare(popups=[self.note()], lives={"media": music, "timers": timer})
        self.assertEqual(isl._scene(now)[0], "popup")
        self.assertIs(isl._scene(now + 6)[1], timer)  # its 5 seconds are up
        isl.lives.pop("timers")
        self.assertIs(isl._scene(now + 6)[1], music)
        isl.lives.clear()
        self.assertEqual(isl._scene(now + 6), ("idle",))

    def test_pointing_at_a_popup_keeps_it(self):
        now = time.time()
        isl = bare(popups=[self.note()])
        isl._scene(now)
        isl.hover = True
        self.assertEqual(isl._scene(now + 30)[0], "popup")

    def test_nothing_over_full_screen_or_with_the_popup_off(self):
        self.assertIsNone(bare(busy=True, popups=[self.note()])._scene(time.time()))
        self.assertIsNone(bare(enabled=False)._scene(time.time()))
        self.assertIsNone(bare(always=False)._scene(time.time()))
        self.assertIsNone(bare(face_style="wave")._scene(time.time()))  # the wave has no face to keep up

    def test_a_popup_that_waited_too_long_isnt_news(self):
        old = self.note()
        old.at -= 200
        self.assertEqual(bare(popups=[old])._scene(time.time()), ("idle",))

    def test_what_shes_working_on_comes_before_a_timer_and_music(self):
        """27 October: what stays was picked from a fixed list, a timer, then music, then the battery, and any other
        plugin's never showed. Now each plugin says how much it matters (Plugin.priority), and her work comes first:
        it may be waiting on you."""
        now = time.time()
        timer = plugins.Activity("timers", "timer", {"label": "Tea", "end": now + 60, "total": 60.0}, live=True)
        music = plugins.Activity("media", "media", {"title": "Song", "playing": True}, live=True)
        work = tasks_card([{"title": "Install VLC", "state": "running"}])
        isl = bare(popups=[self.note()], lives={"media": music, "timers": timer, "tasks": work})
        self.assertEqual(isl._scene(now)[0], "popup")  # a notification still has its 5 seconds over it
        self.assertIs(isl._scene(now + 6)[1], work)
        isl.lives.pop("tasks")
        self.assertIs(isl._scene(now + 6)[1], timer)
        self.assertGreater(plugins.priority("tasks"), plugins.priority("timers"))
        self.assertGreater(plugins.priority("timers"), plugins.priority("media"))

    def test_a_plugin_the_island_doesnt_know_still_shows(self):
        weather = plugins.Activity("weather", "card", {"title": "Rain at 4"}, live=True)
        self.assertIs(bare(lives={"weather": weather})._scene(time.time())[1], weather)


@needs_windows
class Cards(unittest.TestCase):
    """A card (island_plugins.Activity): the Tasks plugin's list or any plugin's, small until you point at it, then
    open with its rows, their bars and their buttons, and kept open by a click."""

    def test_her_list_shows_three_rows_and_how_many_more(self):
        rows = [{"title": f"Job {i}", "state": "running", "progress": 0.5, "lines": ["Searching"], "status": "4/6",
                 "buttons": [{"name": "stop", "label": "Stop", "data": {"key": f"task:{i}", "needs": ""}}]}
                for i in range(5)]
        isl = fonted(self, hover=True)
        lay = isl._make(("live", tasks_card(rows)), time.time())
        self.assertEqual((lay.kind, lay.key[0]), ("card", "card"))
        self.assertEqual([h[0] for h in lay.hot], ["b0", "b1", "b2", "pin"])
        self.assertEqual(lay.press["b2"], ("tasks", "stop", {"key": "task:2", "needs": ""}, False))
        self.assertGreater(drawn(lay).max(), 0.5)  # words, bars and buttons on it
        self.assertEqual((lay.rate, lay.animated), (1, False))  # a long job moves once a second, never every frame

    def test_the_tallest_card_fits_the_window(self):
        row = {"title": "x" * 90, "lines": ["one", "two", "three"], "progress": 0.3, "state": "waiting_yes",
               "buttons": [{"name": "deny", "label": "Deny"}, {"name": "approve", "label": "Approve"}]}
        isl = fonted(self, hover=True)
        lay = isl._card(tasks_card([row] * 3, more=4))
        self.assertLessEqual(lay.h, isl._tallest_card())
        self.assertEqual([lay.press[f"b{i}"][3] for i in range(6)], [False, True] * 3)  # only Approve is careful
        drawn(lay)

    def test_any_plugin_can_show_a_card_without_the_island_knowing_it(self):
        act = plugins.Activity("weather", "card", {"title": "Rain at 4", "lines": ["Take an umbrella"],
                                                   "buttons": [{"name": "open", "label": "Open"}]}, live=True)
        isl = fonted(self)
        small = isl._make(("live", act), time.time())
        self.assertEqual((small.kind, small.key[0]), ("card", "card-row"))
        drawn(small)
        isl.hover = True
        big = isl._make(("live", act), time.time())
        self.assertEqual(big.press["b0"], ("weather", "open", None, False))
        drawn(big)

    def test_a_click_keeps_it_open_and_another_lets_it_go(self):
        isl = fonted(self, hover=True, runner=mock.Mock())
        isl._wake = lambda: None
        act = tasks_card([{"title": "Install VLC", "state": "running", "since": time.time() - 75}])
        lay = isl._make(("live", act), time.time())
        isl._press(lay.press["pin"], False)
        self.assertEqual(isl.pinned, "tasks")
        isl.hover = False
        self.assertEqual(isl._make(("live", act), time.time()).key[0], "card")  # the pointer's gone: still open
        isl._press(lay.press["pin"], False)
        self.assertIsNone(isl.pinned)
        small = isl._make(("live", act), time.time())
        self.assertEqual((small.key[0], small.rate), ("card-row", 1))  # its clock, 1:15, moves once a second
        drawn(small)
        isl.runner.do.assert_not_called()

    def test_her_turn_shows_how_many_go_on_in_the_background(self):
        busy = tasks_card([{"title": "Install VLC", "state": "running"}], badge=1)
        isl = fonted(self, jev={"state": "doing", "text": "Opening Settings"}, you="", since=time.time(), level=0.0,
                     lives={"tasks": busy})
        isl._front_icon = lambda size: None
        lay = isl._jev()
        self.assertEqual(lay.key[3], 1)
        drawn(lay)
        isl.lives = {}
        self.assertEqual(isl._jev().key[3], 0)

    def test_her_turns_own_work_shows_live_over_her_face(self):
        """27 October, review: her face is up for her whole turn, so run_plan's "step 2 of 5" and a task in an app's
        "Round 5 of 30", with their Stop, were only ever seen as done for 3 s after it. Now how far it's got shows
        beside her dots, it counts in the badge, and pointing at her opens the card with Stop."""
        stop = {"name": "stop", "label": "Stop", "data": {"key": "turn:1", "needs": ""}}
        row = {"key": "turn:1", "title": "Night light on", "state": "running", "status": "5/30", "progress": 4 / 30,
               "buttons": [stop], "lines": ["Round 5 of 30, clicked"]}
        act = plugins.Activity("tasks", "card", {"rows": [row], "more": 0, "short": None, "badge": 1, "turn": row},
                               live=True)
        isl = fonted(self, jev={"state": "doing", "text": "Turning on night light"}, you="", since=time.time(),
                     level=0.0, lives={"tasks": act})
        isl._front_icon = lambda size: None
        self.assertEqual(isl._scene(time.time()), ("jev",))
        face_ = isl._make(("jev",), time.time())
        self.assertEqual((face_.kind, face_.key[3], face_.key[4]), ("jev", 1, ("5/30", 4 / 30)))
        drawn(face_)
        isl.hover = True
        card = isl._make(("jev",), time.time())
        self.assertIn(card.kind, island.CLICKABLE)
        self.assertEqual(card.press["b0"], ("tasks", "stop", {"key": "turn:1", "needs": ""}, False))
        drawn(card)
        row["buttons"] = []  # one that can't be stopped (a phone turn's): her face stays, pointed at or not
        self.assertEqual(isl._make(("jev",), time.time()).kind, "jev")
        isl.hover, isl.pinned = False, "tasks"  # nor does a card pinned before her turn cover her face
        row["buttons"] = [stop]
        self.assertEqual(isl._make(("jev",), time.time()).kind, "jev")


class Clicks(unittest.TestCase):
    """Approve on the island counts only once the pointer has rested on it half a second, and never while she's
    doing a task in an app: her clicks are real ones, and winplatform.click moves the pointer there 80 ms before it
    clicks. Stop and Deny go at once. And clicks go through the island except while you point at it."""

    def island(self):
        isl = bare(runner=mock.Mock(), rest_pos=(500, 20), rest_at=time.time(), look_at=None)
        isl._wake = lambda: None
        return isl

    def press(self, isl, careful=True, at=(500, 20)):
        with mock.patch.object(island.win, "cursor_pos", lambda: at), contextlib.redirect_stdout(io.StringIO()):
            isl._press(("tasks", "approve" if careful else "deny", {"key": "ask", "needs": "q1"}, careful), False)

    def test_approve_counts_only_once_the_pointer_has_rested_on_it(self):
        isl = self.island()
        self.press(isl)  # it came there just now, as an agent's click does
        isl.rest_at -= island.REST
        self.press(isl, at=(501, 20))  # and it's moved since the island last looked
        isl.runner.do.assert_not_called()
        self.press(isl)
        isl.runner.do.assert_called_once_with("tasks", "approve", {"key": "ask", "needs": "q1"})

    def test_never_while_she_does_a_task_in_an_app(self):
        isl = self.island()
        isl.rest_at -= 5
        with agent.ACT:
            self.press(isl)
        agent.RUNNING.set()
        try:
            self.press(isl)
        finally:
            agent.RUNNING.clear()
        isl.runner.do.assert_not_called()

    def test_stop_and_deny_go_at_once(self):
        isl = self.island()
        self.press(isl, careful=False)
        isl.runner.do.assert_called_once_with("tasks", "deny", {"key": "ask", "needs": "q1"})

    def test_a_card_takes_clicks_only_while_you_point_at_it(self):
        isl = self.island()
        isl.visible_window, isl.origin, isl.island_rect = True, SimpleNamespace(x=0, y=0), (400, 8, 600, 60)
        isl.hover_at = isl.away_at = time.time() - 1
        isl.layout = island.Layout(("card",), "card", 200, 52, None)
        isl.root, isl.top, isl.hwnd = mock.Mock(), mock.Mock(), 1
        through = []
        with mock.patch.object(island.win, "set_click_through", lambda hwnd, on: through.append(on)):
            for at in ((500, 20), (900, 500)):
                with mock.patch.object(island.win, "cursor_pos", lambda at=at: at):
                    isl._hover_poll()
                isl.away_at -= 1  # and the pointer's been away a while
        self.assertEqual(through, [False, True])
        self.assertEqual(isl.rest_pos, (900, 500))


class TasksPlugin(unittest.TestCase):
    """What she's working on, as the island's card, read from memory (activity.py) and never from tasks.db: on the
    plugins' thread its 5 s busy wait would stall the music and the notifications."""

    def setUp(self):
        activity.clear()
        self.addCleanup(activity.clear)
        self.host = mock.Mock()
        self.plugin = plugins.Tasks(self.host)
        self.plugin.start()

    def posted(self):
        return [c.args[0] for c in self.host.post.call_args_list]

    def test_rows_their_buttons_and_how_many_more(self):
        activity.publish("ask", title="Send the message?", kind="ask", state="waiting_yes", needs="q1",
                         answer=lambda yes: True)
        for i in range(4):
            activity.publish(f"task:{i}", title=f"Job {i}", origin="task", step=2 if i == 0 else 0,
                             total=6 if i == 0 else 0, stop=lambda: True)
        self.plugin.poll(time.time())
        kind, pid, act = self.posted()[-1]
        self.assertEqual((kind, pid, act.kind, act.mood), ("live", "tasks", "card", "surprised"))
        d = act.data
        self.assertEqual((len(d["rows"]), d["more"], d["short"], d["badge"]), (3, 2, "5 tasks", 4))
        ask, first, second = d["rows"]
        self.assertEqual([b["name"] for b in ask["buttons"]], ["deny"])  # a yes is said or tapped on the phone
        self.assertEqual((ask["status"], ask["buttons"][0]["data"]), ("Needs you", {"key": "ask", "needs": "q1"}))
        self.assertEqual((first["status"], first["progress"], [b["name"] for b in first["buttons"]]),
                         ("2/6", 1 / 6, ["stop"]))
        self.assertEqual((second["status"], second["progress"]), ("", None))  # how far isn't known: a clock counts
        self.assertIsNotNone(second["since"])

    def test_the_island_never_approves_even_from_an_old_cards_button(self):
        """27 October: the owner wants Deny and Stop on the island, and a yes only by voice or on the phone."""
        activity.publish("ask", title="Send the message?", state="waiting_yes", needs="q1", answer=lambda yes: True)
        with mock.patch.object(plugins.threading, "Thread") as thread:
            self.plugin.poll(time.time())
            self.plugin.command("approve", {"key": "ask", "needs": "q1"})  # an old card's button
        self.assertEqual([b["name"] for b in self.posted()[-1][2].data["rows"][0]["buttons"]], ["deny"])
        thread.assert_not_called()

    def test_it_posts_only_what_changed_and_goes_once_all_is_over(self):
        activity.publish("task:1", title="Install VLC", origin="task")
        self.plugin.poll(time.time())
        self.plugin.poll(time.time())
        self.assertEqual(len(self.posted()), 1)
        activity.drop("task:1")
        self.plugin.poll(time.time())
        self.assertEqual(self.posted()[-1], ("live", "tasks", None))

    def test_her_eyes_react_when_one_finishes_or_fails(self):
        with mock.patch.object(activity, "QUICK", -1.0):
            activity.publish("task:1", title="Install VLC")
            activity.publish("task:2", title="Install Zoom")
            self.plugin.poll(time.time())
            activity.finish("task:1", "done")
            self.plugin.poll(time.time())
            happy = self.posted()[-1][2].mood
            activity.finish("task:2", "failed")
            self.plugin.poll(time.time())
            sad = self.posted()[-1][2].mood
        self.assertEqual((happy, sad), ("happy", "sad"))

    def test_her_turns_row_goes_first_and_counts_in_the_badge(self):
        """Her turn's own row, step by step, is what the island shows over her face (DynamicIsland._turn): first in
        the card even behind three others, and in the badge on her face, which before counted only the background."""
        for i in range(3):
            activity.publish(f"task:{i}", title=f"Job {i}", origin="task", stop=lambda: True)
        activity.publish("turn:1", title="Night light on", kind="turn", total=30, origin="voice", stop=lambda: True)
        activity.step(5, 30, "Round 5 of 30, clicked", key="turn:1")
        self.plugin.poll(time.time())
        d = self.posted()[-1][2].data
        self.assertEqual((d["turn"]["key"], d["rows"][0]["key"], d["badge"], d["more"]), ("turn:1", "turn:1", 4, 1))
        self.assertEqual((d["turn"]["status"], [b["name"] for b in d["turn"]["buttons"]]), ("5/30", ["stop"]))
        activity.finish("turn:1", "done")
        self.plugin.poll(time.time())
        d = self.posted()[-1][2].data
        self.assertEqual((d["turn"], d["badge"]), (None, 3))  # done: its tick shows in the card, not over her face

    def test_it_reads_memory_never_tasks_db(self):
        """Its poll reads activity.snapshot(), and a press goes to a thread of its own: Deny on a task waiting here
        cancels it in tasks.db from there, never from the plugins' thread."""
        folder = tempfile.mkdtemp(prefix="heyjev-island-")
        self.addCleanup(shutil.rmtree, folder, ignore_errors=True)
        store = tasks.Store(os.path.join(folder, "tasks.db"))
        task = store.create("Install VLC", "install", {"id": "VideoLAN.VLC"}, status="waiting_approval")
        opened, real = [], tasks.sqlite3.connect

        def connect(*args, **kwargs):
            opened.append(threading.current_thread())
            return real(*args, **kwargs)
        with mock.patch.object(siri, "TASK_STORE", store):
            siri.show_task(store.get(task), "waiting_yes")
            with mock.patch.object(tasks.sqlite3, "connect", connect):
                self.plugin.poll(time.time())
                self.plugin.command("deny", {"key": f"task:{task}", "needs": str(task)})
                self.assertTrue(until(lambda: any(i["key"] == f"task:{task}" and i["state"] == "stopped"
                                                  for i in activity.snapshot())))
        self.assertNotIn(threading.current_thread(), opened)  # the thread that polled and pressed
        self.assertIn("island-press", [t.name for t in opened])
        self.assertEqual(store.get(task)["status"], "cancelled")


def painted(isl, lay, now=None):
    """lay drawn into the island's window picture by _draw, as a frame comes out at rest: the picture, (h, w, 4)
    blue, green, red and alpha, premultiplied, and the island's box in it."""
    isl.m = round(isl.MARGIN * isl.k)
    isl.ch = int(isl.m + isl.island_max_h + 200 * isl.k)
    isl.buf = np.zeros((isl.ch, isl.cw, 4), np.uint8)
    isl.align, isl.drawn, isl.cap_key, isl.cap_picture = "center", None, None, None
    isl.layout, isl.prev, isl.content, isl.prev_alpha, isl.alpha = lay, None, 1.0, 0.0, 1.0
    isl.cap_alpha = 1.0 if lay.cap else 0.0
    isl.W, isl.H = SimpleNamespace(x=lay.w), SimpleNamespace(x=lay.h)
    isl.CW = SimpleNamespace(x=lay.cap.w if lay.cap else 0.0)
    isl.CH = SimpleNamespace(x=lay.cap.h if lay.cap else 0.0)
    isl._draw(time.time() if now is None else now)
    return isl.buf, isl.island_rect


def straight(px):
    """A premultiplied blue, green, red, alpha pixel as (red, green, blue) 0 to 1, and its alpha 0 to 1."""
    a = px[3] / 255
    return np.asarray(px[2::-1], np.float32) / 255 / max(a, 1e-6), a


@needs_windows
class Capsule(unittest.TestCase):
    """27 October 2026: the owner's pick, a floating glass capsule with her glowing eyes (the pill's own, after a
    cartoon face was tried and put away the same day), the time beside her when nothing's on, a task's title and how
    far it's got with a line under it, and a glass card. The black pill stays as it was (Drawing, Cards: drawn the
    same, pixel for pixel)."""

    def capsule(self, **kw):
        return fonted(self, **dict({"style": "capsule"}, **kw))

    def test_the_setting_is_the_answer_card_until_another_is_picked(self):
        """28 October 2026: the answer card, Atticus's box for her turns, is the capsule the rest of the time."""
        self.addCleanup(settings.put, "island_style", None)
        self.assertEqual(settings.DEFAULTS["island_style"], "panel")
        isl = bare()
        for saved, style, panel in (("pill", "pill", False), ("capsule", "capsule", False),
                                    ("panel", "capsule", True), ("nonsense", "capsule", True), (None, "capsule", True)):
            settings.put("island_style", saved)
            isl._read_settings()
            self.assertEqual((isl.style, isl.panel), (style, panel), saved)
        isl.theme_name = "amoled"
        self.assertIs(isl.theme(), island.GLASS["dark"])
        isl.style = "pill"
        self.assertIs(isl.theme(), island.THEMES["amoled"])

    def card(self, state, text="", you="", asked=None, answered=None):
        isl = self.capsule(panel=True, you=you, _front_icon=lambda size: None, level=0.0, since=time.time())
        isl.island_max_h = isl.PANEL_MAX_H * isl.k
        isl.jev, isl.asked_at, isl.answered_at = {"state": state, "text": text}, asked, answered
        return isl

    def test_the_answer_card_has_your_words_her_answer_how_long_and_try_again(self):
        """28 October 2026, as Atticus's box: her eyes and x on top, your words in a bubble, her answer, then how long
        it took and Try again."""
        now = time.time()
        listening = self.card("listening", "Play Blinding Lights by")._jev()
        self.assertEqual([h[0] for h in listening.hot], ["close"])
        self.assertIn("Play Blinding Lights by", listening.key)  # your words, as they come
        isl = self.card("speaking", "Playing Blinding Lights on Spotify.", "Play Blinding Lights", now - 2.23, now)
        lay = isl._jev()
        self.assertEqual([h[0] for h in lay.hot], ["close", "words", "answer", "again"])
        self.assertIn("2.23 s", lay.key)
        self.assertGreater(lay.h, listening.h)
        self.assertGreater(drawn(lay).max(), 0.5)
        self.assertIsNone(lay.cap)  # it all goes in the card: nothing under it
        self.assertEqual(lay.radius, isl.GLASS_CORNER * isl.k)

    def test_the_answer_card_stays_a_while_and_try_again_asks_again(self):
        isl = self.card("speaking", "Done.", "open notepad", time.time() - 1, time.time())
        later = []
        isl.root = mock.Mock(after=lambda ms, f: later.append(ms) or "job")
        isl.hide_job = None
        isl.hide(900)
        self.assertEqual(later, [isl.PANEL_LINGER])  # not 0.9 s: there's an answer to read
        asked = mock.Mock()
        with mock.patch.dict(sys.modules, {"siri": mock.Mock(CONTROLS=[asked])}):
            isl._panel_press("again")
        asked.put.assert_called_once_with(("again", "open notepad"))

    def test_her_answer_copies_and_your_words_open_to_fix(self):
        """28 October 2026, as Atticus's box: a click on her answer copies it, with "Copied" where the time was; one
        on your words opens the typing box with them in, under the card, and what you send is a turn of yours."""
        now = time.time()
        isl = self.card("speaking", "It’s 24 degrees in Chennai.", "weather in chennai", now - 1.5, now)
        isl.root, isl._wake = mock.Mock(), lambda: None
        timed = isl._jev()
        with mock.patch.object(island.win, "set_clipboard") as clip:
            isl._panel_press("answer")
        clip.assert_called_once_with("It’s 24 degrees in Chennai.")
        lay = isl._jev()
        self.assertIs(lay.key[-2], True)
        self.assertEqual(lay.h, timed.h)  # "Copied" takes the time's place, nothing moves
        self.assertGreater(drawn(lay).max(), 0.5)
        isl.copied_at = now - 5
        self.assertIs(isl._jev().key[-2], False)  # and gives it back
        isl.copied_at = 0.0
        with mock.patch.object(island.win, "set_clipboard", side_effect=RuntimeError("Couldn't open the clipboard")):
            isl._panel_press("answer")  # another app had it: no "Copied"
        self.assertIs(isl._jev().key[-2], False)
        opened = []
        isl.typing = mock.Mock(open=lambda text, near: opened.append((text, near)))
        isl.origin, isl.island_rect = SimpleNamespace(x=100, y=0), (20, 10, 560, 300)
        isl._panel_press("words")
        self.assertEqual(opened, [("weather in chennai", (120, 300, 540))])  # under the card, as wide
        sent = mock.Mock()
        with mock.patch.dict(sys.modules, {"siri": mock.Mock(CONTROLS=[sent])}):
            isl._typed("weather in chennai tomorrow")
        sent.put.assert_called_once_with(("typed", "weather in chennai tomorrow"))
        colours = isl._box_colours()
        self.assertTrue(all(len(c) == 7 and c.startswith("#") for c in colours.values()))

    def test_a_turn_you_typed_starts_afresh_on_the_card(self):
        isl = self.card("speaking", "Done.", "open notepad", time.time() - 9, time.time() - 8)
        isl.steps, isl._wake = [["Opening Notepad", "done"]], lambda: None
        isl.asked("open   paint")
        self.assertEqual(isl.you, "open paint")
        self.assertIsNone(isl.answered_at)
        self.assertIsNone(isl.steps)
        self.assertAlmostEqual(isl.asked_at, time.time(), delta=1)

    def test_what_she_learned_shows_under_her_answer(self):
        """28 October 2026, Atticus's receipts: a green line on the card, else a popup; never said."""
        now = time.time()
        isl = self.card("speaking", "Done.", "work mode", now - 1, now)
        plain = isl._jev()
        isl.receipt = ("Learned", "Next time “work mode” is instant.", now)
        lay = isl._jev()
        self.assertGreater(lay.h, plain.h)
        self.assertTrue(lay.animated)
        self.assertGreater(drawn(lay).max(), 0.5)
        isl.receipt = ("Learned", "old", now - 60)  # gone after its 9 s
        self.assertEqual(isl._jev().h, plain.h)
        gone = self.card("listening")
        gone.jev, gone.popups, gone.root = None, [], mock.Mock()
        gone._wake = lambda: None
        gone.learned("Remembered", "About you: website careerid.in")
        self.assertEqual(gone.popups[-1].data["title"], "Remembered")

    def test_her_steps_show_as_rows_live_then_done(self):
        """28 October 2026, as Atticus lists its steps: a row each, the last few, "+N earlier" over them."""
        isl = self.card("doing", "Opening Spotify", "open spotify and play lofi")
        isl.panel, isl.jev = True, {"state": "doing", "text": "Opening Spotify"}
        isl.root, isl.hide_job, isl._wake, isl._place = mock.Mock(), None, lambda: None, lambda *a: None
        isl.step("live", "Opening Spotify")
        self.assertEqual(isl.steps, [["Opening Spotify", "live"]])
        isl.step("done", "Opening Spotify")  # the same row, now done
        isl.step("live", "Searching Spotify: lofi")
        self.assertEqual(isl.steps, [["Opening Spotify", "done"], ["Searching Spotify: lofi", "live"]])
        without = self.card("doing", "Opening Spotify", "open spotify and play lofi")._jev()
        self.assertGreater(isl._jev().h, without.h)
        for i in range(6):
            isl.step("done", f"step {i}")
        self.assertEqual(isl._jev().key[-1], 4)  # eight steps: the last four shown, four earlier
        isl.show("listening")  # a new turn: no rows
        self.assertIsNone(isl.steps)

    def test_the_turn_times_itself(self):
        isl = self.card("listening")
        isl.root, isl.hide_job, isl.t0 = mock.Mock(), None, time.time()
        isl.eyes, isl._place, isl._wake = face.Eyes(), lambda *a: None, lambda: None
        isl.show("listening", "open")
        self.assertIsNone(isl.asked_at)
        isl.show("thinking")
        self.assertIsNotNone(isl.asked_at)
        isl.show("speaking", "Done.")
        self.assertGreaterEqual(isl.answered_at, isl.asked_at)
        isl.show("listening")  # the next turn starts again
        self.assertIsNone(isl.asked_at)

    def test_her_eyes_are_the_face_until_another_is_picked(self):
        """28 October 2026: her eyes stay her face, the owner's wish; Atticus's orb is there to pick."""
        self.addCleanup(settings.put, "island_face", None)
        self.assertEqual(settings.DEFAULTS["island_face"], "eyes")
        isl = bare()
        for saved, want in (("eyes", "eyes"), ("wave", "wave"), ("orb", "orb"), ("nonsense", "eyes"), (None, "eyes")):
            settings.put("island_face", saved)
            isl._read_settings()
            self.assertEqual(isl.face_style, want, saved)

    def test_the_orb_breathes_when_nothing_is_on_and_shows_the_voice_itself(self):
        orb = self.capsule(face_style="orb", _front_icon=lambda size: None)
        eyes = self.capsule(face_style="eyes", _front_icon=lambda size: None)
        idle = orb._capsule_idle()
        self.assertEqual(idle.rate, 10)  # a slow breath, not a frame every 16 ms
        self.assertGreater(drawn(idle).max(), 0.5)
        self.assertEqual(eyes._capsule_idle().rate, 0)  # her eyes draw nothing between blinks, as before
        for isl in (orb, eyes):
            isl.jev, isl.you, isl.since = {"state": "listening", "text": ""}, "", time.time()
        self.assertLess(orb._jev().w, eyes._jev().w)  # no dots beside the orb: it ripples with the voice itself

    def test_it_floats_under_the_top_with_round_ends(self):
        isl = self.capsule(align="center", off_x=0, off_y=0, visible_window=False)
        isl.corner = 6
        isl.m = round(isl.MARGIN * isl.k)
        isl._place((0, 0, 1920, 1040))
        self.assertEqual(isl.origin.y + isl.m, round(isl.FLOAT * isl.k))  # Down at 0: still 10 px off the top
        isl.style = "pill"
        isl._place((0, 0, 1920, 1040))
        self.assertEqual(isl.origin.y + isl.m, 0)  # the pill sits where Down says
        for style, round_ in (("capsule", True), ("pill", False)):  # Corners at 6: the capsule's ends stay round
            isl.style, isl.shapes = style, {}
            buf, (x0, y0, x1, y1) = painted(isl, isl._idle())
            corner = buf[int(y0), int(x0 + 0.25 * (y1 - y0)), 3]
            self.assertEqual(corner < 60, round_, style)

    def test_glass_is_see_through_with_a_hairline_and_solid_words(self):
        isl = self.capsule()
        buf, (x0, y0, x1, y1) = painted(isl, isl._idle())
        self.assertTrue((buf[..., :3].max(-1) <= buf[..., 3]).all())  # premultiplied, as Windows needs
        cy = int((y0 + y1) / 2)
        colour, a = straight(buf[cy, int(x1 - 5 * isl.k)])  # bare glass, in the round end right of her eyes
        self.assertAlmostEqual(a, 0.78, delta=0.02)
        self.assertLess(np.abs(colour - 0.13).max(), 0.03)
        line, _ = straight(buf[int(y0), int((x0 + x1) / 2)])  # the top edge: the light hairline over the glass
        self.assertGreater(line.min(), colour.max() + 0.08)
        self.assertEqual(buf[int(y0):int(y1), int(x0):int(x1), 3].max(), 255)  # her eyes: solid

    def test_light_glass(self):
        isl = self.capsule(theme_name="light")
        self.assertIs(isl.theme(), island.GLASS["light"])
        buf, (x0, y0, x1, y1) = painted(isl, isl._idle())
        colour, a = straight(buf[int((y0 + y1) / 2), int(x1 - 5 * isl.k)])
        self.assertAlmostEqual(a, 0.85, delta=0.02)
        self.assertGreater(colour.min(), 0.95)
        line, _ = straight(buf[int(y0), int((x0 + x1) / 2)])
        self.assertLess(line.max(), colour.min() - 0.08)  # a dark hairline on light glass

    def test_idle_is_just_her_eyes_and_waits_for_her_next_blink(self):
        """27 October: the owner asked for the time to go from the island; her eyes alone, in the middle."""
        isl = self.capsule()
        lay = isl._idle()
        self.assertEqual((lay.kind, lay.face, lay.eyes, lay.wander, lay.animated, lay.rate),
                         ("idle", True, "open", True, False, 0))
        col = drawn(lay)
        h, w = col.shape[:2]
        lit = np.nonzero((col.min(-1) > 0.9).any(0))[0]  # the columns with the whites of her eyes
        self.assertAlmostEqual((lit[0] + lit[-1]) / 2, w / 2, delta=2)  # in the middle: nothing beside them
        self.assertLess(lay.w, 80 * isl.k)
        now = time.time()
        e = isl.eyes
        e.next_blink, e.next_look, e.blink_at, e.mood = now + 1000, now + 1000, None, None
        e.look, e.target, e.look_v = [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]
        self.assertAlmostEqual(isl._capsule_wait(now, lay, False), 1000, places=3)  # nothing till then: no minute
        e.next_blink = now + 3
        self.assertAlmostEqual(isl._capsule_wait(now, lay, False), 3, places=3)  # a blink
        e.next_look = now + 2
        self.assertAlmostEqual(isl._capsule_wait(now, lay, False), 2, places=3)  # a glance
        isl.look_at = (0.5, 0.2)  # while the mouse moves her eyes, no glance of her own is waited for
        self.assertAlmostEqual(isl._capsule_wait(now, lay, False), 3, places=3)
        isl.look_at = None
        e.target = [0.9, 0.0]  # on her way to look somewhere: every frame till she's there
        self.assertEqual(isl._capsule_wait(now, lay, False), 0.016)
        e.target, e.blink_at = [0.0, 0.0], now
        self.assertEqual(isl._capsule_wait(now, lay, False), 0.016)  # while she blinks, every frame
        e.blink_at, e.next_blink = None, now - 1
        e.react("love", now)  # the hearts beat and the sparkles twinkle while they last
        self.assertEqual(isl._capsule_wait(now, lay, False), 0.033)
        e.react("surprised", now)  # a look of its own: nothing till it's over, or her next blink
        e.next_blink = now + 0.4
        self.assertAlmostEqual(isl._capsule_wait(now, lay, False), 0.4, places=3)

    def test_the_capsule_has_the_pills_own_eyes(self):
        """27 October 2026: the owner found the cartoon face less alive than the glowing eyes, so the capsule has
        those, drawn by the same face.draw_eyes, as big as on the pill's small rows."""
        isl = self.capsule()
        isl.eye = ("open", 1.0, 0.3, -0.2, False)
        w, draw, expr = isl._face("think")
        self.assertEqual(expr, "think")
        mine, theirs = (np.zeros((60, int(w) + 40, 3), np.float32) for _ in range(2))
        draw(face.Canvas(mine), 20, 30, 1.0, time.time())
        face.draw_eyes(face.Canvas(theirs), 20 + w / 2, 30, isl.SMALL_EYES * isl.k, "open", 1.0, (0.3, -0.2),
                       0.0, 0.0, island.GLASS["dark"]["eyes"], True)
        self.assertTrue(np.allclose(mine, theirs, atol=1e-5))  # the very same eyes, where they're looking
        self.assertFalse(hasattr(face, "cartoon"))
        isl.eye = ("happy", 1.0, 0.0, 0.0, False)  # ^ ^, as the pill has them
        arcs = drawn(isl._idle())
        isl.eye = ("open", 1.0, 0.0, 0.0, False)
        self.assertLess((arcs.min(-1) > 0.9).sum(), (drawn(isl._idle()).min(-1) > 0.9).sum())
        for state, expr in (("listening", "open"), ("thinking", "think"), ("looking", "glasses"),
                            ("doing", "focus"), ("error", "sad")):  # her turns look as on the pill (JEV)
            isl.jev, isl.you, isl.since = {"state": state, "text": ""}, "", time.time()
            isl._front_icon = lambda size: None
            lay = isl._make(("jev",), time.time())
            self.assertEqual((lay.eyes, lay.wander), (expr, False), state)
        self.assertEqual([island.TASK_LOOKS.get(s, "open") for s in ("running", "done", "failed", "waiting_yes")],
                         ["open", "happy", "sad", "surprised"])  # not "focus": its sway never rests

    def test_their_glow_takes_the_colour_of_what_shes_doing(self):
        isl = self.capsule()
        isl.eye = ("open", 1.0, 0.0, 0.0, False)

        def glow(tint, theme="amoled", mood=None):
            isl.theme_name = theme
            isl.eyes.mood, isl.eyes.mood_until = mood, (time.time() + 5 if mood else 0.0)
            w, draw, _ = isl._face("open", tint)
            col = np.zeros((60, int(w) + 40, 3), np.float32)
            draw(face.Canvas(col), 20, 30, 1.0, time.time())
            return col[(col.max(-1) > 0.05) & (col.min(-1) < 0.85)]  # round the eyes, not their whites

        plain, amber = glow(None), glow(island.ORANGE)
        self.assertLess(abs(plain[:, 0].mean() - plain[:, 2].mean()), 0.02)  # her own white glow
        self.assertGreater(amber[:, 0].mean() - amber[:, 2].mean(), 0.05)  # warm while she works
        blue = glow(island.ORANGE, mood="surprised")  # a reaction's colour over it while it lasts
        self.assertGreater(blue[:, 2].mean() - blue[:, 0].mean(), 0.05)
        self.assertEqual(len(glow(island.ORANGE, "light")), len(glow(None, "light")))  # light glass: no glow

    def test_her_eyes_follow_the_pointer_then_glance_about_again(self):
        isl = self.capsule()
        wakes = []
        isl._wake = lambda: wakes.append(1)
        isl.face_at = (300.0, 30.0)
        now = 1000.0
        far = 10 * island.GAZE_REACH * isl.k
        isl._follow(300 + far, 30, now)  # far off to the right: all the way that way
        self.assertAlmostEqual(isl.look_at[0], 1.0, delta=0.06)
        self.assertEqual(isl.look_at[1], 0.0)
        isl._follow(300 - far, 30 + far, now + 0.07)
        self.assertAlmostEqual(isl.look_at[0], -1.0, delta=0.06)
        self.assertAlmostEqual(isl.look_at[1], 1.0, delta=0.06)
        self.assertEqual(len(wakes), 2)
        step = 1 / (0.36 * isl.SMALL_EYES * isl.k)  # a whole pixel of her eyes' move, in look
        isl._follow(300 + 40, 30, now + 0.14)
        before = len(wakes)
        isl._follow(300 + 40.2, 30, now + 0.21)  # moved, but not by a pixel of hers
        self.assertEqual(len(wakes), before)
        self.assertAlmostEqual(isl.look_at[0] / step, round(isl.look_at[0] / step))  # on whole pixels
        isl._follow(300 + 40.2, 30, now + 0.21 + island.GAZE_HOLD + 0.1)  # still a while: her own glances again
        self.assertIsNone(isl.look_at)
        self.assertEqual(len(wakes), before + 1)

    def test_no_frame_while_the_pointer_and_her_mood_stay_put(self):
        isl = bare(style="capsule", runner=mock.Mock(), look_at=None, visible_window=True, hover=False)
        isl.origin, isl.island_rect, isl.face_at = SimpleNamespace(x=0, y=0), (400, 15, 600, 66), (420, 40)
        isl.hover_at = isl.away_at = time.time()
        isl.layout = island.Layout(("idle",), "idle", 200, 51, None, eyes="open", face=True)
        isl.root, isl.top, isl.hwnd = mock.Mock(), mock.Mock(), 1
        wakes = []
        isl._wake = lambda: wakes.append(1)
        with mock.patch.object(island.win, "set_click_through", lambda hwnd, on: None), \
                mock.patch.object(island.win, "cursor_pos", lambda: (900, 500)):
            for _ in range(5):
                isl._hover_poll()
        self.assertEqual(len(wakes), 1)  # her eyes went to the pointer once, then nothing
        isl.layout = island.Layout(("jev",), "jev", 200, 51, None, eyes="think", face=True, wander=False)
        with mock.patch.object(island.win, "set_click_through", lambda hwnd, on: None), \
                mock.patch.object(island.win, "cursor_pos", lambda: (950, 520)):
            isl._hover_poll()
        self.assertIsNone(isl.look_at)  # on her turn they do as it says (thinking: up), not after the mouse

    def test_a_task_shows_its_title_how_far_and_a_line_under_it(self):
        stop = {"name": "stop", "label": "Stop", "data": {"key": "task:1", "needs": ""}}
        poem = {"title": "Writing the poem", "state": "running", "progress": 0.4, "status": "2/5", "buttons": [stop]}
        isl = self.capsule()
        lay = isl._make(("live", tasks_card([poem])), time.time())
        self.assertEqual((lay.kind, lay.key[0], lay.key[2], lay.key[3], lay.rate), ("card", "card-row",
                                                                                     "Writing the poem", "40%", 1))
        buf, (x0, y0, x1, y1) = painted(isl, lay)
        y = int(y1 + 5.5 * isl.k)
        lit = [x for x in range(isl.cw) if buf[y, x, 3] > 200 and np.abs(straight(buf[y, x])[0] -
                                                                          island.ORANGE).max() < 0.1]
        H = y1 - y0
        self.assertAlmostEqual((lit[-1] - lit[0] + 1) / (x1 - x0 - H), 0.4, delta=0.04)  # under the capsule, 40%
        self.assertAlmostEqual(lit[0], x0 + H / 2, delta=2)
        two = isl._make(("live", tasks_card([dict(poem, title="x" * 300), poem], short="2 tasks")), time.time())
        self.assertTrue(two.key[2].endswith("…"))  # the first one's title, cut short
        self.assertEqual(two.key[-1], 2)  # and "2" beside it
        self.assertLessEqual(two.w, isl.CAPSULE_MAX_W * isl.k + 1)
        drawn(two)
        research = dict(poem, progress=None, status="", since=time.time() - 75, kind="research")
        unknown = isl._make(("live", tasks_card([research])), time.time())
        self.assertEqual(unknown.key[3], "")  # its clock instead, 1:15
        buf, (x0, y0, x1, y1) = painted(isl, unknown)
        y = int(y1 + 5.5 * isl.k)
        lit = [x for x in range(isl.cw) if buf[y, x, 3] > 200 and np.abs(straight(buf[y, x])[0] -
                                                                          island.VIOLET).max() < 0.1]
        self.assertAlmostEqual((lit[-1] - lit[0] + 1) / (x1 - x0 - (y1 - y0)), 0.28, delta=0.04)  # a piece of it

    def test_its_card_has_her_rows_bars_and_stop_and_deny(self):
        stop = {"name": "stop", "label": "Stop", "data": {"key": "task:1", "needs": ""}}
        deny = {"name": "deny", "label": "Deny", "data": {"key": "ask", "needs": "q1"}}
        rows = [{"title": "Writing the poem", "state": "running", "progress": 0.4, "status": "2/5",
                 "lines": ["Second verse"], "buttons": [stop]},
                {"title": "Send it?", "state": "waiting_yes", "progress": None, "status": "Needs you",
                 "lines": ["Home by eight"], "buttons": [deny]}]
        isl = self.capsule(hover=True)
        lay = isl._make(("live", tasks_card(rows, more=2, short="4 tasks")), time.time())
        self.assertEqual((lay.kind, lay.key[0], lay.radius, lay.rate), ("card", "card", 18 * isl.k, 1))
        self.assertLessEqual(lay.h, isl._tallest_card())
        self.assertEqual([h[0] for h in lay.hot], ["b0", "b1", "pin"])
        self.assertEqual(lay.press["b0"], ("tasks", "stop", {"key": "task:1", "needs": ""}, False))
        self.assertEqual(lay.press["b1"], ("tasks", "deny", {"key": "ask", "needs": "q1"}, False))
        for name, bx0, by0, bx1, by1 in lay.hot[:2]:  # on the right of their rows, inside the card
            self.assertTrue(lay.w / 2 < bx0 < bx1 <= lay.w and 0 < by0 < by1 < lay.h, name)
        col = drawn(lay)
        for colour in (island.ORANGE, island.BLUE):  # each row's bar in its colour
            self.assertGreater((np.abs(col - np.asarray(colour, np.float32)).max(-1) < 0.05).sum(), 30, colour)
        weather = plugins.Activity("weather", "card", {"title": "Rain at 4", "lines": ["Take an umbrella"]}, live=True)
        drawn(isl._make(("live", weather), time.time()))  # any plugin's card, which says nothing of a state

    def test_her_turn_in_the_capsule(self):
        stop = {"name": "stop", "label": "Stop", "data": {"key": "turn:1", "needs": ""}}
        row = {"key": "turn:1", "title": "Night light on", "state": "running", "status": "5/30", "progress": 4 / 30,
               "buttons": [stop], "lines": []}
        act = plugins.Activity("tasks", "card", {"rows": [row], "more": 0, "short": None, "badge": 1, "turn": row},
                               live=True)
        isl = self.capsule(jev={"state": "listening", "text": "Set a timer"}, you="", since=time.time(),
                           lives={"tasks": act})
        isl._front_icon = lambda size: None
        lay = isl._make(("jev",), time.time())
        self.assertEqual((lay.kind, lay.face, lay.animated, lay.key[3], lay.key[4]), ("jev", True, True, 1,
                                                                                         ("5/30", 4 / 30)))
        self.assertIsNotNone(lay.cap)  # her words under it, as ever
        buf, _ = painted(isl, lay)
        self.assertTrue((buf[..., :3].max(-1) <= buf[..., 3]).all())
        isl.hover = True  # pointing at her: the card with Stop, on glass
        self.assertEqual(isl._make(("jev",), time.time()).press["b0"][1], "stop")

    def test_the_other_plugins_on_glass(self):
        now = time.time()
        isl = self.capsule(runner=SimpleNamespace(plugin=lambda pid: None))
        for scene in (("popup", plugins.Activity("battery", "battery", {"percent": 18, "charging": False,
                                                                         "event": "low"})),
                      ("live", plugins.Activity("timers", "timer", {"label": "Tea", "end": now + 60, "total": 90.0},
                                                live=True)),
                      ("live", plugins.Activity("media", "media", {"title": "Song", "artist": "Band", "app": "Spotify",
                                                                   "playing": True, "art": None}, live=True))):
            lay = isl._make(scene, now)
            self.assertTrue(lay.face, scene[1].kind)  # on glass, with her eyes
            drawn(lay)
        note = plugins.Activity("notifications", "notification", {"app": "WhatsApp", "app_id": "", "title": "Mum",
                                                                  "text": "Home by eight", "phone": False})
        self.assertEqual(isl._make(("popup", note), now).radius, 18 * isl.k)

    def test_the_pill_is_as_it_was(self):
        isl = fonted(self)
        self.assertIs(isl.theme(), island.THEMES["amoled"])
        lay = isl._idle()
        self.assertEqual((lay.face, lay.eyes), (False, "open"))
        buf, (x0, y0, x1, y1) = painted(isl, lay)
        self.assertEqual(buf[int((y0 + y1) / 2), int(x1 - 5 * isl.k), 3], 255)  # solid black
        self.assertIsNone(isl._shape(x0, x1 - x0, y1 - y0, 10, y0)[3])  # and no line round it unless asked


class Drawing(unittest.TestCase):
    """The shortcuts that keep a frame cheap give the same pixels as working out every one."""

    def test_a_wide_bar_worked_out_once_in_the_middle_matches_every_column(self):
        k = 1.5
        isl = bare(border=True)
        x0, W, H, r, y = 40.3, 1000.0, 90.0, 27.0, 120.0
        (rows, cols), cover, alpha, edge = isl._shape(x0, W, H, r, y)
        xs = np.arange(cols.start, cols.stop, dtype=np.float32) + 0.5
        ys = np.arange(rows.start, rows.stop, dtype=np.float32)[:, None] + 0.5
        sd = face.rbox(xs, ys, x0 + W / 2, y + H / 2, W / 2, H / 2, r)
        want = np.clip(0.5 - sd, 0.0, 1.0)
        far = face.rbox(xs, ys - 3 * k, x0 + W / 2, y + H / 2, W / 2, H / 2, r)
        shadow = island.THEMES["amoled"]["shadow"] * np.clip(0.5 - far / (11 * k), 0.0, 1.0) ** 2
        self.assertEqual(cover.shape, want.shape)
        self.assertLess(np.abs(cover - want).max(), 1e-5)
        self.assertLess(np.abs(alpha - (want + shadow * (1 - want))).max(), 1e-5)
        self.assertLess(np.abs(edge - np.clip(0.5 - (np.abs(sd + 0.7 * k) - 0.6 * k), 0.0, 1.0)).max(), 1e-5)
        for side in (alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1]):  # the shadow fades out inside the patch
            self.assertLess(side.max(), 1e-3)

    def test_painting_over_what_is_there(self):
        out = np.zeros((2, 2, 4), np.uint8)
        out[...] = (10, 20, 30, 255)  # blue, green, red, alpha
        col = np.zeros((2, 2, 3), np.float32)
        col[...] = (1.0, 0.5, 0.0)  # red, green, blue
        cover = np.array([[1.0, 0.0], [1.0, 0.0]], np.float32)
        alpha = np.array([[1.0, 0.0], [1.0, 0.5]], np.float32)
        bare()._compose(out, col, cover, alpha, None, 1.0, (0, 2))
        self.assertEqual(tuple(out[0, 0]), (0, 128, 255, 255))  # covered
        self.assertEqual(tuple(out[0, 1]), (10, 20, 30, 255))  # nothing of it there: what was stays
        self.assertEqual(tuple(out[1, 1]), (5, 10, 15, 255))  # half its shadow: what was, darker

    def test_boxes(self):
        self.assertEqual(island._union(None, (1, 2, 3, 4)), (1, 2, 3, 4))
        self.assertEqual(island._union((0, 5, 3, 9), (1, 2, 8, 4)), (0, 2, 8, 9))


if __name__ == "__main__":
    unittest.main()


class TypingBox(unittest.TestCase):
    """28 October 2026, after Atticus's box: typing to her instead of talking. Enter sends it, in one line, as a turn
    of yours; its grey hint is never sent; Up and Down go back through what you typed; clicking away keeps a draft."""

    def setUp(self):
        import tkinter as tk
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            self.skipTest(f"no display for Tk: {exc}")
        self.root.withdraw()
        self.addCleanup(self.root.destroy)
        self.sent = []
        self.box = askbox.AskBox(self.root, self.sent.append)
        self.addCleanup(self.box.close)

    def test_enter_sends_what_you_typed_in_one_line(self):
        self.box.open()
        self.assertTrue(self.box.visible)
        self.assertTrue(self.box.hinting)
        self.assertEqual(self.box.typed(), "")
        self.box._enter()
        self.assertEqual(self.sent, [])  # the hint isn't yours
        self.box._set("  open   notepad ")
        self.box._enter()
        self.assertEqual(self.sent, ["open notepad"])
        self.assertFalse(self.box.visible)

    def test_your_words_open_in_it_to_fix(self):
        self.box.open("play  blinding lights", near=(100, 40, 540))
        self.assertEqual(self.box.typed(), "play blinding lights")
        self.assertEqual(self.box.entry.index("insert"), len("play blinding lights"))  # the cursor at the end
        self.assertFalse(self.box.hinting)

    def test_up_and_down_go_back_through_what_you_typed(self):
        for text in ("one", "two"):
            self.box.open()
            self.box._set(text)
            self.box._enter()
        self.box.open()
        self.box._recall(-1)
        self.assertEqual(self.box.typed(), "two")
        self.box._recall(-1)
        self.box._recall(-1)
        self.assertEqual(self.box.typed(), "one")  # the oldest stays
        self.box._recall(1)
        self.box._recall(1)
        self.assertEqual(self.box.typed(), "")  # past the newest: empty again

    def test_clicking_away_keeps_a_draft_esc_doesnt(self):
        self.box.open()
        self.box._set("half typed")
        self.box.close()
        self.box.open()
        self.assertEqual(self.box.typed(), "half typed")
        self.box.close(keep=False)
        self.box.open()
        self.assertEqual(self.box.typed(), "")
