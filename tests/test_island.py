"""Her island (island.py): what dictation strikes out, her eyes, the plugins' rules, which scene shows, and the
drawing shortcuts that must give the same picture as the long way round."""
import time
import unittest
from unittest import mock

import numpy as np

from tests.support import siri  # noqa: F401  temp APPDATA and the tripwires, before anything else

import dictation
import island
import island_face as face
import island_plugins as plugins
import settings


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
    for name, value in kw.items():
        setattr(isl, name, value)
    return isl


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
