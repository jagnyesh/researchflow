"""
Base Agent Class for ResearchFlow

Provides common functionality for all specialized agents including:
- Task execution framework
- Error handling and retry logic
- Agent state management
- Orchestrator communication
- Human escalation patterns
"""

from abc import ABC, abstractmethod
from typing import Dict, Any, Optional
from datetime import datetime
from enum import Enum
import asyncio
import logging

logger = logging.getLogger(__name__)


class AgentState(Enum):
    """Agent operational states"""
    IDLE = "idle"
    WORKING = "working"
    FAILED = "failed"
    WAITING = "waiting"


class BaseAgent(ABC):
    """Base class for all ResearchFlow agents"""

    def __init__(self, agent_id: str, orchestrator=None):
        self.agent_id = agent_id
        self.orchestrator = orchestrator
        self.state = AgentState.IDLE
        self.current_task = None
        self.task_history = []
        self.max_retries = 3

    @abstractmethod
    async def execute_task(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute assigned task - must be implemented by subclass

        Args:
            task: Task identifier
            context: Task context including request_id and other data

        Returns:
            Dict with task results and next agent/task information
        """
        pass

    async def handle_task(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """
        Wrapper for task execution with logging, error handling, and state management
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

            # Execute the task
            result = await self.execute_task(task, context)

            # Log success
            self.current_task["completed_at"] = datetime.now()
            self.current_task["result"] = result
            self.current_task["status"] = "success"

            duration = (self.current_task["completed_at"] - self.current_task["started_at"]).total_seconds()
            logger.info(f"[{self.agent_id}] Completed task: {task} in {duration:.2f}s")

            # Add to history
            self.task_history.append(self.current_task.copy())

            # Notify orchestrator if next agent specified
            if result.get('next_agent'):
                await self.notify_orchestrator(
                    next_agent=result['next_agent'],
                    next_task=result['next_task'],
                    context={**context, **result.get('additional_context', {})}
                )

            return result

        except Exception as e:
            logger.error(f"[{self.agent_id}] Task failed: {task} - {str(e)}", exc_info=True)

            # Log failure
            self.current_task["completed_at"] = datetime.now()
            self.current_task["error"] = str(e)
            self.current_task["status"] = "failed"

            # Add to history
            self.task_history.append(self.current_task.copy())

            # Attempt retry or escalate
            if self.should_retry(e, context):
                return await self.retry_task(task, context)
            else:
                await self.escalate_to_human(e, context)
                raise

        finally:
            self.state = AgentState.IDLE
            self.current_task = None

    async def notify_orchestrator(self, next_agent: str, next_task: str, context: Dict):
        """Notify orchestrator to route to next agent"""
        if self.orchestrator:
            logger.info(f"[{self.agent_id}] Routing to {next_agent}.{next_task}")
            await self.orchestrator.route_task(
                agent_id=next_agent,
                task=next_task,
                context=context,
                from_agent=self.agent_id
            )

    def should_retry(self, error: Exception, context: Dict) -> bool:
        """Determine if task should be retried"""
        retry_count = context.get('retry_count', 0)

        # Don't retry if max retries exceeded
        if retry_count >= self.max_retries:
            return False

        # Retry on transient errors
        transient_errors = [
            "ConnectionError",
            "TimeoutError",
            "TemporaryFailure",
            "ServiceUnavailable"
        ]

        return type(error).__name__ in transient_errors

    async def retry_task(self, task: str, context: Dict) -> Dict[str, Any]:
        """Retry failed task with exponential backoff"""
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
        logger.info(f"[{self.agent_id}] Retrying task after {wait_time}s (attempt {retry_count + 1}/{self.max_retries})")
        await asyncio.sleep(wait_time)

        # Retry with incremented count
        context['retry_count'] = retry_count + 1
        return await self.handle_task(task, context)

    async def escalate_to_human(self, error: Any, context: Dict):
        """
        Escalate to human review

        Creates an escalation record for admin review in the dashboard
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

        # Save to database (will be implemented with database models)
        await self.save_escalation(escalation)

        # Notify admin (will be implemented with notification system)
        await self.notify_admin(escalation)

    async def save_escalation(self, escalation: Dict):
        """Save escalation to database for admin review"""
        # TODO: Implement database save when models are ready
        logger.info(f"[{self.agent_id}] Escalation saved: {escalation['error']}")

    async def notify_admin(self, escalation: Dict):
        """Send notification to admins about escalation"""
        # TODO: Implement email/Slack notification
        logger.info(f"[{self.agent_id}] Admin notified about escalation")

    def get_metrics(self) -> Dict[str, Any]:
        """Get agent performance metrics"""
        total_tasks = len(self.task_history)
        successful_tasks = sum(1 for t in self.task_history if t.get('status') == 'success')
        failed_tasks = sum(1 for t in self.task_history if t.get('status') == 'failed')

        avg_duration = 0
        if total_tasks > 0:
            durations = [
                (t['completed_at'] - t['started_at']).total_seconds()
                for t in self.task_history
                if 'completed_at' in t and 'started_at' in t
            ]
            avg_duration = sum(durations) / len(durations) if durations else 0

        return {
            "agent_id": self.agent_id,
            "state": self.state.value,
            "total_tasks": total_tasks,
            "successful_tasks": successful_tasks,
            "failed_tasks": failed_tasks,
            "success_rate": successful_tasks / total_tasks if total_tasks > 0 else 0,
            "avg_duration_seconds": avg_duration,
            "current_task": self.current_task
        }
