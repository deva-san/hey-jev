"""The harness itself: the app data is a temp folder and nothing can act on the PC or go online."""
import os
import unittest

from tests.support import DATA, TRIPPED, siri, winplatform


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


if __name__ == "__main__":
    unittest.main()
