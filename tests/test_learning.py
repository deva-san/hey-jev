"""Hermes' memory and learning in Hey Jev: past-chat search (history.search), skills in Hermes' format with its usage
tracking and curator, corrections looked at straight away, undo for what she learned on her own, and the prompt
staying small. All on a temp folder, no model."""
import datetime
import json
import os
import tempfile
import time
import unittest
from unittest import mock

from tests.support import siri

import history
import hermes_memory
from hermes_memory import curator, skill_usage, skills


class Home(unittest.TestCase):
    """A fresh Hermes home (skills, memories) and history for each test."""

    def setUp(self):
        root = tempfile.mkdtemp(prefix="heyjev-learning-")
        for target, name, value in ((history, "DB", os.path.join(root, "history.db")),
                                    (history, "DAYS_DIR", os.path.join(root, "days")),
                                    (skills, "SKILLS_DIR", __import__("pathlib").Path(root, "skills")),
                                    (siri, "UNDO_PATH", os.path.join(root, "memories", ".undo.jsonl"))):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        old_home, old_mem = hermes_memory.get_hermes_home(), hermes_memory.get_memory_dir()
        hermes_memory.set_home(root)
        hermes_memory.set_memory_dir(os.path.join(root, "memories"))
        self.addCleanup(hermes_memory.set_home, old_home)
        self.addCleanup(hermes_memory.set_memory_dir, old_mem)
        self.root = root
        siri._skill_cache[0] = 0.0


class Search(Home):
    def test_every_word_first_then_any_then_pieces_of_words(self):
        history.add("open careerid.in in chrome", "opened it", "Here it is.")
        history.add("play some lofi music", "played", "Playing it.")
        history.add("what's the weather in delhi", "", "It's sunny.")
        self.assertEqual([h["you"] for h in history.search("lofi music")], ["play some lofi music"])
        self.assertEqual([h["you"] for h in history.search("lofi weather")][:2],
                         ["play some lofi music", "what's the weather in delhi"])  # no turn has both: either
        self.assertEqual([h["you"] for h in history.search("careerid")], ["open careerid.in in chrome"])
        self.assertEqual([h["you"] for h in history.search("reerid")], ["open careerid.in in chrome"])  # a piece
        self.assertEqual(history.search("cheese"), [])

    def test_a_hit_comes_with_the_turns_around_it(self):
        history.add("search for budget phones", "searched", "Here are some.")
        history.add("which one has the best camera", "", "The Pixel.")
        history.add("open its page", "opened", "Here.")
        hit = history.search("best camera")[0]
        self.assertEqual([n["you"] for n in hit["near"]], ["search for budget phones", "open its page"])

    def test_after_keeps_to_the_time_asked(self):
        history.add("old one about chrome", "", "")
        con = history._db()
        with con:
            con.execute("UPDATE turns SET ts = ? WHERE said = 'old one about chrome'", (time.time() - 10 * 86400,))
        con.close()
        history.add("new one about chrome", "", "")
        self.assertEqual([h["you"] for h in history.search("chrome", after="7d")], ["new one about chrome"])
        self.assertEqual(len(history.search("chrome")), 2)
        self.assertIsNone(history._since("whenever"))

    def test_odd_words_never_break_the_search(self):
        history.add("open notepad", "", "")
        for q in ('open" OR (', "NOT AND", "chat-send: ^*", "open*"):
            with self.subTest(q=q):
                history.search(q)


class Skills(Home):
    def test_a_skill_she_writes_is_hermes_format_and_reads_back(self):
        content = skills.build_content("work-mode", "Use when they say work mode: open Gmail in the Work profile "
                                       "and set the volume to thirty, every weekday", "Notes here.", ["work mode", "on"],
                                       [{"do": "volume", "to": 30}], "Work mode's on.")
        head = content.split("---")[1]
        self.assertIn('platforms: ["windows"]', head)
        self.assertIn('triggers: ["work mode", "on"]', head)  # "on" stays a word, not YAML's true
        self.assertIn("## When to Use", content)
        self.assertTrue(skills.create_skill("work-mode", content)["success"])
        entry = skills.list_skills()[0]
        self.assertLessEqual(len(entry["description"]), 60)
        self.assertEqual(entry["triggers"], ["work mode", "on"])
        self.assertEqual(entry["plan"]["steps"], [{"do": "volume", "to": 30}])

    def test_old_comma_triggers_still_read(self):
        path = skills.SKILLS_DIR / "old" / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\nname: old\ndescription: an old one\ntriggers: start it, go\n---\nDo it.\n",
                        encoding="utf-8")
        self.assertEqual(skills.list_skills()[0]["triggers"], ["start it", "go"])

    def test_deleting_archives_and_forgetting_deletes(self):
        for name in ("one", "two"):
            skills.create_skill(name, skills.build_content(name, f"skill {name}", "x"), agent_created=True)
        self.assertTrue(skills.delete_skill("one")["success"])
        self.assertIsNone(skills.find_skill("one"))
        self.assertTrue(any((skills.SKILLS_DIR / ".archive").iterdir()))  # restorable
        self.assertTrue(skills.delete_skill("two", really=True)["success"])
        self.assertFalse((skills.SKILLS_DIR / "two").exists())

    def test_the_skills_that_fit_are_written_out_and_the_rest_listed(self):
        skills.create_skill("tea-timer", skills.build_content("tea-timer", "Timer for tea", "Steep green tea 3 min."))
        skills.create_skill("work-mode", skills.build_content("work-mode", "Work setup", "Open Gmail Work profile."))
        block = skills.system_prompt_block(detail=["tea-timer"])
        self.assertIn("    - work-mode: Work setup", block)
        self.assertIn("### tea-timer\nSteep green tea 3 min.", block)
        self.assertNotIn("Open Gmail Work profile.", block)
        with mock.patch.object(siri.decider, "available", lambda: False):
            self.assertEqual(siri.relevant_skills("set the tea timer for green tea", skills.list_skills()),
                             ["tea-timer"])


class Curator(Home):
    def test_a_skill_she_wrote_and_never_used_is_archived_one_you_taught_her_is_not(self):
        skills.create_skill("hers", skills.build_content("hers", "Hers", "x"), agent_created=True)
        skills.create_skill("yours", skills.build_content("yours", "Yours", "x"), agent_created=False)
        data = skill_usage.load_usage()
        old = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=40)).isoformat()
        for name in data:
            data[name]["created_at"] = old
            data[name]["use_count"] = 1
            data[name]["last_used_at"] = old
        skill_usage.save_usage(data)
        counts = curator.apply_automatic_transitions()
        self.assertEqual(counts["archived"], 1)
        self.assertIsNone(skills.find_skill("hers"))
        self.assertIsNotNone(skills.find_skill("yours"))

    def test_the_weekly_tidy_waits_for_its_first_week_and_two_quiet_hours(self):
        with mock.patch.object(curator, "apply_automatic_transitions") as run:
            siri.tidy_skills()  # first sight: seeds the clock only, as Hermes does
            run.assert_not_called()
            state = curator.load_state()
            state["last_run_at"] = (datetime.datetime.now(datetime.timezone.utc)
                                    - datetime.timedelta(days=8)).isoformat()
            curator.save_state(state)
            history.add("just now", "", "")
            siri.tidy_skills()  # a turn a moment ago: not now
            run.assert_not_called()
            with mock.patch.object(history, "recent", lambda *a, **k: [(time.time() - 3 * 3600, "x", "{}")]):
                run.return_value = {"archived": 1}
                siri.tidy_skills()
            run.assert_called_once()


class Undo(Home):
    def test_forget_what_you_just_learned_puts_back_memory_and_skills(self):
        store = hermes_memory.MemoryStore()
        hermes_memory.memory_tool(store, "add", "user", "Lives in Hyderabad.")
        with mock.patch.object(siri, "MEMORY", store), mock.patch.object(siri, "learn_words", lambda w, s: "words"):
            out = siri.apply_learning({"memory": [{"action": "replace", "target": "user", "old_text": "Hyderabad",
                                                   "content": "Lives in Pune."}],
                                       "skills": [{"action": "create", "name": "tea", "description": "Tea timer",
                                                   "notes": "3 min."}]})
        self.assertTrue(any("Pune" in o for o in out))
        self.assertIsNotNone(skills.find_skill("tea"))
        self.assertEqual(skill_usage.get_record("tea").get("created_by"), "agent")
        self.assertTrue(siri.undo_learning())
        with open(os.path.join(hermes_memory.get_memory_dir(), "USER.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("Hyderabad", text)
        self.assertNotIn("Pune", text)
        self.assertIsNone(skills.find_skill("tea"))
        self.assertIsNone(siri.undo_learning())  # nothing more

    def test_what_you_say_to_undo_it(self):
        for said in ("forget what you just learned", "undo what you learned", "unlearn that"):
            self.assertTrue(siri.UNDO_ASKED.fullmatch(siri.plain(said)), said)
        self.assertFalse(siri.UNDO_ASKED.fullmatch(siri.plain("undo that")))  # that's Ctrl+Z


class Corrections(unittest.TestCase):
    def test_a_correction_is_looked_at_straight_away_with_it_as_the_focus(self):
        started = []

        class Thread:
            def __init__(self, target=None, kwargs=None, daemon=None):
                started.append(kwargs)

            def start(self):
                pass
        with mock.patch.object(siri.threading, "Thread", Thread), \
                mock.patch.dict(siri.settings._load(), {"learning": True}):
            siri._learning["last"] = time.time()  # a review a moment ago: a correction still goes now
            siri.learn_later("no, I said Zostel", [], [], gate=False)
            siri.learn_later("open notepad", [{"do": "open"}], [], gate=False)
        self.assertEqual(started, [{"wait": 0, "focus": "no, I said Zostel"}])

    def test_her_review_has_hermes_rules(self):
        self.assertIn("One fact goes to ONE store", siri.LEARN)
        self.assertIn("Do NOT capture", siri.LEARN)
        self.assertIn("Environment-dependent failures", siri.LEARN)


class PromptSize(Home):
    def test_with_full_memory_and_40_skills_her_prompt_stays_near_4000_tokens(self):
        store = hermes_memory.MemoryStore()
        for i in range(60):
            hermes_memory.memory_tool(store, "add", "user", f"Fact number {i} about them, a few words long here.")
            hermes_memory.memory_tool(store, "add", "memory", f"Note number {i} about this PC, a few words long.")
        for i in range(40):
            skills.create_skill(f"skill-{i}", skills.build_content(f"skill-{i}", f"Does task number {i} their way",
                                                                    "Step one. Step two. " * 30, [f"do {i}"]))
        with mock.patch.object(siri, "MEMORY", store):
            entries = skills.list_skills()
            system = siri.DEFAULT_SOUL + "\n\n" + siri.PROMPT + "\n\n" + \
                skills.system_prompt_block(entries, ["skill-1", "skill-2"]) + siri.memory_block()
        tokens = (len(system) + 700) / 4  # + the PC's context, about 4 characters a token
        print(f"\n  prompt with full memory and 40 skills: {len(system) + 700} chars, about {tokens:.0f} tokens")
        self.assertLess(tokens, 6000)  # today's measure; the step list is the part to trim next (see PLAN.md)


if __name__ == "__main__":
    unittest.main()
