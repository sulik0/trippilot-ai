import asyncio
import json

from agents.lazy_agent_registry import LazyAgentRegistry
from agents.orchestration_agent import OrchestrationAgent
from agents.protocol import PROTOCOL_VERSION
from agentscope.message import Msg
from context.memory_manager import MemoryManager
from context.stores import InMemoryShortTermStore, JsonLongTermStore, NoopSummaryQueue
from utils.skill_manifest import SkillManifestLoader


class FakeModel:
    async def __call__(self, messages):
        prompt = messages[-1]["content"]
        if "事项收集专家" in prompt:
            return type("Resp", (), {"content": json.dumps({
                "origin": "北京",
                "destination": "上海",
                "start_date": "2026-07-08",
                "end_date": "2026-07-10",
                "duration_days": 3,
                "return_location": "北京",
                "trip_purpose": "出差",
                "missing_info": [],
                "extracted_count": 7,
                "summary": "北京到上海出差3天",
            }, ensure_ascii=False)})()
        return type("Resp", (), {"content": "{}"})()


def test_memory_roundtrip(tmp_path):
    memory = MemoryManager("smoke_user", "smoke_session", storage_path=str(tmp_path))
    memory.long_term.save_preference("hotel_brands", ["汉庭"])
    memory.long_term.save_trip_history({
        "origin": "北京",
        "destination": "上海",
        "start_date": "2026-07-08",
        "purpose": "出差",
    })

    reloaded = MemoryManager("smoke_user", "next_session", storage_path=str(tmp_path))

    assert reloaded.long_term.get_preference("hotel_brands") == ["汉庭"]
    assert reloaded.long_term.get_trip_history(1)[0]["destination"] == "上海"
    assert reloaded.get_store_backends()["short_term"] == "in_memory"
    assert reloaded.get_store_backends()["long_term"] == "json_file"


def test_memory_manager_accepts_store_adapters(tmp_path):
    short_term = InMemoryShortTermStore(max_turns=1)
    long_term = JsonLongTermStore("adapter_user", str(tmp_path))
    summary_queue = NoopSummaryQueue()
    memory = MemoryManager(
        "adapter_user",
        "adapter_session",
        short_term_store=short_term,
        long_term_store=long_term,
        summary_queue=summary_queue,
    )

    memory.add_message("user", "我喜欢住汉庭")
    memory.add_message("assistant", "已记录")
    memory.add_message("user", "我还喜欢如家")
    memory.long_term.save_preference("hotel_brands", ["汉庭", "如家"])
    memory.summary_queue.publish("memory.session.closed", {"session_id": "adapter_session"})

    context = memory.get_full_context()

    assert len(memory.short_term.get_recent_context()) == 2
    assert memory.long_term.get_preference("hotel_brands") == ["汉庭", "如家"]
    assert context["short_term"]["backend"] == "in_memory"
    assert context["long_term"]["backend"] == "json_file"
    assert context["summary_queue"]["backend"] == "noop"
    assert summary_queue.events[0]["event_type"] == "memory.session.closed"


def test_lazy_registry_loads_event_collection():
    registry = LazyAgentRegistry(model=FakeModel(), cache={})
    agent = registry["event_collection"]

    assert "event_collection" in registry.get_loaded_agents()
    manifest = registry.get_skill_manifest("event_collection")
    assert manifest["name"] == "event-collection"
    assert manifest["agent_name"] == "event_collection"
    assert manifest["entrypoint"] == "script/agent.py"

    async def run():
        msg = Msg(
            name="test",
            content=json.dumps({"context": {"rewritten_query": "北京到上海出差3天"}}, ensure_ascii=False),
            role="user",
        )
        result = await agent.reply(msg)
        return json.loads(result.content)

    data = asyncio.run(run())
    assert data["origin"] == "北京"
    assert data["destination"] == "上海"


def test_skill_manifests_are_valid():
    manifests = SkillManifestLoader(".claude/skills").discover()

    assert set(manifests.keys()) == {
        "ask-question",
        "event-collection",
        "memory-query",
        "plan-trip",
        "preference",
        "query-info",
    }
    assert manifests["preference"].requires == ["llm", "memory_manager"]
    assert manifests["query-info"].timeout_seconds == 45
    assert manifests["plan-trip"].entrypoint_path.exists()


def test_orchestrator_uses_protocol_envelope():
    captured = {}

    class CaptureAgent:
        async def reply(self, msg):
            captured["payload"] = json.loads(msg.content)
            return Msg(
                name="capture",
                content=json.dumps({"answer": "ok"}, ensure_ascii=False),
                role="assistant",
            )

    orchestrator = OrchestrationAgent(
        agent_registry={"memory_query": CaptureAgent()},
        memory_manager=None,
    )
    intention = {
        "run_id": "run_test_001",
        "intents": [{"type": "memory_query"}],
        "key_entities": {},
        "rewritten_query": "查询我的偏好",
        "agent_schedule": [{
            "agent_name": "memory_query",
            "priority": 1,
            "reason": "验证协议",
            "expected_output": "返回答案",
        }],
    }

    async def run():
        msg = Msg(
            name="IntentionAgent",
            content=json.dumps(intention, ensure_ascii=False),
            role="assistant",
        )
        result = await orchestrator.reply(msg)
        return json.loads(result.content)

    data = asyncio.run(run())

    assert data["protocol_version"] == PROTOCOL_VERSION
    assert data["run_id"] == "run_test_001"
    assert data["results"][0]["status"] == "success"
    assert data["results"][0]["task_id"].startswith("task_memory_query_")
    assert data["trace"]["run_id"] == "run_test_001"
    assert data["trace"]["duration_ms"] >= 0
    assert len(data["trace"]["batches"]) == 1
    assert data["trace"]["batches"][0]["parallel"] is False
    assert len(data["trace"]["agents"]) == 1
    assert data["trace"]["agents"][0]["agent_name"] == "memory_query"
    assert data["trace"]["agents"][0]["status"] == "success"
    assert data["trace"]["agents"][0]["duration_ms"] >= 0
    assert captured["payload"]["protocol_version"] == PROTOCOL_VERSION
    assert captured["payload"]["run_id"] == "run_test_001"
    assert captured["payload"]["reason"] == "验证协议"
    assert captured["payload"]["context"]["rewritten_query"] == "查询我的偏好"


def test_orchestrator_rejects_invalid_schedule():
    orchestrator = OrchestrationAgent(agent_registry={}, memory_manager=None)

    async def run():
        msg = Msg(
            name="IntentionAgent",
            content=json.dumps({
                "agent_schedule": [{"priority": 1}],
            }),
            role="assistant",
        )
        result = await orchestrator.reply(msg)
        return json.loads(result.content)

    data = asyncio.run(run())

    assert data["status"] == "error"
    assert data["protocol_version"] == PROTOCOL_VERSION
    assert data["error"]["code"] == "INVALID_AGENT_SCHEDULE"


def test_orchestrator_traces_parallel_batch():
    class OkAgent:
        def __init__(self, name):
            self.name = name

        async def reply(self, msg):
            return Msg(
                name=self.name,
                content=json.dumps({"agent": self.name}, ensure_ascii=False),
                role="assistant",
            )

    orchestrator = OrchestrationAgent(
        agent_registry={
            "memory_query": OkAgent("memory_query"),
            "preference": OkAgent("preference"),
        },
        memory_manager=None,
    )

    async def run():
        msg = Msg(
            name="IntentionAgent",
            content=json.dumps({
                "run_id": "run_parallel_001",
                "agent_schedule": [
                    {"agent_name": "memory_query", "priority": 1},
                    {"agent_name": "preference", "priority": 1},
                ],
            }),
            role="assistant",
        )
        result = await orchestrator.reply(msg)
        return json.loads(result.content)

    data = asyncio.run(run())
    agent_names = {event["agent_name"] for event in data["trace"]["agents"]}

    assert data["status"] == "completed"
    assert data["trace"]["batches"][0]["parallel"] is True
    assert set(data["trace"]["batches"][0]["agent_names"]) == {"memory_query", "preference"}
    assert agent_names == {"memory_query", "preference"}
