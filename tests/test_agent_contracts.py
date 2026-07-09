import asyncio
import importlib.util
import json
import sys
from pathlib import Path

from agents.intention_agent import IntentionAgent
from agentscope.message import Msg


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_CASES = PROJECT_ROOT / "evals" / "agent_contract_cases.jsonl"


class StaticModel:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    async def __call__(self, messages):
        self.calls.append(messages)
        content = self.payload
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        return type("Resp", (), {"content": content})()


class FakeLongTermMemory:
    def __init__(self, preferences=None, trips=None):
        self.preferences = preferences or {}
        self.trips = trips or []

    def get_preference(self, *args, **kwargs):
        return self.preferences

    def get_trip_history(self, limit=50):
        return self.trips[:limit]


class FakeMemoryManager:
    def __init__(self, preferences=None, trips=None):
        self.long_term = FakeLongTermMemory(preferences, trips)

    async def get_long_term_summary_async(self, max_messages=30):
        return ""


def load_cases(agent_name):
    cases = []
    with EVAL_CASES.open("r", encoding="utf-8") as file:
        for line in file:
            item = json.loads(line)
            if item["agent"] == agent_name:
                cases.append(item)
    return cases


def load_skill_agent(skill_name, class_name):
    module_path = PROJECT_ROOT / ".claude" / "skills" / skill_name / "script" / "agent.py"
    module_name = f"test_contract_{skill_name.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return getattr(module, class_name)


def message_from_query(query):
    return Msg(
        name="contract-test",
        content=json.dumps({"context": {"rewritten_query": query}}, ensure_ascii=False),
        role="user",
    )


def test_eval_dataset_is_loadable():
    cases = []
    with EVAL_CASES.open("r", encoding="utf-8") as file:
        for line in file:
            cases.append(json.loads(line))

    assert len(cases) == 6
    assert {case["agent"] for case in cases} == {
        "event_collection",
        "information_query",
        "intention",
        "preference",
    }
    assert all(case.get("id") and case.get("input") and case.get("expected") for case in cases)


def test_intention_agent_contracts_from_eval_cases():
    cases = load_cases("intention")
    outputs = {
        "intent_trip_with_preference": {
            "reasoning": "用户同时提供行程信息和酒店偏好。",
            "intents": [
                {"type": "itinerary_planning", "confidence": 0.95},
                {"type": "preference", "confidence": 0.9},
            ],
            "key_entities": {"origin": "上海", "destination": "北京"},
            "rewritten_query": "下周一从上海去北京出差两天，偏好汉庭酒店",
            "agent_schedule": [
                {"agent_name": "event_collection", "priority": 1},
                {"agent_name": "preference", "priority": 1},
                {"agent_name": "itinerary_planning", "priority": 2},
            ],
        },
        "intent_policy_rag": {
            "reasoning": "用户询问企业差旅住宿标准，应使用知识库。",
            "intents": [{"type": "rag_knowledge", "confidence": 0.92}],
            "key_entities": {"destination": "北京"},
            "rewritten_query": "查询北京出差住宿标准",
            "agent_schedule": [{"agent_name": "rag_knowledge", "priority": 1}],
        },
    }

    async def run_case(case):
        agent = IntentionAgent(model=StaticModel(outputs[case["id"]]))
        result = await agent.reply(Msg(name="user", content=case["input"], role="user"))
        return json.loads(result.content)

    for case in cases:
        data = asyncio.run(run_case(case))
        intent_types = [item["type"] for item in data["intents"]]
        schedule = [item["agent_name"] for item in data["agent_schedule"]]
        for expected_intent in case["expected"]["intents"]:
            assert expected_intent in intent_types
        for expected_agent in case["expected"]["schedule"]:
            assert expected_agent in schedule


def test_event_collection_contract_from_eval_case():
    EventCollectionAgent = load_skill_agent("event-collection", "EventCollectionAgent")
    case = load_cases("event_collection")[0]
    payload = {
        "origin": "杭州",
        "destination": "深圳",
        "start_date": "2026-07-20",
        "end_date": "2026-07-22",
        "duration_days": 3,
        "return_location": "杭州",
        "trip_purpose": "出差",
        "missing_info": [],
        "extracted_count": 7,
        "summary": "杭州到深圳出差三天",
    }

    async def run():
        agent = EventCollectionAgent(model=StaticModel(payload))
        result = await agent.reply(message_from_query(case["input"]))
        return json.loads(result.content)

    data = asyncio.run(run())
    assert data["origin"] == case["expected"]["origin"]
    assert data["destination"] == case["expected"]["destination"]
    assert data["duration_days"] == case["expected"]["duration_days"]
    assert data["missing_info"] == []


def test_preference_contracts_from_eval_cases():
    PreferenceAgent = load_skill_agent("preference", "PreferenceAgent")
    cases = {case["id"]: case for case in load_cases("preference")}
    outputs = {
        "preference_append": {
            "preferences": [{"type": "hotel_brands", "value": "如家", "action": "append"}],
            "has_preferences": True,
        },
        "preference_replace": {
            "preferences": [{"type": "home_location", "value": "上海浦东", "action": "replace"}],
            "has_preferences": True,
        },
    }

    async def run_case(case_id):
        agent = PreferenceAgent(
            model=StaticModel(outputs[case_id]),
            memory_manager=FakeMemoryManager(preferences={"hotel_brands": ["汉庭"]}),
        )
        result = await agent.reply(message_from_query(cases[case_id]["input"]))
        return json.loads(result.content)

    for case_id, case in cases.items():
        data = asyncio.run(run_case(case_id))
        assert data["has_preferences"] is True
        assert data["preferences"][0] == case["expected"]["preferences"][0]


def test_information_query_weather_classification_contract():
    InformationQueryAgent = load_skill_agent("query-info", "InformationQueryAgent")
    case = load_cases("information_query")[0]

    async def fake_weather_query(query):
        return {
            "query_type": "天气查询",
            "query_success": True,
            "results": {"summary": "杭州明天天气晴。"},
        }

    async def run():
        agent = InformationQueryAgent(model=StaticModel({"summary": "unused"}))
        agent._weather_query = fake_weather_query
        result = await agent.reply(message_from_query(case["input"]))
        return json.loads(result.content)

    data = asyncio.run(run())
    assert data["query_type"] == case["expected"]["query_type"]
    assert data["query_success"] is True
