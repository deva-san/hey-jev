"""Check Settings > Answer without her name: which phrases said near the PC, with no "Hey Jev", she takes as for her,
and what she'd do. The real local filter (siri.could_be_request), quick path and answer model decide, but nothing is
done on the PC: no steps run, nothing is said out loud, and nothing is kept in her history.

    .venv\\Scripts\\python checks\\open_mic.py

The phrases go to the answer model in Settings, as text. Exits with 1 if more than ALLOWED are taken wrong: the
model decides the unclear ones, so it can miss one now and then. It works on a copy of her data (checks/sandbox.py),
so her memory, skills and Settings are the ones it sees; with --real-data on her own.
"""
import contextlib
import io
import os
import sys
import time

# In checks\ since 8 Oct, see checks/listen.py: under a test runner, winplatform.own_data refuses her real folders,
# and run by hand it works on a copy of her data unless it's given --real-data
import sandbox  # noqa: E402

sandbox.use()
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import history  # noqa: E402
import siri  # noqa: E402
import speech  # noqa: E402

# (what's said with no name, what it should be taken as: the first step she'd take, "say" for an answer, None for
#  someone else's conversation)
CASES = [
    ("Open Chrome", "open"),
    ("Hey, open YouTube", "website"),
    ("Turn the volume down a bit", "volume"),
    ("Play some lo-fi music", "youtube"),
    ("Who directed Iron Man", "say"),
    ("What's the time", "say"),
    ("Yeah, open prone", "open"),  # how Nemotron heard "open Chrome" here
    ("New term", "new_tab"),  # "new tab"
    ("Okay yeah, clone the tab", "keys"),  # "close the tab"
    ("YouTube", "website"),
    ("Are you coming for dinner tonight", None),
    ("Can you pass me the water", None),
    ("I told him to open the door", None),
    ("What did he say to you yesterday", None),
    ("Okay, so it is gonna rain later", None),
    ("Mom, where are my keys", None),
    ("Yeah, I'll call you back in five minutes", None),
    ("Why are you so late today", None),
    ("Did you watch the match yesterday", None),
    ("Close the window, it's cold in here", None),
]
ALLOWED = 2
SHOW = ("  quick", "  plan", "  llm", "  (")


def main():
    # This checks the no-name classifier, not a real call that happens to be using the mic during the test.
    # Call-aware routing is checked separately without weakening production behavior.
    siri.win.call_apps = lambda: ()
    taken = []
    siri.run_plan = lambda plan, notify: (taken.append(plan), ([], False, None, []))[1]  # nothing is done
    history.add = lambda *a, **k: None  # nothing is kept
    siri.learn_later = lambda *a, **k: None
    wrong, times = 0, []
    for said, want in CASES:
        taken.clear()
        siri.ROOM.clear()  # each one on its own, not as part of a conversation
        text = speech.heard(said, 0.95)
        log, t = io.StringIO(), time.time()
        with contextlib.redirect_stdout(log):
            what = siri.route(text, "other", open_mic=True)
            if isinstance(what, tuple):
                siri.handle(what[0], what[1], 0, None, what[2])
        secs = time.time() - t
        if isinstance(what, tuple):
            times.append(secs)
        plan = taken[0] if taken else None
        got = None if plan is None else (plan["steps"][0]["do"] if plan.get("steps") else "say")
        good = got == want
        wrong += not good
        where = "on this PC" if not isinstance(what, tuple) else f"{secs:.1f}s"
        print(f"  {'ok ' if good else 'BAD'} {said!r:44} -> {str(got):8} (want {want}, {where})")
        if not good:
            for line in log.getvalue().splitlines():
                if line.startswith(SHOW):
                    print(f"        {line.strip()[:150]}")
            if plan:
                print(f"        she'd say: {str(plan.get('say'))[:120]!r}")
    print(f"{len(CASES) - wrong} of {len(CASES)} right. The model took {sum(times) / max(1, len(times)):.1f}s on average "
          f"for the {len(times)} that went to it, the rest were decided on this PC.")
    sys.exit(1 if wrong > ALLOWED else 0)


if __name__ == "__main__":
    main()
