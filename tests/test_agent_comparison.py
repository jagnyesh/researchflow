"""
Test Harness for Production vs Experimental Agent Comparison

Runs identical test requests through both:
- Production agents (app/agents/)
- Experimental LangChain agents (app/langchain_orchestrator/langchain_agents.py)

Compares:
- Execution time
- Success rate
- Output structure/content
- Error handling

Usage:
    pytest tests/test_agent_comparison.py -v -s
    # OR with environment variables for tracing:
    LANGCHAIN_TRACING_V2=true LANGCHAIN_API_KEY=... pytest tests/test_agent_comparison.py -v -s
"""

import pytest
import asyncio
import time
import json
import os
from typing import Dict, Any, List
from datetime import datetime

# Production agents
from app.agents.requirements_agent import RequirementsAgent
from app.agents.phenotype_agent import PhenotypeValidationAgent
from app.agents.calendar_agent import CalendarAgent

# Experimental LangChain agents
from app.langchain_orchestrator.langchain_agents import (
    LangChainRequirementsAgent,
    LangChainPhenotypeAgent,
    LangChainCalendarAgent
)


class AgentComparisonResult:
    """Store results from agent execution for comparison"""

    def __init__(self, agent_type: str, agent_name: str):
        self.agent_type = agent_type  # "production" or "experimental"
        self.agent_name = agent_name
        self.execution_time: float = 0.0
        self.success: bool = False
        self.result: Dict[str, Any] = {}
        self.error: str = None
        self.output_keys: List[str] = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent_type": self.agent_type,
            "agent_name": self.agent_name,
            "execution_time": self.execution_time,
            "success": self.success,
            "output_keys": self.output_keys,
            "error": self.error,
            "result": self.result
        }


class AgentComparisonHarness:
    """Harness for running side-by-side agent comparisons"""

    def __init__(self):
        # Get HAPI DB URL from environment
        self.hapi_db_url = os.getenv("HAPI_DB_URL", "postgresql://hapi:hapi@localhost:5433/hapi")

        # Lazy initialization - agents created on demand
        self._prod_requirements = None
        self._prod_phenotype = None
        self._prod_calendar = None
        self._exp_requirements = None
        self._exp_phenotype = None
        self._exp_calendar = None

    @property
    def prod_requirements(self):
        if self._prod_requirements is None:
            self._prod_requirements = RequirementsAgent()
        return self._prod_requirements

    @property
    def prod_phenotype(self):
        if self._prod_phenotype is None:
            self._prod_phenotype = PhenotypeValidationAgent(database_url=self.hapi_db_url)
        return self._prod_phenotype

    @property
    def prod_calendar(self):
        if self._prod_calendar is None:
            self._prod_calendar = CalendarAgent()
        return self._prod_calendar

    @property
    def exp_requirements(self):
        if self._exp_requirements is None:
            self._exp_requirements = LangChainRequirementsAgent()
        return self._exp_requirements

    @property
    def exp_phenotype(self):
        if self._exp_phenotype is None:
            self._exp_phenotype = LangChainPhenotypeAgent(database_url=self.hapi_db_url)
        return self._exp_phenotype

    @property
    def exp_calendar(self):
        if self._exp_calendar is None:
            self._exp_calendar = LangChainCalendarAgent()
        return self._exp_calendar

    async def run_agent(
        self,
        agent,
        task_name: str,
        context: Dict[str, Any],
        agent_type: str,
        agent_name: str
    ) -> AgentComparisonResult:
        """Run a single agent method and capture metrics"""
        result = AgentComparisonResult(agent_type, agent_name)
        start_time = time.time()  # Initialize before try block

        try:
            # Both production and experimental agents use execute_task() entry point
            output = await agent.execute_task(task_name, context)

            end_time = time.time()

            # Capture results
            result.execution_time = end_time - start_time
            result.success = True
            result.result = output
            result.output_keys = list(output.keys()) if isinstance(output, dict) else []

        except Exception as e:
            result.success = False
            result.error = str(e)
            result.execution_time = time.time() - start_time

        return result

    async def compare_requirements_agents(
        self,
        test_context: Dict[str, Any]
    ) -> Dict[str, AgentComparisonResult]:
        """Compare Requirements agents"""
        print("\n" + "="*80)
        print("COMPARING REQUIREMENTS AGENTS")
        print("="*80)

        # Run production agent
        print("\n[1/2] Running PRODUCTION Requirements Agent...")
        prod_result = await self.run_agent(
            self.prod_requirements,
            "gather_requirements",
            test_context,
            "production",
            "RequirementsAgent"
        )
        print(f"  ✓ Completed in {prod_result.execution_time:.2f}s")
        if prod_result.success:
            print(f"  Output keys: {prod_result.output_keys}")
        else:
            print(f"  ✗ Error: {prod_result.error}")

        # Run experimental agent
        print("\n[2/2] Running EXPERIMENTAL LangChain Requirements Agent...")
        exp_result = await self.run_agent(
            self.exp_requirements,
            "gather_requirements",
            test_context,
            "experimental",
            "LangChainRequirementsAgent"
        )
        print(f"  ✓ Completed in {exp_result.execution_time:.2f}s")
        if exp_result.success:
            print(f"  Output keys: {exp_result.output_keys}")
        else:
            print(f"  ✗ Error: {exp_result.error}")

        # Compare
        self._print_comparison(prod_result, exp_result)

        return {
            "production": prod_result,
            "experimental": exp_result
        }

    async def compare_phenotype_agents(
        self,
        test_context: Dict[str, Any]
    ) -> Dict[str, AgentComparisonResult]:
        """Compare Phenotype agents"""
        print("\n" + "="*80)
        print("COMPARING PHENOTYPE AGENTS")
        print("="*80)

        # Run production agent
        print("\n[1/2] Running PRODUCTION Phenotype Agent...")
        prod_result = await self.run_agent(
            self.prod_phenotype,
            "validate_feasibility",
            test_context,
            "production",
            "PhenotypeValidationAgent"
        )
        print(f"  ✓ Completed in {prod_result.execution_time:.2f}s")
        if prod_result.success:
            print(f"  Output keys: {prod_result.output_keys}")
        else:
            print(f"  ✗ Error: {prod_result.error}")

        # Run experimental agent
        print("\n[2/2] Running EXPERIMENTAL LangChain Phenotype Agent...")
        exp_result = await self.run_agent(
            self.exp_phenotype,
            "validate_feasibility",
            test_context,
            "experimental",
            "LangChainPhenotypeAgent"
        )
        print(f"  ✓ Completed in {exp_result.execution_time:.2f}s")
        if exp_result.success:
            print(f"  Output keys: {exp_result.output_keys}")
        else:
            print(f"  ✗ Error: {exp_result.error}")

        # Compare
        self._print_comparison(prod_result, exp_result)

        return {
            "production": prod_result,
            "experimental": exp_result
        }

    async def compare_calendar_agents(
        self,
        test_context: Dict[str, Any]
    ) -> Dict[str, AgentComparisonResult]:
        """Compare Calendar agents"""
        print("\n" + "="*80)
        print("COMPARING CALENDAR AGENTS")
        print("="*80)

        # Run production agent
        print("\n[1/2] Running PRODUCTION Calendar Agent...")
        prod_result = await self.run_agent(
            self.prod_calendar,
            "schedule_kickoff_meeting",
            test_context,
            "production",
            "CalendarAgent"
        )
        print(f"  ✓ Completed in {prod_result.execution_time:.2f}s")
        if prod_result.success:
            print(f"  Output keys: {prod_result.output_keys}")
        else:
            print(f"  ✗ Error: {prod_result.error}")

        # Run experimental agent
        print("\n[2/2] Running EXPERIMENTAL LangChain Calendar Agent...")
        exp_result = await self.run_agent(
            self.exp_calendar,
            "schedule_kickoff_meeting",
            test_context,
            "experimental",
            "LangChainCalendarAgent"
        )
        print(f"  ✓ Completed in {exp_result.execution_time:.2f}s")
        if exp_result.success:
            print(f"  Output keys: {exp_result.output_keys}")
        else:
            print(f"  ✗ Error: {exp_result.error}")

        # Compare
        self._print_comparison(prod_result, exp_result)

        return {
            "production": prod_result,
            "experimental": exp_result
        }

    def _print_comparison(self, prod: AgentComparisonResult, exp: AgentComparisonResult):
        """Print comparison summary"""
        print("\n" + "-"*80)
        print("COMPARISON SUMMARY")
        print("-"*80)

        # Success rate
        print(f"\nSuccess Rate:")
        print(f"  Production:   {'✓' if prod.success else '✗'}")
        print(f"  Experimental: {'✓' if exp.success else '✗'}")

        # Execution time
        if prod.success and exp.success:
            speedup = prod.execution_time / exp.execution_time if exp.execution_time > 0 else 0
            print(f"\nExecution Time:")
            print(f"  Production:   {prod.execution_time:.2f}s")
            print(f"  Experimental: {exp.execution_time:.2f}s")
            if speedup > 1.0:
                print(f"  → Experimental is {speedup:.2f}x FASTER")
            else:
                print(f"  → Production is {1/speedup:.2f}x faster")

            # Output structure
            print(f"\nOutput Structure:")
            prod_keys = set(prod.output_keys)
            exp_keys = set(exp.output_keys)
            common_keys = prod_keys & exp_keys
            prod_only = prod_keys - exp_keys
            exp_only = exp_keys - prod_keys

            print(f"  Common keys: {sorted(common_keys)}")
            if prod_only:
                print(f"  Production only: {sorted(prod_only)}")
            if exp_only:
                print(f"  Experimental only: {sorted(exp_only)}")

        print("-"*80)


# ============================================================================
# TEST FIXTURES
# ============================================================================

@pytest.fixture
def harness():
    """Create test harness"""
    return AgentComparisonHarness()


@pytest.fixture
def requirements_test_context():
    """Test context for Requirements agents"""
    return {
        "request_id": "TEST-REQ-001",
        "researcher_request": "I need data for heart failure patients with diabetes admitted in 2024",
        "researcher_info": {
            "name": "Dr. Test Researcher",
            "email": "test@hospital.edu",
            "irb_number": "IRB-TEST-001"
        },
        "conversation_history": [
            {
                "role": "user",
                "content": "I need data for heart failure patients with diabetes admitted in 2024"
            }
        ],
        "current_requirements": {}
    }


@pytest.fixture
def phenotype_test_context():
    """Test context for Phenotype agents"""
    return {
        "request_id": "TEST-REQ-002",
        "requirements": {
            "inclusion_criteria": [
                {"type": "condition", "code": "I50", "description": "Heart failure"},
                {"type": "condition", "code": "E11", "description": "Type 2 diabetes"}
            ],
            "time_period": {
                "start": "2024-01-01",
                "end": "2024-12-31"
            }
        }
    }


@pytest.fixture
def calendar_test_context():
    """Test context for Calendar agents"""
    return {
        "request_id": "TEST-REQ-003",
        "requirements": {
            "study_title": "Heart Failure and Diabetes Study",
            "principal_investigator": "Dr. Test Researcher"
        },
        "feasibility_report": {
            "estimated_cohort": 250,
            "feasibility_score": 0.85
        }
    }


# ============================================================================
# TESTS
# ============================================================================

@pytest.mark.asyncio
async def test_requirements_agents_comparison(harness, requirements_test_context):
    """Test Requirements agents side-by-side"""
    results = await harness.compare_requirements_agents(requirements_test_context)

    # Both should succeed
    assert results["production"].success, f"Production agent failed: {results['production'].error}"
    assert results["experimental"].success, f"Experimental agent failed: {results['experimental'].error}"

    # Both should return dict
    assert isinstance(results["production"].result, dict)
    assert isinstance(results["experimental"].result, dict)

    # Performance check (experimental should be within 2x of production)
    # Note: We're lenient here because experimental has @traceable overhead
    assert results["experimental"].execution_time < results["production"].execution_time * 2.0, \
        "Experimental agent is more than 2x slower than production"


@pytest.mark.asyncio
async def test_phenotype_agents_comparison(harness, phenotype_test_context):
    """Test Phenotype agents side-by-side"""
    results = await harness.compare_phenotype_agents(phenotype_test_context)

    # Both should succeed
    assert results["production"].success, f"Production agent failed: {results['production'].error}"
    assert results["experimental"].success, f"Experimental agent failed: {results['experimental'].error}"

    # Both should return dict
    assert isinstance(results["production"].result, dict)
    assert isinstance(results["experimental"].result, dict)

    # Both should have SQL query
    assert "sql_query" in results["production"].result or "approval_data" in results["production"].result
    assert "sql_query" in results["experimental"].result or "approval_data" in results["experimental"].result


@pytest.mark.asyncio
async def test_calendar_agents_comparison(harness, calendar_test_context):
    """Test Calendar agents side-by-side"""
    results = await harness.compare_calendar_agents(calendar_test_context)

    # Both should succeed
    assert results["production"].success, f"Production agent failed: {results['production'].error}"
    assert results["experimental"].success, f"Experimental agent failed: {results['experimental'].error}"

    # Both should return dict
    assert isinstance(results["production"].result, dict)
    assert isinstance(results["experimental"].result, dict)

    # Both should indicate meeting scheduled
    assert results["production"].result.get("meeting_scheduled") == True
    assert results["experimental"].result.get("meeting_scheduled") == True


@pytest.mark.asyncio
async def test_full_comparison_suite(harness, requirements_test_context, phenotype_test_context, calendar_test_context):
    """Run full suite of comparisons"""
    print("\n" + "="*80)
    print("FULL AGENT COMPARISON SUITE")
    print("="*80)

    all_results = {}

    # Requirements
    all_results["requirements"] = await harness.compare_requirements_agents(requirements_test_context)

    # Phenotype
    all_results["phenotype"] = await harness.compare_phenotype_agents(phenotype_test_context)

    # Calendar
    all_results["calendar"] = await harness.compare_calendar_agents(calendar_test_context)

    # Final summary
    print("\n" + "="*80)
    print("FINAL SUMMARY")
    print("="*80)

    for agent_name, results in all_results.items():
        prod = results["production"]
        exp = results["experimental"]

        print(f"\n{agent_name.upper()} Agent:")
        print(f"  Production:   {'✓' if prod.success else '✗'} ({prod.execution_time:.2f}s)")
        print(f"  Experimental: {'✓' if exp.success else '✗'} ({exp.execution_time:.2f}s)")

        if prod.success and exp.success:
            speedup = prod.execution_time / exp.execution_time if exp.execution_time > 0 else 0
            if speedup > 1.0:
                print(f"  Performance:  Experimental {speedup:.2f}x faster")
            else:
                print(f"  Performance:  Production {1/speedup:.2f}x faster")

    print("\n" + "="*80)

    # Write results to file
    results_file = "test_agent_comparison_results.json"
    with open(results_file, "w") as f:
        json.dump({
            agent_name: {
                "production": results["production"].to_dict(),
                "experimental": results["experimental"].to_dict()
            }
            for agent_name, results in all_results.items()
        }, f, indent=2)

    print(f"\nResults written to: {results_file}")


if __name__ == "__main__":
    # Run tests directly
    pytest.main([__file__, "-v", "-s"])
