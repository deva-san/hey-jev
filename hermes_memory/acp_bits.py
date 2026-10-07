# From Hermes Agent by Nous Research, agent/copilot_acp_client.py at commit 3569fba6a686e17f9208da7500de8bd20b4c82f9
# https://github.com/NousResearch/hermes-agent, MIT License, see LICENSE in this folder.
# Copied by sync_hermes.py; only the imports are changed, see UPSTREAM.json. Don't edit by hand.

"""Pieces of Hermes Agent's ACP client (agent/copilot_acp_client.py) Hey Jev uses to drive the OpenCode CLI in
coder.py: its JSON-RPC replies, and picking the session's model from the ones it offers."""

from typing import Any


# --- agent/copilot_acp_client.py ---

def _jsonrpc_result(message_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _jsonrpc_error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _enabled_id_list(entries: Any, key: str) -> list[str]:
    """Ordered ids whose ``_meta.copilotEnablement`` is not ``disabled``."""
    seen: set[str] = set()
    result: list[str] = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        value = str(entry.get(key) or "").strip()
        if (not value or value in seen
                or str((entry.get("_meta") or {}).get("copilotEnablement") or "").strip().lower() == "disabled"):
            continue
        seen.add(value)
        result.append(value)
    return result


def _model_config_option(session: dict[str, Any]) -> dict[str, Any] | None:
    return next((option for option in (session.get("configOptions") or []) if isinstance(option, dict)
                 and "model" in (option.get("category"), option.get("id"))), None)


def _session_model_ids(session: dict[str, Any]) -> list[str]:
    """Account-authorized model ids advertised by ``session/new`` in ACP v1 or its legacy extension."""
    if option := _model_config_option(session):
        return _enabled_id_list(option.get("options"), "value")
    return _legacy_session_model_ids(session)


def _legacy_session_model_ids(session: dict[str, Any]) -> list[str]:
    return _enabled_id_list((session.get("models") or {}).get("availableModels"), "modelId")


def _model_selection_request(session: dict[str, Any], requested_model: str) -> tuple[str, dict[str, str]] | None:
    """ACP request selecting ``requested_model`` for ``session``: stable v1
    ``session/set_config_option``, else Copilot's pre-stabilization ``session/set_model``
    when no model config option is advertised. A reported model list is authoritative:
    unknown and policy-disabled ids return None instead of being sent."""
    session_id = str(session.get("sessionId") or "").strip()
    requested_model = str(requested_model or "").strip()
    if not session_id or not requested_model or requested_model == "copilot-acp":
        return None
    option = _model_config_option(session)
    if option:
        if requested_model not in _enabled_id_list(option.get("options"), "value"):
            return None
        return "session/set_config_option", {"sessionId": session_id, "configId": str(option.get("id") or "model"), "value": requested_model}
    available = _legacy_session_model_ids(session)
    return None if available and requested_model not in available else ("session/set_model", {"sessionId": session_id, "modelId": requested_model})
