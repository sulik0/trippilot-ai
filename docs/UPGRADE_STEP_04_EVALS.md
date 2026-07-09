# Step 04：离线评测集与 Agent 回归测试

## 背景

项目已经具备多 Agent 编排、协议外壳、运行轨迹和 Skill Manifest。接下来需要回答一个面试中很常见的问题：

> 你怎么证明这个 Agent 系统的核心行为没有退化？

真实线上评测通常需要大量数据、真实 LLM、检索服务和人工标注。但这个项目是简历项目，当前更合理的做法是先建立小型离线评测集和 mock-based contract tests。

## 本次新增内容

### 1. 新增离线 Eval 数据集

新增 `evals/agent_contract_cases.jsonl`。

当前覆盖 6 个样例：

- `intent_trip_with_preference`：行程规划 + 偏好收集。
- `intent_policy_rag`：差旅政策问题应路由到 `rag_knowledge`。
- `event_collection_complete`：完整行程事项抽取。
- `preference_append`：偏好追加。
- `preference_replace`：偏好覆盖。
- `information_weather`：天气查询分类。

每条数据包含：

- `id`：用例 ID。
- `agent`：目标 Agent 或能力路径。
- `input`：用户输入。
- `expected`：期望合同结果。

### 2. 新增 Eval 说明

新增 `evals/README.md`，说明数据集目标、覆盖路径和运行方式。

这个目录的定位不是做模型排行榜，而是作为项目工程质量的一部分：

- 固定关键业务路径。
- 让核心能力可以被离线验证。
- 避免每次改 prompt 或 agent 代码都靠手工试。

### 3. 新增 Agent Contract Tests

新增 `tests/test_agent_contracts.py`。

测试特点：

- 不调用真实 SiliconFlow / OpenAI API。
- 不访问网络。
- 不初始化 Milvus / sentence-transformers。
- 使用 `StaticModel` mock LLM 输出。
- 动态加载 `.claude/skills/*/script/agent.py`，验证真实 Agent 解析逻辑。

覆盖内容：

- Eval JSONL 数据可加载。
- `IntentionAgent` 输出意图和调度结构。
- `EventCollectionAgent` 输出结构化事项。
- `PreferenceAgent` 区分 append / replace。
- `InformationQueryAgent` 能把天气问题走天气分支。

### 4. 为什么不用真实 LLM 做测试

当前阶段选择 mock-based contract tests，而不是真实 LLM eval，原因是：

- 真实模型输出有随机性，容易让 CI 不稳定。
- API Key、网络、限额都会影响测试结果。
- 本阶段目标是验证系统合同，不是验证模型最终效果。

后续如果要更接近生产，可以在离线合同测试之外，再增加单独的人工评测或 nightly eval。

## 面试讲法

可以这样描述：

> 我给核心 Agent 链路加了一套小型离线评测集，用 JSONL 固定典型输入和期望合同，再用 mock LLM 输出做 contract tests。这样不依赖真实 API，也能验证意图路由、事项抽取、偏好追加/覆盖、RAG 路由和天气查询分类这些核心行为。真实模型效果可以后续单独做人工评测，但工程回归先保持稳定。

这个点能回答：

- “你怎么验证 Agent 没有改坏？”
- “你们怎么做 prompt 改动回归？”
- “为什么测试不直接调真实模型？”

## 当前边界

本次仍不做完整生产级 eval：

- 没有准确率、召回率等统计指标。
- 没有人工标注平台。
- 没有真实 LLM 多轮采样。
- 没有 RAG 检索质量评估。

但它已经让项目从“能跑 demo”提升到“核心合同可回归”。

## 验证命令

```bash
.venv313/bin/python -m compileall -q agents context utils cli.py config.py config_agentscope.py scripts tests/test_smoke.py tests/test_agent_contracts.py
.venv313/bin/python -m pytest -q
```

预期结果：

- Python 编译检查通过。
- 全部测试通过。
