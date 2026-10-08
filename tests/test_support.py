"""The harness itself: the app data is a temp folder and nothing can act on the PC or go online."""
import glob
import json
import os
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

from tests.support import DATA, REAL, ROOT, TRIPPED, siri, winplatform

import backup
import decider
import dictation
import history
import messaging
import settings
import tasks
import telegram_bot
import voiceid


def real_folders():
    """Her real data folders, as they were before tests/support.py moved %APPDATA% and %LOCALAPPDATA%."""
    home = os.path.expanduser("~")
    bases = REAL.split(os.pathsep) + [os.path.join(home, "AppData", "Roaming"), os.path.join(home, "AppData", "Local"),
                                      home]
    return [os.path.normcase(os.path.abspath(os.path.join(b, "Hey Jev"))) for b in bases if b]


class Isolation(unittest.TestCase):
    def test_app_data_is_a_temp_folder(self):
        self.assertTrue(winplatform.APPDATA_DIR.startswith(DATA))
        self.assertNotIn(os.path.join("AppData", "Roaming", "Hey Jev"), siri.history.DB)

    def test_pc_actions_are_tripwires(self):
        before = len(TRIPPED)
        with self.assertRaisesRegex(RuntimeError, "tripwire"):
            siri.win.open_app("Notepad")
        with self.assertRaisesRegex(RuntimeError, "tripwire"):
            siri.speak("hello")
        self.assertEqual(len(TRIPPED), before + 2)

    def test_quick_runs_without_acting(self):
        plan = siri.quick("open notepad")
        self.assertEqual(plan["steps"][0]["do"], "open")


class RealData(unittest.TestCase):
    """8 Oct: `python -m unittest` from the repo root loaded the hand checks (test_listen.py and co.), which imported
    siri before this harness moved %APPDATA%: 982 test turns went into her real history, 1,488 runs into the task log,
    88 dictations, and an empty contacts book over three real people."""

    def test_no_data_path_is_in_her_real_folders(self):
        paths = [winplatform.APPDATA_DIR, winplatform.LOG_DIR, history.DB, history.DAYS_DIR, settings.PATH,
                 tasks.DB_PATH, messaging.CONTACTS_PATH, messaging.RECIPES_PATH, messaging.FOLLOW_PATH, siri.NOTES_DIR,
                 siri.SOUL_PATH, siri.UNDO_PATH, dictation.HISTORY, voiceid.folder(), decider.folder(),
                 backup.appdata(), backup.localdata(), telegram_bot.files_dir()]
        for module in list(sys.modules.values()):  # and any other path a project module worked out when imported
            if os.path.dirname(getattr(module, "__file__", "") or "") == ROOT:
                paths += [v for v in vars(module).values() if isinstance(v, str) and "Hey Jev" in v and os.sep in v]
        for path in paths:
            target = os.path.normcase(os.path.abspath(path))
            for real in real_folders():
                self.assertFalse(target == real or target.startswith(real + os.sep), path)

    def test_her_real_folders_are_refused_in_a_test_run(self):
        for real in real_folders():
            with self.assertRaisesRegex(RuntimeError, "real data"):
                winplatform.own_data(os.path.join(real, "history.db"))
        here = os.path.join(DATA, "Hey Jev", "history.db")
        self.assertEqual(winplatform.own_data(here), here)

    def test_a_runner_started_without_the_harness_cant_write_to_her_data(self):
        """The 8 Oct run again, in a folder standing in for %APPDATA%: unittest imports a module that imports history
        before anything moved %APPDATA%. Nothing may be made there, and the run must fail."""
        real = tempfile.mkdtemp(prefix="heyjev-real-")
        with open(os.path.join(real, "test_reach.py"), "w", encoding="utf-8") as f:
            f.write("import history  # noqa\n")
        driver = textwrap.dedent(f"""
            import runpy, sys
            sys.path[:0] = [{real!r}, {ROOT!r}]
            from tests import winfakes
            winfakes.install()  # Windows' own modules, off Windows: does nothing on Windows
            sys.argv = ["python -m unittest", "test_reach"]
            runpy.run_module("unittest", run_name="__main__", alter_sys=True)
        """)
        env = {k: v for k, v in os.environ.items() if k != "HEYJEV_TESTING"}
        env.update(APPDATA=real, LOCALAPPDATA=real)
        run = subprocess.run([sys.executable, "-c", driver], cwd=real, env=env, capture_output=True, text=True,
                             timeout=120)
        self.assertNotEqual(run.returncode, 0, run.stderr[-2000:])
        self.assertIn("real data", run.stderr)
        self.assertFalse(os.path.exists(os.path.join(real, "Hey Jev")), os.listdir(real))

    def test_no_hand_check_is_left_where_discovery_finds_it(self):
        """The hand checks are in checks\\ now, which isn't a package: unittest discovery doesn't load them."""
        self.assertEqual(glob.glob(os.path.join(ROOT, "test*.py")), [])
        self.assertFalse(os.path.exists(os.path.join(ROOT, "checks", "__init__.py")))
        for name in ("listen.py", "open_mic.py", "voice_id.py"):
            self.assertTrue(os.path.isfile(os.path.join(ROOT, "checks", name)), name)


class ContactsBook(unittest.TestCase):
    """8 Oct 19:03: a test's clean-up wrote {} over the real contacts.json, and the three people learned that day were
    gone for good. The backup that night had none either."""

    def setUp(self):
        messaging._write_json(messaging.CONTACTS_PATH, {"bunty": {"name": "Bunty", "whatsapp": "15550100"}})
        self.addCleanup(messaging._write_json, messaging.CONTACTS_PATH, {}, emptying=True)

    def test_an_empty_book_never_replaces_one_with_people_in_it(self):
        with self.assertRaises(ValueError):
            messaging._write_json(messaging.CONTACTS_PATH, {})
        self.assertEqual(list(messaging.read_contacts()), ["bunty"])

    def test_forgetting_the_last_person_still_works(self):
        self.assertTrue(messaging.forget_contact("Bunty"))
        self.assertEqual(messaging.read_contacts(), {})

    def test_a_failed_save_leaves_the_book_as_it_was_and_no_stray_file(self):
        with mock.patch.object(messaging.json, "dump", side_effect=OSError("disk full")), self.assertRaises(OSError):
            messaging.save_contact("Ravi", "whatsapp", "15550101")
        self.assertEqual(list(messaging.read_contacts()), ["bunty"])
        folder = os.path.dirname(messaging.CONTACTS_PATH)
        self.assertEqual([f for f in os.listdir(folder) if f.startswith("contacts.json.")], [])
        with open(messaging.CONTACTS_PATH, encoding="utf-8") as f:
            self.assertIn("bunty", json.load(f))


if __name__ == "__main__":
    unittest.main()
