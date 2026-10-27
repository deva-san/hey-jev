"""Hermes' memory and learning in Hey Jev: past-chat search (history.search), skills in Hermes' format with its usage
tracking and curator, corrections looked at straight away, undo for what she learned on her own, and the prompt
staying small. All on a temp folder, no model."""
import contextlib
import datetime
import io
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

    def test_a_skill_is_named_as_its_folder_and_one_that_cant_be_archived_is_kept(self):
        """27 October, found while mapping: Hermes' archive_skill finds a skill by its frontmatter name and skills.py by
        its folder, so one whose names differed couldn't be archived, and delete_skill deleted it for good instead."""
        made = skills.create_skill("work-mode", skills.build_content("focus-mode", "Work setup", "x"))
        self.assertFalse(made["success"])
        self.assertIn("folder name", made["error"])
        self.assertIsNone(skills.find_skill("work-mode"))
        skills.create_skill("tea", skills.build_content("tea", "Tea", "Steep it."))  # nor renamed later
        self.assertFalse(skills.edit_skill("tea", skills.build_content("coffee", "Tea", "x"))["success"])
        self.assertFalse(skills.patch_skill("tea", 'name: "tea"', 'name: "coffee"')["success"])
        # one written by hand before that rule: Hermes can't find it to archive it, so it stays, never deleted
        path = skills.SKILLS_DIR / "old-one" / "SKILL.md"
        path.parent.mkdir(parents=True)
        path.write_text("---\nname: something-else\ndescription: an old one\n---\nDo it.\n", encoding="utf-8")
        with contextlib.redirect_stdout(io.StringIO()):
            gone = skills.delete_skill("old-one")
        self.assertFalse(gone["success"])
        self.assertTrue(path.exists())
        self.assertTrue(skills.patch_skill("old-one", "Do it.", "Do it now.")["success"])  # a line of it still mends

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

    def test_with_many_skills_the_best_fits_are_described_and_the_rest_named(self):
        """40 skills listed with what they do and their words took about 600 tokens of every request (B35, P3). The
        ones that fit best are described, the rest named, none left out: Hermes found a skill missing from the list
        isn't found again."""
        for i in range(12):
            skills.create_skill(f"chore-{i:02}", skills.build_content(f"chore-{i:02}", f"Does chore {i} their way",
                                                                      "Step one.", [f"chore {i}"]))
        skills.create_skill("tea-timer", skills.build_content("tea-timer", "Timer for green tea", "Steep it 3 min.",
                                                              ["tea time"]))
        siri._skill_cache[0] = 0.0
        with mock.patch.object(siri.decider, "available", lambda: False):
            block = siri.skills_block("set the tea timer for green tea")
        self.assertIn("    - tea-timer: Timer for green tea (the user says: tea time)", block)
        self.assertIn("### tea-timer\n", block)
        self.assertEqual(block.count("(the user says: chore"), skills.MOST_DESCRIBED - 1)
        named = block.split("    - also: ")[1].split("\n")[0].split(", ")
        self.assertEqual(len(named), 13 - skills.MOST_DESCRIBED)
        self.assertTrue(all(f"chore-{i:02}" in block for i in range(12)))

    def test_her_review_sees_every_skill_with_its_words(self):
        """learn_later's review lists her skills with no request: with only six described, "no, when I say focus time
        also close Teams" had no skill with "focus time" to patch, and a second one could be written."""
        for i in range(10):
            skills.create_skill(f"chore-{i:02}", skills.build_content(f"chore-{i:02}", f"Does chore {i} their way",
                                                                      "Step one.", [f"chore {i}"]))
        skills.create_skill("zz-focus", skills.build_content("zz-focus", "Mutes Slack and opens VS Code", "Mute it.",
                                                             ["focus time"]))
        siri._skill_cache[0] = 0.0
        with mock.patch.object(siri.decider, "available", lambda: False):
            block = siri.skills_block()
        self.assertIn("zz-focus: Mutes Slack and opens VS Code (the user says: focus time)", block)
        self.assertNotIn("also: ", block)


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


class YourSkills(Home):
    def test_her_review_cant_delete_or_rewrite_a_skill_you_taught_her(self):
        """A review may write skills, and only her procedures were kept from it: one told to fix "the skill it's
        about" after a plain "No" could archive or write over a routine you taught her. A fix to a line of yours
        still goes in, a skill she wrote herself she may still change, and you can still delete yours."""
        skills.create_skill("work-mode", skills.build_content("work-mode", "Work setup", "Open Gmail."))
        skills.create_skill("tea", skills.build_content("tea", "Tea timer", "3 min."), agent_created=True)
        for step in ({"action": "delete", "name": "work-mode"},
                     {"action": "create", "name": "work-mode", "description": "Work setup", "notes": "Open Slack."}):
            with self.assertRaises(RuntimeError, msg=step):
                siri.learn_skill(step, agent=True)
        self.assertIn("Open Gmail.", skills.find_skill("work-mode").read_text(encoding="utf-8"))
        siri.learn_skill({"action": "patch", "name": "work-mode", "old": "Open Gmail.", "new": "Open Gmail, Work."},
                         agent=True)
        self.assertIn("Open Gmail, Work.", skills.find_skill("work-mode").read_text(encoding="utf-8"))
        siri.learn_skill({"action": "create", "name": "tea", "description": "Tea timer", "notes": "4 min."}, agent=True)
        self.assertIn("4 min.", skills.find_skill("tea").read_text(encoding="utf-8"))
        siri.learn_skill({"action": "delete", "name": "tea"}, agent=True)
        self.assertIsNone(skills.find_skill("tea"))
        siri.learn_skill({"action": "delete", "name": "work-mode"})  # you asked
        self.assertIsNone(skills.find_skill("work-mode"))


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

    def test_undo_keeps_what_was_added_since(self):
        store = hermes_memory.MemoryStore()
        hermes_memory.memory_tool(store, "add", "user", "Lives in Hyderabad.")
        with mock.patch.object(siri, "MEMORY", store), mock.patch.object(siri, "learn_words", lambda w, s: "words"):
            siri.apply_learning({"memory": [{"action": "add", "target": "user", "content": "Likes chai."}]})
        hermes_memory.memory_tool(hermes_memory.MemoryStore(), "add", "user", "Sister is Priya.")  # added since
        self.assertTrue(siri.undo_learning())
        store = hermes_memory.MemoryStore()
        store.load_from_disk()
        self.assertEqual(store._entries_for("user"), ["Lives in Hyderabad.", "Sister is Priya."])

    def test_whole_words_are_found_first(self):
        history.add("installing the new printer driver", "", "")
        self.assertEqual([h["you"] for h in history.search("install printer")],
                         ["installing the new printer driver"])  # stemmed, every word: the first pass

    def test_what_you_say_to_undo_it(self):
        for said in ("forget what you just learned", "undo what you learned", "unlearn that"):
            self.assertTrue(siri.UNDO_ASKED.fullmatch(siri.plain(said)), said)
        self.assertFalse(siri.UNDO_ASKED.fullmatch(siri.plain("undo that")))  # that's Ctrl+Z
        self.assertFalse(siri.UNDO_ASKED.fullmatch(siri.plain("forget what you just remembered")))  # the model's job


class MakingRoom(Home):
    """From 20 October her memory was full and everything new was let go, "not kept" five times in the log, while
    one-day facts like "Hari asked Jev to open Telegram and WhatsApp" stayed."""
    NEW = "When Hari says not this about a video, check his screen first."

    def setUp(self):
        super().setUp()
        self.store, self.asked = hermes_memory.MemoryStore(user_char_limit=200), []
        for fact in ("Hari asked about a CWC recruitment page on 22 October.", "Hari prefers Light mode.",
                     "Hari asked Jev to open Telegram and WhatsApp on 23 October."):
            hermes_memory.memory_tool(self.store, "add", "user", fact)
        for patch in (mock.patch.object(siri, "MEMORY", self.store),
                      mock.patch.object(siri, "learn_words", lambda w, s: "words")):
            patch.start()
            self.addCleanup(patch.stop)

    def reply(self, raw):
        def chat(key, messages, **kw):
            self.asked.append(messages[0]["content"])
            return raw, None, None
        return mock.patch.object(siri.opencode, "chat", chat)

    def kept(self):
        self.store.load_from_disk()
        return self.store._entries_for("user")

    def test_a_review_makes_room_for_what_it_learned(self):
        with self.reply(json.dumps({"operations": [{"action": "remove", "entry": 1}, {"action": "remove", "entry": 3},
                                                   {"action": "add", "content": self.NEW}]})):
            out = siri.apply_learning({"memory": [{"action": "add", "target": "user", "content": self.NEW}]})
        self.assertEqual(self.kept(), ["Hari prefers Light mode.", self.NEW])
        self.assertFalse(any("not kept" in o for o in out), out)
        self.assertIn("Free at least", self.asked[0])
        self.assertIn("\n2. Hari prefers Light mode.", self.asked[0])

    def test_entries_are_named_by_number_not_quoted(self):
        """23 October: the model's words from an entry were a little off, matched nothing, and the batch failed."""
        with self.reply(json.dumps({"operations": [
                {"action": "replace", "entry": "3", "content": "Hari uses Telegram and WhatsApp."},
                {"action": "remove", "entry": 1}, {"action": "remove", "entry": 1},  # twice is once
                {"action": "add", "content": self.NEW}]})):
            siri.apply_learning({"memory": [{"action": "add", "target": "user", "content": self.NEW}]})
        self.assertEqual(self.kept(), ["Hari prefers Light mode.", "Hari uses Telegram and WhatsApp.", self.NEW])

    def test_however_much_it_tidies_the_new_one_goes_in(self):
        """24 October: the add came 14th, after 13 changes, and a cap of 10 cut it off."""
        os.remove(os.path.join(hermes_memory.get_memory_dir(), "USER.md"))  # not setUp's entries: twelve short ones
        store = hermes_memory.MemoryStore(user_char_limit=150)
        for i in range(1, 13):
            hermes_memory.memory_tool(store, "add", "user", f"Fact {i}.")
        with mock.patch.object(siri, "MEMORY", store), \
                self.reply(json.dumps({"operations": [{"action": "remove", "entry": i} for i in range(1, 12)]
                                      + [{"action": "add", "content": self.NEW}]})):
            siri.apply_learning({"memory": [{"action": "add", "target": "user", "content": self.NEW}]})
        store.load_from_disk()
        self.assertEqual(store._entries_for("user"), ["Fact 12.", self.NEW])

    def test_only_as_much_is_taken_out_as_it_needs(self):
        """24 October: asked to free 100 characters, it took out 10 entries, 700 characters, preferences among them."""
        os.remove(os.path.join(hermes_memory.get_memory_dir(), "USER.md"))
        store = hermes_memory.MemoryStore(user_char_limit=400)
        facts = [f"Fact {i} ".ljust(100, "x") for i in (1, 2, 3)] + ["Fact 4 ".ljust(90, "y")]
        for fact in facts:
            hermes_memory.memory_tool(store, "add", "user", fact)
        with mock.patch.object(siri, "MEMORY", store), \
                self.reply(json.dumps({"operations": [{"action": "remove", "entry": i} for i in (1, 2, 3, 4)]
                                      + [{"action": "add", "content": self.NEW}]})):
            siri.apply_learning({"memory": [{"action": "add", "target": "user", "content": self.NEW}]})
        store.load_from_disk()
        self.assertEqual(store._entries_for("user"), [facts[3], self.NEW])  # the room it needs and ROOM_SPARE more

    def test_remember_this_makes_room_too(self):
        with self.reply(json.dumps({"operations": [{"action": "remove", "entry": 1},
                                                   {"action": "add", "content": self.NEW}]})):
            siri.do_step({"do": "memory", "action": "add", "target": "user", "content": self.NEW})
        self.assertIn(self.NEW, self.kept())

    def test_nothing_changes_when_no_room_is_made(self):
        before = self.kept()
        for raw in ("not json", json.dumps({"operations": []}),
                    json.dumps({"operations": [{"action": "remove", "entry": 9},
                                               {"action": "add", "content": self.NEW}]})):
            with self.subTest(raw=raw), self.reply(raw):
                out = siri.apply_learning({"memory": [{"action": "add", "target": "user", "content": self.NEW}]})
                self.assertTrue(any("not kept" in o for o in out), out)
                self.assertEqual(self.kept(), before)
        self.store.reset_consolidation_failures()
        with self.reply("not json"), self.assertRaises(RuntimeError) as said:
            siri.do_step({"do": "memory", "action": "add", "target": "user", "content": self.NEW})
        self.assertIn("memory is full", str(said.exception))


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

    def test_a_no_that_only_turns_her_down_isnt_a_correction(self):
        """"Send it?" "No.": every no, nope and no thanks started a review at once, past the 90 s wait, told "They
        just corrected her: "No". Fix the fact or the skill it's about first": a model call each time, pushing it to
        change her memory or a skill. A no that says what was wrong still goes straight away."""
        started = []

        class Thread:
            def __init__(self, target=None, kwargs=None, daemon=None):
                started.append(kwargs)

            def start(self):
                pass
        with mock.patch.object(siri.threading, "Thread", Thread), \
                mock.patch.dict(siri.settings._load(), {"learning": True}), \
                mock.patch.dict(siri._learning, turns=0, last=time.time()):  # a review a moment ago
            for words in ("No.", "Nope", "No thanks", "No, not now", "Nah, leave it", "No, don't send it", "No, wait",
                          "No, it's fine", "No, don't send the message", "No, don't send the email",
                          "No, don't delete the file", "No, do not send", "No, don't", "No, don't worry about it",
                          # cut off in round 2, or "okay" and "now" taken off the end by plain(): all corrections
                          "No, don't send this email", "No, don't send that message", "No, don't delete these files",
                          "No, don't install this app", "No, don't reply to him", "No, it's okay", "No, that's okay",
                          "No, I'm okay", "No, leave it for now", "No, not today", "No, maybe later", "No, skip it",
                          "No, wait a minute", "No, I changed my mind", "Actually, I changed my mind",
                          # and the commonest ways to turn her down after those, in English and in Hinglish
                          "No, stop it", "No, no need", "No, not needed", "No, hold on a sec", "No, one sec",
                          "No, let it be", "No, that's it", "No, maybe tomorrow", "No, I'll do it myself",
                          "No, never mind, I'll do it myself", "No, actually never mind", "No, I don't want to",
                          "No, rehne do", "No, mat bhejo", "No, chhodo"):
                siri.learn_later(words, [], [], gate=True)
            self.assertEqual(started, [])
            fixes = ("No, I said Zostel", "No, not that one", "Nope, wrong one", "No, open Spotify instead",
                     "No, don't do that again", "No, don't call me sir", "No, don't use Edge",
                     "No, don't do it like that", "No, don't open the file again", "No, it's Zostel",
                     "Actually, I meant Spotify", "No, don't send that like this")
            for words in fixes:
                siri.learn_later(words, [], [], gate=True)
        self.assertEqual([s["focus"] for s in started], list(fixes))

    def test_her_review_has_hermes_rules(self):
        self.assertIn("One fact goes to ONE store", siri.LEARN)
        self.assertIn("Do NOT capture", siri.LEARN)
        self.assertIn("Environment-dependent failures", siri.LEARN)


class PromptSize(Home):
    def test_with_full_memory_and_40_skills_her_prompt_stays_within_its_budget(self):
        """PLAN's budget: 3,000 tokens or less for the fixed part, 4,000 in total with full memory, and a test fails if
        it grows. With full memory and 40 skills it measured 5,059 tokens against a test that let it reach 6,000 (B35).
        A request for a command or a schedule, which has those steps written out, stays within it too."""
        store = hermes_memory.store()  # her own limits
        for i in range(60):
            hermes_memory.memory_tool(store, "add", "user", f"Fact number {i} about them, a few words long here.")
            hermes_memory.memory_tool(store, "add", "memory", f"Note number {i} about this PC, a few words long.")
        for i in range(40):
            skills.create_skill(f"skill-{i}", skills.build_content(f"skill-{i}", f"Does task number {i} their way",
                                                                    "Step one. Step two. " * 30, [f"do {i}"]))
        with mock.patch.object(siri, "MEMORY", store), mock.patch.object(siri.decider, "available", lambda: False):
            known = siri.skills_block("do task number 1 their way")
            memory = siri.memory_block()
        self.assertIn("### skill-", known)  # the one that fits, written out
        fixed = len(siri.DEFAULT_SOUL + "\n\n" + siri.PROMPT) + 700  # + the PC's context, about 630 characters
        total = fixed + len("\n\n" + known) + len(memory)
        tasks = total + len(siri.TASK_STEPS) - len(siri.TASK_STUB)
        # without her name (149 of 150 voice turns) COLD_NOTE comes on top: outside PLAN's 4,000, and held here too
        cold = tasks + len(siri.COLD_NOTE)
        print(f"\n  prompt with full memory and 40 skills, about 4 characters a token: fixed {fixed / 4:.0f}, "
              f"total {total / 4:.0f}, for a command or schedule {tasks / 4:.0f}, and that without her name "
              f"{cold / 4:.0f} tokens")
        self.assertLessEqual(fixed / 4, 3000)
        self.assertLessEqual(total / 4, 4000)
        self.assertLessEqual(tasks / 4, 4000)
        self.assertLessEqual(cold / 4, 4300)


if __name__ == "__main__":
    unittest.main()
