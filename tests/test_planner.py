"""The model path: parse_plan, ask_plan, think, let_go, the learning loop, and web.py's search and read. The model, the
web and the PC are all stubbed: nothing goes online or acts."""
import json
import os
import shutil
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from urllib.parse import urljoin

from tests.support import siri

import history  # noqa: E402
import web  # noqa: E402

RECENT = history.recent  # the real one: Turn stubs it out


class FakeModel:
    """ask_model's stand-in: the replies in turn (the last one again once they run out), and what it was asked."""

    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []

    def __call__(self, messages, **kw):
        self.calls.append(([dict(m) for m in messages], kw))
        reply = self.replies[min(len(self.calls), len(self.replies)) - 1]
        return reply, {"completion_tokens": 1}, "fake-model"


class Turn(unittest.TestCase):
    """think() with nothing around it: no skills, memory, history or PC context."""

    def setUp(self):
        # focused_on reads the real window in front: YouTube there makes every search a YouTube one
        for name, value in (("skills_block", ""), ("memory_block", ""), ("context", ""), ("soul", "You are Jev."),
                            ("focused_on", False)):
            p = patch.object(siri, name, lambda *a, _v=value, **k: _v)
            p.start()
            self.addCleanup(p.stop)
        p = patch.object(siri.history, "recent", lambda *a, **k: [])
        p.start()
        self.addCleanup(p.stop)
        self.looked = []
        p = patch.object(siri, "run_info", lambda steps, links=False: self.looked.append(steps) or "[]")
        p.start()
        self.addCleanup(p.stop)

    def think(self, text, gate, *replies):
        self.model = FakeModel(*replies)
        with patch.object(siri, "ask_model", self.model):
            return siri.think(text, gate)

    def asked_again(self):
        return [m for m, _ in self.model.calls if any("didn't create the command" in str(x.get("content"))
                                                      for x in m)]


class CommandRetry(Turn):
    """A11: the command/schedule retry is only for words that ask for one, and never overrides "to others"."""

    def test_overheard_talk_about_a_schedule_is_let_go_in_one_request(self):
        plan = self.think("I will schedule the call with Ravi for tomorrow at 5", "cold", '{"to": "others"}',
                          '{"to": "you", "steps": [{"do": "schedule", "when": "tomorrow at 5 PM", "repeat": "", '
                          '"description": "Call with Ravi", "task": {"kind": "reminder", "text": "call Ravi"}}]}')
        self.assertIsNone(plan)
        self.assertEqual(len(self.model.calls), 1)

    def test_a_question_about_a_command_keeps_its_answer(self):
        plan = self.think("what's the PowerShell command to list files", False,
                          '{"steps": [], "say": "It\'s Get-ChildItem. I will spell it out if you like."}')
        self.assertEqual(len(self.model.calls), 1)
        self.assertEqual(plan["say"], "It's Get-ChildItem. I will spell it out if you like.")

    def test_a_weather_question_with_tomorrow_at_gets_its_lookup(self):
        plan = self.think("what will the weather be like tomorrow at 6", False,
                          '{"steps": [{"do": "weather", "place": ""}], "say": ""}',
                          '{"steps": [], "say": "Clear and about 24 degrees at 6."}')
        self.assertEqual(self.looked, [[{"do": "weather", "place": ""}]])
        self.assertEqual(self.asked_again(), [])
        self.assertEqual(plan["say"], "Clear and about 24 degrees at 6.")

    def test_checking_the_weather_tomorrow_at_keeps_its_answer(self):
        plan = self.think("check the weather tomorrow at 6", False,
                          '{"steps": [{"do": "weather", "place": ""}], "say": ""}',
                          '{"steps": [], "say": "Clear and about 24 degrees at 6."}',
                          '{"steps": [], "say": "I will check it again at 6."}')
        self.assertEqual(self.asked_again(), [])
        self.assertEqual(plan["say"], "Clear and about 24 degrees at 6.")

    def test_a_look_at_the_pc_still_gets_the_retry(self):
        plan = self.think("every Monday at 9 check my C drive", False,
                          '{"steps": [{"do": "lookup", "what": "disk"}], "say": ""}',
                          '{"steps": [], "say": "Your C drive has 40 GB free."}',
                          '{"steps": [{"do": "schedule", "when": "", "repeat": "every Monday at 9 AM", "description": '
                          '"Check C drive", "task": {"kind": "lookup", "what": "disk"}}], "say": ""}')
        self.assertEqual(len(self.asked_again()), 1)
        self.assertEqual(plan["steps"][0]["do"], "schedule")

    def test_git_status_on_its_own_gets_the_retry(self):
        plan = self.think("git status in hey-jev", False, '{"steps": [], "say": "I will check it."}',
                          '{"steps": [{"do": "command", "command": "git status", "cwd": "C:\\\\hey-jev"}], "say": ""}')
        self.assertEqual(len(self.asked_again()), 1)
        self.assertEqual(plan["steps"][0]["do"], "command")

    def test_a_named_request_to_schedule_still_gets_the_retry(self):
        plan = self.think("remind me every day at 9 PM to take my medicine", False,
                          '{"steps": [], "say": "Okay, I will remind you."}',
                          '{"steps": [{"do": "schedule", "when": "", "repeat": "daily at 9 PM", "description": '
                          '"Take medicine", "task": {"kind": "reminder", "text": "take my medicine"}}], "say": ""}')
        self.assertEqual(len(self.asked_again()), 1)
        self.assertEqual(plan["steps"][0]["do"], "schedule")


class TaskSteps(Turn):
    """P3: the steps for commands, schedules and coding jobs were a thousand characters of every request's prompt,
    which few ask for. They're written out for words that may ask for one, or a follow-up to one; the rest get a line
    naming them."""

    def system(self, words, recent=()):
        with patch.object(siri.history, "recent", lambda *a, **k: list(recent)):
            self.think(words, False, '{"steps": [], "say": "Okay."}')
        return self.model.calls[0][0][0]["content"]

    def test_written_out_only_for_words_that_may_ask_for_one(self):
        for words in ("run the tests in hey-jev", "every Monday at 9 check my C drive", "git status in hey-jev",
                      "remind me at 6 to call Mum", "add a dark mode toggle to my project", "cancel task 3",
                      "schedule a disk check for tomorrow",
                      # missed: a two-digit time, "each", a job, a server, an hour from now
                      "can you check how my battery is doing at 10 pm", "find out about the monsoon at 10 am",
                      "check my battery each morning", "stop job 3", "start the dev server in careerid",
                      "look into flights to goa in an hour", "research the monsoon on friday at noon"):
            with self.subTest(words=words):
                self.assertIn(siri.TASK_STEPS, self.system(words))
        for words in ("open notepad", "what's the capital of Japan", "play some lofi music"):
            with self.subTest(words=words):
                system = self.system(words)
                self.assertIn(siri.TASK_STUB, system)
                self.assertNotIn("destructive, admin and download commands are blocked", system)

    def test_a_request_the_words_miss_still_has_each_steps_fields(self):
        """"add a dark mode toggle to the settings page in hey-jev" got only the steps' names, so the model guessed
        their fields and the code turned it down: "Say the project's full folder"."""
        system = self.system("add a dark mode toggle to the settings page in hey-jev")
        self.assertNotIn(siri.TASK_STEPS, system)
        for field in ('"do":"code","task":', '"cwd":', '"task":{"kind":"reminder","text":', '"when":', '"repeat":',
                      '"do":"task_control","action":"cancel|approve","id":'):
            with self.subTest(field=field):
                self.assertIn(field, system)

    def test_and_for_a_follow_up_to_one(self):
        recent = [(0, "remind me every day at 9 to take my medicine",
                   '{"steps": [{"do": "schedule", "when": "", "repeat": "daily at 9 AM"}], "say": ""}')]
        self.assertIn(siri.TASK_STEPS, self.system("make it 10 instead", recent))


class Lookups(Turn):
    """P2: 21 of 30 spoken answers took a look-up, a whole model round trip more, and "what's the capital of Japan"
    and the moon's distance were looked up on the web 2 times in 3. What doesn't change is answered from what the
    model knows; what changes is still looked up."""

    def asked(self, words):
        self.think(words, False, '{"steps": [], "say": "Okay."}')
        return self.model.calls[0][0][-1]["content"]

    def test_a_fact_that_doesnt_change_is_answered_without_a_look_up(self):
        self.assertIn("What doesn't change (capitals, distances", siri.PROMPT)
        for words in ("what's the capital of Japan", "how far away is the moon", "what's 15% of 2,400",
                      "who wrote Pride and Prejudice", "what does serendipity mean", "how many feet in a mile"):
            with self.subTest(words=words):
                self.assertTrue(self.asked(words).endswith(siri.KNOWN_NOTE))

    def test_what_changes_is_still_looked_up(self):
        for words in ("what's the weather in Tokyo", "what's the latest news on the monsoon", "who won the match today",
                      "what's the price of gold now", "who is the prime minister of Japan", "what does this button mean",
                      "how far is my office", "google the capital of Japan", "open notepad",
                      # this PC and what's on it are looked at, not known; an age, a new phone or the news change
                      "how big is the C drive", "how high is the CPU", "what does the error on the screen mean",
                      "how old is Virat Kohli", "how big is the new iPhone",
                      "what does the budget announcement mean for salaried people"):
            with self.subTest(words=words):
                self.assertNotIn(siri.KNOWN_NOTE, self.asked(words))

    def test_words_overheard_get_no_push_to_answer(self):
        """Said near the PC, "how long is the movie" is likely to a friend: the model decides that, unpushed."""
        self.think("how long is the movie", "cold", '{"to": "others"}')
        self.assertNotIn(siri.KNOWN_NOTE, self.model.calls[0][0][-1]["content"])

    def test_a_fact_asked_without_her_name_still_skips_the_look_up(self):
        """149 of 150 voice turns had no name: "what's the capital of Japan" said so still gets the note, worded to
        leave who it's to with the model."""
        self.think("what's the capital of Japan", "cold", '{"to": "others"}')
        self.assertTrue(self.model.calls[0][0][-1]["content"].endswith(siri.COLD_KNOWN_NOTE))
        self.think("how big is the C drive", "cold", '{"to": "others"}')
        self.assertNotIn(siri.COLD_KNOWN_NOTE, self.model.calls[-1][0][-1]["content"])


class GoogleQuestion(Turn):
    """A22: "Google when is ..." is a question, with or without a question mark."""

    def test_google_question_without_a_question_mark_is_looked_up(self):
        plan = self.think("Google when is the next India match.", False,
                          '{"steps": [{"do": "google", "query": "next India match"}], "say": ""}',
                          '{"steps": [], "say": "India play Australia on Friday."}')
        self.assertEqual(self.looked, [[{"do": "web", "query": "next India match"}]])
        self.assertEqual(plan, {"steps": [], "say": "India play Australia on Friday."})

    def test_show_me_still_opens_google(self):
        plan = self.think("Google show me pictures of the Taj Mahal", False,
                          '{"steps": [{"do": "google", "query": "Taj Mahal pictures"}], "say": ""}')
        self.assertEqual(self.looked, [])
        self.assertEqual(plan["steps"], [{"do": "google", "query": "Taj Mahal pictures"}])


class ToolCalls(unittest.TestCase):
    """M1, M2, M3: the ways Ling writes a step as a <tool_call>, from the live runs on 7 October."""

    def test_json_argument_is_an_argument_not_the_plan(self):
        raw = ('<tool_call>schedule\n<arg_key>when</arg_key>\n<arg_value>2026-10-07T14:46:00</arg_value><arg_key>repeat'
               '</arg_key>\n<arg_value></arg_value><arg_key>description</arg_key>\n<arg_value>Call Mum</arg_value>'
               '<arg_key>task</arg_key>\n<arg_value>{"kind": "reminder", "text": "Call Mum"}</arg_value>\n</tool_call>')
        self.assertEqual(siri.parse_plan(raw)["steps"], [
            {"do": "schedule", "when": "2026-10-07T14:46:00", "repeat": "", "description": "Call Mum",
             "task": {"kind": "reminder", "text": "Call Mum"}}])

    def test_arguments_as_one_json_object(self):
        raw = ('<tool_call>schedule\n{"when": "2026-10-07T14:51:00", "repeat": "", "description": "Call Mum", '
               '"task": {"kind": "reminder", "text": "call Mum"}}</arg_value>')
        self.assertEqual(siri.parse_plan(raw)["steps"], [
            {"do": "schedule", "when": "2026-10-07T14:51:00", "repeat": "", "description": "Call Mum",
             "task": {"kind": "reminder", "text": "call Mum"}}])

    def test_attribute_style_arguments(self):
        self.assertEqual(siri.parse_plan('<tool_call>screen\ntask="click the second video on the page"</arg_value>'
                                         '</tool_call>')["steps"],
                         [{"do": "screen", "task": "click the second video on the page"}])
        self.assertEqual(siri.parse_plan('<tool_call>web\nquery="who won the 2024 T20 World Cup</arg_value>\n'
                                         '</tool_call>')["steps"],
                         [{"do": "web", "query": "who won the 2024 T20 World Cup"}])
        self.assertEqual(siri.parse_plan('<tool_call>schedule\nwhen="2026-10-07T14:51:00"\ndescription="Call Mum"\n'
                                         'task={"kind":"reminder","text":"call Mum"}\n</tool_call>')["steps"],
                         [{"do": "schedule", "when": "2026-10-07T14:51:00", "description": "Call Mum",
                           "task": {"kind": "reminder", "text": "call Mum"}}])

    def test_several_attributes_on_one_line(self):
        """R1: on 8 October the model wrote a timer and a video a line each, ending " /". The timer's seconds came out
        as '300 label="5 min" alert=...', so no timer, and YouTube was searched for 'lofi music" play=true /'."""
        raw = ('<tool_call>timer\n seconds=300 label="5 min" alert="Hey, your 5-minute timer\'s up." /\n'
               '<tool_call>youtube\n query="lofi music" play=true /')
        self.assertEqual(siri.parse_plan(raw)["steps"], [
            {"do": "timer", "seconds": 300, "label": "5 min", "alert": "Hey, your 5-minute timer's up."},
            {"do": "youtube", "query": "lofi music", "play": True}])
        self.assertEqual(siri.parse_plan('<tool_call>youtube query=lofi music play=false />')["steps"],
                         [{"do": "youtube", "query": "lofi music", "play": False}])
        self.assertEqual(siri.parse_plan('<tool_call>schedule\nwhen="in 5 minutes" task={"kind": "reminder", '
                                         '"text": "call Mum"} /\n</tool_call>')["steps"],
                         [{"do": "schedule", "when": "in 5 minutes", "task": {"kind": "reminder", "text": "call Mum"}}])

    def test_an_end_without_a_space_is_no_part_of_the_value(self):
        """'play=false/>' kept its '/>', a truthy string, so YouTube played the top video when it should only show it."""
        for raw, play in (('<tool_call>youtube\nquery=lofi play=false/>', False),
                          ('<tool_call>youtube\nquery="lofi music" play=true></tool_call>', True)):
            self.assertIs(siri.parse_plan(raw)["steps"][0]["play"], play, raw)
        self.assertEqual(siri.parse_plan('<tool_call>website\nurl=https://example.com/\n</tool_call>')["steps"],
                         [{"do": "website", "url": "https://example.com/"}])  # a site's own "/" stays

    def test_one_value_with_spaces_quotes_or_equals_stays_whole(self):
        self.assertEqual(siri.parse_plan('<tool_call>say\ntext="She said "hi" to you"\n</tool_call>')["say"],
                         'She said "hi" to you')  # a quote inside the value, not the end of it
        for raw, step in (('<tool_call>website\nurl=https://example.com/?q=a b\n</tool_call>',
                           {"do": "website", "url": "https://example.com/?q=a b"}),
                          ('<tool_call>web\nquery=what is e = mc2\n</tool_call>',
                           {"do": "web", "query": "what is e = mc2"}),
                          # name= inside the text is no argument of a step's, so she types all of it
                          ('<tool_call>type\ntext=let total=5\n</tool_call>', {"do": "type", "text": "let total=5"}),
                          ('<tool_call>type\ntext=git config user_name=Hari\n</tool_call>',
                           {"do": "type", "text": "git config user_name=Hari"}),
                          # a " /" ends the call only on its last line, not text the model meant to type
                          ('<tool_call>type\ntext=and /\nkeys=enter /\n</tool_call>',
                           {"do": "type", "text": "and /", "keys": "enter"})):
            self.assertEqual(siri.parse_plan(raw)["steps"], [step], raw)

    def test_a_say_tool_call_is_what_she_says(self):
        raw = ('<tool_call>steps\n[\n  {"do": "open", "app": "Google Chrome"},\n  {"do": "website", "url": '
               '"https://www.youtube.com"}\n]\n</invoke>\n<tool_call>say\nOpening Chrome and heading to YouTube now.\n'
               '</invoke>')
        self.assertEqual(siri.parse_plan(raw), {
            "steps": [{"do": "open", "app": "Google Chrome"}, {"do": "website", "url": "https://www.youtube.com"}],
            "say": "Opening Chrome and heading to YouTube now."})

    def test_both_end_tags_are_not_said(self):
        raw = ('<tool_call>open\n<arg_key>app</arg_key><arg_value>Notepad</arg_value>\n</invoke>\n</tool_call>\n'
               '<tool_call>say\nOpening Notepad.\n</invoke>\n</tool_call>')
        self.assertEqual(siri.parse_plan(raw), {"steps": [{"do": "open", "app": "Notepad"}], "say": "Opening Notepad."})

    def test_steps_and_say_as_arguments(self):
        raw = ('<tool_call>do\n<arg_key>steps</arg_key>\n<arg_value>[{"do": "open", "app": "Google Chrome"}, '
               '{"do": "keys", "keys": "ctrl+t"}]</arg_value><arg_key>say</arg_key>\n<arg_value>Opening Chrome, Hari.'
               '</arg_value>\n</tool_call>')
        self.assertEqual(siri.parse_plan(raw), {
            "steps": [{"do": "open", "app": "Google Chrome"}, {"do": "keys", "keys": "ctrl+t"}],
            "say": "Opening Chrome, Hari."})

    def test_a_skill_keeps_its_own_steps(self):
        # "when I say work mode, ..." opened Gmail and set the volume on 7 October instead of saving the routine
        skill = {"do": "skill", "action": "create", "name": "work-mode", "triggers": ["work mode"],
                 "steps": [{"do": "open", "app": "Spotify"}], "say": "Work mode's on."}
        for raw in ('<tool_call>skill\n<arg_key>action</arg_key>\n<arg_value>create</arg_value><arg_key>name'
                    '</arg_key>\n<arg_value>work-mode</arg_value><arg_key>triggers</arg_key>\n<arg_value>["work mode"]'
                    '</arg_value><arg_key>steps</arg_key>\n<arg_value>[{"do": "open", "app": "Spotify"}]</arg_value>'
                    '<arg_key>say</arg_key>\n<arg_value>Work mode\'s on.</arg_value>\n</tool_call>',
                    '<tool_call>skill\naction="create"\nname="work-mode"\ntriggers=["work mode"]\nsteps=[{"do": '
                    '"open", "app": "Spotify"}]\nsay="Work mode\'s on."\n</tool_call>',
                    '<tool_call>skill\n' + json.dumps({k: v for k, v in skill.items() if k != "do"}) + '</tool_call>'):
            self.assertEqual(siri.parse_plan(raw), {"steps": [skill], "say": ""}, raw)

    def test_what_a_say_call_says(self):
        for raw in ('<tool_call>say\n<arg_key>text</arg_key>\n<arg_value>Hello, Hari.</arg_value>\n</tool_call>',
                    '<tool_call>say\ntext="Hello, Hari."\n</tool_call>',
                    '<tool_call>do\n{"say": "Hello, Hari."}\n</tool_call>'):
            self.assertEqual(siri.parse_plan(raw), {"steps": [], "say": "Hello, Hari."}, raw)

    def test_no_made_up_steps(self):
        broken = ('<tool_call>do\n<arg_key>recall</arg_value><arg_key>day</arg_key>\n<arg_value>2026-10-06'
                  '</arg_value>\n</tool_call>')
        self.assertEqual(siri.parse_plan(broken)["steps"], [])
        prose = siri.parse_plan("<tool_call>Here are the top AI stories: OpenAI shared new maths results.</tool_call>")
        self.assertEqual(prose, {"steps": [], "say": "Here are the top AI stories: OpenAI shared new maths results."})
        self.assertEqual(siri.parse_plan('{"steps": [{"do": "search", "query": "x"}, {"do": "new_tab"}], "say": ""}')
                         ["steps"], [{"do": "new_tab"}])

    def test_shapes_that_already_worked(self):
        cases = {
            '<tool_call>skill_view\n<arg_key>name</arg_key>\n<arg_value>chrome-search</arg_value>\n</tool_call>':
                [{"do": "skill_view", "name": "chrome-search"}],
            '<tool_call>do\n{"steps": [{"do": "youtube", "query": "CareerID", "play": true}]}\n</tool_call>':
                [{"do": "youtube", "query": "CareerID", "play": True}],
            '<tool_call>do\n<arg_key>do</arg_key>\n<arg_value>open</arg_value><arg_key>app</arg_key>\n<arg_value>'
            'Google Chrome</arg_value>\n</tool_call>': [{"do": "open", "app": "Google Chrome"}],
            '<tool_call>timer\n<arg_key>seconds</arg_key>\n<arg_value>300</arg_value>\n</tool_call>\n<tool_call>youtube'
            '\n<arg_key>query</arg_key>\n<arg_value>lofi music</arg_value><arg_key>play</arg_key>\n<arg_value>true'
            '</arg_value>\n</tool_call>': [{"do": "timer", "seconds": 300},
                                           {"do": "youtube", "query": "lofi music", "play": True}],
            '<tool_call>do\n{"do":"youtube","query":"Arijit Singh songs","play":true}\n{"do":"volume","to":"up"}\n'
            '</arg_value>': [{"do": "youtube", "query": "Arijit Singh songs", "play": True},
                             {"do": "volume", "to": "up"}],
            '<tool_call>recall\n\n</tool_call>': [{"do": "recall"}],
            '{"do": "open_google_chrome"}': [{"do": "open", "app": "google chrome"}],
            '{"steps": [{"do": "click", "x": 5, "y": 6}, {"do": "wait", "seconds": 1}], "say": "", "done": false}':
                [{"do": "click", "x": 5, "y": 6}, {"do": "wait", "seconds": 1}],
        }
        for raw, steps in cases.items():
            self.assertEqual(siri.parse_plan(raw)["steps"], steps, raw)


class AskAgain(unittest.TestCase):
    """M4: an empty reply, or one with nothing she can do, is asked again once, in the time that's left."""

    def ask(self, *replies, **kw):
        self.model = FakeModel(*replies)
        with patch.object(siri, "ask_model", self.model):
            return siri.ask_plan([{"role": "user", "content": "who directed Iron Man 2?"}], **kw)

    def test_an_empty_reply_is_asked_again(self):
        raw, plan, _, _ = self.ask("", '{"steps": [], "say": "Jon Favreau."}', deadline=12.0)
        self.assertEqual(plan["say"], "Jon Favreau.")
        self.assertEqual(len(self.model.calls), 2)
        self.assertLessEqual(self.model.calls[1][1]["deadline"], 12.0)  # the same deadline, not a new one

    def test_only_made_up_steps_is_asked_again(self):
        _, plan, _, _ = self.ask('{"steps": [{"do": "Here"}], "say": ""}', '{"steps": [{"do": "new_tab"}], "say": ""}')
        self.assertEqual(plan["steps"], [{"do": "new_tab"}])

    def test_not_again_without_time_or_when_asked_not_to(self):
        self.ask("", '{"say": "late"}', deadline=2.0)
        self.assertEqual(len(self.model.calls), 1)
        self.ask("", '{"say": "late"}', again=False)
        self.assertEqual(len(self.model.calls), 1)

    def test_a_review_that_found_nothing_is_an_answer(self):
        _, plan, _, _ = self.ask('{"memory": [], "skills": [], "words": {}}')
        self.assertEqual(len(self.model.calls), 1)
        self.assertEqual(plan["memory"], [])

    def test_a_failed_retry_keeps_the_first_answer(self):
        calls = []

        def model(messages, **kw):
            calls.append(kw)
            if len(calls) > 1:
                raise TimeoutError("no answer in 9 s")
            return "", {}, "fake-model"
        with patch.object(siri, "ask_model", model):
            raw, plan, _, _ = siri.ask_plan([{"role": "user", "content": "hi"}])
        self.assertEqual((raw, plan), ("", {"steps": [], "say": ""}))
        self.assertEqual(len(calls), 2)

    def test_think_asks_again_only_when_named(self):
        with patch.object(siri, "ask_plan", wraps=siri.ask_plan) as ask, \
                patch.object(siri, "ask_model", FakeModel('{"to": "others"}')), \
                patch.object(siri.history, "recent", lambda *a, **k: []), \
                patch.object(siri, "context", lambda: ""), patch.object(siri, "memory_block", lambda: ""):
            siri.think("open the door for him", "cold")
        self.assertIs(ask.call_args.kwargs["again"], False)


class RoomTalk(unittest.TestCase):
    """M6: a reply that only says the words weren't for her is let go, not said out loud."""

    def setUp(self):
        p = patch.object(siri, "media_playing", lambda: False)
        p.start()
        self.addCleanup(p.stop)

    def test_not_for_me_is_let_go(self):
        for said in ("That sounded like he was talking to someone else in the room.",
                     "That was to others, Hari \u2014 people talking near the PC, not to me.",
                     "That sounded like someone talking to a person nearby, not a request for me.",
                     "It\u2019s probably to someone nearby, not to me. The sentence is too garbled to summarise.",
                     "That's for someone else, Harish \u2014 not me.", "That sounded like someone else, not me.",
                     "That sounded like someone speaking nearby, not a request for me."):
            self.assertTrue(siri.let_go({"steps": [], "say": said}), said)

    def test_asking_what_room_talk_meant_is_let_go(self):
        """Free models' questions back to room talk, 9 to 21 October: without her name she never asks what you meant."""
        for said in ("What do you need me to do, Hari?", "Merlin is what, Hari? Can you finish the sentence?",
                     "I'm lost, Hari \u2014 can you repeat that? Couldn't make out what you meant.",
                     "Not following you, Hari \u2014 what do you want me to do? Just say it.",
                     "Could you clarify what you'd like me to do with that message?",
                     "Notepad's open \u2014 what do you want me to do with it, Hari?"):
            self.assertTrue(siri.let_go({"steps": [], "say": said}), said)
        for said in ("What would you like me to type to Amma?", "Which Harish profile should I open?",
                     "Who should I message, and what should it say?"):  # what she needs to know to do it
            self.assertIsNone(siri.let_go({"steps": [], "say": said}), said)

    def test_an_answer_is_not_let_go(self):
        for plan in ({"steps": [], "say": "It's 5 PM."},
                     {"steps": [], "say": "It was said to you, Hari. Your C drive is nearly full."},
                     {"steps": [], "say": "I'm here now, Hari. I thought you were speaking to someone else, so I "
                                          "stayed quiet. What's up?"},
                     {"steps": [], "say": "Because you hadn't called me by name first, and I wasn't sure whether you "
                                          "were speaking to me or talking to someone else."},
                     {"steps": [], "say": "That's not for me to judge, but it got good reviews."},
                     {"steps": [], "say": "It's someone else's number, not one I know."},
                     {"steps": [], "say": "You can share it with someone else."},
                     {"steps": [{"do": "open", "app": "Notepad"}], "say": "Opening it for someone else? Sure."}):
            self.assertIsNone(siri.let_go(plan), plan)


class Learning(Turn):
    """M7: overheard room talk isn't learned from, and doesn't put facts in her memory."""

    def test_overheard_i_remember_is_not_saved(self):
        memory = {"do": "memory", "action": "add", "target": "user", "content": "Nine to Kerawal"}
        plan = self.think("I remember nine to Kerawal", "cold",
                          json.dumps({"to": "you", "steps": [memory], "say": "Okay, I'll remember that."}))
        self.assertIsNone(plan)  # not "Okay, I'll remember that" with nothing remembered
        plan = self.think("I remember Kerawal, open Notepad", "cold",
                          json.dumps({"to": "you", "steps": [memory, {"do": "open", "app": "Notepad"}], "say": ""}))
        self.assertEqual(plan["steps"], [{"do": "open", "app": "Notepad"}])

    def test_overheard_remembering_in_other_words_is_not_saved(self):
        memory = {"do": "memory", "action": "add", "target": "user", "content": "Nine to Kerawal"}
        for said in ("I still remember nine to Kerawal", "I don't remember nine to Kerawal",
                     "We'll never forget nine to Kerawal", "We need to remember nine to Kerawal",
                     "Do you remember nine to Kerawal"):
            self.assertIsNone(self.think(said, "cold", json.dumps({"to": "you", "steps": [memory], "say": "Noted."})),
                              said)

    def test_asked_to_keep_it_in_other_words_is_saved(self):
        step = {"do": "memory", "action": "add", "target": "user", "content": "Their website is careerid.in"}
        for said in ("note that my website is careerid.in", "keep in mind my website is careerid.in",
                     "don't forget my website is careerid.in", "I need you to remember my website is careerid.in"):
            plan = self.think(said, "cold", json.dumps({"to": "you", "steps": [step], "say": ""}))
            self.assertEqual((plan or {}).get("steps"), [step], said)

    def test_remember_said_without_her_name_is_saved(self):
        step = {"do": "memory", "action": "add", "target": "user", "content": "Their website is careerid.in"}
        plan = self.think("remember that my website is careerid.in", "cold",
                          json.dumps({"to": "you", "steps": [step], "say": ""}))
        self.assertEqual(plan["steps"], [step])
        plan = self.think("my website is careerid.in", False, json.dumps({"steps": [step], "say": ""}))
        self.assertEqual(plan["steps"], [step])  # with her name, as before

    def test_an_overheard_chat_does_not_start_a_review(self):
        started = []
        with patch.object(siri, "review", lambda *a, **k: started.append(1)), \
                patch.dict(siri._learning, turns=10, last=0.0):
            siri.learn_later("What did he say to you", [], [], "cold")
            time.sleep(0.05)
            self.assertEqual(started, [])
            siri.learn_later("open notepad and type hi then save it", [{"do": "open"}] * 3, [], False)
            time.sleep(0.05)
        self.assertEqual(started, [1])

    def test_a_review_leaves_out_overheard_chat(self):
        """After a restart too: her history keeps which turns she heard without her name (its gate). The list of
        them in memory that this was before was gone once she restarted, and the room talk was looked back at."""
        root = tempfile.mkdtemp(prefix="heyjev-planner-")
        self.addCleanup(shutil.rmtree, root, ignore_errors=True)
        model = FakeModel('{"memory": [], "skills": [], "words": {}}')
        with patch.object(history, "DB", os.path.join(root, "history.db")), \
                patch.object(history, "DAYS_DIR", os.path.join(root, "days")):
            history.add("Who was that on the phone", "", "Sounds like Ravi.",
                        '{"steps": [], "say": "Sounds like Ravi."}', gate="cold")
            history.add("no, I said Zostel", "", "Got it, Zostel.", '{"steps": [], "say": "Got it, Zostel."}',
                        gate="follow")
            history.add("open Zostel", "opened zostel.com", "", '{"steps": [{"do": "website", "url": '
                                                                 '"https://zostel.com"}]}')
            with patch.object(siri.history, "recent", RECENT), patch.object(siri, "ask_model", model), \
                    patch.object(siri, "skills_block", lambda: ""), \
                    patch.dict(siri._learning, lock=threading.Lock()):  # not one an earlier test's review holds
                siri.review(wait=0)
        said = model.calls[0][0][-1]["content"]
        self.assertIn("Zostel", said)
        self.assertNotIn("on the phone", said)


class WebSearch(unittest.TestCase):
    """M5: the sources share one deadline, and what's there by then is the answer."""

    def setUp(self):
        web._cache.clear()
        self.addCleanup(web._cache.clear)

    def test_slow_sources_dont_hold_up_the_answer(self):
        wiki = []

        def slow(*a, **k):
            time.sleep(2.0)
            return {"text": "late", "url": ""}
        with patch.object(web, "_instant", slow), patch.object(web, "news", slow), \
                patch.object(web, "_wikipedia", lambda *a, **k: wiki.append(1) or [{"title": "Iron Man 2"}]), \
                patch.object(web, "SEARCH_WAIT", 0.3, create=True):
            t = time.time()
            found = web.search("who directed iron man 2")
            took = time.time() - t
            self.assertLess(took, 1.5)
            self.assertEqual(found, {"wikipedia": [{"title": "Iron Man 2"}]})
            web.search("who directed iron man 2")  # what was late isn't left out for the next ten minutes
        self.assertEqual(len(wiki), 2)


class WebCache(unittest.TestCase):
    """27 October, found while mapping: web._cache never let anything go, every page she read kept while she ran."""

    def setUp(self):
        web._cache.clear()
        self.addCleanup(web._cache.clear)

    def test_only_the_latest_looks_are_kept(self):
        self.assertEqual(web.CACHE_MOST, 256)
        with patch.object(web, "CACHE_MOST", 3):
            for n in range(4):
                web._cached("read", n, 600, lambda n=n: f"page {n}")
            self.assertEqual(web._cached("read", 1, 600, lambda: self.fail("read again")), "page 1")  # still kept
            web._cached("read", 4, 600, lambda: "page 4")
        self.assertEqual(list(web._cache), [("read", 3), ("read", 1), ("read", 4)])  # 1 was used again, 2 wasn't


class DefaultModel(unittest.TestCase):
    """27 October, found while mapping: the model a fresh install starts on was space-bunny-free, gone (410) from
    OpenCode since 11 October, so every request failed until Settings refreshed the list."""

    def test_a_fresh_install_starts_on_a_free_model_that_answers(self):
        with patch.dict(siri.os.environ, {"OPENCODE_MODEL": ""}), patch.object(siri.settings, "_data", {}):
            model = siri.settings.get("llm_model")
        self.assertEqual(model, siri.FAST_MODEL)
        self.assertTrue(siri.opencode.allowed(model))
        self.assertIn(model, siri.opencode.FALLBACK_FREE)


class CurrentYears(unittest.TestCase):
    """22 October 2026: "GTA six launched any new trailer" was searched as "GTA 6 new trailer 2024 2025", the model's
    own "now", and found 2024's stories a week after the launch trailer came out."""
    NOW = time.localtime().tm_year

    def q(self, query, said):
        return siri.current_query(query, said)

    def test_a_recent_year_they_didnt_say_is_taken_out(self):
        a, b = self.NOW - 2, self.NOW - 1
        self.assertEqual(self.q(f"GTA 6 new trailer {a} {b}", "GTA six launched any new trailer"), "GTA 6 new trailer")
        self.assertEqual(self.q(f"FIFA World Cup {self.NOW - 4} winner", "who won the last world cup"),
                         "FIFA World Cup winner")
        self.assertEqual(self.q(f"Python latest version in {a}-{str(b)[2:]}", "python latest version"),
                         "Python latest version")

    def test_one_they_said_or_counted_back_to_stays_and_so_does_this_years(self):
        old = self.NOW - 2
        for query, said in ((f"who won the {old} T20 World Cup", f"who won the {old} T20 World Cup"),
                            (f"India GDP growth {self.NOW - 1}", "what was India's GDP growth last year"),
                            (f"iPhone price {self.NOW}", "latest iphone price"),
                            (f"x {old}", ""),  # the words aren't known
                            ("World War 2 1945", "when did world war two end")):
            self.assertEqual(self.q(query, said), query, said)

    def test_every_search_she_makes_goes_without_it(self):
        searched = []
        siri.agent.SAID.set("GTA six launched any new trailer")
        self.addCleanup(siri.agent.SAID.set, "")
        with patch.object(siri.web, "search", lambda q, links=False: searched.append(q) or {}), \
                patch.object(siri.web, "news", lambda t, n=6, links=False: searched.append(t) or []):
            out = siri.run_info([{"do": "web", "query": f"GTA 6 trailer {self.NOW - 1}"},
                                 {"do": "news", "topic": f"GTA 6 {self.NOW - 1}"}])
        self.assertEqual(searched, ["GTA 6 trailer", "GTA 6"])
        self.assertIn('"web": "GTA 6 trailer"', out)


class WebRead(unittest.TestCase):
    """A20: names that point at this PC or the home network, and redirects to them, are never fetched."""

    ADDRESSES = {"127.0.0.1.nip.io": "127.0.0.1", "192.168.1.1.nip.io": "192.168.1.1", "localtest.me": "::1",
                 "example.com": "93.184.215.14", "en.wikipedia.org": "103.102.166.224", "192.168.1.1": "192.168.1.1"}

    def setUp(self):
        web._cache.clear()
        self.addCleanup(web._cache.clear)
        self.fetched = []

        def lookup(host, *a, **k):
            if host not in self.ADDRESSES:
                raise OSError("no such host")
            ip = self.ADDRESSES[host]
            return [(2 if "." in ip else 23, 1, 6, "", (ip, 80))]
        p = patch("socket.getaddrinfo", lookup)
        p.start()
        self.addCleanup(p.stop)

    class Page:
        def __init__(self, url, status=200, location=None, body=b"<html><title>Hi</title><p>" + b"words " * 20 + b"</p>"):
            self.url, self.status_code, self.body = url, status, body
            self.headers = {"content-type": "text/html", **({"location": location} if location else {})}
            self.is_redirect, self.encoding = bool(location), "utf-8"

        def raise_for_status(self):
            pass

        def iter_content(self, n):
            yield self.body

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            pass

    def get(self, routes):
        def get(url, allow_redirects=True, **kw):
            while True:
                self.fetched.append(url)
                page = routes(url)
                if allow_redirects and page.is_redirect:  # what requests does by itself
                    url = urljoin(url, page.headers["location"])
                    continue
                return page
        return get

    def test_names_that_point_home_are_not_public(self):
        for url in ("http://127.0.0.1.nip.io:8080/", "http://192.168.1.1.nip.io/admin", "http://localtest.me/",
                    "http://nowhere.invalid/"):
            self.assertFalse(web._public(url), url)
        self.assertTrue(web._public("https://example.com/page"))

    def test_a_redirect_home_is_not_followed(self):
        def routes(url):
            if "example.com" in url:
                return self.Page(url, 302, "http://192.168.1.1/admin")
            return self.Page(url, body=b"router admin page")
        with patch.object(web.S, "get", self.get(routes)):
            with self.assertRaisesRegex(RuntimeError, "only read pages on the internet"):
                web.read("https://example.com/story")
        self.assertEqual(self.fetched, ["https://example.com/story"])

    def test_a_public_redirect_is_read(self):
        def routes(url):
            if url.endswith("/story"):
                return self.Page(url, 301, "/wiki/Iron_Man_2")
            return self.Page(url)
        with patch.object(web.S, "get", self.get(routes)):
            page = web.read("https://example.com/story")
        self.assertEqual(page["url"], "https://example.com/wiki/Iron_Man_2")
        self.assertIn("words", page["text"])


class PromptBits(unittest.TestCase):
    """M8: the clock says which time zone it is, and a plain timer doesn't get the example's tea."""

    def test_now_has_its_time_zone(self):
        with patch.object(siri.win, "front_app_name", lambda: "Google Chrome"), \
                patch.object(siri.win, "media_session", lambda: None), \
                patch.object(siri, "profile_names", lambda key: []):
            self.assertRegex(siri.context(), r"Now: .*UTC[+-]\d\d:\d\d")

    def test_timer_label_only_when_named(self):
        line = next(l for l in siri.PROMPT.splitlines() if l.startswith('{"do":"timer"'))
        self.assertIn("label and alert only", line)

    def test_night_light_has_its_own_step(self):
        """With its thinking off, Haiku turned on dark mode for "turn on night light" 4 times in 4: it had no step
        of its own, only a walk through Settings."""
        self.assertIn('{"do":"dark_mode","on":true} {"do":"night_light","on":true}', siri.PROMPT)


if __name__ == "__main__":
    unittest.main()
