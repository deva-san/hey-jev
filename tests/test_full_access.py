"""Full access (28 October 2026, after Atticus's): off unless you turn it on in the window. On, a message typed into
the chat she opened and read back, or an app she looked up, goes ahead without "Send it?", said first as a statement;
only for words said to her by name or as a follow-up, that she was sure of, with nothing read this turn. Everything
else asks as ever, and no plan, voice or phone can turn it on. No model, voice or network."""
import time
import unittest
from unittest import mock

from tests.support import siri

READY = {"app": "whatsapp", "say": "WhatsApp", "contact": "Mum", "text": "running late", "checked": True,
         "to": "Mum"}


class Heard(str):
    sure = 1.0


def unsure(text):
    h = Heard(text)
    h.sure = 0.5
    return h


class Base(unittest.TestCase):
    def setUp(self):
        self.saved = {}
        real_get, real_put = siri.settings.get, siri.settings.put

        def get(key, *a):
            return self.saved[key] if key in self.saved else real_get(key, *a)

        def put(key, value):
            self.saved[key] = value
        for target, name, value in ((siri.settings, "get", get), (siri.settings, "put", put)):
            p = mock.patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(lambda: (siri.STAGED.update(ready=None, until=0.0),
                                 siri.STAGED_INSTALL.update(ready=None, until=0.0),
                                 siri.TURN_TAINT.__setitem__(0, False),
                                 siri.SEND_OK.update(until=0.0),
                                 siri.PENDING.update(plan=None, until=0.0, origin="voice")))

    def on(self, until=0):
        self.saved.update(full_access=True, full_access_until=until)

    def staged(self, **ready):
        siri.STAGED.update(ready={**READY, **ready}, until=time.time() + 60)
        return {"steps": [], "say": "\u201crunning late\u201d to Mum on WhatsApp. Send it?",
                "confirm": {"steps": [{"do": "message_send"}], "say": ""}}


class Rules(Base):
    def test_off_unless_turned_on(self):
        self.assertFalse(siri.full_access_ok(False))
        self.on()
        self.assertTrue(siri.full_access_ok(False))
        self.assertTrue(siri.full_access_ok(True))  # straight after she answered

    def test_never_from_across_the_room_unsure_or_after_reading(self):
        self.on()
        self.assertFalse(siri.full_access_ok("cold"))
        self.assertFalse(siri.full_access_ok(False, sure=0.5))
        siri.TURN_TAINT[0] = True
        self.assertFalse(siri.full_access_ok(False))

    def test_for_an_hour_runs_out_and_turns_itself_off(self):
        self.on(until=time.time() - 1)
        with mock.patch("builtins.print"):
            self.assertFalse(siri.full_access_ok(False))
        self.assertFalse(self.saved["full_access"])

    def test_only_a_read_back_text_in_a_chat_she_opened_or_an_app_she_found(self):
        plan = self.staged()
        self.assertEqual(siri.full_go(plan), plan["confirm"])
        for ready in ({"checked": False}, {"to": "Mother"}, {"files": ["C:/cv.pdf"]}, {"other": True},
                      {"app": "signal"}):
            with self.subTest(ready=ready):
                self.assertIsNone(siri.full_go(self.staged(**ready)))
        siri.STAGED_INSTALL.update(ready={"name": "VLC", "version": "3.0", "action": "install"}, until=time.time() + 60)
        install = {"steps": [], "say": "Install it?", "confirm": {"steps": [{"do": "install_run"}], "say": ""}}
        self.assertEqual(siri.full_go(install), install["confirm"])
        self.assertEqual(siri.full_line(install["confirm"]), "Installing VLC 3.0.")
        for confirm in ({"steps": [{"do": "shutdown"}]}, {"steps": [{"do": "agent_resume"}]},
                        {"steps": [{"do": "message", "app": "whatsapp", "contact": "Mum", "text": "hi"}]}):
            with self.subTest(confirm=confirm):
                self.assertIsNone(siri.full_go({"steps": [], "say": "?", "confirm": confirm}))

    def test_she_says_what_shes_doing(self):
        plan = self.staged()
        self.assertEqual(siri.full_line(plan["confirm"]), "Sending \u201crunning late\u201d to Mum on WhatsApp.")

    def test_only_the_window_turns_it_on(self):
        for said in ("turn on full access", "give yourself full access", "turn off safe mode", "stop asking me"):
            with self.subTest(said=said):
                plan = siri._quick(said)
                self.assertEqual(plan["say"], "Only you can turn that on, in Settings, under Safety.")
                self.assertNotIn("full_access", self.saved)

    def test_anyone_can_turn_it_off(self):
        for said in ("safe mode", "turn off full access", "ask me first", "safe mode on"):
            with self.subTest(said=said):
                self.on()
                with mock.patch("builtins.print"):
                    plan = siri._quick(said)
                self.assertIn("Full access is off", plan["say"])
                self.assertFalse(self.saved["full_access"])

    def test_a_plan_cant_turn_it_on(self):
        for step in ({"do": "full_access", "on": True}, {"do": "settings", "full_access": True}):
            with self.subTest(step=step):
                self.assertEqual(siri._known([step]), [])

    def test_the_planner_is_told_only_while_its_on(self):
        self.assertNotIn("Full access is on", siri.gated_blocks("send hi to mum", [])[2])
        self.on()
        self.assertIn("Full access is on", siri.gated_blocks("send hi to mum", [])[2])


class Turns(Base):
    """A whole turn, run_plan recorded: with it on, the statement and then the send, nothing left waiting."""

    def setUp(self):
        super().setUp()
        self.ran, self.taint = [], False

        def run_plan(plan, notify):
            self.ran.append(plan)
            return [], False, None, [plan.get("say") or ""]

        def quick(words, gate=False, sure=1.0):
            siri.TURN_TAINT[0] = self.taint  # as think sets it, after handle starts the turn afresh
            return self.staged()
        for name, value in (("run_plan", run_plan), ("quick", quick), ("learn_later", lambda *a, **k: None),
                            ("show_ask", lambda *a, **k: None), ("emit", lambda *a, **k: None)):
            p = mock.patch.object(siri, name, value)
            p.start()
            self.addCleanup(p.stop)
        quiet = mock.patch("builtins.print")
        quiet.start()
        self.addCleanup(quiet.stop)

    def turn(self, text="send running late to mum on whatsapp", gate=False):
        siri.HER.stop.clear()
        siri.handle(text if not isinstance(text, str) or hasattr(text, "sure") else Heard(text), str(text),
                    gate=gate)

    def test_off_it_asks_and_waits_for_your_yes(self):
        self.turn()
        self.assertEqual(len(self.ran), 1)
        self.assertIn("Send it?", self.ran[0]["say"])
        self.assertEqual(siri.PENDING["plan"]["steps"], [{"do": "message_send"}])

    def test_on_it_says_so_and_sends(self):
        self.on()
        self.turn()
        self.assertEqual([p.get("say") for p in self.ran],
                         ["Sending \u201crunning late\u201d to Mum on WhatsApp.", ""])
        self.assertEqual(self.ran[1]["steps"], [{"do": "message_send"}])
        self.assertGreater(siri.SEND_OK["until"], time.time())  # armed for that one send, as a yes would
        self.assertIsNone(siri.PENDING["plan"])

    def test_on_it_still_asks_when_unsure_or_after_reading(self):
        self.on()
        self.turn(unsure("send running late to mum on whatsapp"))
        self.assertIn("Send it?", self.ran[-1]["say"])
        self.ran.clear()
        self.taint = True
        self.turn()
        self.assertIn("Send it?", self.ran[-1]["say"])
        self.assertEqual(len(self.ran), 1)

    def test_stop_over_her_and_it_isnt_sent(self):
        self.on()

        def run_plan(plan, notify):
            self.ran.append(plan)
            siri.HER.stop.set()  # "stop", said over the statement
            return [], False, None, [plan.get("say") or ""]
        discarded = []
        with mock.patch.object(siri, "run_plan", run_plan),                 mock.patch.object(siri.messaging, "discard", lambda ready: discarded.append(ready) or True):
            siri.handle(Heard("send running late to mum on whatsapp"), "send running late to mum on whatsapp")
        siri.HER.stop.clear()
        self.assertEqual(len(self.ran), 1)  # the statement, never the send
        self.assertEqual([r["text"] for r in discarded], ["running late"])  # and it's taken out of the chat


if __name__ == "__main__":
    unittest.main()


class SaferByVoice(Base):
    """28 October 2026, after Atticus: settings by voice only ever the safer way, off by name and on only in the
    window; and her break (PAUSE), with no heads-ups or screen commentary, till it's over or you're back."""

    def setUp(self):
        super().setUp()
        self.addCleanup(siri.PAUSE.update, until=0.0, mode=None)

    def test_off_by_voice_on_only_in_the_window(self):
        self.saved.update(learning=True, heads_ups=True, notifications=True)
        for said, key in (("stop learning from me", "learning"), ("no more heads ups", "heads_ups"),
                          ("stop reading my notifications", "notifications")):
            with self.subTest(said=said):
                plan = siri.voice_setting(siri.plain(said))
                self.assertFalse(self.saved[key])
                self.assertIn("back on in Settings", plan["say"])
        self.assertEqual(siri.voice_setting("stop learning")["say"], "That's already off.")
        for said in ("turn on learning", "start the heads ups", "turn on notifications", "learning again"):
            with self.subTest(said=said):
                self.assertEqual(siri.voice_setting(siri.plain(said))["say"], "Only you can turn that on, in Settings.")
        self.assertFalse(self.saved["learning"])
        self.saved["learning"] = True
        self.assertIsNone(siri.voice_setting("stop learning", gate="cold"))  # never from across the room
        self.assertTrue(self.saved["learning"])

    def test_a_break_and_back(self):
        self.saved.update(vision=True, screen_watch=True, screen_commentary=True)
        now = time.time()
        plan = siri.voice_setting(siri.plain("stop listening for twenty minutes"))
        self.assertAlmostEqual(siri.PAUSE["until"] - now, 1200, delta=5)
        self.assertTrue(siri.paused())
        self.assertIn("Hold right Alt if you need me", plan["say"])
        self.assertEqual(siri.screen_mode(), "off")  # no commentary on a break
        self.assertTrue(siri.ready_text(True).startswith("On a break till"))
        self.assertEqual(siri.voice_setting("resume")["say"], "I'm back.")
        self.assertFalse(siri.paused())
        self.assertEqual(siri.screen_mode(), "live")
        self.assertIsNone(siri.voice_setting("resume"))  # not on a break: someone else's "resume"
        self.assertIsNone(siri.voice_setting("pause"))  # a bare pause is the music's
        self.assertIsNone(siri.voice_setting(siri.plain("stop listening for the doorbell")))
        self.assertIsNone(siri.voice_setting("take a break", gate="cold"))
        siri.voice_setting("take a break")
        self.assertAlmostEqual(siri.PAUSE["until"] - time.time(), siri.PAUSE_FOR * 60, delta=5)

    def test_quick_hears_them_with_no_model(self):
        self.saved.update(learning=True)
        with mock.patch("builtins.print"):
            plan = siri.quick("stop learning")
        self.assertEqual(plan["say"], "Okay, I won't learn from what you ask. It's back on in Settings, under Learning.")
        self.assertFalse(self.saved["learning"])
