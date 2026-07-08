"""
Lightweight run tracing for orchestration.

This is intentionally dependency-free. It gives the demo project a clear
observability story without introducing a full tracing backend.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from time import perf_counter
from typing import Any, Dict, List, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def elapsed_ms(start_perf: float) -> int:
    return int((perf_counter() - start_perf) * 1000)


@dataclass
class AgentTraceEvent:
    task_id: str
    agent_name: str
    priority: int
    status: str = "running"
    started_at: str = field(default_factory=now_iso)
    ended_at: Optional[str] = None
    duration_ms: Optional[int] = None
    error_code: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BatchTraceEvent:
    batch_id: str
    priority: int
    agent_names: List[str]
    parallel: bool
    started_at: str = field(default_factory=now_iso)
    ended_at: Optional[str] = None
    duration_ms: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class RunTrace:
    """Collects one end-to-end orchestration trace."""

    def __init__(self, run_id: str):
        self.run_id = run_id
        self.started_at = now_iso()
        self.ended_at: Optional[str] = None
        self.duration_ms: Optional[int] = None
        self._start_perf = perf_counter()
        self._agent_start_perf: Dict[str, float] = {}
        self._batch_start_perf: Dict[str, float] = {}
        self.agent_events: List[AgentTraceEvent] = []
        self.batch_events: List[BatchTraceEvent] = []

    def start_batch(self, batch_id: str, priority: int, agent_names: List[str], parallel: bool) -> None:
        self._batch_start_perf[batch_id] = perf_counter()
        self.batch_events.append(BatchTraceEvent(
            batch_id=batch_id,
            priority=priority,
            agent_names=agent_names,
            parallel=parallel,
        ))

    def finish_batch(self, batch_id: str) -> None:
        start_perf = self._batch_start_perf.pop(batch_id, None)
        for event in self.batch_events:
            if event.batch_id == batch_id:
                event.ended_at = now_iso()
                event.duration_ms = elapsed_ms(start_perf) if start_perf is not None else None
                return

    def start_agent(self, task_id: str, agent_name: str, priority: int) -> None:
        self._agent_start_perf[task_id] = perf_counter()
        self.agent_events.append(AgentTraceEvent(
            task_id=task_id,
            agent_name=agent_name,
            priority=priority,
        ))

    def finish_agent(self, task_id: str, status: str, error_code: Optional[str] = None) -> None:
        start_perf = self._agent_start_perf.pop(task_id, None)
        for event in self.agent_events:
            if event.task_id == task_id:
                event.status = status
                event.error_code = error_code
                event.ended_at = now_iso()
                event.duration_ms = elapsed_ms(start_perf) if start_perf is not None else None
                return

    def finish(self) -> None:
        self.ended_at = now_iso()
        self.duration_ms = elapsed_ms(self._start_perf)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "batches": [event.to_dict() for event in self.batch_events],
            "agents": [event.to_dict() for event in self.agent_events],
        }
