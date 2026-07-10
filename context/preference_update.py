#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Preference update protocol.

The protocol keeps PreferenceAgent output explicit enough for long-term memory,
session-only overrides, negative preferences, and future audit storage.
"""
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


VALID_ACTIONS = {"append", "replace", "update", "delete", "ignore"}
VALID_SCOPES = {"long_term", "session_only"}
VALID_POLARITIES = {"positive", "negative", "neutral"}


@dataclass(frozen=True)
class PreferenceUpdate:
    preference_type: str
    preference_key: str
    value: Any
    action: str = "replace"
    scope: str = "long_term"
    polarity: str = "positive"
    confidence: float = 1.0
    reason: str = ""

    @classmethod
    def from_dict(cls, raw: Dict[str, Any]) -> "PreferenceUpdate":
        preference_type = raw.get("preference_type") or raw.get("type")
        value = raw.get("value")
        preference_key = raw.get("preference_key") or raw.get("key") or _infer_key(value)
        action = raw.get("action", "replace")
        scope = raw.get("scope", "long_term")
        polarity = raw.get("polarity") or _infer_polarity(action)
        confidence = raw.get("confidence", 1.0)

        if not preference_type:
            raise ValueError("preference_type is required")
        if not preference_key:
            raise ValueError("preference_key is required")
        if value is None:
            value = preference_key
        if action not in VALID_ACTIONS:
            raise ValueError(f"unsupported preference action: {action}")
        if scope not in VALID_SCOPES:
            raise ValueError(f"unsupported preference scope: {scope}")
        if polarity not in VALID_POLARITIES:
            raise ValueError(f"unsupported preference polarity: {polarity}")

        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 1.0
        confidence = min(max(confidence, 0.0), 1.0)

        return cls(
            preference_type=preference_type,
            preference_key=str(preference_key),
            value=value,
            action=action,
            scope=scope,
            polarity=polarity,
            confidence=confidence,
            reason=raw.get("reason", ""),
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "preference_type": self.preference_type,
            "preference_key": self.preference_key,
            "value": self.value,
            "action": self.action,
            "scope": self.scope,
            "polarity": self.polarity,
            "confidence": self.confidence,
            "reason": self.reason,
        }


def normalize_preference_updates(raw_preferences: Any) -> List[PreferenceUpdate]:
    if isinstance(raw_preferences, dict):
        raw_items = [
            {"preference_type": key, "value": value, "action": "replace"}
            for key, value in raw_preferences.items()
            if key not in {"has_preferences", "error"} and value
        ]
    elif isinstance(raw_preferences, list):
        raw_items = [item for item in raw_preferences if isinstance(item, dict)]
    else:
        raw_items = []

    updates: List[PreferenceUpdate] = []
    for item in raw_items:
        try:
            updates.append(PreferenceUpdate.from_dict(item))
        except ValueError:
            continue
    return updates


def apply_preference_update(current_preferences: Dict[str, Any], update: PreferenceUpdate) -> Optional[Any]:
    """Return the new stored value for a long-term update.

    Session-only and ignore updates do not return a long-term value.
    """
    if update.scope == "session_only" or update.action == "ignore":
        return None

    current_value = current_preferences.get(update.preference_type)

    if update.action == "append":
        return _append_value(current_value, update.value)
    if update.action == "replace":
        return update.value
    if update.action == "update":
        if isinstance(current_value, dict) and isinstance(update.value, dict):
            return {**current_value, **update.value}
        return update.value
    if update.action == "delete":
        return _delete_value(current_value, update.preference_key)

    return update.value


def _infer_key(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("name", "value", "city", "brand"):
            if value.get(key):
                return str(value[key])
        return ""
    if isinstance(value, list):
        return str(value[0]) if value else ""
    return str(value) if value else ""


def _infer_polarity(action: str) -> str:
    if action == "delete":
        return "negative"
    if action == "ignore":
        return "neutral"
    return "positive"


def _append_value(current_value: Any, new_value: Any) -> List[Any]:
    values = []
    if isinstance(current_value, list):
        values.extend(current_value)
    elif current_value:
        values.append(current_value)

    if isinstance(new_value, list):
        for item in new_value:
            if item not in values:
                values.append(item)
    elif new_value not in values:
        values.append(new_value)

    return values


def _delete_value(current_value: Any, preference_key: str) -> Any:
    if isinstance(current_value, list):
        return [item for item in current_value if str(item) != preference_key]
    if isinstance(current_value, dict):
        result = dict(current_value)
        result.pop(preference_key, None)
        return result
    if str(current_value) == preference_key:
        return None
    return current_value
