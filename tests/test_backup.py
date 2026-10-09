"""backup.py: a backup puts everything back, a fresh start clears only her memory, skills and old chats."""
import json
import os
import sqlite3
import tempfile
import time
import unittest
import zipfile
from unittest import mock

from tests.support import siri  # noqa: F401  (points %APPDATA% at a temp folder before backup is imported)
import backup
import clean_test_data
import history
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


class CleanTestData(unittest.TestCase):
    """clean_test_data.py, for the 8 Oct leak: a test run wrote its turns into her real history and logs. Only the
    tests' rows go, as many of a phrase as you said yourself stay, and nothing changes without --apply."""
    T0 = 1_791_500_000.0  # inside the window passed below

    def setUp(self):
        root = tempfile.mkdtemp(prefix="heyjev-clean-")
        env = mock.patch.dict(os.environ, {"APPDATA": os.path.join(root, "roaming"),
                                           "LOCALAPPDATA": os.path.join(root, "local")})
        env.start()
        self.addCleanup(env.stop)
        patch = mock.patch.object(backup, "running", lambda: False)
        patch.start()
        self.addCleanup(patch.stop)
        self.data, self.local = backup.appdata(), backup.localdata()
        self.tests = os.path.join(root, "tests")
        write(os.path.join(self.tests, "test_x.py"), 'siri.handle("Open Notepad.")\nsiri.handle("set a timer")\n')
        for path in (mock.patch.object(history, "DB", os.path.join(self.data, "history.db")),
                     mock.patch.object(history, "DAYS_DIR", os.path.join(self.data, "memories", "days"))):
            path.start()
            self.addCleanup(path.stop)
        os.makedirs(self.data, exist_ok=True)
        turns = [(self.T0 - 86400, "what's the weather")]  # yours, the day before
        turns += [(self.T0 + 100, "open notepad")]  # yours, on its own, in her log
        turns += [(self.T0 + 600 + i / 50, "Open Notepad.") for i in range(30)]  # a test's burst
        turns += [(self.T0 + 900 + i / 50, "set a timer") for i in range(5)]  # never said by you
        turns += [(self.T0 + 1200 + i / 50, f"made up in a loop {i}") for i in range(4)]  # a test's, but no phrase
        turns += [(self.T0 + 1500, "remind me to call mum")]  # yours, not a test phrase
        for ts, said in turns:
            with mock.patch("time.time", return_value=ts):
                history.add(said, reply="ok")
        write(os.path.join(self.local, "Logs", "Hey Jev.log"),
              "\n> heard: 'open notepad'  (stt 300ms, 95% sure)\n  quick: open\n> heard: \"what's the weather\"\n")
        agent = [{"at": int(self.T0 + 700 + i), "goal": "set a timer", "ms": 3} for i in range(3)]
        agent += [{"at": int(self.T0 + 2000), "goal": "turn on night light", "ms": 41000}]
        write(os.path.join(self.local, "Logs", "agent.jsonl"), "".join(json.dumps(a) + "\n" for a in agent))
        self.window = (self.T0, self.T0 + 3600)

    def said(self):
        con = sqlite3.connect(os.path.join(self.data, "history.db"))
        try:
            return [r[0] for r in con.execute("SELECT said FROM turns ORDER BY ts")]
        finally:
            con.close()

    def test_only_the_tests_rows_go(self):
        found = clean_test_data.plans(self.window, tests=self.tests)
        made, problems = clean_test_data.apply(found)
        self.assertEqual(problems, [])
        said = self.said()
        self.assertEqual(said.count("what's the weather"), 1)
        self.assertEqual(sum(clean_test_data.plain(s) == "open notepad" for s in said), 1)  # the one you said
        self.assertNotIn("set a timer", said)
        self.assertEqual(sum(s.startswith("made up in a loop") for s in said), 4)  # no phrase: listed, kept
        self.assertIn("remind me to call mum", said)
        con = sqlite3.connect(os.path.join(self.data, "history.db"))
        try:  # the search index too, or "what did I ask about timers" still finds them
            self.assertEqual(con.execute("SELECT count(*) FROM turns_tri").fetchone()[0], len(said))
        finally:
            con.close()
        day = time.strftime("%Y-%m-%d", time.localtime(self.T0 + 600))
        text = read(os.path.join(self.data, "memories", "days", f"{day}.md"))
        self.assertEqual(text.count("You: "), len([s for s in said if s != "what's the weather"]))
        self.assertIn("remind me to call mum", text)
        agent = read(os.path.join(self.local, "Logs", "agent.jsonl"))
        self.assertNotIn("set a timer", agent)
        self.assertIn("turn on night light", agent)
        self.assertTrue(all(os.path.isfile(p) for p in made))
        with zipfile.ZipFile(made[0]) as z:  # her data as it was, before any of this
            self.assertIn("appdata/history.db", z.namelist())
        with zipfile.ZipFile(made[1]) as z:
            self.assertIn("set a timer", z.read(os.path.join("Logs", "agent.jsonl").replace(os.sep, "/")).decode())

    def test_a_dry_run_changes_nothing(self):
        before = self.said()
        phrases = clean_test_data.test_phrases(self.tests)
        with mock.patch.object(clean_test_data, "test_phrases", lambda _=None: phrases), \
                mock.patch("builtins.print") as printed:
            clean_test_data.main(["--from", time.strftime("%Y-%m-%d %H:%M", time.localtime(self.window[0])),
                                  "--to", time.strftime("%Y-%m-%d %H:%M", time.localtime(self.window[1]))])
        self.assertIn("Dry run: nothing changed. 38 rows would go.", printed.call_args_list[-1].args[0])
        self.assertEqual(self.said(), before)
        self.assertFalse(os.path.exists(os.path.join(self.local, "Backups")))
        listed = os.path.join(self.local, "Logs", "clean_test_data.txt")  # every one, not a sample of five
        self.assertIn(listed, "\n".join(str(c.args[0]) for c in printed.call_args_list))
        lines = read(listed).splitlines()
        self.assertEqual(sum(line.startswith("out ") for line in lines), 38)
        self.assertEqual(sum(line.startswith("look ") for line in lines), 4)

    def test_a_match_on_its_own_stays(self):
        """A real "set a timer" in the window, one row on its own, is word for word a test phrase: listed for a look,
        never taken out. Also in the dictation log, which has no log of what you said to go by."""
        with mock.patch("time.time", return_value=self.T0 + 2500):
            history.add("set a timer", reply="ok")  # yours: not in her log, nothing near it
        when = lambda ts: time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts))
        dictated = [{"time": when(self.T0 + 2600), "text": "Set a timer."}]  # yours
        dictated += [{"time": when(self.T0 + 2700 + i), "text": "set a timer"} for i in range(3)]  # a test's
        path = os.path.join(self.local, "Logs", "Hey Jev dictation.jsonl")
        write(path, "".join(json.dumps(d) + "\n" for d in dictated))
        found = clean_test_data.plans(self.window, tests=self.tests)
        clean_test_data.apply(found)
        self.assertEqual(self.said().count("set a timer"), 1)
        self.assertEqual([json.loads(line)["text"] for line in read(path).splitlines()], ["Set a timer."])
        looks = [r[1] for p in found for r in p["look"]]
        self.assertIn("set a timer", looks)
        self.assertIn("Set a timer.", looks)

    def day_file(self):
        return os.path.join(self.data, "memories", "days",
                            time.strftime("%Y-%m-%d", time.localtime(self.T0 + 600)) + ".md")

    def test_the_days_summary_and_your_own_entry_stay_in_her_day_file(self):
        """history.mark_summarized puts the day's summary at the end of its file, after the last entry, which here is a
        test's; and a turn of yours can have the same minute and words as a test's right after it."""
        turns = [(self.T0 + 1580, "set a timer", "Timer set for you")]  # yours, on its own
        turns += [(self.T0 + 1590 + i / 50, "set a timer", "ok") for i in range(2)]  # a test's, in the same minute
        turns += [(self.T0 + 1600 + i / 50, "Open Notepad.", "ok") for i in range(2)]  # a test's, the day's last
        for ts, said, reply in turns:
            with mock.patch("time.time", return_value=ts):
                history.add(said, reply=reply)
        day = os.path.basename(self.day_file())[:-3]
        history.mark_summarized(day, "You asked for a timer and Notepad.")
        clean_test_data.apply(clean_test_data.plans(self.window, tests=self.tests))
        text = read(self.day_file())
        self.assertEqual(history.summary(day), "You asked for a timer and Notepad.")
        self.assertEqual(text.count("You: set a timer"), 1)
        self.assertIn("You: set a timer\n  Jev: Timer set for you", text)
        self.assertEqual(text.count("You: "), len([s for s in self.said() if s != "what's the weather"]))

    def test_a_day_file_it_cant_read_stops_nothing_and_loses_nothing(self):
        """A byte in the day file that isn't UTF-8: history.db has changed by the time the day file is read, so a
        crash there left the logs as they were, and writing it back read as text would have changed that byte."""
        with open(self.day_file(), "ab") as f:
            f.write(b"- **11:59 PM** You: caf\xe9\n  Jev: (nothing said)\n")
        _, problems = clean_test_data.apply(clean_test_data.plans(self.window, tests=self.tests))
        self.assertEqual(problems, [])
        with open(self.day_file(), "rb") as f:
            raw = f.read()
        self.assertIn(b"You: caf\xe9\n", raw)
        self.assertNotIn(b"You: set a timer", raw)
        self.assertNotIn("set a timer", read(os.path.join(self.local, "Logs", "agent.jsonl")))

    def test_what_she_heard_counts_the_way_her_history_keeps_it(self):
        """Her log has what she heard, her name and all; her history keeps the words without it."""
        logs = os.path.join(self.local, "Other logs")
        write(os.path.join(logs, "Hey Jev.log"), "\n> heard: 'Hey Jev, open Notepad.'  (stt 300ms, 95% sure)\n"
                                                 "> heard: 'Jev set a timer'\n")
        heard = clean_test_data.heard_counts(logs)
        self.assertEqual(heard["open notepad"], 1)
        self.assertEqual(heard["set a timer"], 1)

    def test_never_while_she_runs(self):
        with mock.patch.object(backup, "running", lambda: True), self.assertRaises(SystemExit):
            clean_test_data.main(["--apply"])
        self.assertEqual(len(self.said()), 42)


if __name__ == "__main__":
    unittest.main()
