"""Store API keys in Windows Credential Manager (the Mac build used the Keychain), with .env as a dev fallback.

OpenCode Zen and Kilo Gateway (answers, free models only), Fish Audio (her voice, free model), and Anthropic, for
Claude Haiku, the one paid model, billed to your own Anthropic account.
"""
import os

import keyring
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))  # works from the shortcut too

SERVICE = "Hey Jev"  # shows up in Credential Manager > Windows Credentials
KEY_NAMES = ("OPENCODE_ZEN_API_KEY", "FISH_AUDIO_API_KEY", "KILO_API_KEY", "TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY")
# Kilo Gateway's free models, besides OpenCode's (see opencode.py); your own Telegram bot, for your phone; Anthropic,
# the one paid model she may use, only when picked in Settings
OPTIONAL = ("KILO_API_KEY", "TELEGRAM_BOT_TOKEN", "ANTHROPIC_API_KEY")
ALIASES = {"OPENCODE_ZEN_API_KEY": ("OPENCODE_API_KEY",)}  # the name OpenCode's own docs use


def vault_value(name):
    try:
        return keyring.get_password(SERVICE, name)
    except Exception:
        return None


def get_secret(name):
    for env_name in (name, *ALIASES.get(name, ())):
        if os.getenv(env_name):
            return os.getenv(env_name)  # .env wins, so editing it always takes effect
    return vault_value(name)


def save_secret(name, value):
    if name not in KEY_NAMES:
        raise ValueError(f"unknown secret: {name}")
    value = value.strip()
    if not value:
        return
    try:
        keyring.set_password(SERVICE, name, value)
    except Exception as exc:
        raise RuntimeError(f"Could not save to Credential Manager: {exc}")


def missing_secrets():
    return [name for name in KEY_NAMES if name not in OPTIONAL and not get_secret(name)]
