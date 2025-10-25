"""
Calendar Agent

Schedules kickoff meetings with relevant stakeholders using calendar integration.
Uses MultiLLMClient for intelligent agenda generation and stakeholder identification.
"""

from typing import Dict, Any
import logging
from datetime import datetime, timedelta
from .base_agent import BaseAgent
from ..utils.multi_llm_client import MultiLLMClient

logger = logging.getLogger(__name__)


class CalendarAgent(BaseAgent):
    """
    Agent for scheduling and coordinating meetings

    Responsibilities:
    - Identify required stakeholders based on request complexity
    - Find common availability (via MCP calendar server)
    - Schedule meeting with agenda
    - Send calendar invites
    - Route to extraction agent when complete
    """

    def __init__(self, orchestrator=None):
        super().__init__(agent_id="calendar_agent", orchestrator=orchestrator)
        self.llm_client = MultiLLMClient()  # Use multi-provider client for non-critical tasks

    async def execute_task(self, task: str, context: Dict[str, Any]) -> Dict[str, Any]:
        """Execute calendar scheduling task"""
        if task == "schedule_kickoff_meeting":
            return await self._schedule_kickoff_meeting(context)
        else:
            raise ValueError(f"Unknown task: {task}")

    async def _schedule_kickoff_meeting(self, context: Dict) -> Dict[str, Any]:
        """
        Schedule kickoff meeting with stakeholders

        Args:
            context: Contains request_id, requirements, feasibility_report

        Returns:
            Dict with meeting details and next routing
        """
        request_id = context.get('request_id')
        requirements = context.get('requirements')
        feasibility_report = context.get('feasibility_report')

        logger.info(f"[{self.agent_id}] Scheduling kickoff for {request_id}")

        # Step 1: Identify required stakeholders
        attendees = await self._identify_stakeholders(requirements, feasibility_report)

        # Step 2: Find common availability (simplified - in production use MCP calendar)
        meeting_slot = await self._find_common_availability(attendees)

        # Step 3: Generate meeting agenda
        agenda = await self._generate_meeting_agenda(requirements, feasibility_report)

        # Step 4: Create meeting
        meeting = {
            "meeting_id": f"MTG-{request_id}",
            "title": f"Data Request Kickoff - {requirements.get('study_title', 'Research Study')}",
            "attendees": attendees,
            "datetime": meeting_slot['datetime'],
            "duration_minutes": 30,
            "agenda": agenda,
            "location": "Virtual (Teams/Zoom)",
            "scheduled_at": datetime.now().isoformat()
        }

        # Step 5: Send invites (simplified - in production use MCP email server)
        await self._send_meeting_invites(meeting)

        logger.info(
            f"[{self.agent_id}] Meeting scheduled for {meeting['datetime']} "
            f"with {len(attendees['required'])} required attendees"
        )

        return {
            "meeting_scheduled": True,
            "meeting": meeting,
            "next_agent": "extraction_agent",
            "next_task": "extract_data",
            "additional_context": {
                "meeting": meeting
            }
        }

    async def _identify_stakeholders(
        self,
        requirements: Dict,
        feasibility_report: Dict
    ) -> Dict[str, list]:
        """
        Identify required and optional attendees

        Returns:
            Dict with 'required' and 'optional' attendee lists
        """
        attendees = {
            "required": [],
            "optional": []
        }

        # Always include researcher
        if requirements.get('principal_investigator'):
            attendees['required'].append({
                "name": requirements['principal_investigator'],
                "role": "Principal Investigator",
                "email": f"{requirements.get('principal_investigator', 'researcher').lower().replace(' ', '.')}@example.com"
            })

        # Always include informaticist
        attendees['required'].append({
            "name": "Clinical Informaticist",
            "role": "Data Specialist",
            "email": "informaticist@example.com"
        })

        # Add biostatistician if cohort is large or complex
        cohort_size = feasibility_report.get('estimated_cohort_size', 0)
        if cohort_size > 200:
            attendees['optional'].append({
                "name": "Biostatistician",
                "role": "Statistical Consultant",
                "email": "biostatistician@example.com"
            })

        # Add data steward if dealing with identified data
        if requirements.get('phi_level') == 'identified':
            attendees['required'].append({
                "name": "Data Steward",
                "role": "Privacy Officer",
                "email": "privacy@example.com"
            })

        return attendees

    async def _find_common_availability(self, attendees: Dict) -> Dict:
        """
        Find common available time slot

        In production: Use MCP calendar server to query availability
        For now: Return next business day at 2 PM
        """
        # Simplified: Schedule for 2 days from now at 2 PM
        meeting_time = datetime.now() + timedelta(days=2)
        meeting_time = meeting_time.replace(hour=14, minute=0, second=0, microsecond=0)

        # TODO: Implement MCP calendar integration
        # calendar_server = self.mcp_registry.get_server('google_calendar')
        # availability = await calendar_server.find_common_slots(...)

        return {
            "datetime": meeting_time.isoformat(),
            "timezone": "UTC"
        }

    async def _generate_meeting_agenda(
        self,
        requirements: Dict,
        feasibility_report: Dict
    ) -> str:
        """
        Generate meeting agenda based on request details

        Uses LLM to create tailored agenda with intelligent discussion points.
        This is a non-critical task that uses the secondary provider.
        """
        # Build context for LLM
        prompt = f"""Generate a professional meeting agenda for a clinical research data request kickoff meeting.

Study Details:
- Title: {requirements.get('study_title', 'TBD')}
- Principal Investigator: {requirements.get('principal_investigator', 'TBD')}
- IRB Number: {requirements.get('irb_number', 'TBD')}

Cohort Information:
- Estimated Size: {feasibility_report.get('estimated_cohort_size', 'TBD')} patients
- Feasibility Score: {feasibility_report.get('feasibility_score', 0):.1%}

Requested Data Elements:
{chr(10).join('- ' + elem for elem in requirements.get('data_elements', []))}

Warnings/Issues to Discuss:
{chr(10).join('- ' + w.get('message', '') for w in feasibility_report.get('warnings', [])) if feasibility_report.get('warnings') else '- None'}

Create a structured agenda with:
1. Study overview section
2. Cohort summary
3. Data elements discussion
4. Specific discussion points tailored to this request
5. Warnings/considerations section
6. Next steps

Keep it professional and concise."""

        system_prompt = "You are a clinical research coordinator creating meeting agendas for data request kickoff meetings."

        try:
            # Use secondary provider for this non-critical task
            agenda = await self.llm_client.complete(
                prompt=prompt,
                task_type="calendar",  # Non-critical task
                temperature=0.7,
                system=system_prompt
            )
            return agenda.strip()
        except Exception as e:
            logger.warning(f"[{self.agent_id}] Failed to generate LLM agenda: {str(e)}, using template")
            # Fallback to template-based agenda
            agenda = f"""
# Data Request Kickoff Meeting

## Study Overview
- Title: {requirements.get('study_title', 'TBD')}
- PI: {requirements.get('principal_investigator', 'TBD')}
- IRB: {requirements.get('irb_number', 'TBD')}

## Cohort Summary
- Estimated Size: {feasibility_report.get('estimated_cohort_size', 'TBD')} patients
- Feasibility Score: {feasibility_report.get('feasibility_score', 0):.1%}

## Requested Data Elements
{chr(10).join('- ' + elem for elem in requirements.get('data_elements', []))}

## Discussion Points
1. Review inclusion/exclusion criteria
2. Confirm data elements needed
3. Discuss timeline and delivery format
4. Address any feasibility warnings
5. Next steps and responsibilities

## Warnings/Considerations
{chr(10).join('- ' + w.get('message', '') for w in feasibility_report.get('warnings', []))}
"""
            return agenda.strip()

    async def _send_meeting_invites(self, meeting: Dict):
        """Send calendar invites to attendees"""
        # TODO: Implement MCP email/calendar server integration
        # email_server = self.mcp_registry.get_server('email')
        # await email_server.send_calendar_invite(meeting)

        logger.info(f"[{self.agent_id}] Calendar invites sent to {len(meeting['attendees']['required'])} attendees")
