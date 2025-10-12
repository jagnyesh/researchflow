"""
ResearchFlow Central Orchestrator

Coordinates multi-agent workflows for research data requests.
Implements Agent-to-Agent (A2A) communication protocol.

NOW WITH DATABASE PERSISTENCE - All state persists across restarts!
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import asyncio
import logging
from sqlalchemy import select

from .workflow_engine import WorkflowEngine, WorkflowState
from app.database import (
    get_db_session,
    ResearchRequest,
    AuditLog,
    Approval
)

logger = logging.getLogger(__name__)


class ResearchRequestOrchestrator:
    """
    Central coordinator for multi-agent research request workflows

    Changes from previous version:
    - Uses database persistence instead of in-memory dict
    - All state changes logged to audit trail
    - Survives restarts (state in database)
    """

    def __init__(self):
        self.agents = {}  # Will be populated with agent instances
        self.workflow_engine = WorkflowEngine()
        # REMOVED: self.active_requests = {}  # Now using database!

    def register_agent(self, agent_id: str, agent_instance):
        """Register an agent with the orchestrator"""
        self.agents[agent_id] = agent_instance
        agent_instance.orchestrator = self
        logger.info(f"Registered agent: {agent_id}")

    async def process_new_request(
        self,
        researcher_request: str,
        researcher_info: Dict[str, Any]
    ) -> str:
        """
        Main entry point for new research data request

        Args:
            researcher_request: Natural language request from researcher
            researcher_info: Researcher metadata (name, email, IRB, etc.)

        Returns:
            request_id: Unique identifier for tracking the request
        """
        # Generate request ID
        request_id = self._generate_request_id()

        # Create database record for request
        async with get_db_session() as session:
            research_request = ResearchRequest(
                id=request_id,
                researcher_name=researcher_info.get('name', 'Unknown'),
                researcher_email=researcher_info.get('email', ''),
                researcher_department=researcher_info.get('department'),
                irb_number=researcher_info.get('irb_number'),
                initial_request=researcher_request,
                current_state=WorkflowState.NEW_REQUEST.value,
                current_agent=None,
                agents_involved=[],
                state_history=[{
                    'state': WorkflowState.NEW_REQUEST.value,
                    'timestamp': datetime.now().isoformat()
                }]
            )
            session.add(research_request)
            await session.flush()

            # Log to audit trail
            audit_entry = AuditLog(
                request_id=request_id,
                event_type="request_created",
                event_data={
                    'researcher_name': researcher_info.get('name'),
                    'initial_request': researcher_request
                },
                triggered_by='orchestrator',
                severity='info'
            )
            session.add(audit_entry)
            await session.commit()

        logger.info(f"New request {request_id} from {researcher_info.get('name', 'Unknown')}")

        # Start with Requirements Agent
        await self.route_task(
            agent_id='requirements_agent',
            task='gather_requirements',
            context={
                'request_id': request_id,
                'initial_request': researcher_request,
                'researcher_info': researcher_info
            },
            from_agent='orchestrator'
        )

        return request_id

    async def route_task(
        self,
        agent_id: str,
        task: str,
        context: Dict[str, Any],
        from_agent: str = None
    ):
        """
        Route work to specific agent (A2A communication)

        Args:
            agent_id: Target agent identifier
            task: Task to execute
            context: Task context and data
            from_agent: Source agent (for logging)
        """
        request_id = context.get('request_id')

        # Load request from database
        async with get_db_session() as session:
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            research_request = result.scalar_one_or_none()

            if not research_request:
                logger.error(f"Unknown request_id: {request_id}")
                return

            # Update workflow state in database
            research_request.current_agent = agent_id

            # Append to agents_involved list
            agents_involved = research_request.agents_involved or []
            agents_involved.append({
                'agent': agent_id,
                'task': task,
                'timestamp': datetime.now().isoformat(),
                'from_agent': from_agent
            })
            research_request.agents_involved = agents_involved

            # Log state transition to audit trail
            audit_entry = AuditLog(
                request_id=request_id,
                event_type="agent_started",
                agent_id=agent_id,
                event_data={
                    'task': task,
                    'from_agent': from_agent
                },
                triggered_by=from_agent or 'orchestrator',
                severity='info'
            )
            session.add(audit_entry)
            await session.commit()

        logger.info(f"[{request_id}] Routing to {agent_id}.{task} (from {from_agent})")

        # Get agent instance
        agent = self.agents.get(agent_id)
        if not agent:
            logger.error(f"Agent not found: {agent_id}")
            await self._handle_routing_error(request_id, f"Agent not found: {agent_id}")
            return

        try:
            # Execute task on agent
            result = await agent.handle_task(task, context)

            # HUMAN-IN-LOOP: Check if approval is required
            if result.get('requires_approval'):
                await self._handle_approval_request(
                    request_id=request_id,
                    agent_id=agent_id,
                    result=result,
                    context=context
                )
                return  # Wait for approval - don't continue workflow

            # Determine next step based on workflow rules
            next_step = self.workflow_engine.determine_next_step(
                completed_agent=agent_id,
                completed_task=task,
                result=result
            )

            # Update workflow state in database
            async with get_db_session() as session:
                result_db = await session.execute(
                    select(ResearchRequest).where(ResearchRequest.id == request_id)
                )
                research_request = result_db.scalar_one_or_none()

                if next_step and next_step['next_state']:
                    research_request.current_state = next_step['next_state'].value

                    # Append to state history
                    state_history = research_request.state_history or []
                    state_history.append({
                        'state': next_step['next_state'].value,
                        'timestamp': datetime.now().isoformat()
                    })
                    research_request.state_history = state_history

                    # Log state change to audit
                    audit_entry = AuditLog(
                        request_id=request_id,
                        event_type="state_changed",
                        agent_id=agent_id,
                        event_data={
                            'new_state': next_step['next_state'].value,
                            'completed_task': task
                        },
                        triggered_by=agent_id,
                        severity='info'
                    )
                    session.add(audit_entry)

                await session.commit()

            # Check if workflow is complete
            if next_step and next_step['next_agent']:
                # Continue to next agent
                await self.route_task(
                    agent_id=next_step['next_agent'],
                    task=next_step['next_task'],
                    context={**context, **result.get('additional_context', {})},
                    from_agent=agent_id
                )
            else:
                # Workflow complete or needs human review
                async with get_db_session() as session:
                    result_db = await session.execute(
                        select(ResearchRequest).where(ResearchRequest.id == request_id)
                    )
                    req = result_db.scalar_one_or_none()
                    current_state = WorkflowState(req.current_state)
                    await self._complete_workflow(request_id, current_state)

        except Exception as e:
            logger.error(f"[{request_id}] Agent {agent_id} failed: {str(e)}", exc_info=True)
            await self._handle_workflow_error(request_id, agent_id, str(e))

    async def _handle_approval_request(
        self,
        request_id: str,
        agent_id: str,
        result: Dict[str, Any],
        context: Dict[str, Any]
    ):
        """
        Handle agent request for human approval

        Creates approval record, updates state, and notifies coordinator agent
        """
        approval_type = result.get('approval_type')
        approval_data = result.get('additional_context', {}).get('approval_data', {})

        logger.info(
            f"[{request_id}] {agent_id} requesting {approval_type} approval"
        )

        async with get_db_session() as session:
            # Import here to avoid circular dependency
            from app.services.approval_service import ApprovalService

            # Create approval service
            approval_service = ApprovalService(session)

            # Create approval record
            approval = await approval_service.create_approval(
                request_id=request_id,
                approval_type=approval_type,
                submitted_by=agent_id,
                approval_data=approval_data
            )

            # Update workflow state to approval state
            result_db = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            research_request = result_db.scalar_one_or_none()

            # Get approval state from workflow engine
            approval_state_map = {
                "requirements": WorkflowState.REQUIREMENTS_REVIEW,
                "phenotype_sql": WorkflowState.PHENOTYPE_REVIEW,
                "extraction": WorkflowState.EXTRACTION_APPROVAL,
                "qa": WorkflowState.QA_REVIEW,
                "scope_change": WorkflowState.SCOPE_CHANGE
            }

            new_state = approval_state_map.get(approval_type, WorkflowState.HUMAN_REVIEW)
            research_request.current_state = new_state.value

            # Append to state history
            state_history = research_request.state_history or []
            state_history.append({
                'state': new_state.value,
                'timestamp': datetime.now().isoformat(),
                'approval_id': approval.id
            })
            research_request.state_history = state_history

            # Log approval request to audit
            audit_entry = AuditLog(
                request_id=request_id,
                event_type="approval_requested",
                agent_id=agent_id,
                event_data={
                    'approval_type': approval_type,
                    'approval_id': approval.id,
                    'new_state': new_state.value
                },
                triggered_by=agent_id,
                severity='info'
            )
            session.add(audit_entry)
            await session.commit()

            logger.info(
                f"[{request_id}] Created {approval_type} approval (ID: {approval.id}), "
                f"state: {new_state.value}"
            )

        # Notify coordinator agent to send email
        coordinator = self.agents.get('coordinator_agent')
        if coordinator:
            try:
                await coordinator.handle_task(
                    task='coordinate_approval',
                    context={
                        'request_id': request_id,
                        'approval_type': approval_type,
                        'approval_id': approval.id,
                        **context,
                        **result.get('additional_context', {})
                    }
                )
                logger.info(f"[{request_id}] Coordinator notified for {approval_type} approval")
            except Exception as e:
                logger.error(f"[{request_id}] Failed to notify coordinator: {str(e)}")

    async def process_approval_response(
        self,
        approval_id: int,
        reviewer: str,
        decision: str,
        notes: Optional[str] = None,
        modifications: Optional[Dict[str, Any]] = None
    ):
        """
        Process approval response (approve/reject/modify) and continue workflow

        Args:
            approval_id: Approval record ID
            reviewer: User ID or email of reviewer
            decision: 'approve', 'reject', or 'modify'
            notes: Optional review notes
            modifications: Optional modifications (for modify decision)
        """
        async with get_db_session() as session:
            # Import here to avoid circular dependency
            from app.services.approval_service import ApprovalService

            approval_service = ApprovalService(session)

            # Get approval
            approval = await approval_service.get_approval(approval_id)
            if not approval:
                logger.error(f"Approval {approval_id} not found")
                return

            request_id = approval.request_id
            approval_type = approval.approval_type

            logger.info(
                f"[{request_id}] Processing {approval_type} approval: {decision} by {reviewer}"
            )

            # Update approval status
            if decision == 'approve':
                await approval_service.approve(approval_id, reviewer, notes, modifications)
            elif decision == 'reject':
                await approval_service.reject(approval_id, reviewer, notes or "Rejected")
            elif decision == 'modify':
                await approval_service.modify(approval_id, reviewer, modifications, notes)
            else:
                raise ValueError(f"Invalid decision: {decision}")

            # Log to audit
            audit_entry = AuditLog(
                request_id=request_id,
                event_type="approval_processed",
                agent_id="approval_service",
                event_data={
                    'approval_id': approval_id,
                    'approval_type': approval_type,
                    'decision': decision,
                    'reviewer': reviewer
                },
                triggered_by=reviewer,
                severity='info'
            )
            session.add(audit_entry)
            await session.commit()

        # Route to next agent based on decision and approval type
        if decision in ['approve', 'modify']:
            await self._continue_workflow_after_approval(approval_id, decision, modifications)
        else:
            # Rejected - route back to originating agent
            await self._handle_approval_rejection(approval_id)

    async def _continue_workflow_after_approval(
        self,
        approval_id: int,
        decision: str,
        modifications: Optional[Dict[str, Any]] = None
    ):
        """Continue workflow after approval is granted"""
        async with get_db_session() as session:
            # Import here to avoid circular dependency
            from app.services.approval_service import ApprovalService

            approval_service = ApprovalService(session)
            approval = await approval_service.get_approval(approval_id)

            if not approval:
                return

            request_id = approval.request_id
            approval_type = approval.approval_type

            # Determine next agent based on approval type
            next_agent_map = {
                "requirements": ("phenotype_agent", "validate_feasibility"),
                "phenotype_sql": ("calendar_agent", "schedule_kickoff_meeting"),
                "extraction": ("extraction_agent", "extract_data"),
                "qa": ("delivery_agent", "deliver_data"),
                "scope_change": ("requirements_agent", "gather_requirements")  # Restart from requirements
            }

            next_agent, next_task = next_agent_map.get(
                approval_type,
                (None, None)
            )

            if next_agent:
                # Build context with approved data
                context = {
                    'request_id': request_id,
                    'approval_id': approval_id,
                    'approved_by': approval.reviewed_by
                }

                # Add approval data to context
                if approval.approval_data:
                    context.update(approval.approval_data)

                # Add modifications if provided
                if modifications:
                    context['modifications'] = modifications

                logger.info(
                    f"[{request_id}] Routing to {next_agent}.{next_task} after {approval_type} approval"
                )

                await self.route_task(
                    agent_id=next_agent,
                    task=next_task,
                    context=context,
                    from_agent='approval_service'
                )

    async def _handle_approval_rejection(self, approval_id: int):
        """Handle approval rejection - route back to originating agent"""
        async with get_db_session() as session:
            # Import here to avoid circular dependency
            from app.services.approval_service import ApprovalService

            approval_service = ApprovalService(session)
            approval = await approval_service.get_approval(approval_id)

            if not approval:
                return

            request_id = approval.request_id
            approval_type = approval.approval_type

            # Determine agent to return to
            return_agent_map = {
                "requirements": ("requirements_agent", "gather_requirements"),
                "phenotype_sql": ("phenotype_agent", "validate_feasibility"),
                "extraction": ("calendar_agent", "schedule_kickoff_meeting"),  # Re-schedule
                "qa": ("extraction_agent", "extract_data"),  # Re-extract
                "scope_change": (None, None)  # Scope change rejected - continue with current workflow
            }

            return_agent, return_task = return_agent_map.get(
                approval_type,
                (None, None)
            )

            if return_agent:
                logger.info(
                    f"[{request_id}] Approval rejected, routing back to {return_agent}.{return_task}"
                )

                context = {
                    'request_id': request_id,
                    'rejection_reason': approval.review_notes,
                    'previous_attempt': approval.approval_data
                }

                await self.route_task(
                    agent_id=return_agent,
                    task=return_task,
                    context=context,
                    from_agent='approval_service'
                )

    async def _complete_workflow(self, request_id: str, final_state: WorkflowState):
        """Mark workflow as complete"""
        async with get_db_session() as session:
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            research_request = result.scalar_one_or_none()

            if not research_request:
                logger.error(f"Request not found: {request_id}")
                return

            research_request.completed_at = datetime.now()
            research_request.final_state = final_state.value

            duration = (research_request.completed_at - research_request.created_at).total_seconds()

            # Log completion to audit trail
            audit_entry = AuditLog(
                request_id=request_id,
                event_type="workflow_completed",
                event_data={
                    'final_state': final_state.value,
                    'duration_seconds': duration
                },
                triggered_by='orchestrator',
                severity='info'
            )
            session.add(audit_entry)
            await session.commit()

            logger.info(
                f"[{request_id}] Workflow complete: {final_state.value} "
                f"(duration: {duration:.2f}s)"
            )

            # TODO: Send completion notification

    async def _handle_routing_error(self, request_id: str, error: str):
        """Handle routing errors"""
        logger.error(f"[{request_id}] Routing error: {error}")

        async with get_db_session() as session:
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            research_request = result.scalar_one_or_none()

            if research_request:
                research_request.current_state = WorkflowState.FAILED.value
                research_request.error_message = error

                # Log error to audit
                audit_entry = AuditLog(
                    request_id=request_id,
                    event_type="routing_error",
                    event_data={'error': error},
                    triggered_by='orchestrator',
                    severity='error'
                )
                session.add(audit_entry)
                await session.commit()

        await self._complete_workflow(request_id, WorkflowState.FAILED)

    async def _handle_workflow_error(self, request_id: str, agent_id: str, error: str):
        """Handle workflow execution errors"""
        logger.error(f"[{request_id}] Workflow error in {agent_id}: {error}")

        async with get_db_session() as session:
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            research_request = result.scalar_one_or_none()

            if research_request:
                research_request.current_state = WorkflowState.HUMAN_REVIEW.value
                research_request.error_message = error
                research_request.current_agent = agent_id

                # Log error to audit
                audit_entry = AuditLog(
                    request_id=request_id,
                    event_type="workflow_error",
                    agent_id=agent_id,
                    event_data={'error': error},
                    triggered_by=agent_id,
                    severity='error'
                )
                session.add(audit_entry)
                await session.commit()

        await self._complete_workflow(request_id, WorkflowState.HUMAN_REVIEW)

    async def get_request_status(self, request_id: str) -> Optional[Dict[str, Any]]:
        """Get current status of a request"""
        async with get_db_session() as session:
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.id == request_id)
            )
            research_request = result.scalar_one_or_none()

            if not research_request:
                return None

            return {
                'request_id': request_id,
                'current_state': research_request.current_state,
                'current_agent': research_request.current_agent,
                'started_at': research_request.created_at.isoformat(),
                'completed_at': research_request.completed_at.isoformat() if research_request.completed_at else None,
                'agents_involved': research_request.agents_involved,
                'state_history': research_request.state_history,
                'researcher_info': {
                    'name': research_request.researcher_name,
                    'email': research_request.researcher_email,
                    'department': research_request.researcher_department,
                    'irb_number': research_request.irb_number
                }
            }

    async def get_all_active_requests(self) -> list:
        """Get all active requests (not completed)"""
        async with get_db_session() as session:
            result = await session.execute(
                select(ResearchRequest).where(ResearchRequest.completed_at.is_(None))
            )
            active_requests = result.scalars().all()

            # Use asyncio.gather to properly await all status requests
            statuses = await asyncio.gather(*[
                self.get_request_status(req.id)
                for req in active_requests
            ])
            return statuses

    def _generate_request_id(self) -> str:
        """Generate unique request ID"""
        import uuid
        return f"REQ-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"

    def get_agent_metrics(self, agent_id: str = None) -> Dict[str, Any]:
        """Get metrics for specific agent or all agents"""
        if agent_id:
            agent = self.agents.get(agent_id)
            return agent.get_metrics() if agent else {}

        return {
            agent_id: agent.get_metrics()
            for agent_id, agent in self.agents.items()
        }
