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


class Files(unittest.TestCase):
    """A file or photo, pasted into the chat as WhatsApp's preview, read back from it, sent with its own Send button
    after a yes, discarded after a no. WhatsApp and the clipboard are faked."""

    def setUp(self):
        import tempfile
        self.m, folder = real_messaging(), tempfile.mkdtemp()
        self.paths = []
        for name in ("photo.jpg", "report.pdf"):
            self.paths.append(os.path.join(folder, name))
            with open(self.paths[-1], "wb") as f:
                f.write(b"x")
        self.waiting, self.sent, self.clipboard, self.copies = [], [], ["what you copied"], 0
        box = Box(value="")
        m = self

        def press(*keys):
            if keys == ("ctrl", "v") and m.clipboard[0] == "files":
                m.waiting += m.pasted  # added to whatever was waiting already, as WhatsApp does

        class Button:
            def __init__(self, name):
                self.CurrentName = name

        def button(hwnd, name, part=False):
            if name == "Remove attachment" and self.waiting:
                return Button(name)
            if name == f"Send {len(self.waiting)} selected" and self.waiting:
                return Button(name)
            return None

        def click(b):
            if b.CurrentName.startswith("Send"):
                self.sent += list(self.waiting)
                self.waiting.clear()
            elif b.CurrentName == "Remove attachment":
                self.waiting.pop()

        def set_files(paths):
            self.clipboard[0], self.pasted = "files", list(paths)
            self.copies += 1
        for target, name, value in (
                (m.m, "compose_box", lambda app, hwnd: (box, "Amma")), (m.m, "box_value", lambda b: ""),
                (m.m, "in_front", lambda app, hwnd: True), (m.m, "open_chat", lambda app, handle, text: 99),
                (m.m, "find_contact", lambda contact, app: ("amma", "919999999999")),
                (m.m, "offline_reason", lambda app, hwnd: None), (m.m, "typed_text", lambda app, hwnd: ""),
                (m.m, "_button", button), (m.m, "_click", click),
                (m.m, "waiting", lambda hwnd: (sorted(os.path.basename(p) for p in self.waiting), len(self.waiting))),
                (m.m.win, "press", press), (m.m.win, "type_text", lambda text: None),
                (m.m.win, "clipboard_snapshot", lambda: [(13, self.clipboard[0])]),
                (m.m.win, "clipboard_restore", lambda snap: self.clipboard.__setitem__(0, snap[0][1] if snap else None)),
                (m.m.win, "clipboard_sequence", lambda: self.copies),
                (m.m.win, "set_clipboard_files", set_files),
                (m.m.time, "sleep", lambda s: None), (m.m.user32, "IsWindow", lambda h: True)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_something_left_waiting_from_before_is_taken_out_first(self):
        self.waiting.append("C:/old/leftover.png")
        self.m.prepare_files("whatsapp", "amma", self.paths[:1])
        self.assertEqual(self.waiting, self.paths[:1])

    def test_they_wait_in_the_preview_until_the_yes(self):
        ready = self.m.prepare_files("whatsapp", "amma", self.paths)
        self.assertEqual(self.waiting, self.paths)
        self.assertEqual(self.sent, [])
        self.assertEqual(self.clipboard[0], "what you copied")  # put back
        ok, said = self.m.send(ready)
        self.assertEqual(self.sent, self.paths)
        self.assertEqual(said, "Sent 2 files to amma.")

    def test_a_no_discards_them(self):
        ready = self.m.prepare_files("whatsapp", "amma", self.paths[:1])
        self.assertTrue(self.m.discard(ready))
        self.assertEqual((self.waiting, self.sent), ([], []))

    def test_if_whatsapp_took_other_files_nothing_is_sent_and_none_are_left(self):
        with mock.patch.object(self.m.win, "set_clipboard_files",
                               lambda paths: (self.clipboard.__setitem__(0, "files"),
                                              setattr(self, "pasted", paths[:1]))):
            with self.assertRaises(RuntimeError):
                self.m.prepare_files("whatsapp", "amma", self.paths)
        self.assertEqual((self.sent, self.waiting), ([], []))

    def test_changed_before_the_yes_isnt_sent(self):
        ready = self.m.prepare_files("whatsapp", "amma", self.paths[:1])
        self.waiting.append("C:/x/another.jpg")
        with self.assertRaises(RuntimeError):
            self.m.send(ready)
        self.assertEqual(self.sent, [])

    def test_only_real_files_not_too_many_or_too_big(self):
        with self.assertRaises(RuntimeError):
            self.m.check_files([self.paths[0] + ".missing"])
        with self.assertRaises(RuntimeError):
            self.m.check_files(self.paths * 6)
        with mock.patch.object(self.m.os.path, "getsize", lambda p: 200 * 1024 * 1024):
            with self.assertRaises(RuntimeError):
                self.m.check_files(self.paths[:1])


class Sharing(unittest.TestCase):
    """"Send this to Amma": only the files you gave her, from your phone a moment ago or selected in File Explorer."""

    def setUp(self):
        from tests.support import siri
        self.siri, self.staged = siri, []
        p = mock.patch.object(siri, "stage_files", lambda app, who, paths, caption="": self.staged.append(
            (app, who, paths, caption)) or siri.make_plan(say="Send it?"))
        p.start()
        self.addCleanup(p.stop)
        self.addCleanup(siri.PHONE_FILES.clear)

    def on_phone(self, words, files=None):
        siri = self.siri
        if files is not None:
            siri.PHONE_FILES[7] = (files, __import__("time").time())
        to, chat = siri.REPLY_TO.set([]), siri.PHONE_CHAT.set(7)
        try:
            with mock.patch.object(siri.os.path, "isfile", lambda p: True):
                return siri.direct_share(words)
        finally:
            siri.REPLY_TO.reset(to)
            siri.PHONE_CHAT.reset(chat)

    def test_what_came_from_the_phone_goes(self):
        self.on_phone("send this to amma", ["C:/x/photo.jpg"])
        self.assertEqual(self.staged, [("whatsapp", "amma", ["C:/x/photo.jpg"], "")])
        self.on_phone("share these photos with Mum on WhatsApp saying happy birthday", ["a.jpg", "b.jpg"])
        self.assertEqual(self.staged[-1], ("whatsapp", "Mum", ["a.jpg", "b.jpg"], "happy birthday"))

    def test_nothing_given_nothing_sent_and_never_the_word_this(self):
        plan = self.on_phone("send this to amma")
        self.assertEqual(self.staged, [])
        self.assertIn("Send it to me here first", plan["say"])

    def test_at_the_pc_the_files_selected_in_file_explorer(self):
        with mock.patch.object(self.siri.win, "selected_files", lambda: ["C:/docs/cv.pdf"]):
            self.siri.direct_share("send the selected file to Ravi")
        self.assertEqual(self.staged, [("whatsapp", "Ravi", ["C:/docs/cv.pdf"], "")])

    def test_a_text_message_is_still_one(self):
        self.assertIsNone(self.siri.direct_share("send hi to amma on whatsapp"))


class Asking(unittest.TestCase):
    """The yes is to the chat that's open: she names it when it isn't the name you used."""

    def ask(self, to):
        from tests.support import siri
        ready = {"app": "whatsapp", "say": "WhatsApp", "contact": "mum", "text": "Hi", "checked": True, "to": to}
        siri.STAGED.update(ready=None, until=0.0)
        with mock.patch.object(siri.messaging, "prepare", lambda app, contact, text: ready):
            return siri.stage_message("whatsapp", "mum", "Hi")["say"]

    def test_another_name_is_said(self):
        self.assertEqual(self.ask("Mother 💖"), "“Hi” to mum on WhatsApp. Send it? The chat open is "
                                                        "Mother.")

    def test_the_same_name_isnt(self):
        self.assertEqual(self.ask("Mum"), "\u201cHi\u201d to mum on WhatsApp. Send it?")

    def test_another_word_for_her_is_said_too(self):  # "mama" is an uncle in Telugu: names are said as they are
        self.assertIn("The chat open is Amma.", self.ask("Amma"))


if __name__ == "__main__":
    unittest.main()
