# From Hermes Agent by Nous Research, agent/skill_utils.py, hermes_state_common.py, hermes_state_search.py, agent/background_review.py at commit 1ae3c55e4bb16f495ebf0536a5672782d903e15e
# https://github.com/NousResearch/hermes-agent, MIT License, see LICENSE in this folder.
# Copied by sync_hermes.py; only the imports are changed, see UPSTREAM.json. Don't edit by hand.

"""Pieces of Hermes Agent Hey Jev uses on their own: finding skills, the 60-character skill descriptions, its
search query cleaner and its OR-relaxed retry (history.py), its learning review's rules (siri.LEARN)
and its memory review (siri.MEMORY_REVIEW)."""

import os
import re
from pathlib import Path, PurePath
from typing import Any, Dict, List, Optional, Tuple

from ._compat import get_all_skills_dirs, get_disabled_skill_names, is_external_skill_path  # noqa: F401, skill_usage.py imports them from here


# --- agent/skill_utils.py ---

EXCLUDED_SKILL_DIRS = frozenset((
    ".git", ".github", ".hub", ".archive", ".curator_backups", ".locks",
    ".venv", "venv", "node_modules", "site-packages", "__pycache__",
    ".tox", ".nox", ".pytest_cache", ".mypy_cache", ".ruff_cache",
))


SKILL_SUPPORT_DIRS = frozenset(("references", "templates", "assets", "scripts"))


def is_excluded_skill_path(path, *, root: Optional[Path] = None) -> bool:
    """True if *path* should be skipped by skill scanners (VCS/dependency/cache
    dirs + support packages). Apply to every SKILL.md from a direct ``rglob``."""
    parts = PurePath(str(path)).parts
    return any(part in EXCLUDED_SKILL_DIRS for part in parts) or is_skill_support_path(path, root=root)


def is_skill_support_path(path, *, root: Optional[Path] = None) -> bool:
    """True if *path* is under a support dir sitting directly inside a skill root
    (``skills/scripts/foo`` stays discoverable: no ``SKILL.md`` above ``scripts``)."""
    path_obj = path if isinstance(path, Path) else Path(str(path))
    parts = path_obj.parts
    base = root if root is not None and not path_obj.is_absolute() else Path()
    # Only components before the leaf can be containing support directories.
    return any(
        part in SKILL_SUPPORT_DIRS and (base / Path(*parts[:idx]) / "SKILL.md").exists()
        for idx, part in enumerate(parts[:-1])
        if idx > 0
    )


def iter_skill_index_files(skills_dir: Path, filename: str):
    """Walk skills_dir yielding sorted paths matching *filename*; prunes
    EXCLUDED_SKILL_DIRS and support dirs of skill roots."""
    matches: list[str] = []
    for root, dirs, files in os.walk(str(skills_dir), followlinks=True):
        has_skill_md = "SKILL.md" in files
        dirs[:] = [d for d in dirs if d not in EXCLUDED_SKILL_DIRS and not (has_skill_md and d in SKILL_SUPPORT_DIRS)]
        if filename in files:
            matches.append(os.path.join(root, filename))
    yield from map(Path, sorted(matches))


SKILL_PROMPT_DESC_LIMIT = 60


_LAST_WHITESPACE_RE = re.compile(r"\s\S*$")


_CLIP_TRAIL_RE = re.compile(r"[\s.,;:\-\u2013\u2014(/]+$")


def _normalize_skill_description(frontmatter: dict[str, Any]) -> str:
    """Normalize a skill's description field for comparison/truncation."""
    raw_desc = frontmatter.get("description", "")
    return str(raw_desc).strip().strip("'\"") if raw_desc else ""


def clip_skill_description(desc: str) -> str:
    """*desc* fitted to SKILL_PROMPT_DESC_LIMIT, cut at a word boundary so the index never shows a half word."""
    if len(desc) <= SKILL_PROMPT_DESC_LIMIT:
        return desc
    head = desc[:SKILL_PROMPT_DESC_LIMIT - 2]  # one char past the budget: whitespace there means the last word is whole
    boundary = _LAST_WHITESPACE_RE.search(head)  # any whitespace (tab, NBSP, ...) separates words, not just " "
    if not boundary or boundary.start() == 0:  # a single word longer than the budget has no boundary to cut at
        return desc[:SKILL_PROMPT_DESC_LIMIT - 3] + "..."
    return _CLIP_TRAIL_RE.sub("", head[:boundary.start()]) + "..."


def extract_skill_description(frontmatter: dict[str, Any]) -> str:
    """Extract a system-prompt-length description from parsed frontmatter."""
    return clip_skill_description(_normalize_skill_description(frontmatter))


# --- hermes_state_common.py ---

MAX_FTS5_QUERY_CHARS = 2_048


# --- hermes_state_search.py ---

_FTS5_SPECIAL_CHARS = '+{}():"^@/#&|~[]<>,;!?$=\\\''


_FTS5_SPECIAL_RE = re.compile(f"[{re.escape(_FTS5_SPECIAL_CHARS)}]")


_FTS_OPERATORS = frozenset({"AND", "OR", "NOT"})


_LIKE_TOKEN_RE = re.compile(r'"[^"]+"|\S+')


_QUOTED_PHRASE_RE = re.compile(r'"[^"]*"')


_CJK_RANGES = (
    (0x4E00, 0x9FFF), (0x3400, 0x4DBF), (0x20000, 0x2A6DF), (0x3000, 0x303F), (0x3040, 0x309F),
    (0x30A0, 0x30FF), (0xAC00, 0xD7AF),
)


def _is_cjk(cp: int) -> bool:
    return any(lo <= cp <= hi for lo, hi in _CJK_RANGES)


def _non_operator_tokens(raw_query: str) -> list[str]:
    return [t for t in raw_query.split() if t.upper() not in _FTS_OPERATORS]


def _quote_fts_tokens(raw_query: str) -> str:
    """Quote each non-operator token (neutralising FTS5 special characters), keeping AND/OR/NOT."""
    return " ".join(
        tok if tok.upper() in _FTS_OPERATORS else '"' + tok.replace('"', '""') + '"' for tok in raw_query.split()
    )


def _contains_cjk(text: str) -> bool:
    return any(_is_cjk(ord(ch)) for ch in text)


def _sanitize_fts5_query(query: str) -> str:
    """Sanitize user input for FTS5 MATCH (raw special characters raise): preserve paired
    quoted phrases, strip unmatched special characters, and quote hyphenated/dotted
    terms so FTS5 matches them as phrases (``chat-send``, ``P2.2``, ``my-app.config.ts``)."""
    # Cap before any regex processing so adversarial input stays bounded.
    query = query[:MAX_FTS5_QUERY_CHARS]

    # 1. Protect balanced quoted phrases via numbered placeholders (``"[^"]*"`` pairs
    # left-to-right without backtracking); a leftover unmatched quote becomes whitespace.
    _quoted_parts: list = []

    def _hold(m: re.Match[str]) -> str:
        _quoted_parts.append(m.group(0))
        return f"\x00Q{len(_quoted_parts) - 1}\x00"

    sanitized = _QUOTED_PHRASE_RE.sub(_hold, query).replace('"', " ")

    # 2. Strip FTS5-special characters (an unquoted ``TODO: fix`` parses as
    # ``column:term``). ``%`` is only spared for the CJK LIKE fallback.
    sanitized = _FTS5_SPECIAL_RE.sub(" ", sanitized)
    if "%" in sanitized and not _contains_cjk(sanitized):
        sanitized = sanitized.replace("%", " ")
    # 3. Collapse repeated * and drop leading * (prefix needs a char).
    sanitized = re.sub(r"\*+", "*", sanitized)
    sanitized = re.sub(r"(^|\s)\*", r"\1", sanitized)
    # 4. Drop dangling boolean operators at start/end (syntax errors).
    sanitized = re.sub(r"(?i)^(AND|OR|NOT)\b\s*", "", sanitized.strip())
    sanitized = re.sub(r"(?i)\s+(AND|OR|NOT)\s*$", "", sanitized.strip())
    # 5. Quote dotted/hyphenated/underscored terms in ONE pass (sequential passes
    # double-quote ``my-app.config``).
    sanitized = re.sub(r"\b(\w+(?:[._-]\w+)+)\b", r'"\1"', sanitized)
    # 6. Restore preserved quoted phrases.
    for i, quoted in enumerate(_quoted_parts):
        sanitized = sanitized.replace(f"\x00Q{i}\x00", quoted)
    return sanitized.strip()


def _or_relaxed_query(query: str) -> Optional[str]:
    """The sanitized implicit-AND query rewritten as an any-term OR query, or ``None`` when
    relaxation does not apply: fewer than two searchable units (a single term cannot relax)
    or explicit ``OR``/``NOT`` (the caller expressed exact semantics). Quoted phrases stay
    whole units: ``"docker networking" tls`` -> ``"docker networking" OR tls``."""
    units: list[str] = []
    for raw_token in _LIKE_TOKEN_RE.findall(query):
        upper = raw_token.upper()
        if upper in {"OR", "NOT"}:
            return None
        if upper != "AND":
            units.append(raw_token)
    return " OR ".join(units) if len(units) >= 2 else None


# --- agent/background_review.py ---

_MEMORY_ROUTING_BLOCK = (
    "TWO distinct stores — pick the right one for each fact:\n"
    "  • USER.md (memory tool, target='user'): who the user is — persona, preferences, "
    "communication and work style, personal details they revealed, and expectations about how you "
    "should behave.\n"
    "  • MEMORY.md (memory tool, target='memory'): facts about the ENVIRONMENT you operate in — "
    "tool quirks, project conventions, config gotchas, paths and endpoints that matter.\n\n"
    "One fact goes to ONE store, never both — writing it to both bloats both files until they hit "
    "their size limits and crowds out the facts that matter; misrouting it puts it where the next "
    "session won't look. If the tool schema lists only one "
    "target, that store is the only one enabled — use it and skip the other.\n\n"
)


_MEMORY_REVIEW_PROMPT = (
    "Review the conversation above and consider saving to memory if appropriate.\n\n"
    "Memory has " + _MEMORY_ROUTING_BLOCK +
    "If something stands out, save it once, in the right store, using the memory tool with the "
    "matching target. If nothing is worth saving, just say 'Nothing to save.' and stop."
)


_LESSON_LAYER_BLOCK = (
    "What a skill IS: the instructions for doing a class of task the most efficient and correct "
    "way, to THIS user's specifications — the procedure, the tools and commands that work, the "
    "order, the user's preferences for how the result should look, and the pitfalls that cost time. "
    "A future session should be able to follow it and produce what the user wants on the first "
    "try. Everything below is about writing that well:\n"
    "  • Procedure first: the steps in the order they are done, with the concrete commands, tool "
    "calls, and decision points. Lessons and pitfalls attach to the step they affect.\n"
    "  • A pitfall is a generalizable rule + one clause of WHY (the mechanism), imperative. 'Grep the "
    "test tree for the SYMBOL before widening a helper signature — hand-rolled mocks reimplement the "
    "old shape and fail on a shard you did not run.' Not a narrative of what happened this session.\n"
    "  • No PR/issue numbers, dates, ticket IDs, or quoted user text as content — the rule must stand "
    "without the incident behind it. Keep a short quote ONLY when the quote itself is the clearest "
    "statement of the rule.\n"
    "  • The same lesson learned twice is ONE rule. Before adding, search the skill (and its "
    "references/) for the rule already stated; strengthen or clarify it rather than appending a "
    "second copy.\n"
    "  • Not a duplicate of what the environment already teaches: repo AGENTS.md files, tool schema "
    "descriptions, and other always-loaded context. A skill carries the WORKFLOW and the pitfalls; "
    "it does not restate the codebase map or a tool's parameter list.\n"
    "  • Always-on rules (standing user preferences, gates that apply to every instance of the "
    "task) live in SKILL.md itself, whole. references/ is for depth that is only needed sometimes: "
    "a decision table, a recipe, a domain note — each file topical and reusable, never "
    "'<date>-<incident>.md'. Prefer extending an existing references/ file over creating one; "
    "a skill with dozens of one-off references is the failure shape, not the goal.\n"
    "  • Fix the skill in place when it is wrong: edit the sentence that misled, do not append "
    "'UPDATE: actually...' underneath it.\n\n"
)


_DO_NOT_CAPTURE_BLOCK = (
    " (these become persistent self-imposed constraints that bite you later when the environment "
    "changes):\n"
    "  • Environment-dependent failures: missing binaries, fresh-install errors, post-migration "
    "path mismatches, 'command not found', unconfigured credentials, uninstalled packages. The "
    "user can fix these — they are not durable rules.\n"
    "  • Negative claims about tools or features ('browser tools do not work', 'X tool is broken', "
    "'cannot use Y from execute_code'). These harden into refusals the agent cites against itself "
    "for months after the actual problem was fixed.\n"
    "  • Session-specific transient errors that resolved before the conversation ended. If "
    "retrying worked, the lesson is the retry pattern, not the original failure.\n"
    "  • One-off task narratives. A user asking 'summarize today's market' or 'analyze this PR' is "
    "not a class of work that warrants a skill.\n\n"
    "  • Unresolved failures: if the session ended WITHOUT actually finding a working method — you "
    "tried several things, none worked, and told the user to check manually — do NOT write those "
    "attempts up as a 'reliable workflow' or 'recommended approach'. That presents an untested "
    "sequence of failures as validated guidance a future session will trust and repeat. Either say "
    "'Nothing to save', or, only if you are independently confident of a real working alternative "
    "(not something you are merely guessing might work), capture ONLY that alternative — never the "
    "dead ends, and never dressed up as best practice.\n\n"
    "If a tool failed because of setup state, capture the FIX (install command, config step, env "
    "var to set) under an existing setup or troubleshooting skill — never 'this tool does not "
    "work' as a standalone constraint.\n\n"
)
