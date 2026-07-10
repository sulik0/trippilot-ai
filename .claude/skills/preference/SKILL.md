---
name: preference
description: Use this skill when the user states or updates their preferences, e.g. hotel brands, airlines, home location, seat preference. Triggers when user says "我喜欢住汉庭", "我还喜欢如家", "我搬家到上海了", "我常坐东航". This skill uses PreferenceAgent and requires a MemoryManager to persist preferences; when used standalone, apply returned preferences via memory_manager.long_term.save_preference.
---

# Preference (偏好管理)

识别用户偏好并支持**追加**（还、也）与**覆盖**（搬家到、改成）。使用 **PreferenceAgent**。持久化由 **MemoryManager** 完成：在协调器流程中由协调器写回；单独调用时需根据返回的 `preferences` 列表自行调用 `memory_manager.long_term.save_preference()`。

## When to Use

- 用户说「我喜欢XX」「我还喜欢XX」「我搬家到XX」「我常坐东航」等

## Agent

- **PreferenceAgent** (`agents/preference_agent.py`)
- 入参：**model**、**memory_manager**（用于读取当前偏好；写回由协调器或调用方完成）
- **异步**：`reply()` 为 `async`，需 `await`

## 行为

- **append**：识别「还」「也」等，在已有列表上追加
- **replace**：识别「搬家到」「改成」等，覆盖原值
- 偏好类型：`hotel_brands`, `airlines`, `home_location`, `seat_preference`, `meal_preference`, `budget_level` 等，支持自定义

## 初始化与调用

```python
import asyncio
import json
from agentscope.message import Msg
from agentscope.model import OpenAIChatModel
from config_agentscope import init_agentscope
from config import LLM_CONFIG
from context.memory_manager import MemoryManager
from agents.preference_agent import PreferenceAgent

async def save_preference(user_query: str, user_id: str = "default_user", session_id: str = "default"):
    init_agentscope()
    model = OpenAIChatModel(
        model_name=LLM_CONFIG["model_name"],
        api_key=LLM_CONFIG["api_key"],
        client_kwargs={"base_url": LLM_CONFIG["base_url"], "timeout": 60},
        temperature=LLM_CONFIG.get("temperature", 0.7),
        max_tokens=LLM_CONFIG.get("max_tokens", 2000),
    )
    memory_manager = MemoryManager(user_id=user_id, session_id=session_id, llm_model=model)
    agent = PreferenceAgent(name="PreferenceAgent", model=model, memory_manager=memory_manager)
    user_msg = Msg(name="user", content=user_query, role="user")
    result = await agent.reply(user_msg)
    data = json.loads(result.content) if isinstance(result.content, str) else result.content
    if data.get("has_preferences") and data.get("preferences"):
        for item in data["preferences"]:
            pref_type = item.get("type")
            value = item.get("value")
            action = item.get("action", "replace")
            current = memory_manager.long_term.get_preference().get(pref_type)
            if action == "append" and isinstance(current, list):
                memory_manager.long_term.save_preference(pref_type, current + [value])
            else:
                memory_manager.long_term.save_preference(pref_type, value)
    return data

# 使用
data = asyncio.run(save_preference("我还喜欢如家"))
# data: {"preferences": [{"type": "hotel_brands", "value": "如家", "action": "append"}], "has_preferences": true}
```

## 返回格式

- `preferences`: 列表，每项为 PreferenceUpdate，推荐字段为 `{ "preference_type", "preference_key", "value", "action", "scope", "polarity", "confidence", "reason" }`
- `has_preferences`: bool
- 兼容旧格式 `{ "type", "value", "action" }`，但新输出应优先使用 PreferenceUpdate。


## 偏好提取规则

【任务说明】
你需要判断用户的意图：
1. **追加（append）**：用户想在已有偏好基础上增加新的选项
   - 关键词：「还」、「也」、「另外」、「以及」
   - 示例："我还喜欢汉庭" → 追加到 hotel_brands
   - 示例："我也常坐东航" → 追加到 airlines

2. **覆盖（replace）**：用户想更新/替换原有的偏好
   - 关键词：「搬家到」、「改成」、「现在是」、「换成」
   - 示例："我搬家到上海了" → 覆盖 home_location
   - 示例："我现在喜欢靠窗座位" → 覆盖 seat_preference

3. **更新（update）**：用户想调整某类偏好的优先级或属性，不一定替换所有同类偏好
   - 关键词：「以后优先」、「尽量」、「更偏好」
   - 示例："以后优先高铁" → update transportation_preference

4. **删除/负向偏好（delete）**：用户表达长期不要某个选项
   - 关键词：「以后别」、「不要再」、「别推荐」
   - 示例："以后别推荐如家" → delete hotel_brands，polarity=negative，scope=long_term

5. **忽略/会话级约束（ignore）**：用户只对本次或当前会话生效
   - 关键词：「这次」、「本次」、「今天」、「这趟」
   - 示例："这次别住汉庭" → ignore hotel_brands，scope=session_only

6. **首次设置**：用户第一次提及某个偏好
   - 如果当前偏好中没有这个字段，默认使用 replace

【常见偏好类型】
- home_location: 家庭地址/常住地
- hotel_brands: 酒店品牌偏好
- airlines: 航空公司偏好
- seat_preference: 座位偏好
- meal_preference: 餐食偏好
- budget_level: 预算等级
- transportation_preference: 交通偏好
- food_preference: 美食偏好
（支持自定义新的偏好类型）

【输出格式】(严格JSON)
{{
    "preferences": [
        {{
            "preference_type": "hotel_brands",
            "preference_key": "如家",
            "value": "如家",
            "action": "append",
            "scope": "long_term",
            "polarity": "positive",
            "confidence": 0.92,
            "reason": "用户说“我还喜欢如家”，表示在已有酒店偏好上追加"
        }},
        {{
            "preference_type": "home_location",
            "preference_key": "home_location",
            "value": "上海浦东新区",
            "action": "replace",
            "scope": "long_term",
            "polarity": "positive",
            "confidence": 0.95,
            "reason": "用户说搬家到上海浦东新区，表示常住地覆盖"
        }}
    ],
    "has_preferences": true
}}

【重要规则】
1. action 只能是 "append", "replace", "update", "delete", "ignore"
2. scope 只能是 "long_term" 或 "session_only"
3. polarity 只能是 "positive", "negative", "neutral"
4. 如果用户使用「还」、「也」等词，通常使用 append
5. 如果用户使用「搬家」、「改成」等词，通常使用 replace
6. 如果用户使用「以后优先」，通常使用 update + long_term
7. 如果用户使用「以后别」、「别推荐」，通常使用 delete + long_term + negative
8. 如果用户使用「这次」、「本次」、「今天」，通常使用 ignore + session_only
9. 如果用户未提及任何偏好，返回 {{"preferences": [], "has_preferences": false}}
