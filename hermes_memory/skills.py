"""Hermes Agent's skills, for Hey Jev: procedural memory she writes herself, so she gets better at what you ask her
often. A skill is a folder with a SKILL.md: YAML frontmatter with a name and a description, then how to do the task,
in the agentskills.io format Hermes Agent uses.

The rules and checks are Hermes' tools/skill_manager_tool.py, tools/skills_tool.py, agent/skill_utils.py and
agent/prompt_builder.py (MIT, see LICENSE), cut down to what Hey Jev needs. Changes are marked "Hey Jev:". Left
out: categories, the skills hub, pins, the curator, linting and supporting files.

Hey Jev: a skill can also have `triggers`, phrases that start it, and a ```json plan of steps in its body, so a
routine you taught her ("when I say work mode, ...") runs straight away, without asking the model.
"""
import json
import re
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .memory_store import atomic_write_text
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
            frontmatter[key.strip()] = value.strip().strip("'\"")  # Hey Jev: quotes off
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


def create_skill(name: str, content: str) -> Dict[str, Any]:
    if err := (_validate_name(name) or _validate_frontmatter(content) or _validate_content_size(content)
               or _security_scan(content)):
        return _err(err)
    if find_skill(name):
        return _err(f"A skill named '{name}' already exists. Use edit or patch to change it.")
    skill_dir = SKILLS_DIR / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(skill_dir / "SKILL.md", content, tmp_prefix=".skill_")
    return {"success": True, "message": f"Skill '{name}' created."}


def edit_skill(name: str, content: str) -> Dict[str, Any]:
    """Replace the SKILL.md of an existing skill (full rewrite)."""
    if err := (_validate_frontmatter(content) or _validate_content_size(content) or _security_scan(content)):
        return _err(err)
    path = find_skill(name)
    if not path:
        return _err(f"Skill '{name}' not found.")
    atomic_write_text(path, content, tmp_prefix=".skill_")
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
    return {"success": True, "message": f"Patched SKILL.md in skill '{name}'."}


def delete_skill(name: str) -> Dict[str, Any]:
    path = find_skill(name)
    if not path:
        return _err(f"Skill '{name}' not found.")
    shutil.rmtree(path.parent)
    return {"success": True, "message": f"Skill '{name}' deleted."}


# --- Catalog and viewing (tools/skills_tool.py) -------------------------------

def list_skills() -> List[Dict[str, Any]]:
    """name, description, triggers and plan of every skill, by name."""
    out = []
    for skill_md in sorted(SKILLS_DIR.glob("*/SKILL.md")) if SKILLS_DIR.is_dir() else []:
        try:
            fm, body = parse_frontmatter(skill_md.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError):
            continue
        out.append({"name": fm.get("name") or skill_md.parent.name, "dir": skill_md.parent.name,
                    "description": str(fm.get("description") or ""),
                    "triggers": [t.strip() for t in str(fm.get("triggers") or "").split(",") if t.strip()],
                    "plan": plan_of(body)})
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
    it after the notes, and an example plan in the notes would otherwise come first and run as the routine."""
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
    return {"steps": steps, "say": str(plan.get("say") or "")}


def build_content(name: str, description: str, notes: str = "", triggers=(), steps=None, say: str = "") -> str:
    """A SKILL.md in Hermes' format from the parts the model sends."""
    head = [f"name: {name}", f"description: {' '.join(str(description).split())}"]
    triggers = [" ".join(str(t).split()).replace(",", " ") for t in (triggers or []) if str(t).strip()]
    if triggers:
        head.append(f"triggers: {', '.join(triggers)}")
    body = (notes or description).strip()
    if steps:
        body += "\n\n```json\n" + json.dumps({"steps": steps, "say": say or ""}, ensure_ascii=False) + "\n```"
    return "---\n" + "\n".join(head) + "\n---\n" + body + "\n"


# --- The system prompt (agent/prompt_builder.py, build_skills_system_prompt) ---

def system_prompt_block(entries: Optional[List[Dict[str, Any]]] = None) -> str:
    """The skills index for her prompt. Hey Jev: Hermes' wording, with her own steps for skill_view."""
    entries = list_skills() if entries is None else entries
    if not entries:
        return ""
    lines = []
    for e in entries:
        said = f" (the user says: {', '.join(e['triggers'])})" if e["triggers"] else ""  # Hey Jev: no fixed name
        lines.append(f"    - {e['dir']}: {e['description']}{said}")
    return ("## Skills\n"
            "Before replying, scan the skills below. If a skill matches or is even partially relevant to the task, "
            "load it with {\"do\":\"skill_view\",\"name\":\"...\"} and follow its instructions. Skills encode the "
            "user's preferred approach and what works on this PC. If a skill you loaded was missing steps or wrong, "
            "fix it with a skill patch before finishing.\n"
            "<available_skills>\n" + "\n".join(lines) + "\n</available_skills>")
