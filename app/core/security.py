import hashlib
import secrets
import time
from collections.abc import MutableMapping
from hmac import compare_digest
from typing import Any

def token_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def new_state() -> str:
    return secrets.token_urlsafe(32)


OAUTH_STATE_MAX_AGE_SECONDS = 600
OAUTH_STATE_MAX_PENDING = 5

def store_oauth_state(session: MutableMapping[str, Any], state: str, now: float | None = None) -> None:
    current_time = time.time() if now is None else now
    pending = session.get("oauth_states")
    valid_states: list[dict[str, str | float]] = []
    if isinstance(pending, list):
        for item in pending:
            if not isinstance(item, dict):
                continue
            value = item.get("state")
            issued_at = item.get("issued_at")
            if not isinstance(value, str) or not isinstance(issued_at, (int, float)) or isinstance(issued_at, bool):
                continue
            if current_time - OAUTH_STATE_MAX_AGE_SECONDS <= issued_at <= current_time + 60:
                valid_states.append({"state": value, "issued_at": float(issued_at)})
    legacy_state = session.pop("oauth_state", None)
    if isinstance(legacy_state, str):
        valid_states.append({"state": legacy_state, "issued_at": current_time})
    valid_states.append({"state": state, "issued_at": current_time})
    session["oauth_states"] = valid_states[-OAUTH_STATE_MAX_PENDING:]

def consume_oauth_state(session: MutableMapping[str, Any], state: str, now: float | None = None) -> bool:
    if not isinstance(state, str) or not state:
        return False
    current_time = time.time() if now is None else now
    pending = session.get("oauth_states")
    retained: list[dict[str, str | float]] = []
    matched = False
    if isinstance(pending, list):
        for item in pending:
            if not isinstance(item, dict):
                continue
            value = item.get("state")
            issued_at = item.get("issued_at")
            if not isinstance(value, str) or not isinstance(issued_at, (int, float)) or isinstance(issued_at, bool):
                continue
            if not current_time - OAUTH_STATE_MAX_AGE_SECONDS <= issued_at <= current_time + 60:
                continue
            if not matched and compare_digest(value, state):
                matched = True
                continue
            retained.append({"state": value, "issued_at": float(issued_at)})
    legacy_state = session.get("oauth_state")
    if not matched and isinstance(legacy_state, str) and compare_digest(legacy_state, state):
        matched = True
        session.pop("oauth_state", None)
    if retained:
        session["oauth_states"] = retained
    else:
        session.pop("oauth_states", None)
    return matched
