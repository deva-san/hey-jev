"""Every step she can take, in one registry: what each one is called, what it changes, whether it may run after
reading a page, what words it needs said without her name, how she asks about it, when she speaks around it, and
the code that does it. Hermes Agent's tools/registry.py, cut down to Jev's steps.

Until 27 October each step was defined by hand in nine places in siri.py: the prompt, KNOWN_STEPS, do_step's
if-chain or run_info's, READ_SAFE, POWER_STEPS, ASKS_YES, ASKS_FOR, ROUTINE_STEPS, SPEAK_FIRST, SAY_AFTER and
WAIT_AFTER. A new step that missed one of them slipped through a gate unnoticed: click and wait were known to the
planner but had no branch in do_step, so a planned click was said as "I can't click yet". Now siri registers each
step once (register), and those sets are worked out from here (names). Registering fails without a decision on
what the step changes (effect), the words it needs without her name (asks_for, None for none) and how she asks
about it (confirm, None for never), so no step can be added without one. tests/test_toolbox.py holds each worked-out
set to the literal it replaced, so moving to the registry changed no behaviour.

The prompt itself stays literal in siri.py: its lines are found by text there (TASK_STUB, LIST_ANCHOR), and LiveSay
reads the reply's keys in order. A step's line here is a copy, for describe(), which lists steps to a model
compactly; a new step's line goes in a gated block, never the cached fixed prefix.

Only stdlib, and a few hundred dict entries: well under a millisecond at import, against siri's 0.65 s budget."""
from dataclasses import dataclass, replace
import json
import re

from hermes_memory import tool_bits

# What a step changes, from least to most. info: its results go back to the model (run_info) and change nothing.
# own_data: her own notes, memory, skills, lists and timers. reversible: shows, opens, moves or switches something
# another step undoes. acts: changes what's in an app or on the PC (typing, keys, a task on the screen, a message
# typed in). staged: only ever runs on a yes to her own question about it, never planned (siri.ASKS_YES). power:
# shuts down or restarts, always asked about (siri.POWER_STEPS)
EFFECTS = ("info", "own_data", "reversible", "acts", "staged", "power")
# When she speaks around it: first (before it runs, as locking cuts her off), after (once it's done, so "Sent to
# Mum." is never said for a send that was refused), or with (while it runs, as most)
SPEAKS = ("first", "after", "with")
# Whether a job in the background may run it: free (any time), lease (only while she has the PC to herself, as it
# uses the screen or the keyboard), never (only in a turn of yours, with your yes)
BACKGROUNDS = ("free", "lease", "never")
BUILT = "built"  # confirm: siri.confirm_question words the question from the step itself ("Should I type 'hi'?")
GO_AHEAD = "Should I go ahead with that?"  # the question for a step with no words of its own
DO_LINE = re.compile(r'\{"do":"(?P<name>[a-z_]+)"(?P<rest>[^{}]*)\}')  # one step's own JSON in a prompt line
ARG = re.compile(r'"([a-z_]+)":')


@dataclass(frozen=True)
class Tool:
    """One step: name is today's "do" string, never renamed (prompts, gates and tests use it). handler(step)
    returns a few words for the log, or raises RuntimeError with a reason she can say; for an info step it returns
    the entry run_info sends the model. None: siri's if-chain still does it. check(): False when it can't be used
    now (Telegram not paired). gated_by: the prompt block its line is in ("" the fixed prompt, None never planned).
    known: a model may plan it (siri.KNOWN_STEPS); agent_resume and watch_start only ever come from her own code.
    taints: what it brings back is someone else's words, so a change after it needs a yes (siri.needs_asking)."""
    name: str
    effect: str
    asks_for: object  # a compiled regex the words need without her name, or None
    confirm: object  # a question template ("Should I close {app}?"), BUILT, or None (never asked about)
    handler: object = None
    line: str = ""
    args: tuple = ()
    read_safe: bool = False
    speak: str = "with"
    wait_after: float = 0.0
    routine_ok: bool = False
    procedure_ok: bool = False
    parallel_ok: bool = False
    background: str = "never"
    check: object = None
    gated_by: object = ""
    known: bool = True
    taints: bool = False


TOOLS = {}  # name: Tool, in the order they were registered


def _args_of(name, line):
    """The argument names of name's own step in its prompt line: ("app",) for {"do":"close","app":"..."}."""
    for m in DO_LINE.finditer(line or ""):
        if m["name"] == name:
            return tuple(dict.fromkeys(ARG.findall(m["rest"])))
    return ()


def _refuse(name, why):
    raise ValueError(f"tool {name}: {why}")


def register(name, *, effect, asks_for, confirm, handler=None, line="", args=None, read_safe=False, speak="with",
             wait_after=0.0, routine_ok=False, procedure_ok=False, parallel_ok=False, background=None, check=None,
             gated_by="", known=True, taints=False):
    """Adds one step. effect, asks_for and confirm have no defaults on purpose: a step can't be added without
    deciding them (a TypeError says which is missing). The rest are checked against the gates they'd weaken: no step
    that sends, pays or shuts down may run after a read with no yes, in a routine, side by side or in the
    background, and only look-ups run side by side."""
    if name in TOOLS:
        _refuse(name, "registered twice")
    if not re.fullmatch(r"[a-z][a-z_]*", str(name)):
        _refuse(name, "a name is lowercase words joined by _")
    if effect not in EFFECTS:
        _refuse(name, f"effect must be one of {EFFECTS}")
    if speak not in SPEAKS:
        _refuse(name, f"speak must be one of {SPEAKS}")
    if asks_for is not None and not hasattr(asks_for, "search"):
        _refuse(name, "asks_for is a compiled regex or None")
    if confirm is not None and not isinstance(confirm, str):
        _refuse(name, "confirm is a question, BUILT or None")
    if confirm is None and not (effect == "info" or read_safe):
        _refuse(name, "a step that can be asked about (after a read, or without her name) needs a question")
    risky = effect in ("staged", "power")
    if risky and (read_safe or routine_ok or procedure_ok):
        _refuse(name, "a staged or power step never runs without its own yes")
    if parallel_ok and effect != "info":
        _refuse(name, "only look-ups run side by side")
    if background is None:  # what the effect allows, at most
        background = "free" if effect in ("info", "own_data") else "never" if risky else "lease"
    if background not in BACKGROUNDS:
        _refuse(name, f"background must be one of {BACKGROUNDS}")
    if risky and background != "never":
        _refuse(name, "a staged or power step never runs in the background")
    tool = Tool(name, effect, asks_for, confirm, handler, line or "", tuple(args) if args is not None else
                _args_of(name, line), bool(read_safe), speak, float(wait_after or 0.0), bool(routine_ok),
                bool(procedure_ok), bool(parallel_ok), background, check, gated_by, bool(known), bool(taints))
    TOOLS[name] = tool
    return tool


def handles(name):
    """A decorator that gives the registered step name its handler, where the code for it sits:
    @toolbox.handles("lock") over def _lock(step)."""
    def attach(fn):
        tool = TOOLS.get(name)
        if tool is None:
            _refuse(name, "not registered, so it can't have a handler")
        if tool.handler is not None:
            _refuse(name, "already has a handler")
        TOOLS[name] = replace(tool, handler=fn)
        return fn
    return attach


def get(name):
    """The Tool for a step's name, or None for one that isn't registered."""
    return TOOLS.get(name) if isinstance(name, str) else None


def names(**where):
    """The names of every step whose fields equal where's, as a frozenset: names(effect="power") is POWER_STEPS.
    A field's value may be a tuple of values, any of which will do (effect=("info", "own_data"))."""
    def fits(tool):
        for key, want in where.items():
            have = getattr(tool, key)
            if not (have in want if isinstance(want, tuple) else have == want):
                return False
        return True
    return frozenset(n for n, t in TOOLS.items() if fits(t))


def waits():
    """{name: seconds} for each step run_plan pauses after (siri.WAIT_AFTER). A plain dict: agent.py reads it with
    .get, and tests swap it for {}."""
    return {n: t.wait_after for n, t in TOOLS.items() if t.wait_after > 0}


def asks_for():
    """{name: regex} for each step that needs its own words without her name (siri.ASKS_FOR)."""
    return {n: t.asks_for for n, t in TOOLS.items() if t.asks_for is not None}


def question(step, default=GO_AHEAD):
    """The question for a step whose confirm is a template: "Should I close Notepad?". The step's own values fill
    it, with "it" for one that's missing, as confirm_question always had. default for a step with none."""
    tool = get(step.get("do"))
    if tool is None or not tool.confirm or tool.confirm == BUILT:
        return default

    class Filled(dict):
        def __missing__(self, key):
            return "it"
    values = Filled({k: str(v) for k, v in step.items() if v not in (None, "") and not isinstance(v, (dict, list))})
    return tool.confirm.format_map(values)


def available(name):
    """True when the step can be used now: registered, and its check (if any) passes. A check that raises counts as
    no, never as a crash in the middle of a turn."""
    tool = get(name)
    if tool is None:
        return False
    if tool.check is None:
        return True
    try:
        return bool(tool.check())
    except Exception:
        return False


def describe(kinds=None):
    """The steps named in kinds (every known one if None), one line each, as a model is shown them: the prompt's
    own line where there is one (said once, though one line may hold several steps), else the step's JSON with its
    arguments. Unknown names are left out. For an agent loop that lists only the tools a task may use."""
    seen, out = set(), []
    for name in (kinds if kinds is not None else [n for n, t in TOOLS.items() if t.known and t.gated_by is not None]):
        tool = get(name)
        if tool is None:
            continue
        line = tool.line or json.dumps({"do": tool.name, **{a: "..." for a in tool.args}}, separators=(",", ":"))
        if line not in seen:
            seen.add(line)
            out.append(line)
    return "\n".join(out)


def call(name, step, **extra):
    """Runs a registered step's handler for an agent loop, as Hermes' registry.dispatch does: only the arguments
    the handler takes are passed (step, and extra such as links), and anything it raises comes back as a bounded
    JSON error rather than an exception. Returns JSON text either way."""
    tool = get(name)
    if tool is None or tool.handler is None:
        return tool_bits.tool_error(f"Unknown step: {name}")
    try:
        result = tool.handler(**tool_bits._kwargs_accepted_by(tool.handler, {"step": step, **extra}))
    except Exception as exc:
        return tool_bits.tool_error(str(exc) or type(exc).__name__, step=name)
    return result if isinstance(result, str) else tool_bits.tool_result(result)


def run(tool, step, **extra):
    """A handler's own result, the arguments cut to what it takes (step, links): for siri's do_step and run_info,
    which want what it raises."""
    return tool.handler(**tool_bits._kwargs_accepted_by(tool.handler, {"step": step, **extra}))
