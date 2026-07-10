"""
协调器智能体 OrchestrationAgent
职责：根据意图识别结果，协调调度多个子智能体完成任务

核心功能：
1. 接收 IntentionAgent 的调度决策
2. 按照优先级顺序执行子智能体
3. 管理智能体之间的消息传递
4. 聚合多个智能体的结果
5. 与两层记忆系统集成

执行模式：
- Sequential (顺序执行): 按优先级依次执行，前一个的输出作为后一个的输入
- Parallel (并行执行): 同优先级智能体使用 asyncio.gather 并行执行
"""
from agentscope.agent import AgentBase
from agentscope.message import Msg
from typing import Optional, Union, List, Dict, Any
import json
import logging
import asyncio

from context.preference_update import apply_preference_update, normalize_preference_updates
from agents.protocol import (
    AgentError,
    AgentExecutionResult,
    AgentMessageEnvelope,
    AgentTask,
    PROTOCOL_VERSION,
    new_run_id,
    normalize_agent_output,
)
from utils.run_trace import RunTrace

logger = logging.getLogger(__name__)


class OrchestrationAgent(AgentBase):
    """协调器智能体 - 调度和协调多个子智能体"""

    def __init__(
        self,
        name: str = "OrchestrationAgent",
        agent_registry: Dict[str, AgentBase] = None,
        memory_manager = None,
        **kwargs
    ):
        """
        初始化协调器

        Args:
            name: 智能体名称
            agent_registry: 子智能体注册表 {agent_name: agent_instance}
            memory_manager: 记忆管理器
        """
        super().__init__()
        self.name = name
        self.agent_registry = agent_registry or {}
        self.memory_manager = memory_manager

    def register_agent(self, agent_name: str, agent: AgentBase):
        """注册子智能体"""
        self.agent_registry[agent_name] = agent
        logger.info(f"Registered agent: {agent_name}")

    def unregister_agent(self, agent_name: str):
        """注销子智能体"""
        if agent_name in self.agent_registry:
            del self.agent_registry[agent_name]
            logger.info(f"Unregistered agent: {agent_name}")

    async def reply(self, x: Optional[Union[Msg, List[Msg]]] = None) -> Msg:
        """
        协调执行流程

        Args:
            x: 输入消息，应包含 IntentionAgent 的输出

        Returns:
            Msg: 执行结果
        """
        if x is None:
            return Msg(
                name=self.name,
                content=json.dumps({"error": "No input provided"}),
                role="assistant"
            )

        # 解析输入
        if isinstance(x, list):
            intention_output = x[-1].content if x else "{}"
        else:
            intention_output = x.content

        # 解析意图识别结果
        try:
            intention_data = json.loads(intention_output) if isinstance(intention_output, str) else intention_output
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse intention output: {e}")
            return Msg(
                name=self.name,
                content=json.dumps({"error": "Invalid intention format"}),
                role="assistant"
            )

        run_id = intention_data.get("run_id") or new_run_id()
        trace = RunTrace(run_id)

        # 获取并验证智能体调度计划
        raw_schedule = intention_data.get("agent_schedule", [])
        if not raw_schedule:
            return Msg(
                name=self.name,
                content=json.dumps({
                    "status": "no_agents",
                    "run_id": run_id,
                    "protocol_version": PROTOCOL_VERSION,
                    "message": "没有需要调度的智能体"
                }),
                role="assistant"
            )

        try:
            agent_schedule = [AgentTask.from_schedule_item(item) for item in raw_schedule]
        except (TypeError, ValueError) as e:
            logger.error(f"Invalid agent schedule: {e}")
            error = AgentError(
                code="INVALID_AGENT_SCHEDULE",
                message=str(e),
                retryable=False,
                user_message="调度计划格式有误，请重新描述需求。",
            )
            return Msg(
                name=self.name,
                content=json.dumps({
                    "status": "error",
                    "run_id": run_id,
                    "protocol_version": PROTOCOL_VERSION,
                    "error": error.to_dict(),
                }, ensure_ascii=False),
                role="assistant"
            )

        # 按优先级排序
        sorted_schedule = sorted(agent_schedule, key=lambda x: x.priority)

        logger.info(f"Orchestrating {len(sorted_schedule)} agents")

        # 准备上下文信息
        context = self._prepare_context(intention_data, run_id)

        # 并行执行智能体（按优先级分组）
        results = []
        current_priority = None
        parallel_tasks = []

        for task in sorted_schedule:
            priority = task.priority

            # 如果优先级变化，先执行当前批次
            if current_priority is not None and priority != current_priority:
                # 并行执行当前优先级的所有任务
                if parallel_tasks:
                    batch_results = await self._execute_parallel_agents(parallel_tasks, context, results, run_id, trace)
                    results.extend(batch_results)
                    parallel_tasks = []

            current_priority = priority
            parallel_tasks.append(task)

        # 执行最后一批
        if parallel_tasks:
            batch_results = await self._execute_parallel_agents(parallel_tasks, context, results, run_id, trace)
            results.extend(batch_results)

        trace.finish()

        # 聚合结果
        final_result = self._aggregate_results(results, intention_data, run_id, trace)

        # 更新记忆
        if self.memory_manager:
            self._update_memory(intention_data, results)

        return Msg(
            name=self.name,
            content=json.dumps(final_result, ensure_ascii=False),
            role="assistant"
        )

    def _prepare_context(self, intention_data: Dict[str, Any], run_id: str) -> Dict[str, Any]:
        """
        准备上下文信息，供子智能体使用

        Args:
            intention_data: 意图识别结果

        Returns:
            上下文字典
        """
        context = {
            "protocol_version": PROTOCOL_VERSION,
            "run_id": run_id,
            "reasoning": intention_data.get("reasoning", ""),
            "intents": intention_data.get("intents", []),
            "key_entities": intention_data.get("key_entities", {}),
            "rewritten_query": intention_data.get("rewritten_query", "")
        }

        # 从记忆系统获取上下文
        if self.memory_manager:
            # 短期记忆：最近对话
            recent_context = self.memory_manager.short_term.get_recent_context(3)
            context["recent_dialogue"] = recent_context

            # 长期记忆：用户偏好
            preferences = self.memory_manager.long_term.get_preference()
            context["user_preferences"] = preferences

        return context

    async def _execute_parallel_agents(
        self,
        tasks: List[AgentTask],
        context: Dict[str, Any],
        previous_results: List[Dict],
        run_id: str,
        trace: RunTrace
    ) -> List[Dict]:
        """
        并行执行多个智能体

        Args:
            tasks: 任务列表，每个任务包含 agent_name, priority, reason, expected_output
            context: 上下文信息
            previous_results: 前序智能体的结果

        Returns:
            执行结果列表
        """
        if not tasks:
            return []

        batch_id = f"batch_p{tasks[0].priority}_{len(trace.batch_events) + 1}"
        trace.start_batch(
            batch_id=batch_id,
            priority=tasks[0].priority,
            agent_names=[task.agent_name for task in tasks],
            parallel=len(tasks) > 1,
        )

        # 如果只有一个任务，直接执行
        if len(tasks) == 1:
            task = tasks[0]
            result = await self._execute_agent(
                task=task,
                context=context,
                previous_results=previous_results,
                run_id=run_id,
                trace=trace,
            )
            trace.finish_batch(batch_id)
            return [{
                "agent_name": task.agent_name,
                "priority": task.priority,
                "task_id": task.task_id,
                "result": result
            }]

        # 多个任务并行执行
        logger.info(f"Executing {len(tasks)} agents in parallel")

        # 创建并行任务
        parallel_coroutines = []
        for task in tasks:
            agent_name = task.agent_name
            priority = task.priority

            logger.info(f"Parallel executing agent: {agent_name} (priority={priority})")

            # 创建协程
            coroutine = self._execute_agent(
                task=task,
                context=context,
                previous_results=previous_results,
                run_id=run_id,
                trace=trace,
            )
            parallel_coroutines.append((task, coroutine))

        # 使用 asyncio.gather 并行执行
        execution_results = await asyncio.gather(
            *[coro for _, coro in parallel_coroutines],
            return_exceptions=True
        )

        # 整理结果
        results = []
        for (task, _), exec_result in zip(parallel_coroutines, execution_results):
            agent_name = task.agent_name
            priority = task.priority
            if isinstance(exec_result, Exception):
                logger.error(f"Parallel agent execution failed: {agent_name}, error: {exec_result}")
                error = AgentError(
                    code="PARALLEL_AGENT_EXECUTION_FAILED",
                    message=str(exec_result),
                    retryable=False,
                    user_message="并行任务执行失败，请稍后重试。",
                )
                result = {
                    "status": "error",
                    "agent_name": agent_name,
                    "data": {"error": str(exec_result)},
                    "message": f"并行执行失败: {str(exec_result)}",
                    "error": error.to_dict(),
                }
            else:
                result = exec_result

            results.append({
                "agent_name": agent_name,
                "priority": priority,
                "task_id": task.task_id,
                "result": result
            })

        trace.finish_batch(batch_id)
        return results

    async def _execute_agent(
        self,
        task: AgentTask,
        context: Dict[str, Any],
        previous_results: List[Dict],
        run_id: str,
        trace: RunTrace
    ) -> Dict[str, Any]:
        """
        执行单个智能体

        Args:
            task: 智能体调度任务
            context: 上下文信息
            previous_results: 前序智能体的结果
            run_id: 当前端到端请求ID

        Returns:
            执行结果
        """
        agent_name = task.agent_name
        trace.start_agent(task.task_id, agent_name, task.priority)

        # 检查智能体是否注册
        if agent_name not in self.agent_registry:
            logger.warning(f"Agent not registered: {agent_name}")
            error = AgentError(
                code="AGENT_NOT_REGISTERED",
                message=f"Agent not registered: {agent_name}",
                retryable=False,
                user_message=f"智能体未注册: {agent_name}",
            )
            trace.finish_agent(task.task_id, "error", error.code)
            return {
                "status": "error",
                "agent_name": agent_name,
                "data": {},
                "error": error.to_dict(),
                "message": f"智能体未注册: {agent_name}"
            }

        agent = self.agent_registry[agent_name]

        envelope = AgentMessageEnvelope(
            run_id=run_id,
            task=task,
            context=context,
            previous_results=previous_results,
        )

        # 构建输入消息
        input_msg = Msg(
            name="Orchestrator",
            content=json.dumps(envelope.to_payload(), ensure_ascii=False),
            role="user"
        )

        try:
            # 调用智能体
            response = await agent.reply(input_msg)

            # 解析响应
            if isinstance(response.content, str):
                try:
                    result = json.loads(response.content)
                except json.JSONDecodeError:
                    result = {"output": response.content}
            else:
                result = response.content

            normalized = normalize_agent_output(agent_name, result)
            trace.finish_agent(
                task_id=task.task_id,
                status=normalized.get("status", "unknown"),
                error_code=(normalized.get("error") or {}).get("code"),
            )
            return normalized

        except Exception as e:
            logger.error(f"Agent execution failed: {agent_name}, error: {e}")
            error = AgentError(
                code="AGENT_EXECUTION_FAILED",
                message=str(e),
                retryable=False,
                user_message="智能体执行失败，请稍后重试。",
            )
            trace.finish_agent(task.task_id, "error", error.code)
            # 返回友好的错误信息，但不中断流程
            return {
                "status": "error",
                "agent_name": agent_name,
                "data": {"error": str(e)},
                "message": f"智能体执行失败: {str(e)}",
                "error": error.to_dict(),
            }

    def _aggregate_results(
        self,
        results: List[Dict],
        intention_data: Dict[str, Any],
        run_id: str,
        trace: RunTrace
    ) -> Dict[str, Any]:
        """
        聚合多个智能体的结果

        Args:
            results: 所有智能体的执行结果
            intention_data: 原始意图识别结果

        Returns:
            聚合后的最终结果
        """
        aggregated = {
            "status": "completed",
            "protocol_version": PROTOCOL_VERSION,
            "run_id": run_id,
            "intention": {
                "intents": intention_data.get("intents", []),
                "key_entities": intention_data.get("key_entities", {})
            },
            "agents_executed": len(results),
            "results": [],
            "trace": trace.to_dict(),
        }

        # 收集每个智能体的结果
        for result in results:
            execution_result = AgentExecutionResult(
                agent_name=result["agent_name"],
                priority=result["priority"],
                task_id=result.get("task_id", ""),
                status=result["result"].get("status", "unknown"),
                data=result["result"].get("data", {}),
                error=AgentError(**result["result"]["error"]) if result["result"].get("error") else None,
            )
            aggregated["results"].append(execution_result.to_dict())

        # 检查是否有错误
        errors = [r for r in results if r["result"].get("status") == "error"]
        if errors:
            aggregated["status"] = "partial_failure"
            aggregated["errors"] = len(errors)

        return aggregated

    def _update_memory(self, intention_data: Dict[str, Any], results: List[Dict]):
        """
        更新记忆系统

        Args:
            intention_data: 意图识别结果
            results: 智能体执行结果
        """
        if not self.memory_manager:
            return

        # 提取并保存信息到长期记忆
        for result in results:
            agent_name = result["agent_name"]
            data = result["result"].get("data", {})

            # 如果是偏好智能体，保存偏好信息到长期记忆
            if agent_name == "preference" and isinstance(data, dict):
                self._apply_preference_updates(data.get("preferences", {}))

            # 如果是行程规划智能体，保存行程到长期记忆
            if agent_name == "itinerary_planning" and isinstance(data, dict):
                itinerary = data.get("itinerary", {})

                # 只要有行程信息就保存（不管是否完全规划好）
                if itinerary:
                    # 提取事项收集的信息（出发地、目的地等）
                    event_data = {}
                    for r in results:
                        if r["agent_name"] == "event_collection":
                            event_data = r["result"].get("data", {})
                            break

                    # 从 event_data 获取行程信息
                    origin = event_data.get("origin")
                    destination = event_data.get("destination")
                    start_date = event_data.get("start_date")
                    end_date = event_data.get("end_date")
                    purpose = event_data.get("trip_purpose", "旅游")

                    # 保存到长期记忆（只要有目的地就保存）
                    if destination:
                        self.memory_manager.long_term.save_trip_history({
                            "origin": origin,
                            "destination": destination,
                            "start_date": start_date,
                            "end_date": end_date,
                            "purpose": purpose
                        })
                        logger.info(f"Saved trip to long-term memory: {origin} -> {destination}")

        logger.info("Memory updated after orchestration")

    def _apply_preference_updates(self, preferences_data: Any):
        """Apply PreferenceUpdate protocol while keeping legacy outputs valid."""
        updates = normalize_preference_updates(preferences_data)
        if not updates:
            return

        current_prefs = self.memory_manager.long_term.get_preference()
        for update in updates:
            if update.scope == "session_only" or update.action == "ignore":
                overrides = self.memory_manager.short_term.get_state("preference_overrides", [])
                overrides.append(update.to_dict())
                self.memory_manager.short_term.set_state("preference_overrides", overrides)
                logger.info("Skipped long-term preference write: %s", update.to_dict())
                continue

            new_value = apply_preference_update(current_prefs, update)
            if update.action == "delete":
                excluded_type = f"excluded_{update.preference_type}"
                current_excluded = current_prefs.get(excluded_type)
                if isinstance(current_excluded, list):
                    excluded_value = list(current_excluded)
                elif current_excluded:
                    excluded_value = [current_excluded]
                else:
                    excluded_value = []
                if update.preference_key not in excluded_value:
                    excluded_value.append(update.preference_key)
                self.memory_manager.long_term.save_preference(excluded_type, excluded_value)
                current_prefs[excluded_type] = excluded_value

            if update.action == "delete" or new_value not in (None, [], {}):
                self.memory_manager.long_term.save_preference(update.preference_type, new_value)
                current_prefs[update.preference_type] = new_value
            logger.info(
                "Applied preference update: type=%s action=%s scope=%s value=%s",
                update.preference_type,
                update.action,
                update.scope,
                new_value,
            )
