# TripPilot AI 简历项目升级路线图

## 升级原则

本路线图目标不是把项目一次性改造成完整生产系统，而是让它在简历和面试中更有工程可信度：

- 每一步都能讲清楚解决了什么工程问题。
- 每一步都有可验证代码或文档产物。
- 每一步独立提交到 GitHub。
- 优先选择“面试官能看懂、能追问、能解释”的工程升级。

## 路线图总览

### Step 01：Agent 通信协议标准化

目标：

- 给 Agent 间通信增加稳定协议外壳。
- 引入 `protocol_version`、`run_id`、`task_id`。
- 标准化 Agent 错误结构。
- 保持现有 Skill JSON 输入兼容。

面试价值：

- 能讲清楚 Agent 间不是随意传字符串，而是有通信契约。
- 能解释后续如何演进到 Pydantic schema / OpenTelemetry trace。

状态：已实施。

### Step 02：运行轨迹与轻量可观测性

目标：

- 记录每次请求的 Agent 执行轨迹。
- 捕获每个 Agent 的开始时间、结束时间、耗时、状态。
- CLI 输出可以展示本次调用了哪些 Agent 和耗时。

产物：

- `utils/run_trace.py`
- OrchestrationAgent 中写入 trace events
- `docs/UPGRADE_STEP_02_TRACE.md`

面试价值：

- 能讲可观测性，不只是“跑通”。
- 能解释怎么定位某个 Agent 慢或失败。

状态：已实施。

### Step 03：Skill Manifest 与能力注册

目标：

- 为每个 Skill 增加机器可读 manifest。
- 声明名称、描述、输入输出、权限、超时。
- LazyAgentRegistry 从 manifest 读取能力元数据。

产物：

- `.claude/skills/*/skill.yaml`
- Skill manifest loader
- manifest 校验测试

面试价值：

- 能讲插件化不是目录扫描，而是有元数据治理。

状态：已实施。

### Step 04：评测集与 Agent 回归测试

目标：

- 建立小型离线 eval 数据集。
- 覆盖意图识别、事项抽取、偏好追加/覆盖、RAG query 分类。
- 增加无需真实 LLM 的 mock-based contract tests。

产物：

- `evals/`
- `tests/test_agent_contracts.py`
- `docs/UPGRADE_STEP_04_EVALS.md`

面试价值：

- 能回答“你怎么证明效果好”。

状态：已实施。

### Step 05：记忆层接口抽象

目标：

- 将短期记忆和长期记忆抽象成接口。
- 当前仍使用 in-memory + JSON 实现。
- 预留 Redis / PostgreSQL adapter 接口，但不真正接入。
- 明确生产目标架构：AgentScope Memory + Redis + PostgreSQL + Milvus + MQ。
- 设计 PreferenceAgent 偏好更新协议，支持 append / replace / update / delete / ignore。

方案产物：

- `context/stores.py`
- `JsonLongTermStore`
- `InMemoryShortTermStore`
- `docs/UPGRADE_STEP_05_MEMORY_ARCHITECTURE.md`

面试价值：

- 能诚实说当前不是 Redis/PG，但架构上已经可替换。
- 能讲清楚短期状态、结构化长期记忆、语义长期记忆和异步总结的边界。

状态：Phase 1 接口抽象已实施；Redis / PostgreSQL / Milvus / MQ adapter 待后续接入。

### Step 06：RAG 索引与检索治理文档化

目标：

- 给文档 ingestion 增加版本、checksum、source metadata。
- 增加 RAG 初始化说明和小型 QA 样例。
- 将 Milvus Lite db 继续排除在 Git 外。

面试价值：

- 能讲 RAG 数据治理和可重建索引。

## 每步提交规范

每一步都按以下格式执行：

1. 代码或文档改动。
2. 新增 `docs/UPGRADE_STEP_XX_*.md`。
3. 运行离线测试。
4. Git commit。
5. Git push。
6. 返回本步改动说明、测试结果、commit hash。

## 当前状态

- GitHub 仓库：`https://github.com/sulik0/trippilot-ai`
- 当前升级阶段：Step 05 记忆模块改造方案
