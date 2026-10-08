"""shortcuts.py: Windows' and the main apps' keyboard shortcuts, pressed straight away for words that ask for one, the
one for the app in front, and the Windows key only ever for one of these."""
import unittest
from unittest import mock

from tests.support import siri

import shortcuts

CHROME, WORD, CODE, EXPLORER = r"C:\x\chrome.exe", r"C:\x\WINWORD.EXE", r"C:\x\Code.exe", r"C:\Windows\explorer.exe"


def keys(said, exe=CHROME, youtube=False):
    found = shortcuts.find(said, shortcuts.scopes(exe, youtube))
    return found and found.keys


class Table(unittest.TestCase):
    def test_every_row_compiles_and_is_one_of_a_kind(self):
        self.assertEqual(len(shortcuts.BY_ID), len(shortcuts.ALL))
        for s in shortcuts.ALL:
            self.assertIn(s.kind, ("safe", "edit"), s)
            self.assertIn(s.scope, ("youtube", "browser", "explorer", "word", "vscode", "notepad", "text", "windows"), s)

    def test_nothing_that_runs_deletes_or_signs_out(self):
        banned = {"win+r", "shift+delete", "ctrl+alt+delete", "win+x", "win+l", "alt+f4", "win+ctrl+shift+win"}
        self.assertFalse({s.keys for s in shortcuts.ALL} & banned)

    def test_the_windows_key_alone_is_only_for_the_start_menu(self):
        self.assertEqual([s.said for s in shortcuts.ALL if s.keys == "win"], [["(open | show) ~ start [menu]",
                                                                              "start menu"]])


class Saying(unittest.TestCase):
    def test_windows_ones_anywhere(self):
        for said, want in (("show the desktop", "win+d"), ("minimize everything", "win+d"),
                           ("open clipboard history", "win+v"), ("snap this window to the left", "win+left"),
                           ("take a screenshot of part of the screen", "win+shift+s"), ("open emoji panel", "win+."),
                           ("new virtual desktop", "win+ctrl+d"), ("go to the next desktop", "win+ctrl+right"),
                           ("open quick settings", "win+a"), ("show notifications", "win+n"),
                           ("open task view", "win+tab"), ("open task manager", "ctrl+shift+esc"),
                           ("move this window to the other monitor", "win+shift+left"),
                           ("turn on the narrator", "win+ctrl+enter"), ("open the start menu", "win")):
            for exe in (CHROME, WORD, EXPLORER):
                self.assertEqual(keys(said, exe), want, (said, exe))

    def test_the_app_in_front_decides(self):
        self.assertEqual(keys("new tab", CHROME), "ctrl+t")
        self.assertEqual(keys("new tab", EXPLORER), "ctrl+t")
        self.assertIsNone(keys("new tab", WORD))
        self.assertEqual(keys("zoom in", CHROME), "ctrl+=")
        self.assertEqual(keys("full screen", CHROME), "f11")
        self.assertEqual(keys("full screen", CHROME, youtube=True), "f")  # YouTube's own, in the browser
        self.assertEqual(keys("turn on captions", CHROME, youtube=True), "c")
        self.assertIsNone(keys("turn on captions", WORD))  # said for another app: the model works it out
        self.assertEqual(keys("center the text", WORD), "ctrl+e")
        self.assertEqual(keys("open the command palette", CODE), "ctrl+shift+p")
        self.assertEqual(keys("rename this file", EXPLORER), "f2")
        self.assertEqual(keys("go up a level", EXPLORER), "alt+up")

    def test_text_shortcuts_in_any_app(self):
        for said, want in (("undo", "ctrl+z"), ("paste it here", "ctrl+v"), ("select all", "ctrl+a"),
                           ("make this bold", "ctrl+b")):
            self.assertEqual(keys(said, WORD), want, said)
        self.assertEqual(keys("paste as plain text", CHROME), "ctrl+shift+v")
        self.assertEqual(keys("paste as plain text", WORD), "ctrl+shift+v")  # Microsoft 365 Word's too, since 2023

    def test_more_from_the_research(self):
        for said, exe, yt, want in (("snap this window to the top", WORD, False, "win+alt+up"),
                                    ("open the third taskbar app", WORD, False, "win+3"),
                                    ("go to the fifth tab", CHROME, False, "ctrl+5"),
                                    ("jump to 50 percent", CHROME, True, "5"), ("next chapter", CHROME, True, "ctrl+right"),
                                    ("make this a heading 2", WORD, False, "ctrl+alt+2"),
                                    ("go to definition", CODE, False, "f12"), ("show as list", EXPLORER, False, "ctrl+shift+5"),
                                    ("details view", EXPLORER, False, "ctrl+shift+6"),
                                    ("turn on live captions", WORD, False, "win+ctrl+l"),
                                    ("select the next word", WORD, False, "ctrl+shift+right")):
            self.assertEqual(keys(said, exe, yt), want, said)

    def test_only_the_whole_phrase(self):
        for said in ("show the desktop to my friend", "can you tell me how to undo", "what is the start menu"):
            self.assertIsNone(keys(said), said)


class Pressing(unittest.TestCase):
    def setUp(self):
        self.pressed = []
        for target, name, value in ((siri.win, "press", lambda *k: self.pressed.append(k)),
                                    (siri.win, "foreground_exe", lambda: CHROME)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    def test_a_vetted_one_presses_the_windows_key(self):
        siri.do_step({"do": "shortcut", "id": "windows:win+shift+s"})
        self.assertEqual(self.pressed, [("cmd", "shift", "s")])

    def test_a_model_never_does(self):
        with self.assertRaises(RuntimeError):
            siri.do_step({"do": "keys", "keys": "win+r"})
        with self.assertRaises(RuntimeError):
            siri.do_step({"do": "shortcut", "id": "windows:win+r"})  # not one of them, whatever it's called
        self.assertEqual(self.pressed, [])

    def test_plans_from_words(self):
        with mock.patch.object(siri, "focused_on", lambda app: False):
            plan = siri.shortcut_plan("Can you show the desktop please")
            self.assertEqual(plan["steps"], [{"do": "shortcut", "id": "windows:win+d"}])
            self.assertIsNone(siri.shortcut_plan("back", gate="cold"))  # a TV's "back"
            self.assertIsNone(siri.shortcut_plan("paste it here", gate="cold"))  # changes things: the model decides
            self.assertIsNotNone(siri.shortcut_plan("show the desktop", gate="cold"))


if __name__ == "__main__":
    unittest.main()
