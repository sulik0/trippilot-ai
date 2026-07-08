# Step 02：运行轨迹与轻量可观测性

## 背景

Step 01 已经为 Agent 通信增加了 `run_id`、`task_id` 和标准协议外壳，但系统仍然缺少一次请求内部的运行轨迹。

在面试或真实排障场景中，仅知道“调用了哪些 Agent”还不够，还需要回答：

- 本次请求总耗时多少？
- 每个 Agent 分别耗时多少？
- 哪些 Agent 是同一个优先级并行执行的？
- 哪个 Agent 失败了？
- 是否可以把一次请求的执行过程完整回放出来？

因此 Step 02 增加一个轻量级 trace 能力，不引入外部依赖，不接入完整 OpenTelemetry，但让系统具备可观测性雏形。

## 改动内容

### 1. 新增轻量 trace 模块

新增文件：

```text
utils/run_trace.py
```

核心对象：

- `RunTrace`
- `AgentTraceEvent`
- `BatchTraceEvent`

记录维度：

- `run_id`
- run 开始和结束时间
- run 总耗时 `duration_ms`
- 每个优先级批次
- 批次是否并行
- 每个 Agent 的开始时间、结束时间、耗时、状态、错误码

### 2. OrchestrationAgent 接入 trace

改动文件：

```text
agents/orchestration_agent.py
```

接入点：

- 每次请求创建 `RunTrace(run_id)`。
- 每个 priority 批次开始时记录 batch event。
- 每个子 Agent 执行前记录 agent start。
- 子 Agent 执行成功/失败后记录 agent finish。
- 聚合结果时把 trace 放入最终输出。

最终结果新增字段：

```json
{
  "trace": {
    "run_id": "run_test_001",
    "started_at": "2026-07-08T...",
    "ended_at": "2026-07-08T...",
    "duration_ms": 1234,
    "batches": [
      {
        "batch_id": "batch_p1_1",
        "priority": 1,
        "agent_names": ["memory_query", "preference"],
        "parallel": true,
        "duration_ms": 340
      }
    ],
    "agents": [
      {
        "task_id": "task_memory_query_xxxxxxxx",
        "agent_name": "memory_query",
        "priority": 1,
        "status": "success",
        "duration_ms": 120
      }
    ]
  }
}
```

### 3. CLI 展示执行轨迹摘要

改动文件：

```text
cli.py
```

用户在 CLI 中执行一次请求后，会看到类似：

```text
⏱️ 执行轨迹: 总耗时 1.23s | 事项收集 0.42s / 行程规划 0.78s
```

这样在演示时可以直接证明：

- 系统确实调用了多个 Agent。
- 每个 Agent 有独立耗时。
- 后续可以进一步接入日志系统或 trace backend。

### 4. 测试覆盖

更新文件：

```text
tests/test_smoke.py
```

新增覆盖：

- 最终聚合结果包含 `trace`。
- `trace.run_id` 与请求 `run_id` 一致。
- 单 Agent 调用会记录一个 batch 和一个 agent event。
- 同优先级两个 Agent 会记录 `parallel=true`。
- 每个 Agent event 都包含状态和耗时。

## 验证命令

```bash
.venv313/bin/python -m compileall -q agents context utils cli.py config.py config_agentscope.py scripts tests/test_smoke.py
.venv313/bin/python -m pytest -q
```

## 面试讲法

可以这样介绍本次升级：

> 我在协议层的 run_id/task_id 基础上继续补了轻量可观测性。每次 OrchestrationAgent 执行都会生成一个 RunTrace，记录 priority 批次、是否并行、每个子 Agent 的状态和耗时。这样演示时不仅能看到最终答案，也能看到 Agent 执行链路；如果后续生产化，可以把这个 trace 平滑接入 OpenTelemetry 或日志平台。

如果被问为什么不直接接 OpenTelemetry：

> 当前项目是简历展示型原型，我先用标准库做轻量 trace，避免引入部署复杂度。设计上保留了 run、batch、agent event 三层结构，未来迁移到 OpenTelemetry 时可以对应到 trace/span/event。

## 本次没有做的事

- 没有接入 Prometheus / OpenTelemetry。
- 没有把 trace 写入数据库。
- 没有统计 token 和成本。
- 没有做完整日志平台。

这些可以作为后续生产化方向继续扩展。
