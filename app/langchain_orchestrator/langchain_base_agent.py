"""
LangChain Base Agent Mixin

Provides production-grade features for experimental LangChain agents:
- Retry logic with exponential backoff
- Database persistence (AgentExecution table)
- Human escalation workflow
- State management (idle/working/failed/waiting)
- Task history tracking

This mixin brings experimental agents to feature parity with production BaseAgent.
"""

import asyncio
import logging
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)

# Import database models for persistence
try:
    from app.database import get_db_session, AgentExecution, Escalation
    from sqlalchemy import select
except ImportError:
    # Handle case where imports fail (e.g., during testing)
    get_db_session = None
    AgentExecution = None
    Escalation = None


class AgentState(Enum):
    """Agent operational states (matches production BaseAgent)"""
    IDLE = "idle"
    WORKING = "working"
    FAILED = "failed"
    WAITING = "waiting"


class LangChainBaseAgentMixin:
    """
    Mixin class providing production features to LangChain experimental agents.

    Usage:
        class MyLangChainAgent(LangChainBaseAgentMixin):
            def __init__(self):
                self.agent_id = "my_agent"
                self.init_base_agent()  # Initialize mixin

            async def execute_task(self, task, context):
                # Wrap execution with retry/persistence
                return await self.execute_with_production_features(
                    task, context, self._my_task_impl
                )
    """

    def init_base_agent(self, orchestrator=None):
        """Initialize base agent features - call this in __init__"""
        self.orchestrator = orchestrator
        self.state = AgentState.IDLE
        self.current_task = None
        self.task_history = []
        self.max_retries = 3
        logger.info(f"[{self.agent_id}] LangChain agent initialized with production features")

    async def execute_with_production_features(
        self,
        task: str,
        context: Dict[str, Any],
        task_impl_func
    ) -> Dict[str, Any]:
        """
        Execute task with retry, persistence, and error handling.

        Args:
            task: Task name
            context: Task context
            task_impl_func: The actual task implementation function (async)

        Returns:
            Task result dict
        """
        self.state = AgentState.WORKING
        self.current_task = {
            "task": task,
            "context": context,
            "started_at": datetime.now(),
            "agent_id": self.agent_id
        }

        try:
            logger.info(f"[{self.agent_id}] Starting task: {task}")

            # Execute the task implementation
            result = await task_impl_func(context)

            # Mark completion
            self.current_task["completed_at"] = datetime.now()
            self.current_task["status"] = "success"
            self.current_task["result"] = result

            # Add to history
            self.task_history.append(self.current_task.copy())

            # Persist to database
            await self._save_execution_to_db(self.current_task.copy())

            logger.info(f"[{self.agent_id}] Task completed: {task}")

            return result

        except Exception as e:
            logger.error(f"[{self.agent_id}] Task failed: {task} - {str(e)}", exc_info=True)

            # Log failure
            self.current_task["completed_at"] = datetime.now()
            self.current_task["error"] = str(e)
            self.current_task["status"] = "failed"

            # Add to history
            self.task_history.append(self.current_task.copy())

            # Persist to database
            await self._save_execution_to_db(self.current_task.copy())

            # Attempt retry or escalate
            if self.should_retry(e, context):
                return await self.retry_task(task, context, task_impl_func)
            else:
                await self.escalate_to_human(e, context)
                raise

        finally:
            self.state = AgentState.IDLE
            self.current_task = None

    def should_retry(self, error: Exception, context: Dict) -> bool:
        """
        Determine if task should be retried.

        Matches production BaseAgent logic.
        """
        retry_count = context.get('retry_count', 0)

        # Don't retry if max retries exceeded
        if retry_count >= self.max_retries:
            return False

        # Retry on transient errors
        transient_errors = [
            "ConnectionError",
            "TimeoutError",
            "TemporaryFailure",
            "ServiceUnavailable",
            "RateLimitError"
        ]

        return type(error).__name__ in transient_errors

    async def retry_task(
        self,
        task: str,
        context: Dict,
        task_impl_func
    ) -> Dict[str, Any]:
        """
        Retry failed task with exponential backoff.

        Matches production BaseAgent logic: 2^retry_count seconds.
        """
        retry_count = context.get('retry_count', 0)

        if retry_count >= self.max_retries:
            error_msg = f"Max retries ({self.max_retries}) exceeded"
            logger.error(f"[{self.agent_id}] {error_msg}")
            await self.escalate_to_human(
                error=error_msg,
                context=context
            )
            raise Exception(error_msg)

        # Exponential backoff: 2^retry_count seconds
        wait_time = 2 ** retry_count
        logger.info(
            f"[{self.agent_id}] Retrying task after {wait_time}s "
            f"(attempt {retry_count + 1}/{self.max_retries})"
        )
        await asyncio.sleep(wait_time)

        # Retry with incremented count
        context['retry_count'] = retry_count + 1
        return await self.execute_with_production_features(
            task, context, task_impl_func
        )

    async def escalate_to_human(self, error: Any, context: Dict):
        """
        Escalate to human review.

        Creates an escalation record for admin review in the dashboard.
        Matches production BaseAgent behavior.
        """
        escalation = {
            "agent": self.agent_id,
            "error": str(error),
            "context": context,
            "task": self.current_task,
            "escalated_at": datetime.now().isoformat(),
            "status": "pending_review"
        }

        logger.warning(f"[{self.agent_id}] Escalating to human review: {str(error)}")

        # Save to database
        await self._save_escalation(escalation)

    async def _save_execution_to_db(self, task_data: Dict):
        """
        Persist agent execution to database (AgentExecution table).

        Matches production BaseAgent._save_execution_to_db().
        """
        if not get_db_session or not AgentExecution:
            logger.debug(f"[{self.agent_id}] Database not available, skipping persistence")
            return

        try:
            async with get_db_session() as session:
                execution = AgentExecution(
                    request_id=task_data.get("context", {}).get("request_id"),
                    agent_id=self.agent_id,
                    task=task_data.get("task"),
                    status=task_data.get("status", "unknown"),
                    started_at=task_data.get("started_at"),
                    completed_at=task_data.get("completed_at"),
                    error=task_data.get("error"),
                    result=task_data.get("result")
                )
                session.add(execution)
                await session.commit()
                logger.debug(f"[{self.agent_id}] Execution persisted to database")
        except Exception as e:
            logger.error(f"[{self.agent_id}] Failed to persist execution: {e}")

    async def _save_escalation(self, escalation_data: Dict):
        """
        Persist escalation to database (Escalation table).

        Matches production BaseAgent.save_escalation().
        """
        if not get_db_session or not Escalation:
            logger.debug(f"[{self.agent_id}] Database not available, skipping escalation")
            return

        try:
            async with get_db_session() as session:
                escalation = Escalation(
                    request_id=escalation_data.get("context", {}).get("request_id"),
                    agent_id=self.agent_id,
                    error=escalation_data.get("error"),
                    context=escalation_data.get("context"),
                    task=escalation_data.get("task"),
                    status="pending_review",
                    escalated_at=datetime.fromisoformat(escalation_data["escalated_at"])
                )
                session.add(escalation)
                await session.commit()
                logger.info(f"[{self.agent_id}] Escalation saved to database")
        except Exception as e:
            logger.error(f"[{self.agent_id}] Failed to save escalation: {e}")

    def get_state(self) -> str:
        """Get current agent state"""
        return self.state.value if isinstance(self.state, AgentState) else str(self.state)

    def get_task_history(self) -> list:
        """Get task execution history"""
        return self.task_history.copy()
