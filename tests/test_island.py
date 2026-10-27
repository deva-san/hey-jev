"""Her island (island.py): what dictation strikes out, her eyes, the plugins' rules, which scene shows, the drawing
shortcuts that must give the same picture as the long way round, and what she's working on: the Tasks plugin, read
from memory only, its card with Stop, Approve and Deny, and the guards on Approve."""
import contextlib
import io
import os
import shutil
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from tests.support import needs_windows, siri  # temp APPDATA and the tripwires, before anything else
from tests.test_watchers import until

import activity
import agent
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
        self.assertEqual([(b["name"], b.get("careful", False)) for b in ask["buttons"]],
                         [("deny", False), ("approve", True)])
        self.assertEqual((ask["status"], ask["buttons"][1]["data"]), ("Needs you", {"key": "ask", "needs": "q1"}))
        self.assertEqual((first["status"], first["progress"], [b["name"] for b in first["buttons"]]),
                         ("2/6", 1 / 6, ["stop"]))
        self.assertEqual((second["status"], second["progress"]), ("", None))  # how far isn't known: a clock counts
        self.assertIsNotNone(second["since"])

    def test_with_approve_off_in_the_island_tab_only_deny(self):
        activity.publish("ask", title="Send the message?", state="waiting_yes", needs="q1", answer=lambda yes: True)
        with mock.patch.dict(settings._load(), {"island_plugin_options": {"tasks": {"approve": False}}}), \
                mock.patch.object(plugins.threading, "Thread") as thread:
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
