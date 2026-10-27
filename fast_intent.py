"""How speech-to-text gets everyday commands wrong, put right before siri's fast path matches them a second time.

This held a second table of commands of its own, run after siri.QUICK on every miss. On 27 October its phrasings
QUICK lacked (zoom, full screen, editing keys, windows, screenshots, Windows' folders, shutdown and restart, apps
named a little off) moved into QUICK, so there's one table, and what's left here is the text side both use:
COMMON_SLIPS (siri.SLIPS, heard_as), clean_text (siri._quick's second look, shortcuts) and fuzzy_match
(siri.guess_app).
"""
from __future__ import annotations

import difflib
import re
from typing import List, Optional

# Filler prefixes and polite suffixes that speech-to-text adds
FILLERS_START = re.compile(
    r"^(?:(?:hey|hi|hello|ok|okay|yo)\s+(?:jev|jarvis|jeff|joe|jim|jill)\s*,?\s*)?"
    r"(?:(?:can|could|would|will)\s+you\s+(?:please\s+)?(?:just\s+)?|"
    r"(?:please\s+)?(?:just\s+)?(?:go\s+ahead\s+and\s+|i\s+(?:want|need|would\s+like)\s+you\s+to\s+|"
    r"let(?:'s|s)\s+|kindly\s+)?)+",
    re.I
)

FILLERS_END = re.compile(
    r"\s+(?:please|now|right\s+now|for\s+me|thanks|thank\s+you|quickly)$",
    re.I
)

# Common phonetic slips from ASR (accent repair without heavy models)
COMMON_SLIPS = {
    "prone": "chrome",
    "crome": "chrome",
    "spotty": "spotify",
    "spotted": "spotify",
    "potify": "spotify",
    "noted": "notepad",
    "no bad": "notepad",
    "note pad": "notepad",
    "this code": "vs code",
    "v s code": "vs code",
    "calc": "calculator",
    "hedg": "edge",
    "hedge": "edge",
    "fire fox": "firefox",
    "you tube": "youtube",
    "whats app": "whatsapp",
    "whatsup": "whatsapp",
    "new term": "new tab",
    "new tap": "new tab",
    "clone the tab": "close the tab",
    "clothes the tab": "close the tab",
}
# The slips of more than one word, as whole words of the line, the longest first
MULTI_SLIPS = re.compile(r"\b(?:" + "|".join(re.escape(k) for k in sorted((k for k in COMMON_SLIPS if " " in k),
                                                                          key=len, reverse=True)) + r")\b")


def clean_text(text: str) -> str:
    """Normalize text by stripping punctuation, extra spaces, and polite conversational filler."""
    t = text.lower().replace("\u2019", "'").strip()
    t = " ".join(re.sub(r"[^\w\s'%.-]|\.(?!\w)|(?<!\w)-|-(?!\w)", " ", t).split())
    # Strip start and end fillers
    t = FILLERS_START.sub("", t).strip()
    t = FILLERS_END.sub("", t).strip()
    # Repair the slips of more than one word on the whole line first: looked up a word at a time, "note pad", "you
    # tube" and the other nine of them could never match (found 27 October)
    t = MULTI_SLIPS.sub(lambda m: COMMON_SLIPS[m[0]], t)
    # Repair common phonetic single-word slips
    words = t.split()
    repaired = [COMMON_SLIPS.get(w, w) for w in words]
    return " ".join(repaired)


def fuzzy_match(query: str, candidates: List[str], cutoff: float = 0.75) -> Optional[str]:
    """Fast fuzzy matching with high confidence threshold (< 0.1ms)."""
    q = query.lower().strip()
    if not q:
        return None
    # 1. Exact match
    for c in candidates:
        if c.lower() == q:
            return c
    # 2. Strict prefix match (query must be at least 4 chars, candidate starts with query)
    if len(q) >= 4:
        for c in candidates:
            if c.lower().startswith(q):
                return c
    # 3. High-confidence fuzzy ratio match (minimum 0.75 ratio)
    matches = difflib.get_close_matches(q, candidates, n=1, cutoff=cutoff)
    return matches[0] if matches else None
