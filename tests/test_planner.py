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
