"""Every provider she can think with, set up the way Hermes Agent's `hermes model` and OpenClaw's model picker do it:
pick a provider, then any model it has. A model is saved as "<provider>/<model id>", like "openai/gpt-5.2" or
"openrouter/anthropic/claude-sonnet-5"; OpenCode Zen's own keep their bare IDs ("big-pickle"), as they were saved before.

Each provider's list is read live from its /models and kept in models.json, then read again once it's half an hour
old, so new models show up by themselves and ones taken away drop out. Newest first.

All but Anthropic speak the OpenAI-style API (opencode.chat sends to them). A model that isn't free is billed to your
own account with that provider.
"""
import json
import os
import re
import threading
import time
from collections import namedtuple
from concurrent.futures import ThreadPoolExecutor

import requests

from winplatform import APPDATA_DIR

OPENCODE_BASE = os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1").rstrip("/")
KILO_BASE = "https://api.kilo.ai/api/gateway"

# key: its name in secrets_store, None for one on this PC. open_list: its /models answers without a key
Provider = namedtuple("Provider", "id name base key key_url open_list local")
PROVIDERS = (
    Provider("opencode", "OpenCode Zen", OPENCODE_BASE, "OPENCODE_ZEN_API_KEY", "https://opencode.ai/zen", True, False),
    Provider("kilo", "Kilo Gateway", KILO_BASE, "KILO_API_KEY", "https://kilo.ai/docs/gateway/authentication", True,
             False),
    Provider("openrouter", "OpenRouter", "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
             "https://openrouter.ai/keys", True, False),
    Provider("anthropic", "Anthropic", "https://api.anthropic.com/v1", "ANTHROPIC_API_KEY",
             "https://platform.claude.com/settings/keys", False, False),
    Provider("openai", "OpenAI", "https://api.openai.com/v1", "OPENAI_API_KEY", "https://platform.openai.com/api-keys",
             False, False),
    Provider("google", "Google Gemini", "https://generativelanguage.googleapis.com/v1beta/openai", "GEMINI_API_KEY",
             "https://aistudio.google.com/apikey", False, False),
    Provider("xai", "xAI Grok", "https://api.x.ai/v1", "XAI_API_KEY", "https://console.x.ai", False, False),
    Provider("groq", "Groq", "https://api.groq.com/openai/v1", "GROQ_API_KEY", "https://console.groq.com/keys", False,
             False),
    Provider("deepseek", "DeepSeek", "https://api.deepseek.com/v1", "DEEPSEEK_API_KEY",
             "https://platform.deepseek.com/api_keys", False, False),
    Provider("mistral", "Mistral", "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "https://console.mistral.ai/api-keys",
             False, False),
    Provider("cerebras", "Cerebras", "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", "https://cloud.cerebras.ai",
             False, False),
    Provider("together", "Together AI", "https://api.together.xyz/v1", "TOGETHER_API_KEY",
             "https://api.together.ai/settings/api-keys", False, False),
    Provider("nous", "Nous Portal", "https://inference-api.nousresearch.com/v1", "NOUS_API_KEY",
             "https://portal.nousresearch.com", False, False),
    Provider("huggingface", "Hugging Face", "https://router.huggingface.co/v1", "HF_TOKEN",
             "https://huggingface.co/settings/tokens", False, False),
    Provider("moonshot", "Moonshot Kimi", "https://api.moonshot.ai/v1", "MOONSHOT_API_KEY",
             "https://platform.moonshot.ai/console/api-keys", False, False),
    Provider("ollama", "Ollama (this PC)", "http://localhost:11434/v1", None, "https://ollama.com/download", True, True),
    Provider("lmstudio", "LM Studio (this PC)", "http://localhost:1234/v1", None, "https://lmstudio.ai", True, True),
)
BY_ID = {p.id: p for p in PROVIDERS}
OPENCODE = BY_ID["opencode"]

# Not chat models: pictures, speech, embeddings, safety checkers. Also OpenCode's own (Jev's own endpoint, Muse Spark
# only does /responses), and Kilo's that answered in October 2026 but not with Hey Jev's JSON: a router that picked a
# safety model, or empty replies
NOT_CHAT = re.compile(r"embed|tts|whisper|dall-e|moderation|transcri|realtime|audio|image|imagen|veo|sora|rerank|"
                      r"guard|aqa|davinci|babbage|lyria|content-safety|computer-use|^jev-|^muse-spark|"
                      r"^openrouter/free$|^kilo-auto/free$|^apodex/", re.I)
FREE_EXTRA = {"big-pickle"}  # free on OpenCode's price list without "-free" in the name
PATH = os.path.join(APPDATA_DIR, "models.json")
FRESH_FOR = 30 * 60  # seconds a provider's list is kept before it's read again

_lock = threading.Lock()
_catalog = None  # provider ID: {"at": when read, "models": [{id, free, created, ctx}], "error": why it wasn't}


def split(model):
    """(provider, its ID for the model) for a saved model. One with no provider in front is OpenCode Zen's."""
    model = str(model or "")
    head, _, rest = model.partition("/")
    if rest and head in BY_ID:
        return BY_ID[head], rest
    return OPENCODE, model


def full(provider, model_id):
    """The model as it's saved: "<provider>/<id>", or the bare ID for OpenCode Zen."""
    return model_id if provider.id == "opencode" else f"{provider.id}/{model_id}"


def key(provider):
    if not provider.key:
        return ""
    from secrets_store import get_secret
    return get_secret(provider.key) or ""


def ready(provider):
    """It can answer: it runs on this PC, or its key is saved."""
    return provider.local or bool(key(provider))


def endpoint(model, opencode_key=None):
    """(provider, chat URL, key, model ID) for an OpenAI-style provider's model."""
    p, model_id = split(model)
    k = (opencode_key if p is OPENCODE else None) or key(p)
    if p.key and not k:
        raise RuntimeError(f"Add your {p.name} key in Settings > Answer model")
    return p, f"{p.base}/chat/completions", k, model_id


def is_free(provider, model_id, row=None):
    if provider.local:
        return True
    if provider.id == "opencode":
        return model_id.endswith("-free") or model_id in FREE_EXTRA
    if model_id.endswith(":free") or (row or {}).get("isFree") is True:
        return True
    price = (row or {}).get("pricing") or {}
    return bool(price) and all(str(price.get(k, "")) in ("0", "0.0") for k in ("prompt", "completion"))


def free(model):
    """True if a saved model is free: by its name, or by its provider's list ("kilo/reflection/beam-free" is free on
    Kilo's list without ending in ":free")."""
    p, model_id = split(model)
    if not model_id:
        return False
    return is_free(p, model_id) or any(m["id"] == model_id and m["free"] for m in cached(p)["models"])


def _when(created):
    """A list's created time as seconds: OpenAI-style lists give seconds, Anthropic an ISO date."""
    if isinstance(created, (int, float)):
        return int(created)
    try:
        from datetime import datetime
        return int(datetime.fromisoformat(str(created).replace("Z", "+00:00")).timestamp())
    except ValueError:
        return 0


def _version(model_id):
    """The first number in its name that isn't a size, "gemini-3.1-pro" 3.1 but not the 40 of "flint-40b", for lists
    that don't say when a model came out."""
    m = re.search(r"(?<![\d.])\d+(?:\.\d+)?(?![\d.]*[bkm]\b)", model_id.rsplit("/", 1)[-1], re.I)
    return float(m.group()) if m else 0.0


def _models(provider, rows):
    seen, out = set(), []
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = str(row.get("id") or row.get("name") or "")
        if model_id.startswith("models/"):  # Gemini's
            model_id = model_id[len("models/"):]
        outputs = (row.get("architecture") or {}).get("output_modalities")
        if not model_id or model_id in seen or NOT_CHAT.search(model_id) or (outputs and "text" not in outputs):
            continue
        seen.add(model_id)
        out.append({"id": model_id, "free": is_free(provider, model_id, row),
                    "created": _when(row.get("created") or row.get("created_at") or 0),
                    "ctx": int(row.get("context_length") or row.get("context_window") or 0)})
    out.sort(key=lambda m: (-m["created"], -_version(m["id"]), m["id"]))  # newest first
    return out


def _fetch(provider, timeout):
    k = key(provider)
    if provider.key and not k and not provider.open_list:
        raise RuntimeError(f"Add your {provider.name} key to see its models")
    if provider.id == "anthropic":
        from opencode import ANTHROPIC_VERSION
        headers, params = {"x-api-key": k, "anthropic-version": ANTHROPIC_VERSION}, {"limit": 1000}
    else:
        headers, params = ({"Authorization": f"Bearer {k}"} if k else {}), None
    try:
        r = requests.get(f"{provider.base}/models", headers=headers, params=params,
                         timeout=3 if provider.local else timeout)
    except requests.ConnectionError:
        if provider.local:
            raise RuntimeError(f"{provider.name.split(' (')[0]} isn't running on this PC")
        raise
    if r.status_code in (401, 403):
        raise RuntimeError(f"{provider.name} turned the key down ({r.status_code}), check it")
    r.raise_for_status()
    j = r.json()
    return _models(provider, j if isinstance(j, list) else j.get("data") or j.get("models") or [])


def _load():
    global _catalog
    if _catalog is None:
        try:
            with open(PATH, encoding="utf-8") as f:
                _catalog = json.load(f)
        except (OSError, ValueError):
            _catalog = {}
    return _catalog


def _save():
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_catalog, f)
    os.replace(tmp, PATH)


def cached(provider):
    """What's known of its list: {"at", "models", "error"}, models empty before it's first read."""
    with _lock:
        return dict(_load().get(provider.id) or {"at": 0, "models": [], "error": ""})


def stale(provider):
    """Half an hour old, or read before its key was saved, when it could only say to add one."""
    entry = cached(provider)
    return time.time() - entry["at"] > FRESH_FOR or (entry["error"].startswith("Add your") and bool(key(provider)))


def refresh(provider, timeout=15):
    """Reads its list again. One that fails keeps the models it had, with why."""
    entry = cached(provider)
    try:
        entry.update(models=_fetch(provider, timeout), error="")
    except Exception as exc:
        entry["error"] = str(exc) if isinstance(exc, RuntimeError) else f"couldn't get the list: {exc}"
    entry["at"] = time.time()
    with _lock:
        _load()[provider.id] = entry
        try:
            _save()
        except OSError as exc:
            print(f"  couldn't save the model lists: {exc!r}")
    return entry


def refresh_all(providers=PROVIDERS, only_stale=True):
    """Every provider that can list its models, at once."""
    todo = [p for p in providers if (ready(p) or p.open_list) and (not only_stale or stale(p))]
    with ThreadPoolExecutor(len(todo) or 1) as pool:
        list(pool.map(refresh, todo))
    return todo
