"""WhatsApp's 2025 app (a web view): its message box is "Type a message to Amma", its link leaves the text out, and
it puts its web view in front once the box has the keyboard. She types the text herself, reads it back, says which
chat is open, and presses Enter only on exactly that, in that chat. Nothing here touches the real WhatsApp."""
import importlib.util
import time
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
                (m, "_compose_box", lambda app, hwnd: (self.box, "Amma \U0001f496") if self.box else (None, "")),
                (m, "window_of", lambda app: 99),  # open already, in the tray or not
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

    def stays_on(self, chat, number, before=None):
        """WhatsApp shows chat's box, before the link and after it (or before, then chat), its contact panel
        number: (what prepare raised or "", what was typed, the panels read), on a clock the waits move on."""
        shown, panels, clock = [before or chat], [], [0.0]
        self.box.value, self.typed[:] = "", []
        with mock.patch.object(self.m.time, "time", lambda: clock[0]), \
                mock.patch.object(self.m.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s)), \
                mock.patch.object(self.m, "compose_box", lambda app, hwnd: (self.box, shown[0])), \
                mock.patch.object(self.m, "read_follows", lambda: {}), \
                mock.patch.object(self.m, "window_of", lambda app: 99), \
                mock.patch.object(self.m, "open_chat", lambda app, handle, text: shown.__setitem__(0, chat) or 99), \
                mock.patch.object(self.m, "find_contact", lambda contact, app: ("Mum", "919999999999")), \
                mock.patch.object(self.m, "_uia", lambda: SimpleNamespace(ElementFromHandle=lambda h: None)), \
                mock.patch.object(self.m, "_panel_person", lambda *a: panels.append(chat) or ("", number), create=True):
            try:
                self.m.prepare("whatsapp", "mum", "I love you")
                return "", self.typed, panels
            except RuntimeError as exc:
                return str(exc), self.typed, panels

    def test_a_link_that_didnt_switch_chats_types_nothing(self):
        """Mum's number isn't on WhatsApp (a digit misheard when it was saved): its link stays on Ravi's chat, and
        she typed into Ravi's box, asked, sent it to Ravi on a yes, said "Sent to Mum." and took Ravi's replies for
        Mum's."""
        said, typed, panels = self.stays_on("Ravi", "+91 98765 43210")
        self.assertIn("Ravi's chat open, not Mum's", said)
        self.assertEqual((typed, panels), ([], ["Ravi"]))  # its number checked, nothing typed

    def test_mums_chat_already_open_or_opened_is_still_hers(self):
        self.assertEqual(self.stays_on("Amma", "+91 99999 99999"), ("", ["I love you"], ["Amma"]))  # by its number
        self.assertEqual(self.stays_on("Amma", "", before="Ravi"), ("", ["I love you"], []))  # the link switched
        self.assertEqual(self.stays_on("Mum \U0001f496", ""), ("", ["I love you"], []))  # her name, no look needed
        self.assertIn("not Mum's", self.stays_on("Mumbai Office", "")[0])  # a name that starts the same isn't hers

    def test_a_no_clears_only_what_she_typed_where_she_typed_it(self):
        """"Message Mum: hi" waited for its yes while you opened Ravi's chat and started a draft: a no pressed Ctrl+A
        and Backspace in whatever had the keyboard, wiping your draft, and left "hi" in Mum's box."""
        ready = self.m.prepare("whatsapp", "amma", "Hi")
        self.box.value = "my long draft to Ravi"
        with mock.patch.object(self.m, "compose_box", lambda app, hwnd: (self.box, "Ravi")):
            self.assertFalse(self.m.discard(ready))
        self.box.value = "Hi, and more"  # you went on typing in her box
        self.assertFalse(self.m.discard(ready))
        self.assertEqual(self.pressed, [])
        self.box.value, self.box.CurrentHasKeyboardFocus = "Hi", False  # as she left it: cleared
        self.assertTrue(self.m.discard(ready))
        self.assertEqual((self.box.value, self.pressed), ("", [("ctrl", "a"), ("backspace",)]))

    def test_a_send_she_couldnt_read_back_is_never_called_sent(self):
        """8 October: after Enter the message box couldn't be read ("NULL COM pointer access"), and she said "Sent, as
        far as I can tell" for a "Hi" that hadn't come; asked again and again, it went four times."""
        ready = self.m.prepare("whatsapp", "amma", "Hi")

        def unreadable(app, hwnd):  # fine until Enter, then never again
            if ("enter",) in self.pressed:
                raise ValueError("NULL COM pointer access")
            return self.box, "Amma \U0001f496"
        with mock.patch.object(self.m, "compose_box", unreadable), mock.patch.object(self.m, "_compose_box", unreadable):
            ok, said = self.m.send(ready)
        self.assertFalse(ok)
        self.assertNotIn("Sent", said)
        self.assertIn("Look at the chat before asking me again", said)

    def test_a_null_com_pointer_now_and_then_is_read_again(self):
        flaky, self.box.value = [ValueError("NULL COM pointer access")], "Hi"

        def read(app, hwnd):
            if flaky:
                raise flaky.pop()
            return self.box, "Amma \U0001f496"
        with mock.patch.object(self.m, "compose_box", read), mock.patch.object(self.m, "_compose_box", read):
            self.assertEqual(self.m.typed_text("whatsapp", 99), "Hi")

    def test_from_closed_its_page_is_waited_for_before_the_chat(self):
        """"Close WhatsApp" quits the 2025 app, whose page takes up to 25 s to draw: the chat was looked for 4 s, and a
        number that was fine got "WhatsApp didn't open the chat with amma", so you had to ask again. Quit while narrow,
        it comes back with only the chat drawn and no search box: that chat is ready, not "still starting"."""
        for page_at, box_at in ((10.0, 11.0), (None, 10.0), (None, None)):
            with self.subTest(page_at=page_at, box_at=box_at):
                self.typed.clear()
                self.box.value = ""
                clock = [0.0]

                def chat(app, hwnd):  # the chat the link asked for, once the page is there
                    return (self.box, "Amma") if box_at is not None and clock[0] >= box_at else (None, "")
                with mock.patch.object(self.m, "time", SimpleNamespace(time=lambda: clock[0], sleep=lambda s: clock.
                                                                       __setitem__(0, clock[0] + s))), \
                        mock.patch.object(self.m, "window_of", lambda app: None), \
                        mock.patch.object(self.m, "_uia", lambda: SimpleNamespace(ElementFromHandle=lambda h: None)), \
                        mock.patch.object(self.m, "_search_box", lambda uia, root: "search" if page_at is not None
                                          and clock[0] >= page_at else None), \
                        mock.patch.object(self.m, "compose_box", chat), mock.patch.object(self.m, "_compose_box", chat):
                    if box_at is not None:
                        self.assertTrue(self.m.prepare("whatsapp", "amma", "Hi")["checked"])
                        self.assertEqual(self.typed, ["Hi"])
                    else:  # still drawing after all that time: said so, never blamed on the chat
                        with self.assertRaises(RuntimeError) as err:
                            self.m.prepare("whatsapp", "amma", "Hi")
                        self.assertIn("WhatsApp is still starting", str(err.exception))
                        self.assertEqual((self.typed, self.pressed), ([], []))

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
                (m.m, "window_of", lambda app: 99),
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

    def test_a_no_or_running_out_takes_out_only_these_files_in_their_chat(self):
        """'Send report.pdf to Amma' ran out while you attached holiday.jpg to Ravi: every Remove attachment in the
        window was clicked, and your photo to Ravi went with it."""
        ready = self.m.prepare_files("whatsapp", "amma", self.paths[:1])
        self.assertEqual(ready["to"], "Amma")
        self.waiting[:] = ["C:/x/holiday.jpg"]  # Ravi's chat now, your own photo waiting
        with mock.patch.object(self.m, "compose_box", lambda app, hwnd: (None, "Ravi")):
            self.assertFalse(self.m.discard(ready))
        self.assertFalse(self.m.discard(ready))  # Amma's chat, but not what she put there
        self.assertEqual(self.waiting, ["C:/x/holiday.jpg"])
        self.waiting[:] = self.paths[:1]
        with mock.patch.object(self.m, "compose_box", lambda app, hwnd: (None, "Ravi")):
            self.assertFalse(self.m.discard(ready))
        self.assertEqual(self.waiting, self.paths[:1])
        self.waiting.clear()
        self.assertTrue(self.m.discard(ready))  # nothing waiting: nothing to take out

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

    def test_they_go_only_into_their_chat(self):
        """The link left Ravi's chat open, Amma's number not being on WhatsApp: the files went into his preview."""
        clock = [0.0]
        with mock.patch.object(self.m, "compose_box", lambda app, hwnd: (Box(), "Ravi")), \
                mock.patch.object(self.m, "_number_open", lambda hwnd: "919876543210", create=True), \
                mock.patch.object(self.m.time, "time", lambda: clock[0]), \
                mock.patch.object(self.m.time, "sleep", lambda s: clock.__setitem__(0, clock[0] + s)):
            with self.assertRaises(RuntimeError) as err:
                self.m.prepare_files("whatsapp", "amma", self.paths[:1])
        self.assertIn("Ravi's chat open", str(err.exception))
        self.assertEqual((self.waiting, self.copies), ([], 0))

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


BUNTY = {"name": "Buntyyy \U0001f43c", "number": "919573309199", "shown": "+91 95733 09199"}
OTHER = {"name": "Buntyyy \U0001f43c", "number": "918888802607", "shown": "+91 88888 02607"}


class FindingThem(unittest.TestCase):
    """Asked on 8 October: someone she doesn't know is looked up in your WhatsApp and asked about with their number,
    rather than "What's their number?". Nobody is saved, and nothing staged, without a yes to that."""

    def setUp(self):
        from tests.support import siri
        self.siri, self.staged, self.found = siri, [], [BUNTY]
        m = siri.messaging

        def known(contact):
            if not m.read_contacts().get(m.alias_key(contact), {}).get("whatsapp"):
                raise m.NeedContact(f"I don't know {contact} on WhatsApp yet. What's their phone number, with the "
                                    f"country code?")

        def prepare(app, contact, text):
            known(contact)
            self.staged.append((contact, text))
            return {"app": app, "contact": contact, "text": text, "checked": True, "say": "WhatsApp",
                    "to": "Buntyyy \U0001f43c"}

        def prepare_files(app, contact, paths, caption=""):
            known(contact)
            self.staged.append((contact, paths))
            return {"app": app, "contact": contact, "text": caption, "files": paths, "say": "WhatsApp", "to": ""}

        def people(name, **kw):
            if isinstance(self.found, Exception):
                raise self.found
            return list(self.found)
        for target, name, value in ((m, "prepare", prepare), (m, "prepare_files", prepare_files),
                                    (m, "whatsapp_people", people), (siri, "say", lambda line, notify: None)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: (siri.FOUND.update(alias="", text="", files=None, people=[], until=0.0),
                                 siri.ASKED.update(alias="", app="", text="", until=0.0, files=None),
                                 siri.STAGED.update(ready=None, until=0.0),
                                 m._write_json(m.CONTACTS_PATH, {}, emptying=True)))

    def ask(self):
        self.plan = self.siri.stage_message("whatsapp", "buntyy", "hi")
        return self.plan

    def step(self):
        """The step her last question's yes or no is to."""
        return self.plan["confirm"]["steps"][0]

    def yes(self):
        self.plan = self.siri.use_found(self.step())
        return self.plan

    def no(self):
        self.plan = self.siri.not_them(self.step())
        return self.plan

    def test_she_asks_with_their_number_before_saving_anything(self):
        plan = self.ask()
        self.assertEqual(plan["say"], "I found Buntyyy in your WhatsApp, number plus 9 1, 9 5 7 3 3, 0 9 1 9 9. "
                                      "Is that them?")
        self.assertEqual(self.step()["do"], "contact_found")
        self.assertEqual((self.siri.messaging.read_contacts(), self.staged), ({}, []))

    def test_yes_saves_them_and_the_message_is_asked_about_as_ever(self):
        self.ask()
        asked = self.step()
        plan = self.yes()
        self.assertEqual(self.siri.messaging.read_contacts()["buntyy"]["whatsapp"], "919573309199")
        self.assertEqual(self.staged, [("buntyy", "hi")])
        self.assertEqual(plan["say"], "\u201chi\u201d to buntyy on WhatsApp. Send it? The chat open is Buntyyy.")
        self.assertEqual(plan["confirm"]["steps"], [{"do": "message_send"}])
        self.assertEqual(self.siri.use_found(asked)["say"], "That was a while ago now. Ask me again.")  # one yes, one save

    def test_no_asks_about_the_next_then_for_the_number(self):
        self.found = [BUNTY, OTHER]
        self.assertTrue(self.ask()["say"].startswith("I found 2 who could be them in your WhatsApp. The first is "
                                                     "Buntyyy, number plus 9 1, 9 5 7 3 3"))
        plan = self.no()
        self.assertEqual(plan["say"], "Then is it Buntyyy, number plus 9 1, 8 8 8 8 8, 0 2 6 0 7?")
        self.assertEqual(self.step()["do"], "contact_found")
        self.assertEqual(self.no()["say"], "Okay. What's their phone number, with the country code?")
        self.assertEqual((self.siri.messaging.read_contacts(), self.staged), ({}, []))
        self.siri.finish_asked("+91 98765 43210")  # and the number you give her is saved, as before
        self.assertEqual(self.siri.messaging.read_contacts()["buntyy"]["whatsapp"], "919876543210")
        self.assertEqual(self.staged, [("buntyy", "hi")])

    def test_the_second_one_yes(self):
        self.found = [BUNTY, OTHER]
        self.ask()
        self.no()
        self.yes()
        self.assertEqual(self.siri.messaging.read_contacts()["buntyy"]["whatsapp"], "918888802607")

    def test_the_first_one_said_to_the_second_question_is_no_yes(self):
        """Review: "the first one" to "Then is it Buntyyy, number ...2607?" saved the 2607 one."""
        self.found = [BUNTY, OTHER]
        self.ask()
        self.no()
        for words in ("The first one", "Oh, the first one", "The first number", "Same one"):
            self.assertFalse(self.siri.said_yes(words, self.plan["confirm"]), words)

    def test_a_yes_to_an_older_question_saves_nobody(self):
        """Review: one lookup's yes, from the phone say, saved who a later lookup found."""
        self.ask()
        old = self.step()
        self.found = [OTHER]
        self.ask()  # another lookup since
        self.assertEqual(self.siri.use_found(old)["say"], "That was a while ago now. Ask me again.")
        self.assertEqual(self.siri.not_them(old)["say"] in self.siri.REPLIES["confirm_no"], True)
        self.assertEqual(self.siri.messaging.read_contacts(), {})

    def test_a_step_without_its_question_saves_nobody(self):
        self.ask()
        self.siri.use_found({"do": "contact_found"})  # as a model might write it
        self.assertEqual(self.siri.messaging.read_contacts(), {})

    def test_the_number_isnt_kept_in_history(self):
        plan = self.ask()
        self.assertEqual(plan["keep"], "I found Buntyyy in your WhatsApp. Is that them?")

    def test_nobody_by_that_name_asks_for_the_number(self):
        self.found = []
        self.assertEqual(self.ask()["say"], "I couldn't find buntyy in your WhatsApp. What's their phone number, "
                                            "with the country code?")
        self.assertEqual(self.siri.ASKED["alias"], "buntyy")

    def test_an_older_question_for_a_number_is_dropped(self):
        """Review: a number said in reply to "Is that them?" was saved under whoever was asked about before."""
        self.siri.ASKED.update(alias="ravi", app="whatsapp", text="hello", until=time.time() + 60)
        self.ask()
        self.assertEqual(self.siri.ASKED["alias"], "")
        self.assertIsNone(self.siri.finish_asked("+91 98765 43210"))
        self.assertEqual(self.siri.messaging.read_contacts(), {})

    def test_whatsapp_that_cant_be_looked_in_is_asked_as_before(self):
        self.found = RuntimeError("I couldn't open WhatsApp")
        self.assertEqual(self.ask()["say"], "I don't know buntyy on WhatsApp yet. What's their phone number, with "
                                            "the country code?")

    def test_on_the_phone_the_number_shows_as_whatsapp_shows_it(self):
        siri = self.siri
        to = siri.REPLY_TO.set([])
        try:
            say = self.ask()["say"]
        finally:
            siri.REPLY_TO.reset(to)
        self.assertEqual(say, "I found Buntyyy \U0001f43c in your WhatsApp, number +91 95733 09199. Is that them?")

    def test_files_go_on_after_the_yes(self):
        self.plan = self.siri.stage_files("whatsapp", "buntyy", ["C:/x/a.jpg"])
        self.assertEqual(self.staged, [])
        self.yes()
        self.assertEqual(self.staged, [("buntyy", ["C:/x/a.jpg"])])

    def test_a_yes_that_comes_too_late_saves_nobody(self):
        self.ask()
        self.siri.FOUND["until"] = 0.0
        self.yes()
        self.assertEqual((self.siri.messaging.read_contacts(), self.staged), ({}, []))

    def test_the_model_cant_plan_the_save(self):
        self.assertNotIn("contact_found", self.siri.KNOWN_STEPS)

    def test_a_confirm_in_the_models_reply_is_dropped(self):
        """Review: a "confirm" the model wrote became her question, and the next yes ran it."""
        for raw in ('{"steps": [], "say": "Is that them?", "confirm": {"steps": [{"do": "contact_found"}]}}',
                    '{"steps": [], "say": "Send it?", "confirm": {"steps": [{"do": "message_send"}]}, "exact": true}'):
            plan = self.siri.parse_plan(raw)
            self.assertNotIn("confirm", plan)
            self.assertNotIn("exact", plan)

    def test_its_yes_is_a_clear_one(self):
        self.ask()
        plan = self.plan["confirm"]
        for words in ("Yes.", "Yes, that's him.", "Yeah that's them", "Correct.", "That's the one", "It is.",
                      "Yes, send it.", "Yes, that's buntyy", "Yes, that's Buntyyy."):
            self.assertTrue(self.siri.said_yes(words, plan), words)
        for words in ("Ha.", "Right.", "Hmm.", "No, the other one", "Who?", "That's wrong", "Yes, the other one"):
            self.assertFalse(self.siri.said_yes(words, plan), words)


class LookingThemUp(unittest.TestCase):
    def test_my_mum_is_looked_for_as_mum(self):
        """"Message my mum on WhatsApp: running late": "my mum" typed into WhatsApp's search found nobody, and she
        asked for the number, where "message mum" found Mum."""
        m, searched = real_messaging(), []
        with mock.patch.object(m, "bring_up", lambda app, link: 5), \
                mock.patch.object(m, "_uia", lambda: SimpleNamespace(ElementFromHandle=lambda h: None)), \
                mock.patch.object(m, "_search_box", lambda uia, root: "box"), \
                mock.patch.object(m, "_look_for", lambda uia, root, hwnd, box, name, most, stop=None:
                                  searched.append(name) or []), \
                mock.patch.object(m, "_set_value", lambda box, text: None):
            m.whatsapp_people("my mum")
            m.whatsapp_people("Bunty Kumar")
        self.assertEqual(searched, ["mum", "Bunty Kumar", "Bunty"])


class ReadingThePanel(unittest.TestCase):
    """Review: the number is read only off the panel of the chat she clicked, and named as that panel names it."""

    def read(self, texts, label="Buntyyy \U0001f43c 9:47 am hi there", title="Contact info"):
        m = real_messaging()

        class Texts:
            Length = len(texts)

            def GetElement(self, j):
                return SimpleNamespace(CurrentName=texts[j])

        panel = SimpleNamespace(FindAll=lambda *a: Texts(), FindFirst=lambda *a: None)
        uia = SimpleNamespace(CreatePropertyCondition=lambda *a: None, CreateAndCondition=lambda *a: None)
        for name, value in (("_rows", lambda uia, root: [(label, object())]), ("_open_row", lambda *a: True),
                            ("_find_button", lambda *a: object()), ("_click", lambda b: None),
                            ("_panel", lambda *a: (panel, title))):
            p = mock.patch.object(m, name, value)
            p.start()
            self.addCleanup(p.stop)
        return m._read_person(uia, None, 1, 0, label)

    def test_a_saved_contacts_panel(self):
        self.assertEqual(self.read(["Contact info", "Buntyyy", "+91 95733 09199", "About", "Call me +91 11111 11111"]),
                         {"name": "Buntyyy", "number": "919573309199", "shown": "+91 95733 09199"})

    def test_another_chats_panel_is_never_read_as_theirs(self):
        self.assertIsNone(self.read(["Contact info", "Amma", "+91 98765 43210"]))
        self.assertIsNone(self.read(["Contact info", "+91 98765 43210", "~Ramesh"]))  # a number not saved
        self.assertIsNone(self.read(["Contact info", "\u2764\ufe0f", "+91 98765 43210"]))  # a name that's only emoji

    def test_a_number_not_saved_is_named_by_its_number(self):
        self.assertEqual(self.read(["Contact info", "+91 98765 43210", "~Ramesh"], label="+91 98765 43210 Yesterday hi"),
                         {"name": "+91 98765 43210", "number": "919876543210", "shown": "+91 98765 43210"})

    def test_a_group_or_a_panel_without_a_number(self):
        self.assertIsNone(self.read(["Group info", "Buntyyy", "+91 95733 09199"], title="Group info"))
        self.assertIsNone(self.read(["Contact info", "Buntyyy", "About", "Call me +91 95733 09199"]))


class WhatsAppNumbers(unittest.TestCase):
    """Reading the contact panel: the number on a line of its own, as WhatsApp shows it."""

    def test_the_panels_number(self):
        m = real_messaging()
        shown = "\u202a+91 95733 09199\u202c"  # wrapped in direction marks
        cleaned = " ".join(m.MARKS.sub("", shown).split())
        self.assertTrue(m.SHOWN_NUMBER.fullmatch(cleaned))
        self.assertEqual(m.clean_number(cleaned), "919573309199")
        self.assertIsNone(m.SHOWN_NUMBER.fullmatch("Call me on +91 95733 09199"))  # their About isn't their number

    def test_names_compare_without_emoji(self):
        m = real_messaging()
        self.assertTrue(m._letters("Buntyyy \U0001f43c 9:47 am Photo").startswith(m._letters("Buntyyy\U0001f43c")))


if __name__ == "__main__":
    unittest.main()
