# Step 01：Agent 通信协议标准化

## 背景

原系统中 Agent 之间通过 AgentScope `Msg.content` 传递 JSON 字符串。这个方式简单直接，但工程上存在几个问题：

- JSON 字段是隐式约定，缺少统一协议描述。
- 无法稳定追踪一次用户请求经过了哪些 Agent。
- 子 Agent 失败时错误结构不统一。
- 后续要做可观测性、评测和任务回放时缺少 `run_id` / `task_id`。

本次升级的目标不是重写所有 Skill，而是在不破坏现有插件的前提下，为 Agent 通信增加一层稳定协议外壳。

## 改动内容

### 1. 新增协议模块

新增文件：

```text
agents/protocol.py
```

核心对象：

- `PROTOCOL_VERSION`
- `AgentTask`
- `AgentMessageEnvelope`
- `AgentExecutionResult`
- `AgentError`
- `normalize_agent_output`

协议版本：

```text
trippilot.agent/v1
```

### 2. 调度任务标准化

原始 `agent_schedule` 中的每一项会被转换成 `AgentTask`：

```json
{
  "agent_name": "event_collection",
  "priority": 1,
  "reason": "提取行程基础信息",
  "expected_output": "出发地、目的地、时间"
}
```

升级后会补充：

```json
{
  "agent_name": "event_collection",
  "priority": 1,
  "reason": "提取行程基础信息",
  "expected_output": "出发地、目的地、时间",
  "required": true,
  "task_id": "task_event_collection_xxxxxxxx"
}
```

如果调度项缺少 `agent_name`，系统会返回结构化错误：

```json
{
  "status": "error",
  "error": {
    "code": "INVALID_AGENT_SCHEDULE",
    "message": "agent_name is required in agent_schedule item",
    "retryable": false,
    "user_message": "调度计划格式有误，请重新描述需求。"
  }
}
```

### 3. Agent 调用信封

OrchestrationAgent 调用子 Agent 时，现在会发送统一信封：

```json
{
  "protocol_version": "trippilot.agent/v1",
  "run_id": "run_xxxxxxxxxxxx",
  "task_id": "task_memory_query_xxxxxxxx",
  "agent_name": "memory_query",
  "priority": 1,
  "context": {},
  "reason": "调用原因",
  "expected_output": "期望输出",
  "previous_results": [],
  "required": true,
  "created_at": "2026-07-08T..."
}
```

为了兼容现有 Skill，信封仍保留旧字段：

- `context`
- `reason`
- `expected_output`
- `previous_results`

因此现有 `.claude/skills/*/script/agent.py` 不需要同步重写。

### 4. 聚合结果增加协议字段

OrchestrationAgent 的最终输出新增：

```json
{
  "protocol_version": "trippilot.agent/v1",
  "run_id": "run_xxxxxxxxxxxx",
  "results": [
    {
      "agent_name": "memory_query",
      "priority": 1,
      "task_id": "task_memory_query_xxxxxxxx",
      "status": "success",
      "data": {}
    }
  ]
}
```

### 5. 错误结构标准化

新增统一错误模型：

```json
{
  "code": "AGENT_EXECUTION_FAILED",
  "message": "原始错误",
  "retryable": false,
  "user_message": "智能体执行失败，请稍后重试。"
}
```

当前覆盖的错误类型：

- `INVALID_AGENT_SCHEDULE`
- `AGENT_NOT_REGISTERED`
- `AGENT_EXECUTION_FAILED`
- `PARALLEL_AGENT_EXECUTION_FAILED`
- `CHILD_AGENT_ERROR`

## 测试覆盖

新增/更新测试：

```text
tests/test_smoke.py
```

覆盖内容：

1. `LazyAgentRegistry` 仍能加载原有 Skill。
2. `OrchestrationAgent` 会向子 Agent 发送协议字段。
3. 聚合结果包含 `protocol_version`、`run_id`、`task_id`。
4. 无效调度计划会返回 `INVALID_AGENT_SCHEDULE`。

## 验证命令

```bash
.venv313/bin/python -m compileall -q agents context utils cli.py config.py config_agentscope.py scripts tests/test_smoke.py
.venv313/bin/python -m pytest -q
```

## 面试讲法

可以这样介绍本次升级：

> 原项目里 Agent 之间虽然通过 OrchestrationAgent 中转，但消息本质上是自由 JSON。我做了一个轻量协议层，把一次请求抽象成 run，把每个子 Agent 调用抽象成 task，并为消息加上 protocol_version、run_id、task_id 和标准错误结构。这样不改变现有 Skill 插件的情况下，后续可以继续接入 trace、评测、任务回放和 schema 校验。

如果被问为什么不用 Pydantic：

> 当前阶段为了保持依赖轻量和兼容现有 Skill，我先用 dataclass 做协议外壳；下一步可以把 `AgentTask`、`AgentMessageEnvelope`、`AgentExecutionResult` 平滑升级为 Pydantic model，并对每个 Skill 做输入输出 schema 校验。

## 本次没有做的事

- 没有重写所有 Skill 的输入输出。
- 没有引入 Redis/PostgreSQL。
- 没有引入 OpenTelemetry。
- 没有实现完整生产级 schema registry。

这些会放到后续步骤中逐步增强。
