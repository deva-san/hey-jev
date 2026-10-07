"""OpenCode Zen, in place of OpenRouter: one key for the model that works out what you asked and answers it.
Free models only.

Same setup as Hermes Agent's opencode-zen provider: an OPENCODE_ZEN_API_KEY from https://opencode.ai/zen
and the OpenAI-style relay at https://opencode.ai/zen/v1. A paid model is refused before any request goes out,
so nothing can be billed even if billing is turned on later.
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor

import requests

import settings

BASE = os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1").rstrip("/")
# Kilo Gateway (kilo.ai), the same OpenAI-style API. Its models show here as "kilo/<id>", free ones end in ":free"
KILO = "kilo/"
KILO_BASE = "https://api.kilo.ai/api/gateway"
# these answered in October 2026 but not with Hey Jev's JSON: a router that picked a safety model, or empty replies
KILO_SKIP = ("openrouter/free", "kilo-auto/free", "apodex/", "nemotron-3.5-content-safety", "lyria")
SESSION = requests.Session()  # one kept-open connection: an answer came in 0.6 s on it, 1.4 s on a fresh one
# These speak a different API (Jev has its own endpoint, Muse Spark only does /responses), so they can't answer here
NOT_CHAT = ("jev-", "muse-spark")
FREE_EXTRA = {"big-pickle"}  # free on OpenCode's price list without "-free" in the name
# OpenCode keeps most free chat models for its own app and turns other apps away with a 403.
# space-bunny-free is the one that answered from Hey Jev in October 2026. Refresh in Settings checks again.
FALLBACK_FREE = ["kilo/inclusionai/ling-3.0-flash-sante:free", "space-bunny-free"]
WHY = (("can only be used from within OpenCode", "OpenCode only lets this free model run inside OpenCode itself"),
       ("isn't a free model", "it isn't free, and Hey Jev only uses free models"),
       ("unavailable", "not available right now"),
       ("429", "busy, too many people on it right now"),
       ("401", "the key was turned down, check it in Keys"),
       ("timed out", "it took too long to answer"))


def is_free(model):
    if model and model.startswith(KILO):
        return model.endswith(":free")
    return bool(model) and (model.endswith("-free") or model in FREE_EXTRA)


def _where(model, key):
    """(chat URL, key, model id) for OpenCode or Kilo."""
    if model.startswith(KILO):
        from secrets_store import get_secret
        kilo_key = get_secret("KILO_API_KEY")
        if not kilo_key:
            raise RuntimeError("Add your Kilo key in the Keys tab")
        return f"{KILO_BASE}/chat/completions", kilo_key, model[len(KILO):]
    if not key:
        raise RuntimeError("Add your OpenCode Zen key in the Keys tab")
    return f"{BASE}/chat/completions", key, model


def require_free(model):
    if not is_free(model):
        raise RuntimeError(f"OpenCode ({model}) isn't a free model, Hey Jev only uses free ones")


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


def chat(key, messages, max_tokens=400, timeout=30, model=None, on_text=None, stop=None, **extra):
    """One chat completion on a free OpenCode Zen model. Returns (text, usage, model). extra goes in the request,
    like reasoning_effort.
    on_text(text so far): the reply streamed, called as each piece comes in, so she can start saying it before it's
    all there. stop: a threading.Event that ends the stream early, as when another try won."""
    model = model or settings.get("llm_model")
    require_free(model)
    url, key, model_id = _where(model, key)
    body = {"model": model_id, "max_tokens": max_tokens, "messages": messages, **extra}
    if on_text is not None:
        body.update(stream=True, stream_options={"include_usage": True})
    r = SESSION.post(url, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=timeout,
                     stream=on_text is not None)
    if not r.ok:
        raise RuntimeError(f"OpenCode ({model}) {error_text(r)}")
    if on_text is not None:
        return _streamed(r, model, on_text, stop)
    j = r.json()
    if not j.get("choices"):  # Kilo sends an error this way now and then
        raise RuntimeError(f"OpenCode ({model}) unavailable: {str(j.get('error') or j)[:200]}")
    return _text(j["choices"][0]["message"].get("content")), j.get("usage") or {}, model


def _streamed(r, model, on_text, stop):
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
                raise RuntimeError(f"OpenCode ({model}) unavailable: {str(j['error'])[:200]}")
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


def _model_ids(timeout):
    r = requests.get(f"{BASE}/models", timeout=timeout)
    r.raise_for_status()
    return [m["id"] for m in r.json().get("data", [])]


def _kilo_ids(timeout):
    from secrets_store import get_secret
    if not get_secret("KILO_API_KEY"):
        return []
    try:
        r = requests.get(f"{KILO_BASE}/models", timeout=timeout)
        r.raise_for_status()
    except Exception:
        return []
    return [KILO + m["id"] for m in r.json().get("data", []) if not any(s in m["id"] for s in KILO_SKIP)]


def free_chat_models(timeout=10):
    """Free models that answer on /chat/completions, from the live lists. Free ones come and go."""
    return [i for i in _model_ids(timeout) + _kilo_ids(timeout) if is_free(i) and not i.startswith(NOT_CHAT)]


def explain(error):
    """A plain reason for an OpenCode error, for the window."""
    for clue, why in WHY:
        if clue in error:
            return why
    return error.split(") ", 1)[-1] if error.startswith("OpenCode (") else error


def check_model(key, model, timeout=25):
    """(True, seconds) if the model answers Hey Jev, (False, reason) if not."""
    t = time.time()
    try:
        chat(key, [{"role": "user", "content": "Reply with the word OK."}], max_tokens=200, timeout=timeout, model=model)
        return True, time.time() - t
    except Exception as exc:
        return False, explain(str(exc))


def working_free_models(key):
    """(working, all free) from the live list, working ones fastest first. Each check is one tiny free request."""
    free = free_chat_models()
    with ThreadPoolExecutor(len(free) or 1) as pool:
        results = list(zip(free, pool.map(lambda m: check_model(key, m), free)))
    working = sorted((secs, m) for m, (ok, secs) in results if ok)
    return [m for _, m in working], free
