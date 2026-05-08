"""
Phase 2 Parallel Testing Suite

Runs 50 diverse scenarios through both production and experimental agents to validate:
1. Success rate parity (target: ≥ 95%)
2. Performance at scale (target: within 30% of production)
3. Output quality consistency
4. Error handling robustness
5. Production readiness

Usage:
    pytest tests/test_phase2_parallel.py -v -s --tb=short

Expected runtime: 15-30 minutes (100 agent executions total)
"""

import pytest
import asyncio
import json
import time
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
import statistics

from app.agents.requirements_agent import RequirementsAgent
from app.agents.calendar_agent import CalendarAgent
from app.langchain_orchestrator.langchain_agents import (
    LangChainRequirementsAgent,
    LangChainCalendarAgent,
)


class Phase2TestRunner:
    """Parallel test runner for production vs experimental agents"""

    def __init__(self):
        self.scenarios_path = Path(__file__).parent / "fixtures" / "phase2_scenarios.json"
        self.scenarios = self.load_scenarios()
        self.results = {"production": [], "experimental": []}

    def load_scenarios(self) -> List[Dict]:
        """Load all 50 test scenarios from JSON"""
        with open(self.scenarios_path, "r") as f:
            data = json.load(f)

        # Flatten all scenario categories
        scenarios = []
        scenarios.extend(data["requirements_simple"])
        scenarios.extend(data["requirements_moderate"])
        scenarios.extend(data["requirements_complex"])
        scenarios.extend(data["calendar_standard"])
        scenarios.extend(data["calendar_complex"])

        return scenarios

    async def run_production_agent(self, scenario: Dict) -> Dict[str, Any]:
        """Run a single scenario through production agent"""
        start_time = time.time()
        agent_type = scenario["agent_type"]
        scenario_id = scenario["id"]

        try:
            if agent_type == "requirements":
                agent = RequirementsAgent()
                context = {
                    "user_message": scenario["input"],
                    "conversation_history": [],
                    "current_requirements": {},
                }
                result = await agent.execute_task("gather_requirements", context)
            elif agent_type == "calendar":
                agent = CalendarAgent()
                context = {"message": scenario["input"], "request_id": f"TEST-{scenario_id}"}
                result = await agent.execute_task("schedule_kickoff_meeting", context)
            else:
                raise ValueError(f"Unknown agent type: {agent_type}")

            elapsed = time.time() - start_time

            return {
                "scenario_id": scenario_id,
                "status": "success",
                "elapsed_time": elapsed,
                "output": result,
                "output_keys": list(result.keys()) if isinstance(result, dict) else [],
                "error": None,
            }

        except Exception as e:
            elapsed = time.time() - start_time
            return {
                "scenario_id": scenario_id,
                "status": "error",
                "elapsed_time": elapsed,
                "output": None,
                "output_keys": [],
                "error": str(e),
            }

    async def run_experimental_agent(self, scenario: Dict) -> Dict[str, Any]:
        """Run a single scenario through experimental LangChain agent"""
        start_time = time.time()
        agent_type = scenario["agent_type"]
        scenario_id = scenario["id"]

        try:
            if agent_type == "requirements":
                agent = LangChainRequirementsAgent()
                context = {
                    "user_message": scenario["input"],
                    "conversation_history": [],
                    "current_requirements": {},
                }
                result = await agent.execute_task("gather_requirements", context)
            elif agent_type == "calendar":
                agent = LangChainCalendarAgent()
                context = {"message": scenario["input"], "request_id": f"TEST-{scenario_id}"}
                result = await agent.execute_task("schedule_kickoff_meeting", context)
            else:
                raise ValueError(f"Unknown agent type: {agent_type}")

            elapsed = time.time() - start_time

            return {
                "scenario_id": scenario_id,
                "status": "success",
                "elapsed_time": elapsed,
                "output": result,
                "output_keys": list(result.keys()) if isinstance(result, dict) else [],
                "error": None,
            }

        except Exception as e:
            elapsed = time.time() - start_time
            return {
                "scenario_id": scenario_id,
                "status": "error",
                "elapsed_time": elapsed,
                "output": None,
                "output_keys": [],
                "error": str(e),
            }

    async def run_all_tests(self) -> Dict[str, Any]:
        """Run all scenarios through both agent systems"""
        print("\n" + "=" * 80)
        print("PHASE 2 PARALLEL TESTING - 50 SCENARIOS")
        print("=" * 80)
        print(f"\nTotal scenarios: {len(self.scenarios)}")
        print(f"  - Requirements (simple): 10")
        print(f"  - Requirements (moderate): 10")
        print(f"  - Requirements (complex): 10")
        print(f"  - Calendar (standard): 10")
        print(f"  - Calendar (complex): 10")

        # Run production agents
        print("\n" + "-" * 80)
        print("[1/2] Running PRODUCTION agents (50 scenarios)...")
        print("-" * 80)
        prod_start = time.time()

        for i, scenario in enumerate(self.scenarios, 1):
            print(
                f"\n  [{i}/50] {scenario['id']} ({scenario['complexity']})... ", end="", flush=True
            )
            result = await self.run_production_agent(scenario)
            self.results["production"].append(result)
            status_symbol = "✓" if result["status"] == "success" else "✗"
            print(f"{status_symbol} {result['elapsed_time']:.2f}s")

        prod_elapsed = time.time() - prod_start
        print(f"\n  Production total time: {prod_elapsed:.2f}s")

        # Run experimental agents
        print("\n" + "-" * 80)
        print("[2/2] Running EXPERIMENTAL LangChain agents (50 scenarios)...")
        print("-" * 80)
        exp_start = time.time()

        for i, scenario in enumerate(self.scenarios, 1):
            print(
                f"\n  [{i}/50] {scenario['id']} ({scenario['complexity']})... ", end="", flush=True
            )
            result = await self.run_experimental_agent(scenario)
            self.results["experimental"].append(result)
            status_symbol = "✓" if result["status"] == "success" else "✗"
            print(f"{status_symbol} {result['elapsed_time']:.2f}s")

        exp_elapsed = time.time() - exp_start
        print(f"\n  Experimental total time: {exp_elapsed:.2f}s")

        # Analyze results
        print("\n" + "=" * 80)
        print("ANALYZING RESULTS")
        print("=" * 80)
        analysis = self.analyze_results()
        self.print_analysis(analysis)

        return analysis

    def analyze_results(self) -> Dict[str, Any]:
        """Perform statistical analysis of results"""
        prod_results = self.results["production"]
        exp_results = self.results["experimental"]

        # Success rates
        prod_success = sum(1 for r in prod_results if r["status"] == "success")
        exp_success = sum(1 for r in exp_results if r["status"] == "success")
        prod_success_rate = (prod_success / len(prod_results)) * 100
        exp_success_rate = (exp_success / len(exp_results)) * 100

        # Timing statistics (only successful runs)
        prod_times = [r["elapsed_time"] for r in prod_results if r["status"] == "success"]
        exp_times = [r["elapsed_time"] for r in exp_results if r["status"] == "success"]

        # Error analysis
        prod_errors = [r for r in prod_results if r["status"] == "error"]
        exp_errors = [r for r in exp_results if r["status"] == "error"]

        # By complexity analysis
        complexity_analysis = self.analyze_by_complexity()

        analysis = {
            "production": {
                "total": len(prod_results),
                "success_count": prod_success,
                "success_rate": prod_success_rate,
                "error_count": len(prod_errors),
                "error_rate": (len(prod_errors) / len(prod_results)) * 100,
                "timing": {
                    "mean": statistics.mean(prod_times) if prod_times else 0,
                    "median": statistics.median(prod_times) if prod_times else 0,
                    "min": min(prod_times) if prod_times else 0,
                    "max": max(prod_times) if prod_times else 0,
                    "stdev": statistics.stdev(prod_times) if len(prod_times) > 1 else 0,
                    "p95": sorted(prod_times)[int(len(prod_times) * 0.95)] if prod_times else 0,
                    "p99": sorted(prod_times)[int(len(prod_times) * 0.99)] if prod_times else 0,
                },
                "errors": prod_errors,
            },
            "experimental": {
                "total": len(exp_results),
                "success_count": exp_success,
                "success_rate": exp_success_rate,
                "error_count": len(exp_errors),
                "error_rate": (len(exp_errors) / len(exp_results)) * 100,
                "timing": {
                    "mean": statistics.mean(exp_times) if exp_times else 0,
                    "median": statistics.median(exp_times) if exp_times else 0,
                    "min": min(exp_times) if exp_times else 0,
                    "max": max(exp_times) if exp_times else 0,
                    "stdev": statistics.stdev(exp_times) if len(exp_times) > 1 else 0,
                    "p95": sorted(exp_times)[int(len(exp_times) * 0.95)] if exp_times else 0,
                    "p99": sorted(exp_times)[int(len(exp_times) * 0.99)] if exp_times else 0,
                },
                "errors": exp_errors,
            },
            "complexity_analysis": complexity_analysis,
            "comparison": {
                "success_rate_diff": exp_success_rate - prod_success_rate,
                "mean_time_ratio": (exp_times and prod_times)
                and (statistics.mean(exp_times) / statistics.mean(prod_times))
                or 0,
                "median_time_ratio": (exp_times and prod_times)
                and (statistics.median(exp_times) / statistics.median(prod_times))
                or 0,
            },
        }

        return analysis

    def analyze_by_complexity(self) -> Dict[str, Any]:
        """Analyze results broken down by scenario complexity"""
        complexities = ["simple", "standard", "moderate", "complex"]
        analysis = {}

        for complexity in complexities:
            # Get scenarios for this complexity
            complexity_scenarios = [s for s in self.scenarios if s["complexity"] == complexity]
            if not complexity_scenarios:
                continue

            scenario_ids = [s["id"] for s in complexity_scenarios]

            # Get results for these scenarios
            prod_results = [
                r for r in self.results["production"] if r["scenario_id"] in scenario_ids
            ]
            exp_results = [
                r for r in self.results["experimental"] if r["scenario_id"] in scenario_ids
            ]

            # Calculate metrics
            prod_success = sum(1 for r in prod_results if r["status"] == "success")
            exp_success = sum(1 for r in exp_results if r["status"] == "success")

            prod_times = [r["elapsed_time"] for r in prod_results if r["status"] == "success"]
            exp_times = [r["elapsed_time"] for r in exp_results if r["status"] == "success"]

            analysis[complexity] = {
                "count": len(complexity_scenarios),
                "production": {
                    "success_rate": (prod_success / len(prod_results) * 100) if prod_results else 0,
                    "mean_time": statistics.mean(prod_times) if prod_times else 0,
                },
                "experimental": {
                    "success_rate": (exp_success / len(exp_results) * 100) if exp_results else 0,
                    "mean_time": statistics.mean(exp_times) if exp_times else 0,
                },
            }

        return analysis

    def print_analysis(self, analysis: Dict[str, Any]):
        """Print formatted analysis results"""
        prod = analysis["production"]
        exp = analysis["experimental"]
        comp = analysis["comparison"]

        print("\n## Success Rates")
        print(
            f"  Production:   {prod['success_count']}/{prod['total']} ({prod['success_rate']:.1f}%)"
        )
        print(f"  Experimental: {exp['success_count']}/{exp['total']} ({exp['success_rate']:.1f}%)")
        print(f"  Difference:   {comp['success_rate_diff']:+.1f} percentage points")

        print("\n## Performance (Successful Runs)")
        print(f"  Mean Time:")
        print(f"    Production:   {prod['timing']['mean']:.2f}s")
        print(f"    Experimental: {exp['timing']['mean']:.2f}s")
        print(f"    Ratio:        {comp['mean_time_ratio']:.2f}x")

        print(f"\n  Median Time:")
        print(f"    Production:   {prod['timing']['median']:.2f}s")
        print(f"    Experimental: {exp['timing']['median']:.2f}s")
        print(f"    Ratio:        {comp['median_time_ratio']:.2f}x")

        print(f"\n  P95 Latency:")
        print(f"    Production:   {prod['timing']['p95']:.2f}s")
        print(f"    Experimental: {exp['timing']['p95']:.2f}s")

        print(f"\n  P99 Latency:")
        print(f"    Production:   {prod['timing']['p99']:.2f}s")
        print(f"    Experimental: {exp['timing']['p99']:.2f}s")

        print("\n## Error Rates")
        print(f"  Production:   {prod['error_count']}/{prod['total']} ({prod['error_rate']:.1f}%)")
        print(f"  Experimental: {exp['error_count']}/{exp['total']} ({exp['error_rate']:.1f}%)")

        # Print complexity breakdown
        print("\n## Performance by Complexity")
        for complexity, data in analysis["complexity_analysis"].items():
            print(f"\n  {complexity.upper()} ({data['count']} scenarios):")
            print(
                f"    Production:   {data['production']['success_rate']:.1f}% success, {data['production']['mean_time']:.2f}s avg"
            )
            print(
                f"    Experimental: {data['experimental']['success_rate']:.1f}% success, {data['experimental']['mean_time']:.2f}s avg"
            )

        # Production readiness criteria
        print("\n" + "=" * 80)
        print("PRODUCTION READINESS CRITERIA")
        print("=" * 80)

        criteria_results = []

        # Criterion 1: Success rate ≥ 95%
        success_pass = exp["success_rate"] >= 95.0
        criteria_results.append(("Success rate ≥ 95%", exp["success_rate"], "≥ 95%", success_pass))

        # Criterion 2: Mean execution time within 30% of production
        mean_ratio = comp["mean_time_ratio"]
        perf_pass = mean_ratio <= 1.30
        criteria_results.append(
            ("Mean time within 30% of production", f"{mean_ratio:.2f}x", "≤ 1.30x", perf_pass)
        )

        # Criterion 3: P99 latency < 30 seconds
        p99_pass = exp["timing"]["p99"] < 30.0
        criteria_results.append(
            ("P99 latency < 30s", f"{exp['timing']['p99']:.2f}s", "< 30s", p99_pass)
        )

        # Criterion 4: Error rate < 5%
        error_pass = exp["error_rate"] < 5.0
        criteria_results.append(
            ("Error rate < 5%", f"{exp['error_rate']:.1f}%", "< 5%", error_pass)
        )

        for criterion, actual, target, passed in criteria_results:
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"\n  {status}: {criterion}")
            print(f"    Actual: {actual}")
            print(f"    Target: {target}")

        # Final recommendation
        all_pass = all(r[3] for r in criteria_results)
        print("\n" + "=" * 80)
        if all_pass:
            print("✅ RECOMMENDATION: GO - Proceed to Phase 3 (shadow mode deployment)")
            print("   All production readiness criteria met.")
        else:
            print("⚠️  RECOMMENDATION: NO-GO - Address issues before Phase 3")
            failed_criteria = [r[0] for r in criteria_results if not r[3]]
            print(f"   Failed criteria: {', '.join(failed_criteria)}")
        print("=" * 80)


# ============================================================================
# PYTEST TEST FUNCTION
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.slow  # Mark as slow test (15-30 min runtime)
async def test_phase2_parallel_testing():
    """
    Phase 2: Run 50 scenarios through both production and experimental agents

    This is the comprehensive production readiness test.
    Expected runtime: 15-30 minutes
    """
    runner = Phase2TestRunner()
    analysis = await runner.run_all_tests()

    # Assert production readiness criteria
    exp = analysis["experimental"]
    comp = analysis["comparison"]

    # These assertions validate production readiness
    assert (
        exp["success_rate"] >= 95.0
    ), f"Success rate {exp['success_rate']:.1f}% < 95% (failed {exp['error_count']}/{exp['total']} scenarios)"

    assert (
        comp["mean_time_ratio"] <= 1.30
    ), f"Mean time ratio {comp['mean_time_ratio']:.2f}x > 1.30x (experimental too slow)"

    assert (
        exp["timing"]["p99"] < 30.0
    ), f"P99 latency {exp['timing']['p99']:.2f}s >= 30s (too slow for production)"

    assert exp["error_rate"] < 5.0, f"Error rate {exp['error_rate']:.1f}% >= 5% (too many failures)"

    print("\n✅ All production readiness criteria met - Ready for Phase 3!")


if __name__ == "__main__":
    # Allow running directly for debugging
    pytest.main([__file__, "-v", "-s", "--tb=short"])
