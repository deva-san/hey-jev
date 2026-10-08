"""WhatsApp's 2025 app (a web view): its message box is "Type a message to Amma", its link leaves the text out, and
it puts its web view in front once the box has the keyboard. She types the text herself, reads it back, says which
chat is open, and presses Enter only on exactly that, in that chat. Nothing here touches the real WhatsApp."""
import importlib.util
import os
import unittest
from types import SimpleNamespace
from unittest import mock

from tests.support import ROOT  # noqa: F401, the test setup: data in a temp folder, tripwires on the real thing


def real_messaging():
    """messaging.py fresh: the one tests share has tripwires on prepare, send and the like."""
    spec = importlib.util.spec_from_file_location("messaging_real", os.path.join(ROOT, "messaging.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class Box:
    """WhatsApp's message box, as UI Automation shows it."""

    def __init__(self, name="Type a message to Amma \U0001f496", value="", focus=True):
        self.CurrentName, self.value, self.CurrentHasKeyboardFocus = name, value, focus

    def SetFocus(self):
        self.CurrentHasKeyboardFocus = True


class Messaging(unittest.TestCase):
    def setUp(self):
        self.m = real_messaging()
        self.box, self.pressed, self.typed = Box(), [], []
        m = self.m

        def press(*keys):
            self.pressed.append(keys)
            if keys == ("enter",):
                self.box.value = ""  # WhatsApp takes it
            elif keys == ("backspace",):
                self.box.value = ""

        def type_text(text):
            self.typed.append(text)
            self.box.value += text
        for target, name, value in (
                (m, "compose_box", lambda app, hwnd: (self.box, "Amma \U0001f496") if self.box else (None, "")),
                (m, "box_value", lambda box: " ".join(box.value.split())),
                (m, "in_front", lambda app, hwnd: True),
                (m, "open_chat", lambda app, handle, text: 99),
                (m, "find_contact", lambda contact, app: ("amma", "919999999999")),
                (m, "offline_reason", lambda app, hwnd: None),
                (m.win, "press", press), (m.win, "type_text", type_text),
                (m.time, "sleep", lambda s: None), (m.user32, "IsWindow", lambda h: True)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_the_link_left_the_text_out_so_she_types_it_and_reads_it_back(self):
        ready = self.m.prepare("whatsapp", "amma", "Hi")
        self.assertEqual(self.typed, ["Hi"])
        self.assertEqual(self.box.value, "Hi")
        self.assertTrue(ready["checked"])
        self.assertEqual(ready["to"], "Amma \U0001f496")
        self.assertNotIn(("enter",), self.pressed)  # nothing is sent until the yes

    def test_a_draft_already_there_is_cleared_first(self):
        self.box.value = "old draft"
        self.m.prepare("whatsapp", "amma", "Hi")
        self.assertEqual(self.box.value, "Hi")

    def test_no_message_box_means_nothing_is_typed(self):
        self.box = None
        with self.assertRaises(RuntimeError) as err:
            self.m.prepare("whatsapp", "amma", "Hi")
        self.assertIn("didn't open the chat", str(err.exception))
        self.assertEqual((self.typed, self.pressed), ([], []))

    def test_send_presses_enter_on_exactly_that_and_checks_it_went(self):
        ready = self.m.prepare("whatsapp", "amma", "Hi")
        ok, said = self.m.send(ready)
        self.assertEqual(said, "Sent to amma.")
        self.assertEqual(self.pressed[-1], ("enter",))

    def test_a_changed_message_or_chat_isnt_sent(self):
        ready = self.m.prepare("whatsapp", "amma", "Hi")
        self.box.value = "Hi there"
        with self.assertRaises(RuntimeError):
            self.m.send(ready)
        self.box.value = "Hi"
        with mock.patch.object(self.m, "compose_box", lambda app, hwnd: (self.box, "Ravi")):
            with self.assertRaises(RuntimeError) as err:
                self.m.send(ready)
        self.assertIn("another chat", str(err.exception))
        self.assertNotIn(("enter",), self.pressed)

    def test_still_in_the_box_after_enter_isnt_called_sent(self):
        ready = self.m.prepare("whatsapp", "amma", "Hi")
        with mock.patch.object(self.m.win, "press", lambda *k: None):  # Enter didn't take
            with self.assertRaises(RuntimeError) as err:
                self.m.send(ready)
        self.assertIn("still sitting", str(err.exception))

    def test_the_new_name_of_the_box_is_read(self):
        m = real_messaging()
        box = SimpleNamespace(CurrentName="Type a message to Amma \U0001f496")
        uia = SimpleNamespace(ElementFromHandle=lambda h: SimpleNamespace(FindFirst=lambda scope, cond: box),
                              CreateAndCondition=lambda a, b: None, CreatePropertyCondition=lambda p, v: None,
                              CreatePropertyConditionEx=lambda p, v, f: None)
        with mock.patch.object(m, "_uia", lambda: uia):
            self.assertEqual(m.compose_box("whatsapp", 5), (box, "Amma \U0001f496"))
            box.CurrentName = "Type a message"  # the app before 2025
            self.assertEqual(m.compose_box("whatsapp", 5)[1], "")

    def test_its_web_view_in_front_is_it_but_another_apps_isnt(self):
        m = real_messaging()
        procs = {2: SimpleNamespace(pid=2, parent=lambda: procs[3]), 3: SimpleNamespace(pid=3, parent=lambda: procs[1]),
                 1: SimpleNamespace(pid=1, parent=lambda: None),
                 8: SimpleNamespace(pid=8, parent=lambda: procs[9]), 9: SimpleNamespace(pid=9, parent=lambda: None)}
        pids = {"whatsapp": 1, "view": 2, "other view": 8}
        with mock.patch.object(m.win, "window_exe", lambda h: "C:\\x\\msedgewebview2.exe"), \
                mock.patch.object(m.win, "_pid", lambda h: pids[h]), \
                mock.patch("psutil.Process", lambda pid: procs[pid]):
            self.assertTrue(m._hosted_by("view", "whatsapp"))
            self.assertFalse(m._hosted_by("other view", "whatsapp"))


class Asking(unittest.TestCase):
    """The yes is to the chat that's open: she names it when it isn't the name you used."""

    def ask(self, to):
        from tests.support import siri
        ready = {"app": "whatsapp", "say": "WhatsApp", "contact": "mum", "text": "Hi", "checked": True, "to": to}
        with mock.patch.object(siri.messaging, "prepare", lambda app, contact, text: ready):
            return siri.stage_message("whatsapp", "mum", "Hi")["say"]

    def test_another_name_is_said(self):
        self.assertEqual(self.ask("Mother 💖"), "“Hi” to mum on WhatsApp. Send it? The chat open is "
                                                        "Mother.")

    def test_the_same_person_isnt(self):
        self.assertEqual(self.ask("Amma"), "“Hi” to mum on WhatsApp. Send it?")  # amma is mum


if __name__ == "__main__":
    unittest.main()
