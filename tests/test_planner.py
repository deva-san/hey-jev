"""The model path: parse_plan, ask_plan, think, let_go, the learning loop, and web.py's search and read. The model, the
web and the PC are all stubbed: nothing goes online or acts."""
import json
import time
import unittest
from unittest.mock import patch
from urllib.parse import urljoin

from tests.support import siri

import web  # noqa: E402


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
        for name, value in (("skills_block", ""), ("memory_block", ""), ("context", ""), ("soul", "You are Jev.")):
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

    def test_a_named_request_to_schedule_still_gets_the_retry(self):
        plan = self.think("remind me every day at 9 PM to take my medicine", False,
                          '{"steps": [], "say": "Okay, I will remind you."}',
                          '{"steps": [{"do": "schedule", "when": "", "repeat": "daily at 9 PM", "description": '
                          '"Take medicine", "task": {"kind": "reminder", "text": "take my medicine"}}], "say": ""}')
        self.assertEqual(len(self.asked_again()), 1)
        self.assertEqual(plan["steps"][0]["do"], "schedule")


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

    def test_a_say_tool_call_is_what_she_says(self):
        raw = ('<tool_call>steps\n[\n  {"do": "open", "app": "Google Chrome"},\n  {"do": "website", "url": '
               '"https://www.youtube.com"}\n]\n</invoke>\n<tool_call>say\nOpening Chrome and heading to YouTube now.\n'
               '</invoke>')
        self.assertEqual(siri.parse_plan(raw), {
            "steps": [{"do": "open", "app": "Google Chrome"}, {"do": "website", "url": "https://www.youtube.com"}],
            "say": "Opening Chrome and heading to YouTube now."})

    def test_steps_and_say_as_arguments(self):
        raw = ('<tool_call>do\n<arg_key>steps</arg_key>\n<arg_value>[{"do": "open", "app": "Google Chrome"}, '
               '{"do": "keys", "keys": "ctrl+t"}]</arg_value><arg_key>say</arg_key>\n<arg_value>Opening Chrome, Hari.'
               '</arg_value>\n</tool_call>')
        self.assertEqual(siri.parse_plan(raw), {
            "steps": [{"do": "open", "app": "Google Chrome"}, {"do": "keys", "keys": "ctrl+t"}],
            "say": "Opening Chrome, Hari."})

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

if __name__ == "__main__":
    unittest.main()
