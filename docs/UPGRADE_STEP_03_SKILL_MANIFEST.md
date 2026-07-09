# Step 03：Skill Manifest 与能力注册

## 背景

项目原本已经把子 Agent 放在 `.claude/skills/` 目录下，每个技能有 `SKILL.md` 和 `script/agent.py`。这个结构能运行，但工程表达还不够清晰：

- 运行时主要靠目录扫描判断技能是否存在。
- 技能的输入、输出、依赖、权限和超时没有机器可读契约。
- 面试时只能说“有 skills 目录”，很难进一步讲能力治理。

本次升级目标是保留原有执行方式，同时为每个 Skill 增加 `skill.yaml` manifest，让系统具备明确的能力注册元数据。

## 本次新增内容

### 1. 新增 Skill Manifest

为 6 个技能补充 `skill.yaml`：

- `.claude/skills/ask-question/skill.yaml`
- `.claude/skills/event-collection/skill.yaml`
- `.claude/skills/memory-query/skill.yaml`
- `.claude/skills/plan-trip/skill.yaml`
- `.claude/skills/preference/skill.yaml`
- `.claude/skills/query-info/skill.yaml`

每个 manifest 包含：

- `name`：技能目录级名称。
- `display_name`：展示名称。
- `description`：能力描述。
- `agent_name`：编排器内部使用的 Agent 名称。
- `entrypoint`：Agent 加载入口。
- `timeout_seconds`：建议超时。
- `requires`：运行依赖，例如 `llm`、`memory_manager`、`rag_index`。
- `permissions`：能力权限，例如读写长期记忆、调用搜索服务。
- `triggers`：触发场景。
- `input_schema` / `output_schema`：输入输出结构说明。
- `sop`：执行步骤。

### 2. 新增 Manifest Loader

新增 `utils/skill_manifest.py`：

- `SkillManifest`：结构化 manifest 数据类。
- `SkillManifestLoader`：扫描 `.claude/skills/*/skill.yaml` 并加载 manifest。
- `SkillManifestError`：manifest 缺失字段、字段类型错误或入口不存在时抛出。

校验规则：

- 必须包含核心字段。
- `timeout_seconds` 必须是正整数。
- `requires`、`permissions`、`triggers`、`sop` 必须是列表。
- `input_schema` 和 `output_schema` 必须是对象。
- `entrypoint` 必须真实存在。

### 3. Registry 接入 Manifest

升级 `agents/lazy_agent_registry.py`：

- 启动时优先扫描 `skill.yaml`。
- manifest 存在时使用 manifest 的 `entrypoint` 加载 Agent。
- manifest 不存在时仍回退到原来的 `script/agent.py` 目录扫描。
- 新增 `get_skill_manifest(agent_name)`，可以按 Agent 名称查看能力元数据。
- 新增 `get_skill_manifests()`，可以导出所有技能元数据。

这样既不破坏原有运行方式，又让系统有了明确的能力注册层。

### 4. SkillLoader 接入 Manifest

升级 `utils/skill_loader.py`：

- 生成意图识别 prompt 时，优先使用 `skill.yaml` 中的能力描述。
- 没有 manifest 的技能继续回退读取 `SKILL.md` frontmatter。

这能减少“文档描述”和“运行时能力注册”之间的漂移。

### 5. 测试覆盖

更新 `tests/test_smoke.py`：

- 验证 6 个 skill manifest 都能被加载。
- 验证关键字段，例如 `requires`、`timeout_seconds`、`entrypoint_path`。
- 验证 `LazyAgentRegistry` 能通过 `get_skill_manifest()` 暴露能力元数据。
- 保留原来的事件抽取 Agent 加载和执行测试。

## 面试讲法

可以这样描述：

> 我把项目里的子 Agent 抽象成 Skill Plugin，每个 Skill 除了有执行代码和自然语言说明外，还有机器可读的 manifest。manifest 声明技能名称、入口、依赖、权限、超时、输入输出结构和 SOP。编排器注册 Agent 时优先读取 manifest，因此后续可以继续演进到权限控制、动态路由、超时治理和自动化评测。

这个点比“我有多个 Agent”更有工程价值，因为它回答了一个常见追问：

> 多 Agent 系统里，能力是怎么治理和注册的？

## 当前边界

本次没有做真正的权限拦截和超时中断，只是把权限和超时变成了 manifest 元数据。原因是当前目标是简历项目增强，不是完整生产系统。

后续如果继续升级，可以把这些字段用于：

- OrchestrationAgent 执行前的权限检查。
- Agent 执行超时控制。
- 根据 `input_schema` / `output_schema` 做 contract test。
- 自动生成能力文档或 API schema。

## 验证命令

```bash
.venv313/bin/python -m compileall -q agents context utils cli.py config.py config_agentscope.py scripts tests/test_smoke.py
.venv313/bin/python -m pytest -q
```

预期结果：

- Python 编译检查通过。
- smoke tests 全部通过。
