#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Memory store interfaces and local adapters.

These interfaces make the memory layer replaceable without introducing Redis,
PostgreSQL, Milvus, or MQ as hard runtime dependencies for the local demo.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol

from .long_term_memory import LongTermMemory
from .short_term_memory import ShortTermMemory


class ShortTermStore(Protocol):
    """Session-level memory store, replaceable with Redis later."""

    backend_name: str

    def add_message(self, role: str, content: str, metadata: Dict = None) -> None:
        ...

    def get_recent_context(self, n_turns: int = None) -> List[Dict[str, Any]]:
        ...

    def get_context_string(self, n_turns: int = 5) -> str:
        ...

    def clear(self) -> None:
        ...

    def get_statistics(self) -> Dict[str, Any]:
        ...


class LongTermStore(Protocol):
    """User-level structured memory store, replaceable with PostgreSQL later."""

    backend_name: str

    def save_preference(self, pref_type: str, value: Any) -> None:
        ...

    def get_preference(self, pref_type: str = None) -> Any:
        ...

    def add_chat_message(self, role: str, content: str, session_id: str = None) -> None:
        ...

    def get_chat_history(self, limit: int = None, session_id: str = None) -> List[Dict[str, Any]]:
        ...

    def save_trip_history(self, trip_info: Dict[str, Any]) -> None:
        ...

    def get_trip_history(self, limit: int = 10) -> List[Dict[str, Any]]:
        ...

    def get_frequent_destinations(self, top_n: int = 5) -> List[tuple]:
        ...

    def get_statistics(self) -> Dict[str, Any]:
        ...


class SemanticMemoryStore(Protocol):
    """Long-term semantic memory store, replaceable with Milvus later."""

    backend_name: str

    def upsert_summary(self, summary: Dict[str, Any], embedding: List[float]) -> None:
        ...

    def search(
        self,
        user_id: str,
        query_embedding: List[float],
        memory_type: Optional[str] = None,
        top_k: int = 5,
        score_threshold: float = 0.68,
    ) -> List[Dict[str, Any]]:
        ...


class SummaryQueue(Protocol):
    """Async summarization queue, replaceable with MQ later."""

    backend_name: str

    def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        ...


class InMemoryShortTermStore(ShortTermMemory):
    """Local short-term adapter used by the CLI and tests."""

    backend_name = "in_memory"


class JsonLongTermStore(LongTermMemory):
    """Local JSON long-term adapter used by the CLI and tests."""

    backend_name = "json_file"


@dataclass
class NoopSemanticMemoryStore:
    """Semantic-memory placeholder until a Milvus adapter is introduced."""

    backend_name: str = "noop"

    def upsert_summary(self, summary: Dict[str, Any], embedding: List[float]) -> None:
        return None

    def search(
        self,
        user_id: str,
        query_embedding: List[float],
        memory_type: Optional[str] = None,
        top_k: int = 5,
        score_threshold: float = 0.68,
    ) -> List[Dict[str, Any]]:
        return []


@dataclass
class NoopSummaryQueue:
    """Summary-event placeholder until an MQ adapter is introduced."""

    backend_name: str = "noop"
    events: List[Dict[str, Any]] = field(default_factory=list)

    def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        self.events.append({
            "event_type": event_type,
            "payload": payload,
        })
