"""Settings > Answer model: any provider and any of its models (providers.py), and opencode.chat sending to each the
way it takes it. No network: the lists and replies are fakes."""
import importlib.util
import os
import unittest
from unittest import mock

from tests.support import ROOT

import providers
import requests

# support.py makes opencode.chat a tripwire, so these load their own copy of opencode to send with
_spec = importlib.util.spec_from_file_location("opencode_under_test", os.path.join(ROOT, "opencode.py"))
oc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(oc)


class Reply:
    def __init__(self, status, body=None):
        self.status_code, self.ok, self.reason = status, status < 400, "Bad Request" if status >= 400 else "OK"
        self.body = body or {"choices": [{"message": {"content": "OK"}}], "usage": {}}
        self.text = str(self.body)

    def json(self):
        return self.body

    def close(self):
        pass


class Models(unittest.TestCase):
    def test_a_saved_model_is_its_provider_and_its_id_there(self):
        for saved, pid, model_id in (("openai/gpt-5.2", "openai", "gpt-5.2"), ("big-pickle", "opencode", "big-pickle"),
                                     ("openrouter/openai/gpt-5", "openrouter", "openai/gpt-5"),
                                     ("kilo/nvidia/nemotron-3.5-lightning:free", "kilo",
                                      "nvidia/nemotron-3.5-lightning:free")):
            p, got = providers.split(saved)
            self.assertEqual((p.id, got), (pid, model_id))
            self.assertEqual(providers.full(p, got), saved)

    def test_the_list_is_chat_models_only_newest_first(self):
        rows = [{"id": "text-embedding-3-large", "created": 9}, {"id": "gpt-image-1", "created": 9},
                {"id": "flint-40b-free", "created": 1}, {"id": "gpt-6.1", "created": 1},
                {"id": "gpt-5.2", "created": 5},
                {"id": "picture-maker", "architecture": {"output_modalities": ["image"]}},
                {"id": "models/gemini-3.1-pro"}, {"id": "gpt-5.2", "created": 5}]
        self.assertEqual([m["id"] for m in providers._models(providers.BY_ID["openai"], rows)],
                         ["gpt-5.2", "gpt-6.1", "flint-40b-free", "gemini-3.1-pro"])

    def test_free_is_what_the_provider_says(self):
        router = providers.BY_ID["openrouter"]
        zero = {"pricing": {"prompt": "0", "completion": "0"}}
        self.assertTrue(providers.is_free(router, "x/y", zero))
        self.assertTrue(providers.is_free(router, "x/y:free"))
        self.assertFalse(providers.is_free(router, "x/y", {"pricing": {"prompt": "0.000001", "completion": "0"}}))
        self.assertTrue(providers.is_free(providers.OPENCODE, "big-pickle"))
        self.assertFalse(providers.is_free(providers.OPENCODE, "gpt-6.1-sol"))
        self.assertTrue(providers.is_free(providers.BY_ID["ollama"], "llama3"))


class Sending(unittest.TestCase):
    def send(self, model, replies, key="key", **extra):
        sent = []

        def post(url, headers=None, json=None, **kw):
            sent.append((url, headers, dict(json)))
            return replies.pop(0)
        self.addCleanup(oc.PLAIN.clear)
        with mock.patch.object(oc.SESSION, "post", post), mock.patch("secrets_store.get_secret", return_value=key):
            text, _, _ = oc.chat("oc-key", [{"role": "user", "content": "hi"}], max_tokens=50, model=model, **extra)
        return text, sent

    def test_openai_gets_max_completion_tokens_on_its_own_url_with_its_own_key(self):
        text, sent = self.send("openai/gpt-5.2", [Reply(200)])
        url, headers, body = sent[0]
        self.assertEqual(url, "https://api.openai.com/v1/chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer key")
        self.assertEqual((body["model"], body["max_completion_tokens"]), ("gpt-5.2", 50))
        self.assertNotIn("max_tokens", body)
        self.assertEqual(text, "OK")

    def test_a_provider_that_wont_take_reasoning_effort_is_asked_again_without_and_from_then_on(self):
        _, sent = self.send("mistral/mistral-large-3", [Reply(422, {"error": "Extra inputs"}), Reply(200)],
                            reasoning_effort="low")
        self.assertEqual(sent[0][2]["reasoning_effort"], "low")
        self.assertNotIn("reasoning_effort", sent[1][2])
        _, sent = self.send("mistral/mistral-large-3", [Reply(200)], reasoning_effort="low")
        self.assertNotIn("reasoning_effort", sent[0][2])

    def test_opencode_and_kilo_leave_a_400_to_ask_model(self):
        """siri.ask_model asks again without reasoning_effort itself, as before there were other providers."""
        for model in ("big-pickle", "kilo/nvidia/nemotron-3.5-lightning:free"):
            with self.assertRaisesRegex(RuntimeError, r"^OpenCode \(.*\) 400"):
                self.send(model, [Reply(400, {"error": "no"})], reasoning_effort="low")

    def test_opencode_still_uses_the_key_it_was_given(self):
        _, sent = self.send("big-pickle", [Reply(200)], key=None)
        self.assertEqual(sent[0][1]["Authorization"], "Bearer oc-key")
        self.assertTrue(sent[0][0].startswith(providers.OPENCODE_BASE))

    def test_no_key_says_where_to_add_it(self):
        with self.assertRaisesRegex(RuntimeError, "Add your OpenAI key"):
            self.send("openai/gpt-5.2", [], key=None)

    def test_ollama_needs_no_key_and_says_when_it_isnt_running(self):
        def refused(*a, **k):
            raise requests.ConnectionError("refused")
        with mock.patch.object(oc.SESSION, "post", refused), mock.patch("secrets_store.get_secret", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "isn't running on this PC"):
                oc.chat(None, [{"role": "user", "content": "hi"}], model="ollama/llama3")
        self.assertEqual(oc.explain("Ollama (ollama/llama3) isn't running on this PC, start it first"),
                         "isn't running on this PC, start it first")


if __name__ == "__main__":
    unittest.main()
