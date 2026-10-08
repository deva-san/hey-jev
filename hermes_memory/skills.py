"""Hermes Agent's skills, for Hey Jev: procedural memory she writes herself, so she gets better at what you ask her
often. A skill is a folder with a SKILL.md: YAML frontmatter with a name and a description, then how to do the task,
in the agentskills.io format Hermes Agent uses.

The rules and checks are Hermes' tools/skill_manager_tool.py, tools/skills_tool.py, agent/skill_utils.py and
agent/prompt_builder.py (MIT, see LICENSE), cut down to what Hey Jev needs. Changes are marked "Hey Jev:". Left
out: categories, the skills hub, linting and supporting files. Hermes' own usage tracking and curator are copied in
whole (skill_usage.py, curator.py): a skill she wrote herself that goes unused is marked stale after 14 days and
archived after 30, never deleted; one you taught her is never touched.

Hey Jev: a skill can also have `triggers`, phrases that start it, and a ```json plan of steps in its body, so a
routine you taught her ("when I say work mode, ...") runs straight away, without asking the model.
"""
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import skill_usage
from ._compat import atomic_write_text
from .hermes_bits import SKILL_PROMPT_DESC_LIMIT, extract_skill_description
from .threat_patterns import first_threat_message

MAX_NAME_LENGTH = 64
MAX_DESCRIPTION_LENGTH = 1024
MAX_SKILL_CONTENT_CHARS = 100_000   # ~36k tokens at 2.75 chars/token
VALID_NAME_RE = re.compile(r'^[a-z0-9][a-z0-9._-]*$')  # filesystem-safe, URL-friendly
_FRONTMATTER_END_RE = re.compile(r'\n---\s*\n')
_NAME_RULE = "Use lowercase letters, numbers, hyphens, dots, and underscores."
_PLAN_RE = re.compile(r"```json\s*\n(.*?)\n\s*```", re.S)  # Hey Jev: a routine's steps
SKILLS_DIR = Path.home() / ".hermes" / "skills"  # Hey Jev: set with set_skills_dir()


def set_skills_dir(path) -> None:
    global SKILLS_DIR
    SKILLS_DIR = Path(path)


def _err(message: str) -> Dict[str, Any]:
    return {"success": False, "error": message}


# --- Frontmatter (agent/skill_utils.py) ---------------------------------------

def parse_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Parse YAML frontmatter from markdown; returns (frontmatter_dict, body).
    A leading UTF-8 BOM (Windows editors) is stripped first or it would defeat the ``---`` fence check.
    Hey Jev: always Hermes' fallback, key: value line splitting, so no YAML library is needed."""
    content = content.removeprefix("\ufeff")
    end_match = re.search(r"\n---\s*\n", content[3:]) if content.startswith("---") else None
    if not end_match:
        return {}, content
    yaml_content = content[3: end_match.start() + 3]
    body = content[end_match.end() + 3:]
    frontmatter: Dict[str, Any] = {}
    for line in yaml_content.strip().split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            value = value.strip()
            if value[:1] in ('"', "["):  # Hey Jev: written as JSON by build_content, which YAML reads the same
                try:
                    frontmatter[key.strip()] = json.loads(value)
                    continue
                except ValueError:
                    pass
            frontmatter[key.strip()] = value.strip("'\"")  # Hey Jev: quotes off
    return frontmatter, body


# --- Validation helpers (tools/skill_manager_tool.py) ------------------------

def _validate_name(name: str) -> Optional[str]:
    if not name:
        return "Skill name is required."
    if len(name) > MAX_NAME_LENGTH:
        return f"Skill name exceeds {MAX_NAME_LENGTH} characters."
    if not VALID_NAME_RE.match(name):
        return f"Invalid skill name '{name}'. {_NAME_RULE} Must start with a letter or digit."
    return None


def _validate_frontmatter(content: str) -> Optional[str]:
    """Validate frontmatter (name + description) and a non-empty body."""
    if not content.strip():
        return "Content cannot be empty."
    content = content.lstrip("\ufeff")  # tolerate a Windows UTF-8 BOM
    if not content.startswith("---"):
        return "SKILL.md must start with YAML frontmatter (---). See existing skills for format."
    if not _FRONTMATTER_END_RE.search(content[3:]):
        return "SKILL.md frontmatter is not closed. Ensure you have a closing '---' line."
    parsed, body = parse_frontmatter(content)
    for field in ("name", "description"):
        if not parsed.get(field):
            return f"Frontmatter must include '{field}' field."
    if len(str(parsed["description"])) > MAX_DESCRIPTION_LENGTH:
        return f"Description exceeds {MAX_DESCRIPTION_LENGTH} characters."
    if not body.strip():
        return "SKILL.md must have content after the frontmatter (instructions, procedures, etc.)."
    return None


def _validate_content_size(content: str, label: str = "SKILL.md") -> Optional[str]:
    if len(content) > MAX_SKILL_CONTENT_CHARS:
        return (f"{label} content is {len(content):,} characters (limit: {MAX_SKILL_CONTENT_CHARS:,}). "
                f"Make it shorter.")
    return None


def _security_scan(content: str) -> Optional[str]:
    """Hey Jev: Hermes' threat patterns in the scope it uses for memory and skills, in place of skills_guard."""
    return first_threat_message(content, scope="strict")


# --- Core actions (tools/skill_manager_tool.py) -------------------------------

def find_skill(name: str) -> Optional[Path]:
    path = SKILLS_DIR / name / "SKILL.md"
    return path if _validate_name(name) is None and path.exists() else None


def create_skill(name: str, content: str, agent_created: bool = False) -> Dict[str, Any]:
    """agent_created: her learning review wrote it, so the curator looks after it; one you taught her, it doesn't."""
    if err := (_validate_name(name) or _validate_frontmatter(content) or _validate_content_size(content)
               or _security_scan(content)):
        return _err(err)
    if find_skill(name):
        return _err(f"A skill named '{name}' already exists. Use edit or patch to change it.")
    skill_dir = SKILLS_DIR / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(skill_dir / "SKILL.md", content, tmp_prefix=".skill_")
    _usage(skill_usage.record_created, name, agent_created=agent_created)
    return {"success": True, "message": f"Skill '{name}' created."}


def _usage(record, name, **kw):
    """Hermes' usage tracking (skill_usage.py), never in the way of the skill itself."""
    try:
        record(name, **kw)
    except Exception:
        pass


def edit_skill(name: str, content: str) -> Dict[str, Any]:
    """Replace the SKILL.md of an existing skill (full rewrite)."""
    if err := (_validate_frontmatter(content) or _validate_content_size(content) or _security_scan(content)):
        return _err(err)
    path = find_skill(name)
    if not path:
        return _err(f"Skill '{name}' not found.")
    atomic_write_text(path, content, tmp_prefix=".skill_")
    _usage(skill_usage.bump_patch, name, action="edit")
    return {"success": True, "message": f"Skill '{name}' updated (full rewrite)."}


def patch_skill(name: str, old_string: str, new_string: str) -> Dict[str, Any]:
    """Targeted find-and-replace in SKILL.md, unique match. Hey Jev: an exact match, not Hermes' fuzzy one."""
    if not old_string:
        return _err("old_string is required.")
    path = find_skill(name)
    if not path:
        return _err(f"Skill '{name}' not found.")
    content = path.read_text(encoding="utf-8-sig")
    count = content.count(old_string)
    if count != 1:
        return _err(f"old_string matched {count} times in skill '{name}'. It must match exactly once.")
    new_content = content.replace(old_string, new_string or "")
    if err := (_validate_content_size(new_content) or _validate_frontmatter(new_content)):
        return _err(f"Patch would break SKILL.md structure: {err}")
    if err := _security_scan(new_content):
        return _err(err)
    atomic_write_text(path, new_content, tmp_prefix=".skill_")
    _usage(skill_usage.bump_patch, name)
    return {"success": True, "message": f"Patched SKILL.md in skill '{name}'."}


def delete_skill(name: str, really: bool = False) -> Dict[str, Any]:
    """Hey Jev: archived (skills\\.archive, Hermes' way, restorable), unless really: forgotten for good, as from the
    Memory tab's Forget this."""
    path = find_skill(name)
    if not path:
        return _err(f"Skill '{name}' not found.")
    if not really:
        try:
            ok, _ = skill_usage.archive_skill(name)
            if ok:
                return {"success": True, "message": f"Skill '{name}' archived."}
        except Exception:
            pass
    shutil.rmtree(path.parent)
    _usage(skill_usage.forget, name)
    return {"success": True, "message": f"Skill '{name}' deleted."}


def used(name: str) -> None:
    """A skill was used (a routine ran, or its notes went to the model): it isn't stale."""
    _usage(skill_usage.bump_use, name)


# --- Catalog and viewing (tools/skills_tool.py) -------------------------------

def list_skills() -> List[Dict[str, Any]]:
    """name, description, triggers and plan of every skill, by name."""
    out = []
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")) if SKILLS_DIR.is_dir() else []:
        try:
            fm, body = parse_frontmatter(skill_md.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError):
            continue
        triggers = fm.get("triggers") or ""
        triggers = triggers if isinstance(triggers, list) else str(triggers).split(",")  # Hey Jev: old comma lists
        out.append({"name": fm.get("name") or skill_md.parent.name, "dir": skill_md.parent.name,
                    "description": str(fm.get("description") or ""),
                    "triggers": [str(t).strip() for t in triggers if str(t).strip()],
                    "plan": plan_of(body), "notes": _PLAN_RE.sub("", body).strip()})
    return out


def skill_view(name: str) -> Dict[str, Any]:
    """The full SKILL.md of a skill, or an error listing the ones there are."""
    path = find_skill(name)
    if not path:
        names = ", ".join(s["dir"] for s in list_skills()) or "none yet"
        return _err(f"Skill '{name}' not found. Skills: {names}.")
    return {"success": True, "name": name, "content": path.read_text(encoding="utf-8-sig")}


# --- Hey Jev: routines, and SKILL.md from what the model sends -----------------

def plan_of(body: str) -> Optional[Dict[str, Any]]:
    """The ```json plan in a skill's body, {"steps": [...], "say": "..."}, or None. The last one: build_content puts
    it after the notes, and an example plan in the notes would otherwise come first and run as the routine.
    A procedure (agent.py) comes with it as "procedure", its steps empty, so it never runs as a routine."""
    found = _PLAN_RE.findall(body or "")
    if not found:
        return None
    try:
        plan = json.loads(found[-1])
    except ValueError:
        return None
    steps = plan.get("steps") if isinstance(plan, dict) else None
    if not isinstance(steps, list) or not all(isinstance(s, dict) and s.get("do") for s in steps):
        return None
    out = {"steps": steps, "say": str(plan.get("say") or "")}
    if isinstance(plan.get("procedure"), dict):
        out["procedure"] = plan["procedure"]
    return out


def build_content(name: str, description: str, notes: str = "", triggers=(), steps=None, say: str = "",
                  procedure: Optional[Dict[str, Any]] = None) -> str:
    """A SKILL.md in Hermes' format from the parts the model sends. Hey Jev: each value written as JSON, which YAML
    reads the same way, so Hermes' parser takes it whatever it holds (a bare "on" is a boolean to YAML 1.1); the
    description cut to Hermes' 60 letters for a new skill; triggers under "When to Use", where Hermes keeps them.
    procedure: one of her procedures (agent.py), kept in the plan with no steps of its own."""
    description = " ".join(str(description).split())
    if len(description) > SKILL_PROMPT_DESC_LIMIT:
        description = description[:SKILL_PROMPT_DESC_LIMIT].rsplit(" ", 1)[0].rstrip(",.;:") or \
            description[:SKILL_PROMPT_DESC_LIMIT]
    head = [f"name: {json.dumps(name)}", f"description: {json.dumps(description, ensure_ascii=False)}",
            'platforms: ["windows"]']
    triggers = [" ".join(str(t).split()) for t in (triggers or []) if str(t).strip()]
    if triggers:
        head.append(f"triggers: {json.dumps(triggers, ensure_ascii=False)}")
    body = (notes or description).strip()
    if triggers:
        body = "## When to Use\n" + "\n".join(f'- "{t}"' for t in triggers) + "\n\n" + body
    if steps or procedure:
        plan = {"steps": steps or [], "say": say or "", **({"procedure": procedure} if procedure else {})}
        body += "\n\n```json\n" + json.dumps(plan, ensure_ascii=False) + "\n```"
    return "---\n" + "\n".join(head) + "\n---\n" + body + "\n"


# --- The system prompt (agent/prompt_builder.py, build_skills_system_prompt) ---

DETAIL_CHARS = 900  # the most of one skill's notes written out in her prompt
MOST_PROCEDURES = 15  # Hey Jev: procedures listed, the ones used last first; the rest she does from scratch again


def _procedure(entry: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Hey Jev: the procedure in a skill (agent.py), or None. siri.routines() moves it out of the plan."""
    proc = entry["procedure"] if "procedure" in entry else (entry.get("plan") or {}).get("procedure")
    return proc if isinstance(proc, dict) else None


def _last_used(entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Hey Jev: entries, the one used most lately first (Hermes' usage records)."""
    try:
        usage = skill_usage.load_usage()
    except Exception:
        usage = {}
    return sorted(entries, key=lambda e: skill_usage.latest_activity_at(usage.get(e["dir"]) or {})
                  or (usage.get(e["dir"]) or {}).get("created_at") or "", reverse=True)


def system_prompt_block(entries: Optional[List[Dict[str, Any]]] = None, detail=()) -> str:
    """The skills index for her prompt. Hey Jev: Hermes' wording and its 60-letter descriptions; the skills in detail
    (the ones that fit this request, see siri.skills_block) are written out in full, so the model needn't ask for
    them with skill_view, a whole extra round trip; the rest by name and description. Her procedures (agent.py) are
    listed with their slots and how to run one, never with the words that start them, which only code matches."""
    entries = list_skills() if entries is None else entries
    if not entries:
        return ""
    lines, full = [], []
    procedures = _last_used([e for e in entries if _procedure(e)])[:MOST_PROCEDURES]
    for e in [e for e in entries if not _procedure(e)] + procedures:
        proc = _procedure(e)
        if proc:
            slots = ", ".join(str(s) for s in (proc.get("slots") or {}))
            said = f" (procedure{', slots: ' + slots if slots else ''})"
        else:
            said = f" (the user says: {', '.join(e['triggers'])})" if e["triggers"] else ""  # Hey Jev: no fixed name
        lines.append(f"    - {e['dir']}: {extract_skill_description({'description': e['description']})}{said}")
        if e["dir"] in detail and e.get("notes"):
            full.append(f"### {e['dir']}\n{e['notes'][:DETAIL_CHARS]}")
    how = ("\nA procedure is a task you've done in an app before: run it with "
           "{\"do\":\"procedure\",\"name\":\"...\",\"slots\":{...}}, each slot filled from their words now, and no other "
           "steps for it." if procedures else "")
    return ("## Skills\n"
            "Before replying, scan the skills below. If a skill matches or is even partially relevant to the task, "
            "follow it: the ones that fit this request are written out after the list, load any other with "
            "{\"do\":\"skill_view\",\"name\":\"...\"}. Skills encode the user's preferred approach and what works on "
            "this PC. If a skill was missing steps or wrong, fix it with a skill patch before finishing." + how + "\n"
            "<available_skills>\n" + "\n".join(lines) + "\n</available_skills>"
            + ("\n\n" + "\n\n".join(full) if full else ""))
