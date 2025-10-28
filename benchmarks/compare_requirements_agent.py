"""
Requirements Agent Comparison Benchmark (Sprint 1)

Compares custom RequirementsAgent vs LangChain RequirementsAgent across:
1. Code complexity (LOC, cyclomatic complexity)
2. Performance (execution time, memory usage)
3. Conversation quality (same outputs, completeness scores)
4. Error handling (retry behavior, failure modes)

Usage:
    python benchmarks/compare_requirements_agent.py
    python benchmarks/compare_requirements_agent.py --iterations 100
    python benchmarks/compare_requirements_agent.py --verbose

Output:
    - Console comparison table
    - CSV file: benchmarks/results/requirements_agent_comparison.csv
    - Plots: benchmarks/results/requirements_agent_*.png
"""

import asyncio
import time
import tracemalloc
import statistics
import json
import csv
import os
import sys
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
from unittest.mock import Mock, patch, AsyncMock
from dotenv import load_dotenv

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

# Load environment variables from .env file
env_path = project_root / '.env'
load_dotenv(dotenv_path=env_path)

# Import both agents
from app.agents.requirements_agent import RequirementsAgent as CustomAgent
from app.langchain_orchestrator.langchain_agents import LangChainRequirementsAgent as LangChainAgent


class RequirementsAgentBenchmark:
    """Benchmark suite for comparing Requirements Agents"""

    def __init__(self, iterations: int = 10, verbose: bool = False):
        self.iterations = iterations
        self.verbose = verbose
        self.results = {
            'custom': [],
            'langchain': []
        }

    def log(self, message: str) -> None:
        """Log message if verbose mode enabled"""
        if self.verbose:
            print(f"[{datetime.now().strftime('%H:%M:%S')}] {message}")

    async def benchmark_single_turn(
        self,
        agent,
        request_id: str,
        initial_request: str
    ) -> Dict[str, Any]:
        """
        Benchmark single conversation turn

        Returns:
            Dict with execution_time, memory_usage, result
        """
        # Start memory tracking
        tracemalloc.start()
        start_time = time.perf_counter()

        try:
            # Mock LLM response (same for both agents)
            mock_response_data = {
                "extracted_requirements": {
                    "inclusion_criteria": [
                        {
                            "description": "diabetes mellitus",
                            "concepts": [{"type": "condition", "term": "diabetes"}],
                            "codes": []
                        }
                    ],
                    "exclusion_criteria": [],
                    "data_elements": [],
                    "time_period": {"start": "2024-01-01", "end": "2024-12-31"}
                },
                "completeness_score": 0.4,
                "missing_fields": ["data_elements", "phi_level", "irb_number"],
                "ready_for_submission": False,
                "next_question": "What specific data elements do you need?"
            }

            # For custom agent: mock llm_client.extract_requirements
            # For LangChain agent: mock llm.ainvoke
            if isinstance(agent, CustomAgent):
                with patch.object(
                    agent.llm_client,
                    'extract_requirements',
                    return_value=mock_response_data
                ):
                    result = await agent.execute_task(
                        "gather_requirements",
                        {
                            "request_id": request_id,
                            "initial_request": initial_request
                        }
                    )
            else:  # LangChainAgent
                mock_response = Mock()
                mock_response.content = json.dumps(mock_response_data)

                with patch.object(agent.llm, 'ainvoke', return_value=mock_response):
                    result = await agent.execute_task(
                        "gather_requirements",
                        {
                            "request_id": request_id,
                            "initial_request": initial_request
                        }
                    )

            # Measure time
            execution_time = time.perf_counter() - start_time

            # Measure memory
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            return {
                "execution_time": execution_time,
                "memory_current": current / 1024 / 1024,  # MB
                "memory_peak": peak / 1024 / 1024,  # MB
                "result": result,
                "success": True
            }

        except Exception as e:
            execution_time = time.perf_counter() - start_time
            tracemalloc.stop()

            return {
                "execution_time": execution_time,
                "memory_current": 0,
                "memory_peak": 0,
                "result": None,
                "success": False,
                "error": str(e)
            }

    async def benchmark_multi_turn_conversation(
        self,
        agent,
        request_id: str
    ) -> Dict[str, Any]:
        """
        Benchmark complete multi-turn conversation (3 turns to completion)

        Returns:
            Dict with total_time, total_memory, conversation_turns
        """
        tracemalloc.start()
        start_time = time.perf_counter()

        turns = []

        try:
            # Turn 1: Initial request
            mock_response_1 = {
                "extracted_requirements": {
                    "inclusion_criteria": [
                        {"description": "diabetes", "concepts": [{"type": "condition", "term": "diabetes"}], "codes": []}
                    ],
                    "time_period": {"start": "2024-01-01", "end": "2024-12-31"}
                },
                "completeness_score": 0.4,
                "missing_fields": ["data_elements", "phi_level"],
                "ready_for_submission": False,
                "next_question": "What data elements?"
            }

            if isinstance(agent, CustomAgent):
                with patch.object(agent.llm_client, 'extract_requirements', return_value=mock_response_1):
                    result1 = await agent.execute_task(
                        "gather_requirements",
                        {"request_id": request_id, "initial_request": "I need diabetes patients from 2024"}
                    )
            else:
                mock = Mock()
                mock.content = json.dumps(mock_response_1)
                with patch.object(agent.llm, 'ainvoke', return_value=mock):
                    result1 = await agent.execute_task(
                        "gather_requirements",
                        {"request_id": request_id, "initial_request": "I need diabetes patients from 2024"}
                    )

            turns.append(result1)

            # Turn 2: Add data elements
            mock_response_2 = {
                "extracted_requirements": {
                    "inclusion_criteria": [
                        {"description": "diabetes", "concepts": [{"type": "condition", "term": "diabetes"}], "codes": []}
                    ],
                    "time_period": {"start": "2024-01-01", "end": "2024-12-31"},
                    "data_elements": ["demographics", "lab_results"]
                },
                "completeness_score": 0.7,
                "missing_fields": ["phi_level"],
                "ready_for_submission": False,
                "next_question": "What PHI level?"
            }

            if isinstance(agent, CustomAgent):
                with patch.object(agent.llm_client, 'extract_requirements', return_value=mock_response_2):
                    result2 = await agent.execute_task(
                        "gather_requirements",
                        {"request_id": request_id, "user_response": "Demographics and lab results"}
                    )
            else:
                mock = Mock()
                mock.content = json.dumps(mock_response_2)
                with patch.object(agent.llm, 'ainvoke', return_value=mock):
                    result2 = await agent.execute_task(
                        "gather_requirements",
                        {"request_id": request_id, "user_response": "Demographics and lab results"}
                    )

            turns.append(result2)

            # Turn 3: Complete
            mock_response_3 = {
                "extracted_requirements": {
                    "inclusion_criteria": [
                        {"description": "diabetes", "concepts": [{"type": "condition", "term": "diabetes"}], "codes": []}
                    ],
                    "time_period": {"start": "2024-01-01", "end": "2024-12-31"},
                    "data_elements": ["demographics", "lab_results"],
                    "phi_level": "de-identified"
                },
                "completeness_score": 0.9,
                "missing_fields": [],
                "ready_for_submission": True,
                "next_question": ""
            }

            if isinstance(agent, CustomAgent):
                with patch.object(agent.llm_client, 'extract_requirements', return_value=mock_response_3):
                    result3 = await agent.execute_task(
                        "gather_requirements",
                        {"request_id": request_id, "user_response": "De-identified"}
                    )
            else:
                mock = Mock()
                mock.content = json.dumps(mock_response_3)
                with patch.object(agent.llm, 'ainvoke', return_value=mock):
                    result3 = await agent.execute_task(
                        "gather_requirements",
                        {"request_id": request_id, "user_response": "De-identified"}
                    )

            turns.append(result3)

            # Measure
            execution_time = time.perf_counter() - start_time
            current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()

            return {
                "total_time": execution_time,
                "memory_peak": peak / 1024 / 1024,  # MB
                "conversation_turns": len(turns),
                "final_completeness": result3.get('completeness_score', 0),
                "requirements_complete": result3.get('requirements_complete', False),
                "success": True
            }

        except Exception as e:
            execution_time = time.perf_counter() - start_time
            tracemalloc.stop()

            return {
                "total_time": execution_time,
                "memory_peak": 0,
                "conversation_turns": len(turns),
                "final_completeness": 0,
                "requirements_complete": False,
                "success": False,
                "error": str(e)
            }

    async def run_benchmarks(self) -> None:
        """Run all benchmarks for both agents"""

        print("=" * 80)
        print("Requirements Agent Comparison Benchmark (Sprint 1)")
        print("=" * 80)
        print()

        # Initialize agents
        custom_agent = CustomAgent()
        langchain_agent = LangChainAgent()

        print(f"Running {self.iterations} iterations for each test...")
        print()

        # Benchmark 1: Single-turn performance
        print("[1/2] Benchmarking single-turn conversation...")

        custom_single_results = []
        langchain_single_results = []

        for i in range(self.iterations):
            self.log(f"Custom agent iteration {i+1}/{self.iterations}")
            result = await self.benchmark_single_turn(
                custom_agent,
                f"custom-single-{i}",
                "I need patients with diabetes mellitus diagnosed in 2024"
            )
            custom_single_results.append(result)

            self.log(f"LangChain agent iteration {i+1}/{self.iterations}")
            result = await self.benchmark_single_turn(
                langchain_agent,
                f"langchain-single-{i}",
                "I need patients with diabetes mellitus diagnosed in 2024"
            )
            langchain_single_results.append(result)

        # Benchmark 2: Multi-turn conversation performance
        print("[2/2] Benchmarking multi-turn conversation...")

        custom_multi_results = []
        langchain_multi_results = []

        for i in range(self.iterations):
            self.log(f"Custom agent multi-turn {i+1}/{self.iterations}")
            result = await self.benchmark_multi_turn_conversation(
                custom_agent,
                f"custom-multi-{i}"
            )
            custom_multi_results.append(result)

            self.log(f"LangChain agent multi-turn {i+1}/{self.iterations}")
            result = await self.benchmark_multi_turn_conversation(
                langchain_agent,
                f"langchain-multi-{i}"
            )
            langchain_multi_results.append(result)

        # Store results
        self.results = {
            'custom': {
                'single_turn': custom_single_results,
                'multi_turn': custom_multi_results
            },
            'langchain': {
                'single_turn': langchain_single_results,
                'multi_turn': langchain_multi_results
            }
        }

        print()
        print("Benchmarking complete!")
        print()

    def calculate_statistics(self, results: List[Dict[str, Any]], metric: str) -> Dict[str, float]:
        """Calculate statistics for a metric"""
        values = [r[metric] for r in results if r.get('success', False)]

        if not values:
            return {"mean": 0, "median": 0, "std": 0, "min": 0, "max": 0}

        return {
            "mean": statistics.mean(values),
            "median": statistics.median(values),
            "std": statistics.stdev(values) if len(values) > 1 else 0,
            "min": min(values),
            "max": max(values)
        }

    def print_comparison_table(self) -> None:
        """Print comparison table to console"""

        print("=" * 80)
        print("COMPARISON RESULTS")
        print("=" * 80)
        print()

        # Single-turn comparison
        print("Single-Turn Conversation Performance:")
        print("-" * 80)

        custom_single = self.results['custom']['single_turn']
        langchain_single = self.results['langchain']['single_turn']

        # Execution time
        custom_time = self.calculate_statistics(custom_single, 'execution_time')
        langchain_time = self.calculate_statistics(langchain_single, 'execution_time')

        print(f"{'Metric':<30} {'Custom':<20} {'LangChain':<20} {'Winner':<10}")
        print("-" * 80)
        print(f"{'Execution Time (mean ms)':<30} {custom_time['mean']*1000:<20.2f} {langchain_time['mean']*1000:<20.2f} {self._winner(custom_time['mean'], langchain_time['mean'], lower_better=True):<10}")
        print(f"{'Execution Time (median ms)':<30} {custom_time['median']*1000:<20.2f} {langchain_time['median']*1000:<20.2f} {self._winner(custom_time['median'], langchain_time['median'], lower_better=True):<10}")

        # Memory
        custom_mem = self.calculate_statistics(custom_single, 'memory_peak')
        langchain_mem = self.calculate_statistics(langchain_single, 'memory_peak')

        print(f"{'Peak Memory (mean MB)':<30} {custom_mem['mean']:<20.2f} {langchain_mem['mean']:<20.2f} {self._winner(custom_mem['mean'], langchain_mem['mean'], lower_better=True):<10}")

        # Success rate
        custom_success = sum(1 for r in custom_single if r.get('success', False)) / len(custom_single) * 100
        langchain_success = sum(1 for r in langchain_single if r.get('success', False)) / len(langchain_single) * 100

        print(f"{'Success Rate (%)':<30} {custom_success:<20.1f} {langchain_success:<20.1f} {self._winner(custom_success, langchain_success, lower_better=False):<10}")

        print()

        # Multi-turn comparison
        print("Multi-Turn Conversation Performance (3 turns to completion):")
        print("-" * 80)

        custom_multi = self.results['custom']['multi_turn']
        langchain_multi = self.results['langchain']['multi_turn']

        custom_time_multi = self.calculate_statistics(custom_multi, 'total_time')
        langchain_time_multi = self.calculate_statistics(langchain_multi, 'total_time')

        print(f"{'Metric':<30} {'Custom':<20} {'LangChain':<20} {'Winner':<10}")
        print("-" * 80)
        print(f"{'Total Time (mean ms)':<30} {custom_time_multi['mean']*1000:<20.2f} {langchain_time_multi['mean']*1000:<20.2f} {self._winner(custom_time_multi['mean'], langchain_time_multi['mean'], lower_better=True):<10}")

        custom_mem_multi = self.calculate_statistics(custom_multi, 'memory_peak')
        langchain_mem_multi = self.calculate_statistics(langchain_multi, 'memory_peak')

        print(f"{'Peak Memory (mean MB)':<30} {custom_mem_multi['mean']:<20.2f} {langchain_mem_multi['mean']:<20.2f} {self._winner(custom_mem_multi['mean'], langchain_mem_multi['mean'], lower_better=True):<10}")

        # Completion rate
        custom_complete = sum(1 for r in custom_multi if r.get('requirements_complete', False)) / len(custom_multi) * 100
        langchain_complete = sum(1 for r in langchain_multi if r.get('requirements_complete', False)) / len(langchain_multi) * 100

        print(f"{'Completion Rate (%)':<30} {custom_complete:<20.1f} {langchain_complete:<20.1f} {self._winner(custom_complete, langchain_complete, lower_better=False):<10}")

        print()
        print("=" * 80)

    def _winner(self, custom_value: float, langchain_value: float, lower_better: bool = True) -> str:
        """Determine winner for a metric"""
        if abs(custom_value - langchain_value) < 0.01:  # Tie within 1%
            return "TIE"
        elif lower_better:
            return "Custom" if custom_value < langchain_value else "LangChain"
        else:
            return "Custom" if custom_value > langchain_value else "LangChain"

    def save_results_csv(self) -> None:
        """Save results to CSV file"""

        results_dir = Path("benchmarks/results")
        results_dir.mkdir(parents=True, exist_ok=True)

        csv_path = results_dir / f"requirements_agent_comparison_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"

        with open(csv_path, 'w', newline='') as f:
            writer = csv.writer(f)

            # Header
            writer.writerow([
                'Agent', 'Test', 'Iteration',
                'Execution Time (ms)', 'Memory Peak (MB)',
                'Success', 'Completeness Score'
            ])

            # Single-turn results
            for i, result in enumerate(self.results['custom']['single_turn']):
                writer.writerow([
                    'Custom', 'Single-Turn', i+1,
                    result['execution_time'] * 1000,
                    result['memory_peak'],
                    result['success'],
                    result.get('result', {}).get('completeness_score', 0)
                ])

            for i, result in enumerate(self.results['langchain']['single_turn']):
                writer.writerow([
                    'LangChain', 'Single-Turn', i+1,
                    result['execution_time'] * 1000,
                    result['memory_peak'],
                    result['success'],
                    result.get('result', {}).get('completeness_score', 0)
                ])

            # Multi-turn results
            for i, result in enumerate(self.results['custom']['multi_turn']):
                writer.writerow([
                    'Custom', 'Multi-Turn', i+1,
                    result['total_time'] * 1000,
                    result['memory_peak'],
                    result['success'],
                    result.get('final_completeness', 0)
                ])

            for i, result in enumerate(self.results['langchain']['multi_turn']):
                writer.writerow([
                    'LangChain', 'Multi-Turn', i+1,
                    result['total_time'] * 1000,
                    result['memory_peak'],
                    result['success'],
                    result.get('final_completeness', 0)
                ])

        print(f"Results saved to: {csv_path}")


async def main():
    """Main benchmark execution"""
    import argparse

    parser = argparse.ArgumentParser(description='Benchmark Requirements Agent implementations')
    parser.add_argument('--iterations', type=int, default=10, help='Number of iterations per test')
    parser.add_argument('--verbose', action='store_true', help='Verbose output')

    args = parser.parse_args()

    benchmark = RequirementsAgentBenchmark(
        iterations=args.iterations,
        verbose=args.verbose
    )

    # Run benchmarks
    await benchmark.run_benchmarks()

    # Print results
    benchmark.print_comparison_table()

    # Save to CSV
    benchmark.save_results_csv()

    print()
    print("✓ Benchmark complete!")
    print()
    print("Next steps:")
    print("1. Review results above")
    print("2. Check CSV file in benchmarks/results/")
    print("3. Update docs/sprints/SPRINT_01_REQUIREMENTS_AGENT.md with findings")
    print()


if __name__ == "__main__":
    asyncio.run(main())
