"""The model that works out what you asked and answers it, on whichever provider's picked in Settings (providers.py).

OpenCode Zen is the default, the same setup as Hermes Agent's opencode-zen provider: an OPENCODE_ZEN_API_KEY from
https://opencode.ai/zen and the OpenAI-style relay at https://opencode.ai/zen/v1. Every other provider but Anthropic
speaks the same API. A model that isn't free is billed to your own account with its provider.
"""
import json
import re
import time

import requests

import providers
import settings

BASE = providers.OPENCODE_BASE
# Kilo Gateway (kilo.ai), the same OpenAI-style API. Its models show here as "kilo/<id>", free ones end in ":free"
KILO = "kilo/"
KILO_BASE = providers.KILO_BASE
SESSION = requests.Session()  # one kept-open connection: an answer came in 0.6 s on it, 1.4 s on a fresh one
# OpenCode keeps most free chat models for its own app and turns other apps away with a 403. On 11 October 2026
# space-bunny-free was gone (410) and Kilo's Nemotron 3 Super 404'd; these answered. Refresh in Settings checks again.
FALLBACK_FREE = ["kilo/nvidia/nemotron-3-ultra-550b-a55b:free", "kilo/cohere/north-mini-code:free",
                 "kilo/nvidia/nemotron-3.5-lightning:free"]
# Anthropic, on its own API, used when one of its models is picked in Settings and its key is saved. Billed per
# request on your Anthropic account. Shown here as "anthropic/<id>"
ANTHROPIC = "anthropic/"
ANTHROPIC_BASE = "https://api.anthropic.com/v1"
ANTHROPIC_VERSION = "2023-06-01"
HAIKU = "anthropic/claude-haiku-5-5"
WHY = (("can only be used from within OpenCode", "OpenCode only lets this free model run inside OpenCode itself"),
       ("unavailable", "not available right now"),
       ("429", "busy, too many people on it right now"),
       ("401", "the key was turned down, check it"),
       ("timed out", "it took too long to answer"))


def is_free(model):
    p, model_id = providers.split(model)
    return bool(model_id) and providers.is_free(p, model_id)


def is_anthropic(model):
    return bool(model) and str(model).startswith(ANTHROPIC)


def allowed(model):
    """Any model on a provider in Settings: a free one, or one you pay for with your own key."""
    return bool(model)


def error_text(r):
    """The message out of an error reply, so the window says why and not just the status code."""
    try:
        body = r.json()
        err = body.get("error", body)
        msg = err.get("message") if isinstance(err, dict) else str(err)
    except ValueError:
        msg = r.text
    return f"{r.status_code} {r.reason}: {(msg or '').strip()[:200]}"


def _text(content):
    if isinstance(content, list):  # some models send a list of parts
        content = "".join(p.get("text", "") for p in content if isinstance(p, dict))
    content = re.sub(r"<think>.*?</think>", "", content or "", flags=re.S)
    if "<think>" in content:  # ran out of tokens while still thinking
        return ""
    return content.strip()


# What a provider other than OpenCode and Kilo may not take: it's asked again without them, and from then on (PLAIN)
EXTRAS = ("reasoning_effort", "stream_options")
PLAIN = set()


def chat(key, messages, max_tokens=400, timeout=30, model=None, on_text=None, stop=None, **extra):
    """One chat completion on the model picked in Settings, or model. Returns (text, usage, model). extra goes in the
    request, like reasoning_effort. key: OpenCode Zen's, the other providers' are read for them.
    on_text(text so far): the reply streamed, called as each piece comes in, so she can start saying it before it's
    all there. stop: a threading.Event that ends the stream early, as when another try won."""
    model = model or settings.get("llm_model")
    if is_anthropic(model):  # its own API: reasoning_effort and the like don't apply there
        return _anthropic(messages, max_tokens, timeout, model, on_text, stop)
    p, url, key, model_id = providers.endpoint(model, key)
    own = p.id in ("opencode", "kilo")
    who = "OpenCode" if own else p.name.split(" (")[0]
    # OpenAI's newer models turn max_tokens down, max_completion_tokens works on all of them
    body = {"model": model_id, "max_completion_tokens" if p.id == "openai" else "max_tokens": max_tokens,
            "messages": messages, **extra}
    if on_text is not None:
        body.update(stream=True, stream_options={"include_usage": True})
    if model in PLAIN:
        for name in EXTRAS:
            body.pop(name, None)

    def send():
        return SESSION.post(url, headers={"Authorization": f"Bearer {key}"} if key else {}, json=body,
                            timeout=timeout, stream=on_text is not None)
    try:
        r = send()
    except requests.ConnectionError:
        if not p.local:
            raise
        raise RuntimeError(f"{who} ({model}) isn't running on this PC, start it first")
    if r.status_code in (400, 422) and not own and any(name in body for name in EXTRAS):
        PLAIN.add(model)
        for name in EXTRAS:
            body.pop(name, None)
        r.close()
        r = send()
    if not r.ok:
        raise RuntimeError(f"{who} ({model}) {error_text(r)}")
    if on_text is not None:
        return _streamed(r, model, on_text, stop, who)
    j = r.json()
    if not j.get("choices"):  # Kilo sends an error this way now and then
        raise RuntimeError(f"{who} ({model}) unavailable: {str(j.get('error') or j)[:200]}")
    return _text(j["choices"][0]["message"].get("content")), j.get("usage") or {}, model


def _streamed(r, model, on_text, stop, who="OpenCode"):
    """Server-sent events, as both Kilo and OpenCode send them: "data: {...}" lines, then "data: [DONE]". The words
    are in delta.content; a model's thinking (delta.reasoning / reasoning_content) is left out."""
    text, usage = "", {}
    try:
        for line in r.iter_lines():
            if stop is not None and stop.is_set():
                break
            if not line.startswith(b"data:"):
                continue
            data = line[5:].strip()
            if data == b"[DONE]":
                break
            j = json.loads(data)
            if j.get("error"):
                raise RuntimeError(f"{who} ({model}) unavailable: {str(j['error'])[:200]}")
            usage = j.get("usage") or usage
            for choice in j.get("choices") or []:
                piece = (choice.get("delta") or {}).get("content")
                if isinstance(piece, list):
                    piece = "".join(p.get("text", "") for p in piece if isinstance(p, dict))
                if piece:
                    text += piece
                    on_text(text)
    finally:
        r.close()
    return _text(text), usage, model


# --------------------------------------------------------------------------- Anthropic
class Cached(str):
    """A system prompt the same turn after turn up to cache_at (her soul and a prompt), with what changes after it:
    Anthropic keeps that start for 5 minutes once asked to (prompt caching), and reads it back sooner and at a tenth
    of the price. Haiku 5.5 caches one of 512 tokens or more; a shorter one is just sent. Still a str, so all else
    reads it as before."""

    def __new__(cls, text, cache_at=None):
        s = super().__new__(cls, text)
        s.cache_at = len(s) if cache_at is None else max(0, min(int(cache_at), len(s)))
        return s


def _system(system):
    """The system prompt as Anthropic takes it: a string, or for one with a start to cache (Cached), that start as a
    text block marked for the cache, then the rest."""
    at = getattr(system, "cache_at", 0)
    if not at:
        return str(system)
    head, tail = str(system)[:at], str(system)[at:]
    return [{"type": "text", "text": head, "cache_control": {"type": "ephemeral"}}] + \
        ([{"type": "text", "text": tail}] if tail.strip() else [])


def _usage(u, into=None):
    """Anthropic's token counts as hers: in and out, and how many came from the cache or went into it."""
    into = {} if into is None else into
    for ours, theirs in (("prompt_tokens", "input_tokens"), ("completion_tokens", "output_tokens"),
                         ("cache_read", "cache_read_input_tokens"), ("cache_write", "cache_creation_input_tokens")):
        if (u or {}).get(theirs) is not None:
            into[ours] = u[theirs]
    return into


def _anthropic_part(part):
    """One piece of an OpenAI-style message as Anthropic wants it: text, or a picture from a data: or web address."""
    if not isinstance(part, dict):
        return {"type": "text", "text": str(part)}
    if part.get("type") == "image_url":
        url = str((part.get("image_url") or {}).get("url") or "")
        m = re.match(r"data:(image/[\w.+-]+);base64,(.+)$", url, re.S)
        if m:
            return {"type": "image", "source": {"type": "base64", "media_type": m.group(1), "data": m.group(2)}}
        return {"type": "image", "source": {"type": "url", "url": url}}
    return {"type": "text", "text": str(part.get("text") or "")}


def _anthropic_messages(messages):
    """(system, messages) from OpenAI-style ones. The leading system messages are Anthropic's system prompt; a
    system note later on goes in as user text where it was. Turns from the same side are joined, as Anthropic wants
    them taking turns, and it must start with the user."""
    system, out, started, cache_at = [], [], False, 0
    for m in messages:
        role, content = m.get("role"), m.get("content")
        if role == "system" and not started:
            text = content if isinstance(content, str) else \
                "".join(p.get("text", "") for p in content or [] if isinstance(p, dict))
            if not cache_at and getattr(content, "cache_at", 0) and text:  # where its fixed start ends, once joined
                cache_at = sum(len(s) + 2 for s in system if s) + content.cache_at
            system.append(text)
            continue
        started = True
        role = "assistant" if role == "assistant" else "user"
        parts = [_anthropic_part(p) for p in content] if isinstance(content, list) else \
            [{"type": "text", "text": str(content or "")}]
        parts = [p for p in parts if p["type"] != "text" or p["text"].strip()] or [{"type": "text", "text": "..."}]
        if out and out[-1]["role"] == role:
            out[-1]["content"] += parts
        else:
            out.append({"role": role, "content": parts})
    if not out or out[0]["role"] != "user":
        out.insert(0, {"role": "user", "content": [{"type": "text", "text": "..."}]})
    if out[-1]["role"] == "assistant":  # a last assistant turn would be taken as the start of its answer
        for p in out[-1]["content"]:
            if p["type"] == "text":
                p["text"] = p["text"].rstrip() or "..."
    joined = "\n\n".join(s for s in system if s)
    return (Cached(joined, cache_at) if cache_at else joined), out


# Claude Haiku 5.5 thinks before it answers unless it's told not to: adaptive thinking is on there by default, so
# every request had a hidden think first. On her own prompt on 22 October that was 2.4 s to the first word against
# 1.4 s with it off (the worst 3.5 s against 1.9 s), and 280 tokens a reply against 50. A model that won't have it
# off says so with a 400: it's asked again without, and left to think from then on (THINKS)
NO_THINKING = {"type": "disabled"}
THINKS = set()


def _anthropic(messages, max_tokens, timeout, model, on_text=None, stop=None):
    from secrets_store import get_secret
    key = get_secret("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("Add your Anthropic key in the Keys tab")
    system, msgs = _anthropic_messages(messages)
    body = {"model": model[len(ANTHROPIC):], "max_tokens": max_tokens, "messages": msgs}
    if model not in THINKS:
        body["thinking"] = NO_THINKING
    if system:
        body["system"] = _system(system)
    if on_text is not None:
        body["stream"] = True

    def send():
        return SESSION.post(f"{ANTHROPIC_BASE}/messages", json=body, timeout=timeout, stream=on_text is not None,
                            headers={"x-api-key": key, "anthropic-version": ANTHROPIC_VERSION})
    r = send()
    if r.status_code == 400 and "thinking" in body and "thinking" in r.text.lower():
        THINKS.add(model)
        body.pop("thinking")
        r.close()
        r = send()
    if not r.ok:
        raise RuntimeError(f"Anthropic ({model}) {error_text(r)}")
    if on_text is None:
        j = r.json()
        text = "".join(b.get("text", "") for b in j.get("content") or [] if b.get("type") == "text")
        return _text(text), _usage(j.get("usage"), {"prompt_tokens": None, "completion_tokens": None}), model
    text, usage = "", {}
    try:
        for line in r.iter_lines():
            if stop is not None and stop.is_set():
                break
            if not line.startswith(b"data:"):
                continue
            j = json.loads(line[5:].strip() or b"{}")
            kind = j.get("type")
            if kind == "error":
                raise RuntimeError(f"Anthropic ({model}) {(j.get('error') or {}).get('type', 'error')}: "
                                   f"{str((j.get('error') or {}).get('message'))[:200]}")
            if kind == "message_start":  # with what was read from the cache, or written to it
                _usage((j.get("message") or {}).get("usage"), usage)
            elif kind == "message_delta":
                usage["completion_tokens"] = (j.get("usage") or {}).get("output_tokens")
            elif kind == "content_block_delta" and (j.get("delta") or {}).get("type") == "text_delta":
                text += j["delta"].get("text", "")
                on_text(text)
            elif kind == "message_stop":
                break
    finally:
        r.close()
    return _text(text), usage, model


def explain(error):
    """A plain reason for an OpenCode error, for the window."""
    for clue, why in WHY:
        if clue in error:
            return why
    return re.sub(r"^[\w .]+ \([^)]*\) ", "", error)  # "OpenAI (openai/gpt-5.2) 429 ...": the model's said already


def check_model(key, model, timeout=25):
    """(True, seconds) if the model answers Hey Jev, (False, reason) if not."""
    t = time.time()
    try:
        chat(key, [{"role": "user", "content": "Reply with the word OK."}], max_tokens=200, timeout=timeout, model=model)
        return True, time.time() - t
    except Exception as exc:
        return False, explain(str(exc))
