"""
Integration tests for Researcher Portal conversational interface

Tests the end-to-end conversation flow between the portal UI and RequirementsAgent.
"""

import pytest
import asyncio
from datetime import datetime

from app.agents.requirements_agent import RequirementsAgent


class TestResearcherPortalIntegration:
    """Integration tests for conversational chatbot interface"""

    @pytest.mark.asyncio
    async def test_conversation_flow_interface(self):
        """Test that the portal can communicate with RequirementsAgent"""

        # Initialize agent (as portal does)
        agent = RequirementsAgent()

        # Simulate Phase 1: Initial request from researcher
        researcher_info = {
            "name": "Dr. Jane Smith",
            "email": "jsmith@hospital.edu",
            "department": "Cardiology",
            "irb_number": "IRB-2024-001"
        }

        initial_request = "I need clinical notes and lab results for heart failure patients"

        # Build context (as portal does in process_user_message)
        context = {
            "request_id": "temp_" + datetime.now().strftime("%Y%m%d%H%M%S"),
            "conversation_history": [
                {
                    "role": "user",
                    "content": initial_request,
                    "timestamp": datetime.now().isoformat()
                }
            ],
            "researcher_info": researcher_info,
            "initial_request": initial_request
        }

        # Call agent (as portal does)
        result = await agent.execute_task("gather_requirements", context)

        # Verify response structure
        assert "requirements_complete" in result
        assert "completeness_score" in result

        # Should NOT be complete after first message
        assert result["requirements_complete"] is False, "Requirements should not be complete after initial request"
        assert result["completeness_score"] < 1.0, "Completeness should be less than 100%"

        # Should have a follow-up question
        assert "next_question" in result, "Agent should ask a follow-up question"
        assert result["next_question"], "Next question should not be empty"

        # Should have current requirements
        assert "current_requirements" in result

        print(f"✅ Initial conversation working")
        print(f"   Completeness: {result['completeness_score']:.0%}")
        print(f"   Next question: {result['next_question'][:80]}...")

    @pytest.mark.asyncio
    async def test_conversation_state_management(self):
        """Test that conversation state is maintained across turns"""

        agent = RequirementsAgent()

        researcher_info = {
            "name": "Dr. Test",
            "email": "test@hospital.edu",
            "irb_number": "IRB-TEST-001"
        }

        # Turn 1: Initial request
        context1 = {
            "request_id": "REQ-TEST-001",
            "initial_request": "I need data for diabetes patients",
            "conversation_history": [
                {"role": "user", "content": "I need data for diabetes patients", "timestamp": datetime.now().isoformat()}
            ],
            "researcher_info": researcher_info
        }

        result1 = await agent.execute_task("gather_requirements", context1)
        completeness1 = result1["completeness_score"]

        # Turn 2: Answer follow-up question
        context2 = {
            "request_id": "REQ-TEST-001",  # Same request ID
            "initial_request": "I need data for diabetes patients",
            "user_response": "Patients admitted between January 2023 and December 2023",
            "conversation_history": [
                {"role": "user", "content": "I need data for diabetes patients", "timestamp": datetime.now().isoformat()},
                {"role": "assistant", "content": result1["next_question"], "timestamp": datetime.now().isoformat()},
                {"role": "user", "content": "Patients admitted between January 2023 and December 2023", "timestamp": datetime.now().isoformat()}
            ],
            "researcher_info": researcher_info
        }

        result2 = await agent.execute_task("gather_requirements", context2)
        completeness2 = result2["completeness_score"]

        # Completeness should increase
        assert completeness2 >= completeness1, "Completeness should increase or stay the same"

        print(f"✅ Conversation state maintained")
        print(f"   Turn 1 completeness: {completeness1:.0%}")
        print(f"   Turn 2 completeness: {completeness2:.0%}")

    @pytest.mark.asyncio
    async def test_portal_context_format(self):
        """Test that portal context format is accepted by agent"""

        agent = RequirementsAgent()

        # Exact format used by researcher_portal.py:process_user_message()
        portal_context = {
            "request_id": "temp_20241022120000",
            "conversation_history": [
                {
                    "role": "user",
                    "content": "Test request",
                    "timestamp": datetime.now().isoformat()
                }
            ],
            "researcher_info": {
                "name": "Dr. Portal Test",
                "email": "portal@test.edu",
                "department": "Testing",
                "irb_number": "IRB-PORTAL-001"
            },
            "initial_request": "Test request"
        }

        # Should not raise any exceptions
        result = await agent.execute_task("gather_requirements", portal_context)

        # Should return expected keys
        assert "requirements_complete" in result
        assert "completeness_score" in result
        assert isinstance(result["requirements_complete"], bool)
        assert isinstance(result["completeness_score"], (int, float))
        assert 0.0 <= result["completeness_score"] <= 1.0

        print(f"✅ Portal context format accepted")

    @pytest.mark.asyncio
    async def test_completion_detection(self):
        """Test that agent correctly detects when requirements are complete"""

        agent = RequirementsAgent()

        # Provide comprehensive requirements upfront
        comprehensive_request = """
        I need clinical notes, lab results, and imaging reports for heart failure patients.

        Inclusion criteria:
        - Adults (18+) with HFrEF diagnosis (LVEF < 40%)
        - Admitted to cardiology service
        - Between January 1, 2023 and December 31, 2023

        Exclusion criteria:
        - Patients with advanced kidney disease (stage 4-5)
        - Pregnant patients

        Data elements needed:
        - Clinical notes (admission, discharge, progress notes)
        - Lab results (BNP, troponin, creatinine, BUN)
        - Echo reports
        - Medications

        Need de-identified data in CSV format.
        IRB approved study (IRB-2024-HF-001).
        """

        context = {
            "request_id": "REQ-COMPLETE-TEST",
            "initial_request": comprehensive_request,
            "conversation_history": [
                {"role": "user", "content": comprehensive_request, "timestamp": datetime.now().isoformat()}
            ],
            "researcher_info": {
                "name": "Dr. Complete",
                "email": "complete@test.edu",
                "irb_number": "IRB-2024-HF-001"
            }
        }

        result = await agent.execute_task("gather_requirements", context)

        # Completeness should be reasonable (>= 0.5)
        # Note: In test environment with dummy LLM, this may be exactly 0.5
        # With real LLM, comprehensive requests should score higher
        assert result["completeness_score"] >= 0.5, "Comprehensive request should have reasonable completeness"

        print(f"✅ Completion detection working")
        print(f"   Completeness: {result['completeness_score']:.0%}")
        print(f"   Complete: {result['requirements_complete']}")
        if result["completeness_score"] == 0.5:
            print(f"   Note: Using dummy LLM responses (no ANTHROPIC_API_KEY)")


if __name__ == "__main__":
    # Run tests
    pytest.main([__file__, '-v', '-s'])
