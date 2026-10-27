# From Hermes Agent by Nous Research, tools/voice_mode_transcript.py, tools/tts_streaming.py at commit 1ae3c55e4bb16f495ebf0536a5672782d903e15e
# https://github.com/NousResearch/hermes-agent, MIT License, see LICENSE in this folder.
# Copied by sync_hermes.py; only the imports are changed, see UPSTREAM.json. Don't edit by hand.

"""Pieces of Hermes Agent's voice mode Hey Jev uses while she talks (tools/voice_mode_transcript.py,
tools/tts_streaming.py): whole-utterance stop phrases, her own words heard back (the TTS echo guard), and the
note that you cut her off."""

import difflib
import re
import time
from contextlib import suppress
from typing import Optional


# --- tools/voice_mode_transcript.py ---

def _voice_config() -> dict:
    """``voice`` section of config.yaml, or ``{}`` when missing, malformed, or the
    config system can't be imported (broken config mid-install)."""
    with suppress(Exception):
        from hermes_cli.config import load_config
        voice_cfg = load_config().get("voice", {})
        return voice_cfg if isinstance(voice_cfg, dict) else {}
    return {}


DEFAULT_VOICE_STOP_PHRASES = ("stop",)


def _load_voice_stop_phrases() -> tuple:
    """Configured ``voice.stop_phrases`` (default ``("stop",)``); an empty tuple disables
    the feature. Malformed config (dict, list of non-strings) falls back to the default
    rather than crashing the voice loop."""
    with suppress(Exception):
        raw = _voice_config().get("stop_phrases", DEFAULT_VOICE_STOP_PHRASES)
        if isinstance(raw, str):
            raw = [raw]
        if isinstance(raw, (list, tuple)):
            return tuple(str(p).strip().lower() for p in raw if isinstance(p, (str, int, float)) and str(p).strip())
    return DEFAULT_VOICE_STOP_PHRASES


def is_voice_stop_phrase(transcript: str, stop_phrases: Optional[tuple] = None) -> bool:
    """True when *transcript* is EXACTLY a configured stop phrase. Deliberately strict: the whole
    utterance — lowercased, surrounding punctuation stripped — must equal a phrase, so "stop doing
    that and try again" still reaches the agent. ``voice.stop_phrases: []`` disables."""
    cleaned = transcript.strip().lower().strip(".,!?;: \t\n\"'") if transcript else ""
    return bool(cleaned) and cleaned in (_load_voice_stop_phrases() if stop_phrases is None else stop_phrases)


DEFAULT_TTS_ECHO_SIMILARITY_THRESHOLD = 0.6


MIN_FRAGMENT_LENGTH_FOR_ECHO = 10


def _normalize_for_echo_compare(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def is_tts_echo(transcript: str, spoken_text: str,
                threshold: float = DEFAULT_TTS_ECHO_SIMILARITY_THRESHOLD) -> bool:
    """True when *transcript* looks like a self-capture of *spoken_text*. Character-level similarity
    (language-agnostic): a genuine interjection rarely matches Hermes' own words, so a high ratio signals
    speaker-bleed (fail-closed guard for the playback-phase listener). Playback capture spans only pre-roll
    plus time-to-silence, so for long replies the transcript is a FRAGMENT and the whole-string ratio dilutes
    toward 0; when it misses, a transcript-sized window slides across `spoken_text`. Transcripts shorter than
    `MIN_FRAGMENT_LENGTH_FOR_ECHO` skip the fallback (a short interjection trivially matches a short window)."""
    a, b = _normalize_for_echo_compare(transcript or ""), _normalize_for_echo_compare(spoken_text or "")
    if not a or not b:
        return False

    def _similar(x: str, y: str) -> bool:
        return difflib.SequenceMatcher(None, x, y).ratio() >= threshold

    if _similar(a, b):
        return True
    if len(a) < MIN_FRAGMENT_LENGTH_FOR_ECHO or len(a) >= len(b):
        return False
    return any(_similar(a, b[start : start + len(a)]) for start in range(len(b) - len(a) + 1))


# --- tools/tts_streaming.py ---

SPEECH_INTERRUPTED_NOTE = "[Note: the user interrupted your previous spoken reply before it finished.]"


_INTERRUPT_TTL_S = 120.0


_interrupted_at: Optional[float] = None


def mark_speech_interrupted() -> None:
    global _interrupted_at
    _interrupted_at = time.monotonic()


def take_speech_interrupted() -> bool:
    """Pop the latch; True when a barge happened within the TTL."""
    global _interrupted_at
    at, _interrupted_at = _interrupted_at, None
    return at is not None and time.monotonic() - at < _INTERRUPT_TTL_S
