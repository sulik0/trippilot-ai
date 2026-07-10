# Step 05：记忆模块改造方案

## 结论

用户提出的四层记忆方案方向可行，但不建议在当前简历项目中一次性真实接入 Redis、PostgreSQL、Milvus 和 MQ。更合理的方案是：

1. 当前代码先保持可运行，不破坏已有 JSON 文件记忆实现。
2. 设计统一 `MemoryManager` / Store 接口，将当前 JSON 和 list 实现作为本地 adapter。
3. 文档中明确生产级目标架构：AgentScope Memory + Redis + PostgreSQL + Milvus + MQ。
4. 后续代码改造按接口优先、外部组件后置的方式推进。

这样面试时可以诚实说明：

> 当前项目实现了本地可运行版本，升级方案已经按生产记忆系统拆分为短期状态、结构化长期记忆、语义长期记忆和异步总结链路。外部中间件不会在 demo 中强依赖启动，但接口和数据模型已按可替换架构设计。

## 当前项目现状

当前记忆模块位于：

- `context/short_term_memory.py`
- `context/long_term_memory.py`
- `context/memory_manager.py`
- `.claude/skills/preference/script/agent.py`
- `.claude/skills/memory-query/script/agent.py`
- `agents/orchestration_agent.py`

当前实现：

- 短期记忆：`ShortTermMemory` 使用 Python list 保存最近 10 轮消息。
- 长期记忆：`LongTermMemory` 使用 `data/memory/{user_id}.json` 保存偏好、聊天记录、行程历史。
- 偏好写入：`PreferenceAgent` 提取偏好，`OrchestrationAgent._update_memory()` 根据 `append` 或默认 `replace` 写入。
- 长期总结：`MemoryManager.get_long_term_summary_async()` 在主流程内直接调用 LLM 生成摘要。
- 语义记忆：当前没有独立用户长期语义记忆，RAG Milvus 只用于企业差旅知识库。

主要不足：

- 短期记忆不能跨进程共享，服务重启后丢失。
- 长期记忆 JSON 文件不适合并发写入、审计、查询和权限治理。
- 偏好缺少版本、作用域、置信度、删除和冲突处理。
- LLM 总结在主服务内执行，容易影响请求延迟。
- 没有用户历史摘要向量召回，MemoryQueryAgent 主要依赖结构化历史和摘要文本。

## 目标架构

```text
User Request
    |
    v
CLI / API Service
    |
    v
IntentionAgent
    |
    v
OrchestrationAgent
    |
    +--> AgentScope Memory
    |       当前 Agent 运行时上下文：messages、tool results、retrieved evidence、planning state
    |
    +--> Redis Short-Term Store
    |       session 最近对话、槽位状态、任务状态、中间工具结果、TTL 会话恢复
    |
    +--> PostgreSQL Long-Term Structured Store
    |       preferences、trip_history、chat_messages、memory_summaries
    |
    +--> Milvus Long-Term Semantic Store
    |       session_summary、trip_summary、preference_summary、历史行程摘要向量
    |
    +--> MQ
            session.closed / trip.completed / context.threshold_exceeded
                    |
                    v
            MemorySummarizer Service
                    |
                    v
            MemoryPolicy
                    |
                    +--> PostgreSQL
                    +--> Milvus
```

## 第一层：短期记忆

### AgentScope Memory

定位：

- 管理当前 Agent 运行时上下文。
- 保留本次推理需要的消息、工具结果、检索证据、规划状态。
- 适合放在单个 Agent 执行周期内，不负责跨服务持久化。

建议保存内容：

- 当前用户输入。
- IntentionAgent 输出。
- EventCollectionAgent 槽位抽取结果。
- InformationQueryAgent 工具结果。
- RAGKnowledgeAgent 检索证据。
- ItineraryPlanningAgent 的规划草稿和最终结果。

### Redis Short-Term Store

定位：

- session 级短期状态。
- 支持多副本共享、TTL、会话恢复。
- 服务重启后仍能恢复最近状态。

建议 key 设计：

```text
trippilot:session:{session_id}:messages
trippilot:session:{session_id}:state
trippilot:session:{session_id}:slots
trippilot:session:{session_id}:missing_slots
trippilot:session:{session_id}:tool_results
```

建议 TTL：

- 默认 24 小时。
- 活跃会话每次写入刷新 TTL。
- 会话结束后可缩短 TTL 到 1 小时，等待异步总结完成。

建议数据结构：

```json
{
  "session_id": "session_001",
  "user_id": "user_001",
  "recent_messages": [],
  "task_state": "collecting_slots",
  "collected_slots": {
    "origin": "上海",
    "destination": "北京",
    "start_date": "2026-07-20"
  },
  "missing_slots": ["end_date"],
  "tool_results": {
    "weather": {},
    "rag": {}
  },
  "updated_at": "2026-07-10T12:00:00Z"
}
```

## 第二层：长期结构化记忆

### PostgreSQL 定位

PostgreSQL 负责可审计、可查询、可追溯的长期结构化数据：

- 用户偏好。
- 历史行程。
- 完整聊天记录。
- 摘要元数据。
- 偏好变更历史。

### 表结构设计

#### user_preferences

保存当前有效偏好，同时支持作用域、置信度和版本。

```sql
CREATE TABLE user_preferences (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    preference_type TEXT NOT NULL,
    preference_key TEXT NOT NULL,
    preference_value JSONB NOT NULL,
    scope TEXT NOT NULL DEFAULT 'long_term',
    status TEXT NOT NULL DEFAULT 'active',
    confidence NUMERIC(4,3) NOT NULL DEFAULT 1.0,
    source_session_id TEXT,
    source_message_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    expires_at TIMESTAMPTZ,
    version INT NOT NULL DEFAULT 1,
    UNIQUE (user_id, preference_type, preference_key, scope)
);
```

字段说明：

- `preference_type`：如 `hotel_brands`、`transportation_preference`、`home_location`。
- `preference_key`：具体实体或偏好键，如 `汉庭`、`如家`、`high_speed_rail`。
- `preference_value`：JSONB，支持布尔、字符串、数组和结构化权重。
- `scope`：`long_term` 或 `session_only`。
- `status`：`active`、`negative`、`deleted`、`ignored`。
- `confidence`：提取置信度。
- `expires_at`：session_only 或临时偏好的过期时间。

#### user_preference_events

保存偏好变更历史，支持追溯和审计。

```sql
CREATE TABLE user_preference_events (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    preference_id BIGINT,
    action TEXT NOT NULL,
    preference_type TEXT NOT NULL,
    preference_key TEXT,
    old_value JSONB,
    new_value JSONB,
    scope TEXT NOT NULL,
    confidence NUMERIC(4,3),
    reason TEXT,
    source_session_id TEXT,
    source_message_id BIGINT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### trip_history

保存历史行程和规划结果。

```sql
CREATE TABLE trip_history (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT,
    origin TEXT,
    destination TEXT,
    start_date DATE,
    end_date DATE,
    duration_days INT,
    trip_purpose TEXT,
    itinerary JSONB,
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### chat_messages

保存完整对话，支持审计和异步总结。

```sql
CREATE TABLE chat_messages (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    trace_id TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

#### memory_summaries

保存总结结果和元数据。

```sql
CREATE TABLE memory_summaries (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    session_id TEXT,
    summary_type TEXT NOT NULL,
    content TEXT NOT NULL,
    source_message_ids BIGINT[] DEFAULT '{}',
    source_trip_ids BIGINT[] DEFAULT '{}',
    confidence NUMERIC(4,3) NOT NULL DEFAULT 1.0,
    policy_status TEXT NOT NULL DEFAULT 'approved',
    metadata JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

建议索引：

```sql
CREATE INDEX idx_preferences_user_type ON user_preferences (user_id, preference_type, status);
CREATE INDEX idx_trip_user_date ON trip_history (user_id, start_date DESC);
CREATE INDEX idx_chat_user_session ON chat_messages (user_id, session_id, created_at);
CREATE INDEX idx_summary_user_type ON memory_summaries (user_id, summary_type, created_at DESC);
```

## 第三层：长期语义记忆

### Milvus 定位

Milvus 不保存全部原始聊天内容，只保存适合语义召回的摘要和记忆片段：

- `session_summary`
- `trip_summary`
- `preference_summary`
- 历史行程摘要
- 高频问题摘要

这样可以支持：

- “我之前是不是去过华东？”
- “我以前好像说过不喜欢哪家酒店？”
- “帮我参考以前的出差习惯规划一下。”

### Collection 设计

建议 collection：`user_memory_semantic`

字段：

```text
id: varchar / int64 primary key
user_id: varchar
memory_type: varchar
source_table: varchar
source_id: varchar
session_id: varchar
content: varchar
embedding: float_vector
confidence: float
created_at: int64
metadata: json
```

`memory_type` 枚举：

- `session_summary`
- `trip_summary`
- `preference_summary`
- `chat_summary`
- `memory_candidate`

### 写入流程

```text
MemorySummarizer 生成 summary
    |
    v
MemoryPolicy 过滤和判定
    |
    v
写入 PostgreSQL memory_summaries
    |
    v
EmbeddingModel 生成向量
    |
    v
写入 Milvus user_memory_semantic
```

写入要求：

- 先写 PostgreSQL，拿到 summary_id。
- 再写 Milvus，`source_table=memory_summaries`，`source_id=summary_id`。
- Milvus 写入失败不回滚 PostgreSQL，但记录重试任务。

### 检索流程

```text
MemoryQueryAgent 收到模糊历史问题
    |
    v
判断是否需要 semantic memory
    |
    v
生成 query embedding
    |
    v
Milvus filter: user_id + memory_type
    |
    v
top_k + score threshold
    |
    v
用 source_id 回查 PostgreSQL
    |
    v
把摘要和结构化偏好/行程一起交给 LLM
```

建议参数：

```text
top_k: 5
score_threshold: 0.68
memory_type: 按问题类型限制
user_id: 必须强制过滤
```

防止无关召回：

- 必须按 `user_id` 过滤，不能跨用户召回。
- 优先按 `memory_type` 过滤，例如偏好问题只查 `preference_summary`。
- 相似度低于阈值直接丢弃。
- 召回结果必须回查 PostgreSQL，确认 `policy_status=approved`。
- LLM 回答时必须引用“可用记忆”，不足则说明没有相关记录。

## 第四层：异步总结

### MQ 事件

主服务不直接执行 LLM 总结，只投递事件。

触发时机：

- 会话结束：`memory.session.closed`
- 行程生成完成：`memory.trip.completed`
- 上下文超过阈值：`memory.context.threshold_exceeded`
- 用户显式要求保存偏好：`memory.preference.detected`

事件结构：

```json
{
  "event_id": "evt_001",
  "event_type": "memory.session.closed",
  "user_id": "user_001",
  "session_id": "session_001",
  "trace_id": "run_001",
  "created_at": "2026-07-10T12:00:00Z",
  "payload": {
    "message_id_range": [1001, 1030],
    "trip_id": 88,
    "reason": "session_closed"
  }
}
```

### MemorySummarizer 服务

职责：

1. 消费 MQ 事件。
2. 从 PostgreSQL 读取 `chat_messages`、`trip_history`、已有偏好。
3. 调用 LLM 生成：
   - `session_summary`
   - `trip_summary`
   - `preference_summary`
   - `memory_candidates`
4. 调用 MemoryPolicy。
5. 写入 PostgreSQL。
6. 生成 embedding 并写入 Milvus。

### MemoryPolicy

MemoryPolicy 是记忆写入前的治理层。

建议规则：

- 敏感信息过滤：身份证、手机号、银行卡、精确住址等默认不进入语义记忆。
- 置信度判断：低置信度候选只保存为 `memory_candidate`，不直接成为偏好。
- 冲突检测：新偏好和已有 active 偏好冲突时，按 action 和 scope 判断。
- 作用域判断：区分 `long_term` 和 `session_only`。
- 写入幂等：同一 `event_id` 重复消费不会重复写入。

## PreferenceAgent 偏好更新机制

### 输出协议

建议 PreferenceAgent 输出从当前简化格式：

```json
{
  "preferences": [
    {"type": "hotel_brands", "value": "如家", "action": "append"}
  ],
  "has_preferences": true
}
```

升级为：

```json
{
  "has_preferences": true,
  "preferences": [
    {
      "preference_type": "hotel_brands",
      "preference_key": "如家",
      "value": {"name": "如家"},
      "action": "append",
      "scope": "long_term",
      "polarity": "positive",
      "confidence": 0.92,
      "reason": "用户说“我还喜欢如家”，表示在已有酒店偏好上追加"
    }
  ]
}
```

### action 定义

#### append

语义：在已有偏好基础上增加。

示例：

- “我还喜欢如家”
- “我也常坐东航”

写入：

- 若同 key 不存在，新增 active positive。
- 若已存在 deleted/negative，可改回 active。
- 记录 `user_preference_events.action=append`。

#### replace

语义：整体替换某类偏好。

示例：

- “我现在住上海”
- “以后酒店就优先全季”

写入：

- 同 `preference_type` 下旧 active 偏好置为 deleted 或 inactive。
- 新偏好写为 active。
- 适合常住地、预算等级、座位偏好这类单值偏好。

#### update

语义：修改某个已有偏好的属性，不一定替换整个类型。

示例：

- “以后优先高铁”
- “预算稍微提高一点”

写入：

- 定位对应 `preference_type/preference_key`。
- 更新权重、优先级或 value。
- 不删除同类型其它偏好。

#### delete

语义：长期删除或拉黑某个偏好。

示例：

- “以后别推荐如家”
- “以后不要住汉庭”

写入：

- 若表示长期排除，写入 `status=negative` 或 `deleted`。
- 对酒店这类推荐场景，建议保留 negative preference，而不是物理删除。
- 这样规划时可以显式避开。

#### ignore

语义：不应写入长期偏好。

示例：

- “这次别住汉庭”
- “今天不想坐飞机”
- “这趟预算低一点”

写入：

- `scope=session_only`，保存到 Redis session state。
- 不写入长期 `user_preferences` active 记录。
- 可以写入 `user_preference_events` 做审计，但不影响长期偏好。

### scope 定义

#### long_term

适用：

- “以后”
- “我一直”
- “我通常”
- “我喜欢”
- “我不喜欢”
- “以后别”

写入 PostgreSQL，并可进入摘要和 Milvus。

#### session_only

适用：

- “这次”
- “今天”
- “这趟”
- “本次出差”
- “临时”

写入 Redis session state，不进入长期偏好。

### 场景判定

| 用户表达 | action | scope | polarity | 写入位置 |
| --- | --- | --- | --- | --- |
| 我还喜欢如家 | append | long_term | positive | PostgreSQL |
| 以后优先高铁 | update | long_term | positive | PostgreSQL |
| 这次别住汉庭 | ignore | session_only | negative | Redis |
| 以后别推荐如家 | delete | long_term | negative | PostgreSQL |
| 我搬家到上海了 | replace | long_term | positive | PostgreSQL |
| 我现在不喜欢靠窗了 | delete | long_term | negative | PostgreSQL |

### 冲突处理

建议优先级：

1. 用户最新显式表达优先。
2. `session_only` 不覆盖 `long_term`，只在当前会话规划时生效。
3. negative preference 在推荐时优先于 positive preference。
4. `replace` 会关闭同类型旧 active 单值偏好。
5. `append` 不删除旧偏好。
6. 低置信度候选进入 `memory_candidates`，等待后续确认。

## 核心读写链路

### 请求进入链路

```text
User message
    |
    v
MemoryManager.add_message()
    |
    +--> AgentScope Memory / local runtime context
    +--> Redis recent_messages
    +--> PostgreSQL chat_messages
```

### Agent 编排读上下文

```text
OrchestrationAgent._prepare_context()
    |
    +--> Redis: recent dialogue, slots, task_state
    +--> PostgreSQL: active long_term preferences, recent trips
    +--> Milvus: relevant summaries when query is fuzzy/history-related
```

### 偏好写入链路

```text
PreferenceAgent
    |
    v
PreferenceUpdate[]
    |
    v
MemoryPolicy
    |
    +--> session_only -> Redis session preference_overrides
    +--> long_term -> PostgreSQL user_preferences + user_preference_events
```

### 行程完成链路

```text
ItineraryPlanningAgent completed
    |
    v
PostgreSQL trip_history
    |
    v
MQ memory.trip.completed
    |
    v
MemorySummarizer
    |
    +--> memory_summaries
    +--> Milvus user_memory_semantic
```

### 会话总结链路

```text
session ended / context too long
    |
    v
MQ event
    |
    v
MemorySummarizer
    |
    v
LLM summary + MemoryPolicy
    |
    +--> PostgreSQL memory_summaries
    +--> Milvus semantic memory
```

## 异常处理

### Redis 不可用

处理：

- 降级到本地 `ShortTermMemory`。
- 标记 trace：`short_term_store=local_fallback`。
- 不影响主流程，但会失去跨副本会话恢复。

### PostgreSQL 写入失败

处理：

- 主流程不能静默成功。
- 聊天消息写入失败可记录错误并继续，但偏好和行程写入失败应返回 partial warning。
- 可将写入任务放入本地 outbox，等待重试。

### Milvus 写入失败

处理：

- 不影响 PostgreSQL 主记录。
- 记录 `vector_sync_status=failed`。
- 后台重试补写向量。

### MQ 投递失败

处理：

- 使用 outbox pattern：先写 PostgreSQL `memory_events`，再由后台投递 MQ。
- 避免会话结束事件丢失。

### LLM 总结失败

处理：

- MemorySummarizer 标记事件失败并重试。
- 超过重试次数后进入 dead letter queue。
- 不影响用户主请求。

### 偏好冲突

处理：

- 新显式长期偏好覆盖旧长期偏好。
- session_only 只覆盖当前会话。
- 低置信度不覆盖高置信度，除非用户表达明确。
- 所有冲突写入 `user_preference_events`。

## 分阶段落地建议

### Phase 1：接口抽象

代码目标：

- 新增 `context/stores.py`
- 定义 `ShortTermStore`、`LongTermStore`、`SemanticMemoryStore`、`SummaryQueue`
- 当前 JSON/list 实现作为 adapter
- 保持测试全部通过

简历表述：

> 抽象记忆读写接口，将本地 JSON 和内存实现封装为可替换 adapter，预留 Redis/PostgreSQL/Milvus/MQ 扩展点。

### Phase 2：PreferenceUpdate 协议

代码目标：

- 定义 `PreferenceUpdate` 数据结构。
- 支持 `append / replace / update / delete / ignore`。
- 支持 `long_term / session_only`。
- 更新 PreferenceAgent prompt 和 contract tests。

简历表述：

> 设计偏好变更协议，支持长期偏好、会话级偏好、负向偏好、冲突检测和审计事件。

### Phase 3：PostgreSQL Adapter

代码目标：

- 增加 schema SQL。
- 实现 `PostgresLongTermStore`。
- JSON 实现继续作为本地 fallback。

简历表述：

> 将长期记忆从文件存储演进为 PostgreSQL 结构化存储，支持偏好追溯、历史行程查询和聊天审计。

### Phase 4：Redis Adapter

代码目标：

- 实现 `RedisShortTermStore`。
- 支持 TTL、最近 10 轮对话、槽位和中间结果。
- Redis 不可用时 fallback 到本地内存。

简历表述：

> 使用 Redis 管理 session 级短期记忆，实现多副本共享、会话恢复和 TTL 自动过期。

### Phase 5：Semantic Memory + MQ

代码目标：

- 增加 `MemorySummarizer` 服务骨架。
- 增加 MQ event schema。
- 增加 Milvus collection schema 和 adapter。
- 不阻塞主请求。

简历表述：

> 将 LLM 总结从主链路拆到异步服务，摘要通过 PostgreSQL 存元数据、Milvus 存向量，实现用户长期语义记忆召回。

## 简历写法

可以写：

> 设计并改造差旅 Agent 记忆系统，按短期会话记忆、长期结构化记忆、长期语义记忆、异步总结四层拆分；抽象 Memory Store 接口，规划 Redis 管理 session 状态、PostgreSQL 持久化偏好/行程/聊天审计、Milvus 存储用户历史摘要向量，MQ 解耦 LLM 总结链路；设计 PreferenceUpdate 协议，支持 append / replace / update / delete / ignore 以及 long_term / session_only 作用域。

更保守写法：

> 对多 Agent 差旅助手的记忆模块做架构升级设计，抽象短期/长期/语义记忆边界，补充 PostgreSQL 表结构、Milvus collection、MQ 异步总结链路和偏好冲突处理策略，为后续 Redis/PostgreSQL/Milvus 接入预留 adapter。

## 面试讲解版本

可以按这个顺序讲：

1. 原项目只有本地 list 和 JSON，能跑 demo，但不适合多副本、审计和长期召回。
2. 我把记忆拆成四层：AgentScope Memory 管运行时上下文，Redis 管 session 状态，PostgreSQL 管结构化长期记忆，Milvus 管语义长期召回。
3. 主请求链路只做必要写入，不在主链路做 LLM 总结。
4. 会话结束、行程完成或上下文过长时投递 MQ，MemorySummarizer 异步生成摘要。
5. 摘要先经过 MemoryPolicy，过滤敏感信息、判断置信度、处理冲突，再写入 PostgreSQL 和 Milvus。
6. PreferenceAgent 不再只返回 append/replace，而是返回 PreferenceUpdate，支持长期偏好、会话临时偏好和负向偏好。

可追问回答：

- 为什么 Redis 和 AgentScope Memory 都需要？
  - AgentScope Memory 更偏 Agent 运行时上下文；Redis 是跨请求、跨副本、带 TTL 的 session 状态。

- 为什么 PostgreSQL 和 Milvus 都需要？
  - PostgreSQL 保存可审计的结构化事实；Milvus 用于模糊语义召回。二者职责不同。

- 为什么总结要异步？
  - LLM 总结耗时且可能失败，不应该阻塞用户请求。异步链路可以重试、限流和进入 dead letter queue。

- “这次别住汉庭”和“以后别推荐如家”怎么区分？
  - 前者是 `ignore + session_only`，只写 Redis 当前会话；后者是 `delete + long_term + negative`，写入长期偏好，未来规划持续生效。

## 不在本 Step 直接实现的内容

本 Step 仅确定完整方案和文档，不修改运行时代码。原因：

- 当前项目目标是简历增强，不需要一次性引入多个外部中间件。
- 直接接 Redis/PG/Milvus/MQ 会增加部署复杂度，影响当前可运行性。
- 更合理的下一步是先做接口抽象和本地 adapter，再逐步替换真实后端。
