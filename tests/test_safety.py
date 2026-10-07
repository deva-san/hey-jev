"""Safety gates: what needs a yes after reading the web or messages, what a routine may hold, who a message goes to,
how a browser is started, what keys reach a chat app and which commands may run by themselves."""
import json
import unittest
from unittest import mock

from tests.support import siri


def planned_after(text, steps, looked=({"do": "web", "query": "x"},), gate=False):
    """What think returns when the model first looks something up, then plans steps, without asking any model."""
    plans = [{"steps": [dict(s) for s in looked], "say": ""}, {"steps": steps, "say": "Done."}]
    replies = [(json.dumps(p), p, {}, "test") for p in plans]
    with mock.patch.object(siri, "ask_plan", side_effect=replies), \
            mock.patch.object(siri, "run_info", return_value="[]"), mock.patch.object(siri, "context", return_value=""):
        return siri.think(text, gate)


class AfterReading(unittest.TestCase):
    """README: after reading the web or your messages, anything that changes things needs a yes first."""

    def test_a_message_cant_save_its_own_number_as_mum(self):
        save = {"do": "contact", "action": "save", "alias": "Mum", "app": "whatsapp", "number": "+447700900123"}
        plan = planned_after("any new messages?", [save], looked=({"do": "lookup", "what": "messages"},))
        self.assertEqual(plan["steps"], [])
        self.assertEqual(plan["confirm"]["steps"], [save])
        self.assertIn("+447700900123", plan["say"])  # the yes is to that number, not just to "Mum"

    def test_edit_words_in_the_question_dont_let_a_page_type(self):
        for text in ("look up how to make biryani", "search for tables in python"):
            plan = planned_after(text, [{"do": "keys", "keys": "ctrl+a"}, {"do": "type", "text": "x"}])
            self.assertIn("confirm", plan, text)
            self.assertEqual(plan["say"], "Should I press Control A?")

    def test_sleep_lock_and_closing_ask_after_reading(self):
        for text, step in (("how much sleep do I need", {"do": "sleep"}),
                           ("look up how to lock a door", {"do": "lock"}),
                           ("why does chrome close by itself", {"do": "close", "app": "Google Chrome"})):
            self.assertIn("confirm", planned_after(text, [step]), text)

    def test_lasting_changes_ask_after_reading(self):
        for step in ({"do": "skill", "action": "create", "name": "x", "triggers": ["x"], "steps": []},
                     {"do": "memory", "action": "add", "target": "user", "content": "They bank with X"},
                     {"do": "task_control", "action": "approve", "id": 3}, {"do": "dark_mode", "on": True},
                     {"do": "schedule", "when": "", "repeat": "every 5 minutes", "task": {"kind": "reminder"}},
                     {"do": "cancel_timers"}, {"do": "contact", "action": "remove", "alias": "Mum"}):
            plan = planned_after("look it up", [step])
            self.assertIn("confirm", plan, step)
            self.assertNotEqual(plan["say"], f"Should I {step['do']}?")  # said in words, not the step's name

    def test_showing_things_after_reading_goes_ahead(self):
        steps = [{"do": "website", "url": "https://example.com"}, {"do": "volume", "to": "up"},
                 {"do": "keys", "keys": "ctrl+t"}, {"do": "timer", "seconds": 60}, {"do": "note", "title": "x"}]
        plan = planned_after("look up the match and open it", steps)
        self.assertNotIn("confirm", plan)
        self.assertEqual(plan["steps"], steps)

    def test_a_named_request_with_nothing_read_is_not_asked(self):
        plan = {"steps": [{"do": "type", "text": "hi"}], "say": ""}
        with mock.patch.object(siri, "ask_plan", return_value=(json.dumps(plan), plan, {}, "test")), \
                mock.patch.object(siri, "context", return_value=""):
            self.assertNotIn("confirm", siri.think("say hi", False))

    def test_the_shutdown_is_what_gets_asked(self):
        # a yes to "Should I type that?" used to let the shutdown in the same plan run without its own question
        steps = [{"do": "type", "text": "bye"}, {"do": "shutdown"}]
        self.assertEqual(siri.confirm_question(siri.needs_asking(steps, "do it")), "Should I shut down the computer?")
        plan = planned_after("look it up", steps)
        self.assertEqual(plan["say"], "Should I shut down the computer?")


if __name__ == "__main__":
    unittest.main()
