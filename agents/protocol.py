"""
Shared message protocol for agent orchestration.

The project still passes JSON through AgentScope Msg for compatibility with the
existing Skill plugins, but this module gives the payload a stable envelope that
can be validated and extended without coupling every child agent together.
"""
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import uuid


PROTOCOL_VERSION = "trippilot.agent/v1"


def new_run_id() -> str:
    """Create a readable run id for one end-to-end user request."""
    return f"run_{uuid.uuid4().hex[:12]}"


def new_task_id(agent_name: str) -> str:
    """Create a task id for one child-agent execution."""
    safe_name = (agent_name or "unknown").replace("-", "_")
    return f"task_{safe_name}_{uuid.uuid4().hex[:8]}"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass
class AgentError:
    code: str
    message: str
    retryable: bool = False
    user_message: str = "当前任务执行失败，请稍后重试或补充信息。"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentTask:
    agent_name: str
    priority: int = 0
    reason: str = ""
    expected_output: str = ""
    required: bool = True
    task_id: str = ""

    @classmethod
    def from_schedule_item(cls, item: Dict[str, Any]) -> "AgentTask":
        agent_name = item.get("agent_name") or item.get("agent_type") or ""
        priority = item.get("priority", 0)
        try:
            priority = int(priority)
        except (TypeError, ValueError):
            priority = 999

        task = cls(
            agent_name=agent_name,
            priority=priority,
            reason=item.get("reason", ""),
            expected_output=item.get("expected_output", ""),
            required=bool(item.get("required", True)),
            task_id=item.get("task_id") or new_task_id(agent_name),
        )
        task.validate()
        return task

    def validate(self) -> None:
        if not self.agent_name:
            raise ValueError("agent_name is required in agent_schedule item")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentMessageEnvelope:
    run_id: str
    task: AgentTask
    context: Dict[str, Any]
    previous_results: List[Dict[str, Any]]
    protocol_version: str = PROTOCOL_VERSION
    created_at: str = field(default_factory=utc_now_iso)

    def to_payload(self) -> Dict[str, Any]:
        # Keep legacy top-level fields for existing Skill agents.
        return {
            "protocol_version": self.protocol_version,
            "run_id": self.run_id,
            "task_id": self.task.task_id,
            "agent_name": self.task.agent_name,
            "priority": self.task.priority,
            "context": self.context,
            "reason": self.task.reason,
            "expected_output": self.task.expected_output,
            "previous_results": self.previous_results,
            "required": self.task.required,
            "created_at": self.created_at,
        }


@dataclass
class AgentExecutionResult:
    agent_name: str
    status: str
    data: Dict[str, Any]
    priority: int = 0
    task_id: str = ""
    error: Optional[AgentError] = None

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "agent_name": self.agent_name,
            "priority": self.priority,
            "task_id": self.task_id,
            "status": self.status,
            "data": self.data,
        }
        if self.error:
            result["error"] = self.error.to_dict()
        return result


def normalize_agent_output(agent_name: str, raw_result: Any) -> Dict[str, Any]:
    """Normalize child-agent output into the structure used by OrchestrationAgent."""
    if not isinstance(raw_result, dict):
        raw_result = {"output": raw_result}

    if "error" in raw_result:
        error_message = str(raw_result.get("error") or "Unknown child-agent error")
        return {
            "status": "error",
            "agent_name": agent_name,
            "data": raw_result,
            "message": error_message,
            "error": AgentError(
                code="CHILD_AGENT_ERROR",
                message=error_message,
                retryable=False,
            ).to_dict(),
        }

    return {
        "status": "success",
        "agent_name": agent_name,
        "data": raw_result,
    }
