"""backup.py: a backup puts everything back, a fresh start clears only her memory, skills and old chats."""
import json
import os
import sqlite3
import tempfile
import unittest
import zipfile
from unittest import mock

from tests.support import siri  # noqa: F401  (points %APPDATA% at a temp folder before backup is imported)
import backup
import settings


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


class Backup(unittest.TestCase):
    def setUp(self):
        root = tempfile.mkdtemp(prefix="heyjev-backup-")
        self.repo = os.path.join(root, "repo")
        env = mock.patch.dict(os.environ, {"APPDATA": os.path.join(root, "roaming"),
                                           "LOCALAPPDATA": os.path.join(root, "local")})
        env.start()
        self.addCleanup(env.stop)
        for patch in (mock.patch.object(backup, "HERE", self.repo), mock.patch.object(backup, "running", lambda: False)):
            patch.start()
            self.addCleanup(patch.stop)
        self.data = backup.appdata()
        write(os.path.join(self.data, "memories", "USER.md"), "Lives in Hyderabad.")
        write(os.path.join(self.data, "memories", "MEMORY.md"), "Chrome is the browser.")
        write(os.path.join(self.data, "memories", "days", "2026-10-07.md"), "# Tuesday")
        write(os.path.join(self.data, "skills", "work-mode", "SKILL.md"), "---\nname: work-mode\n---\n")
        write(os.path.join(self.data, "settings.json"), json.dumps({"name": "Hari", "met": True}))
        write(os.path.join(self.data, "contacts.json"), '{"mum": "+91"}')
        write(os.path.join(self.data, "SOUL.md"), "Calm and quick.")
        con = sqlite3.connect(os.path.join(self.data, "history.db"))
        with con:
            con.execute("CREATE TABLE turns (said TEXT)")
            con.execute("INSERT INTO turns VALUES ('open notepad')")
        con.close()
        write(os.path.join(self.repo, "vocabulary.json"), '["Zostel"]')
        write(os.path.join(self.repo, "apps.json"), '{"notepad": "notepad.exe"}')
        write(os.path.join(backup.localdata(), "voice", "owner.npy"), "voice")
        write(os.path.join(backup.localdata(), "Logs", "Hey Jev.log"), "log")

    def turns(self):
        con = sqlite3.connect(os.path.join(self.data, "history.db"))
        try:
            return [row[0] for row in con.execute("SELECT said FROM turns")]
        finally:
            con.close()

    def test_a_backup_holds_her_data_the_dictionary_apps_and_voice_but_not_logs(self):
        with zipfile.ZipFile(backup.backup()) as z:
            names = set(z.namelist())
        for name in ("appdata/memories/USER.md", "appdata/skills/work-mode/SKILL.md", "appdata/history.db",
                     "appdata/settings.json", "repo/vocabulary.json", "repo/apps.json", "local/voice/owner.npy",
                     "manifest.json"):
            self.assertIn(name, names)
        self.assertFalse([n for n in names if "Logs" in n])

    def test_restore_puts_everything_back_and_backs_up_what_was_there(self):
        saved = backup.backup()
        write(os.path.join(self.data, "memories", "USER.md"), "Changed.")
        write(os.path.join(self.data, "new.txt"), "made after the backup")
        write(os.path.join(self.repo, "vocabulary.json"), "[]")
        os.remove(os.path.join(self.data, "history.db"))
        before = backup.restore(saved)
        self.assertEqual(read(os.path.join(self.data, "memories", "USER.md")), "Lives in Hyderabad.")
        self.assertEqual(read(os.path.join(self.repo, "vocabulary.json")), '["Zostel"]')
        self.assertEqual(self.turns(), ["open notepad"])
        self.assertFalse(os.path.exists(os.path.join(self.data, "new.txt")))
        with zipfile.ZipFile(before) as z:  # the restore itself can be undone
            self.assertIn("appdata/new.txt", z.namelist())

    def test_fresh_clears_memory_skills_and_chats_and_keeps_the_rest(self):
        saved = backup.fresh()
        for gone in ("memories", "skills", "history.db"):
            self.assertFalse(os.path.exists(os.path.join(self.data, gone)), gone)
        self.assertEqual(read(os.path.join(self.data, "contacts.json")), '{"mum": "+91"}')
        self.assertEqual(read(os.path.join(self.data, "SOUL.md")), "Calm and quick.")
        self.assertEqual(read(os.path.join(self.repo, "vocabulary.json")), '["Zostel"]')
        self.assertTrue(os.path.exists(os.path.join(backup.localdata(), "voice", "owner.npy")))
        self.assertEqual(json.loads(read(os.path.join(self.data, "settings.json"))), {"name": "Hari", "met": False})
        backup.restore(saved)  # and it all comes back
        self.assertEqual(read(os.path.join(self.data, "memories", "MEMORY.md")), "Chrome is the browser.")
        self.assertEqual(self.turns(), ["open notepad"])

    def test_nothing_is_touched_while_she_is_running(self):
        with mock.patch.object(backup, "running", lambda: True):
            for call in (backup.backup, backup.fresh):
                with self.assertRaises(SystemExit):
                    call()
        self.assertTrue(os.path.exists(os.path.join(self.data, "history.db")))
        self.assertFalse(os.path.exists(os.path.join(backup.localdata(), "Backups")))

    def test_a_zip_that_isnt_a_backup_changes_nothing(self):
        other = os.path.join(self.repo, "other.zip")
        with zipfile.ZipFile(other, "w") as z:
            z.writestr("appdata/memories/USER.md", "planted")
        with self.assertRaises(SystemExit):
            backup.restore(other)
        self.assertEqual(read(os.path.join(self.data, "memories", "USER.md")), "Lives in Hyderabad.")


class FirstHello(unittest.TestCase):
    def test_she_introduces_herself_until_she_has_met_you(self):
        self.assertEqual(siri.REPLIES["first_run"], ["Hey, I'm Jev, what can I do for you?"])
        self.assertIs(settings.DEFAULTS["met"], False)


if __name__ == "__main__":
    unittest.main()
