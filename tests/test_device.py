"""Settings switched straight away, from Tomte (github.com/xditya/tomte-windows, MIT): the screen's brightness,
Wi-Fi, Bluetooth, the mic and where the sound goes. On 25 October "Increase brightness" went to a task in Settings,
which pressed Win+A and stopped. Nothing here reaches the PC: every winplatform call is a fake."""
import contextlib
import io
import unittest
from unittest import mock

from tests.support import siri

SPEAKERS = ("{0.0.0}.{laptop}", "Speakers (Realtek(R) Audio)", True)
JBL = ("{0.0.0}.{jbl}", "Speakers (JBL Flip 5)", False)  # as Windows names a Bluetooth speaker
BUDS = ("{0.0.0}.{buds}", "Headphones (Galaxy Buds2 Pro)", False)


class FakePC:
    """The PC's settings as device_step finds them, and what she changed."""

    def __init__(self, test):
        self.bright, self.radios, self.mic, self.outputs, self.done = 30, {"wifi": True, "bluetooth": False}, False, \
            [SPEAKERS, JBL], []
        self.allowed = True
        for name, fake in (("brightness", lambda: self.bright), ("set_brightness", self.set_brightness),
                           ("radio_on", lambda kind: self.radios[kind]), ("set_radio", self.set_radio),
                           ("mic_muted", lambda: self.mic), ("set_mic_muted", self.set_mic),
                           ("output_devices", lambda: list(self.outputs)), ("set_output", self.set_output),
                           ("open_windows_page", lambda page: self.done.append(("page", page)))):
            patch = mock.patch.object(siri.win, name, fake)
            patch.start()
            test.addCleanup(patch.stop)

    def set_brightness(self, n):
        self.bright = n
        self.done.append(("brightness", n))

    def set_radio(self, kind, on):
        if not self.allowed:
            siri.win.open_windows_page(siri.win.RADIO_PAGES[kind])
            raise RuntimeError("Windows didn't let me switch Bluetooth, so I've opened its settings")
        self.radios[kind] = on
        self.done.append((kind, on))

    def set_mic(self, muted):
        self.mic = muted
        self.done.append(("mic", muted))

    def set_output(self, device_id):
        self.outputs = [(i, n, i == device_id) for i, n, _ in self.outputs]
        self.done.append(("output", device_id))


class Quick(unittest.TestCase):
    def plan(self, words, gate=False):
        with contextlib.redirect_stdout(io.StringIO()):
            plan = siri.quick(words, gate)
        return plan and plan["steps"]

    def test_straight_away_with_no_model(self):
        for words, step in (("Increase brightness", ("brightness", "up")), ("turn up the brightness", ("brightness", "up")),
                            ("dim the screen", ("brightness", "down")), ("brightness 70%", ("brightness", 70)),
                            ("set the brightness to fifty percent", ("brightness", 50)),
                            ("full brightness", ("brightness", 100)), ("turn on bluetooth", ("bluetooth", "on")),
                            ("Bluetooth off", ("bluetooth", "off")), ("turn on Wi-Fi", ("wifi", "on")),
                            ("mute my mic", ("mic", "mute")), ("unmute the microphone", ("mic", "unmute")),
                            ("switch the sound to my headphones", ("output", "headphones")),
                            ("switch to my speaker", ("output", "speaker"))):
            with self.subTest(words=words):
                self.assertEqual(self.plan(words, "cold"), [{"do": "device", "what": step[0], "to": step[1]}])

    def test_wifi_off_goes_to_the_model_and_the_rest_is_as_before(self):
        self.assertIsNone(self.plan("turn off wifi", "cold"))  # it decides who that was said to
        self.assertEqual(self.plan("mute"), [{"do": "volume", "to": "mute"}])  # the sound, not the mic
        self.assertEqual(self.plan("switch to chrome"), [{"do": "open", "app": "Google Chrome"}])

    def test_a_model_writing_the_setting_as_the_step_is_mended(self):
        plan = siri.parse_plan('{"steps": [{"do": "bluetooth", "on": true}, {"do": "brightness", "level": 70}, '
                               '{"do": "screen", "task": "x"}], "say": ""}')
        self.assertEqual(plan["steps"], [{"do": "device", "what": "bluetooth", "to": True},
                                         {"do": "device", "what": "brightness", "to": 70},
                                         {"do": "screen", "task": "x"}])
        self.assertIn('"do":"device"', siri.PROMPT)


class Doing(unittest.TestCase):
    def setUp(self):
        self.pc = FakePC(self)

    def do(self, what, to, said="turn on the mic"):
        token = siri.agent.SAID.set(said)
        try:
            return siri.device_step({"do": "device", "what": what, "to": to})
        finally:
            siri.agent.SAID.reset(token)

    def test_brightness(self):
        self.assertEqual(self.do("brightness", "up"), "Brightness is at 50 percent.")
        self.assertEqual(self.do("brightness", 75), "Brightness is at 75 percent.")
        self.assertEqual(self.do("brightness", "down"), "Brightness is at 55 percent.")
        self.pc.bright = 100
        self.assertEqual(self.do("brightness", "up"), "Brightness is already at 100 percent.")
        with self.assertRaisesRegex(RuntimeError, "how bright"):
            self.do("brightness", "lovely")
        with mock.patch.object(siri.win, "brightness", lambda: None), \
                self.assertRaisesRegex(RuntimeError, "isn't one Windows lets me set"):
            self.do("brightness", "up")  # an external monitor

    def test_wifi_and_bluetooth(self):
        self.assertEqual(self.do("bluetooth", "on"), "Bluetooth's on.")
        self.assertEqual(self.do("bluetooth", True), "Bluetooth's already on.")
        self.assertEqual(self.do("wifi", "on"), "Wi-Fi's already on.")
        self.assertEqual(self.do("bluetooth", None), "Bluetooth's off.")  # no state said: switched
        self.pc.allowed = False
        with self.assertRaisesRegex(RuntimeError, "opened its settings"):
            self.do("bluetooth", "on")
        self.assertIn(("page", "ms-settings:bluetooth"), self.pc.done)

    def test_the_mic_is_muted_only_when_the_words_say_mic(self):
        self.assertIn("muted, for every app and for me too", self.do("mic", "mute", "mute my mic"))
        self.assertEqual(self.do("mic", "unmute"), "Your mic's on again.")
        with self.assertRaisesRegex(RuntimeError, "when you say mic"):
            self.do("mic", "mute", "mute it")  # the sound, as a model could misread it
        self.assertEqual(self.pc.done, [("mic", True), ("mic", False)])

    def test_where_the_sound_goes(self):
        self.assertEqual(self.do("output", "my JBL speaker"), "Sound's coming out of JBL Flip 5 now.")
        self.assertEqual(self.do("output", "jbl"), "Sound's already coming out of JBL Flip 5.")
        with self.assertRaisesRegex(RuntimeError, "more than one like that: Speakers or JBL Flip 5"):
            self.do("output", "speaker")  # the laptop's or the JBL: she asks rather than guess
        self.pc.outputs.append(BUDS)
        self.assertEqual(self.do("output", "headphones"), "Sound's coming out of Galaxy Buds2 Pro now.")
        with self.assertRaisesRegex(RuntimeError, "can't find a sound output called airpods"):
            self.do("output", "airpods")
        self.assertEqual(self.do("output", "list"),
                         "Sound can go to Speakers, JBL Flip 5, Galaxy Buds2 Pro, which it does now.")
        self.assertEqual([d for d in self.pc.done if d[0] == "output"], [("output", JBL[0]), ("output", BUDS[0])])


class SaidColdAndSaidBack(unittest.TestCase):
    def setUp(self):
        self.pc = FakePC(self)

    def test_said_cold_the_words_name_what_changes(self):
        off = {"do": "device", "what": "wifi", "to": "off"}
        self.assertIs(siri.unasked([off], "turn it off", "cold", planned=True), off)  # a TV's line
        self.assertIsNone(siri.unasked([off], "turn off the wifi", "cold", planned=True))
        mic = {"do": "device", "what": "mic", "to": "mute"}
        self.assertIs(siri.unasked([mic], "mute this", "cold", planned=True), mic)
        self.assertIsNone(siri.unasked([{"do": "device", "what": "brightness", "to": "up"}], "brighter", "cold"))

    def run_plan(self, steps, say=""):
        spoken = []
        with mock.patch.object(siri, "say", lambda line, notify: spoken.append(line)), \
                contextlib.redirect_stdout(io.StringIO()):
            failed, _, _, _ = siri.run_plan({"steps": steps, "say": say}, None)
        return failed, spoken

    def test_she_says_what_it_did_once_its_done(self):
        failed, spoken = self.run_plan([{"do": "device", "what": "brightness", "to": "up"},
                                        {"do": "device", "what": "bluetooth", "to": "on"}])
        self.assertEqual((failed, spoken), ([], ["Brightness is at 50 percent. Bluetooth's on."]))
        # what it is now, not the model's line: it said "Turning Bluetooth on." for one that was on already
        failed, spoken = self.run_plan([{"do": "device", "what": "bluetooth", "to": "on"}], "Turning Bluetooth on.")
        self.assertEqual(spoken, ["Bluetooth's already on."])
        self.pc.allowed = False
        self.pc.radios["bluetooth"] = False
        failed, spoken = self.run_plan([{"do": "device", "what": "bluetooth", "to": "on"}])
        self.assertEqual(failed, ["Windows didn't let me switch Bluetooth, so I've opened its settings"])
        self.assertNotIn("Bluetooth's on.", spoken)

    def test_before_wifi_goes_off_she_says_so(self):
        order = []
        with mock.patch.object(self.pc, "set_radio", lambda kind, on: order.append(("wifi", on))):
            with mock.patch.object(siri.win, "set_radio", lambda kind, on: order.append(("wifi", on))):
                spoken = []
                with mock.patch.object(siri, "say", lambda line, notify: (spoken.append(line), order.append("said"))), \
                        contextlib.redirect_stdout(io.StringIO()):
                    siri.run_plan({"steps": [{"do": "device", "what": "wifi", "to": "off"}], "say": ""}, None)
        self.assertEqual(order, ["said", ("wifi", False)])
        self.assertTrue(spoken[0].startswith("Turning Wi-Fi off."))


class Pick(unittest.TestCase):
    def test_by_name_or_its_words(self):
        devices = [SPEAKERS, JBL, BUDS]
        self.assertEqual(siri.win.pick_output(devices, "Galaxy Buds2 Pro"), BUDS)
        self.assertEqual(siri.win.pick_output(devices, "the jbl"), JBL)
        self.assertEqual(siri.win.pick_output(devices, "my galaxy buds"), BUDS)
        self.assertEqual(siri.win.output_name(SPEAKERS[1]), "Speakers")  # the laptop's own, by what it is
        for name in ("", "the", "airpods"):
            with self.subTest(name=name), self.assertRaises(LookupError):
                siri.win.pick_output(devices, name)


if __name__ == "__main__":
    unittest.main()
