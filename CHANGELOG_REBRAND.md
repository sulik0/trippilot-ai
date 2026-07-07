# TripPilot AI 项目整理与改动说明

## 改动目标

将项目整理为可公开展示的个人简历项目，统一命名为 **TripPilot AI 智能差旅助手**，并完成运行环境、模型配置、GitHub 提交前清理和基础验证。

## 主要改动

### 1. 项目命名与品牌清理

- 将公开项目名统一为 `TripPilot AI`。
- CLI 横幅改为 `TripPilot AI 商旅助手`。
- AgentScope 项目标识改为 `TripPilot-AI-Travel-Assistant`。
- README、Skill 文档、知识库文档中的旧品牌与旧供应商表述已替换为通用的企业差旅场景表述。

### 2. SiliconFlow 模型接入

- 默认 LLM 接口改为 SiliconFlow OpenAI 兼容地址：
  - `https://api.siliconflow.cn/v1`
- 默认模型改为：
  - `Pro/deepseek-ai/DeepSeek-R1`
- 配置改为从 `.env` 读取，避免把 API Key 写入代码。
- 新增 `scripts/check_siliconflow.py`，用于先验证 SiliconFlow 直连，再启动完整多智能体系统。

### 3. 环境变量规范

新增 `.env.example`：

```env
TRIPPILOT_LLM_API_KEY=your_siliconflow_api_key
TRIPPILOT_LLM_MODEL=Pro/deepseek-ai/DeepSeek-R1
TRIPPILOT_LLM_BASE_URL=https://api.siliconflow.cn/v1
TRIPPILOT_LLM_TEMPERATURE=0.7
TRIPPILOT_LLM_MAX_TOKENS=8192
```

### 4. 运行稳定性修复

- 使用 Python 3.13 虚拟环境 `.venv313` 验证运行。
- 补齐缺失依赖：`httpx`、`PyYAML`、`pytest`。
- 修复 AgentScope 1.0.16 下 `temperature/max_tokens` 参数位置导致的启动 warning。
- 修复 CLI 缺少模型配置时的报错体验，改为清晰提示。
- 修复记忆查询中偏好字段新旧格式不一致的问题。

### 5. GitHub 提交前清理

`.gitignore` 已排除以下本地或敏感文件：

- `.env`
- `.venv/`、`.venv313/`
- `.pytest_cache/`、`__pycache__/`
- `.idea/`
- `data/memory/`
- `tests/results/`
- `*.db`、`*.db-shm`、`*.db-wal`

说明：Milvus Lite 的二进制向量库不提交，公开仓库保留文本知识库与初始化脚本，避免旧向量元数据残留。

## 验证结果

已通过：

```bash
.venv313/bin/python -m compileall -q agents context utils cli.py config.py config_agentscope.py scripts tests/test_smoke.py
.venv313/bin/python -m pytest -q
```

测试结果：

```text
2 passed
```

## 运行方式

```bash
cp .env.example .env
# 填写 TRIPPILOT_LLM_API_KEY

.venv313/bin/python scripts/check_siliconflow.py
.venv313/bin/python cli.py health
.venv313/bin/python cli.py
```

## 简历描述建议

项目名称：TripPilot AI 智能差旅助手

项目描述：

基于 AgentScope 与 OpenAI 兼容大模型接口构建的多智能体差旅规划系统，采用 Plan-and-Execute 架构，将意图识别、事项收集、偏好管理、RAG 知识库问答、联网信息查询与行程生成拆分为可懒加载的 Skill 插件。系统支持同优先级 Agent 并行调度、本地长期记忆、SiliconFlow 模型接入、Milvus Lite 向量检索和 LLM 调用熔断重试机制。
