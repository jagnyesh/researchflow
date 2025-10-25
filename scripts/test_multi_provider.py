#!/usr/bin/env python3
"""
Multi-Provider LLM Testing Script

Comprehensive testing and comparison of different LLM providers
(Claude, OpenAI, Ollama) for ResearchFlow's Calendar and Delivery agents.

Measures:
- Response quality
- Response time
- Token usage
- Cost comparison
"""

import os
import sys
import time
import asyncio
import json
from datetime import datetime
from typing import Dict, List, Any

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
from app.utils.multi_llm_client import MultiLLMClient

# Load environment variables
load_dotenv()

# Color codes
GREEN = '\033[92m'
YELLOW = '\033[93m'
RED = '\033[91m'
BLUE = '\033[94m'
CYAN = '\033[96m'
RESET = '\033[0m'


def print_header(text):
    """Print section header"""
    print(f"\n{BLUE}{'=' * 80}{RESET}")
    print(f"{BLUE}{text.center(80)}{RESET}")
    print(f"{BLUE}{'=' * 80}{RESET}\n")


def print_test_case(number, total, description):
    """Print test case header"""
    print(f"\n{CYAN}[Test {number}/{total}] {description}{RESET}")
    print(f"{CYAN}{'-' * 80}{RESET}")


# Test prompts for different scenarios
TEST_CASES = {
    "calendar_agenda": {
        "description": "Generate meeting agenda for data request kickoff",
        "prompt": """Generate a professional meeting agenda for a clinical research data request kickoff meeting.

Study Details:
- Title: Diabetes Outcomes Study
- Principal Investigator: Dr. Jane Smith
- IRB Number: IRB-2024-12345

Cohort Information:
- Estimated Size: 450 patients
- Feasibility Score: 85%

Requested Data Elements:
- HbA1c lab results
- Medication history
- Clinical notes

Warnings/Issues to Discuss:
- Large cohort size may require extended timeline
- Some historical data may have gaps

Create a structured agenda with:
1. Study overview section
2. Cohort summary
3. Data elements discussion
4. Specific discussion points tailored to this request
5. Warnings/considerations section
6. Next steps

Keep it professional and concise.""",
        "max_tokens": 500,
        "expected_keywords": ["agenda", "study", "data", "cohort", "discussion"]
    },

    "delivery_notification": {
        "description": "Generate delivery notification email",
        "prompt": """Generate a professional email notification to a researcher that their data request is ready.

Recipient: Dr. Jane Smith
Request ID: REQ-2024-789
Cohort Size: 450 patients
Data Elements: HbA1c lab results, Medication history, Clinical notes
Download Location: https://secure.example.com/downloads/REQ-2024-789

The email should:
1. Be professional and friendly
2. Inform them their data is ready
3. Provide key statistics
4. Include download location
5. Remind them to review the data dictionary and QA report
6. Include appropriate sign-off

Keep it concise and professional.""",
        "max_tokens": 400,
        "expected_keywords": ["ready", "download", "data", "request", "review"]
    },

    "delivery_citation": {
        "description": "Generate citation information",
        "prompt": """Generate professional citation information for a clinical research data extract.

Study Information:
- Title: Diabetes Outcomes Study
- Principal Investigator: Dr. Jane Smith
- IRB Number: IRB-2024-12345
- Extraction Date: 2024-10-24

Create a professional citation block that includes:
1. Data source acknowledgment
2. Study details
3. Proper citation format
4. Any necessary disclaimers

Keep it concise and professional.""",
        "max_tokens": 300,
        "expected_keywords": ["data", "extracted", "study", "research", "citation"]
    }
}


# Pricing for cost calculation (per 1M tokens)
PRICING = {
    "claude": {"input": 3.00, "output": 15.00},
    "openai": {"input": 2.50, "output": 10.00},
    "ollama": {"input": 0.00, "output": 0.00}
}


async def test_provider(
    provider: str,
    model: str,
    test_case: Dict[str, Any],
    task_type: str
) -> Dict[str, Any]:
    """
    Test a specific provider with a test case

    Returns:
        Dict with test results including response, timing, tokens, etc.
    """
    # Configure environment for this provider
    original_provider = os.getenv('SECONDARY_LLM_PROVIDER')
    original_model = os.getenv('SECONDARY_LLM_MODEL')

    os.environ['SECONDARY_LLM_PROVIDER'] = provider
    if model:
        os.environ['SECONDARY_LLM_MODEL'] = model

    # Create client
    client = MultiLLMClient()

    # Run test
    start_time = time.time()
    error = None

    try:
        response = await client.complete(
            prompt=test_case["prompt"],
            task_type=task_type,
            max_tokens=test_case["max_tokens"],
            temperature=0.7
        )
        end_time = time.time()

        # Estimate tokens (rough estimate: 1 token ≈ 4 characters)
        input_tokens = len(test_case["prompt"]) // 4
        output_tokens = len(response) // 4

        # Calculate cost
        provider_key = provider if provider != "anthropic" else "claude"
        cost = (
            (input_tokens / 1_000_000) * PRICING[provider_key]["input"] +
            (output_tokens / 1_000_000) * PRICING[provider_key]["output"]
        )

        # Check for expected keywords
        keywords_found = sum(1 for kw in test_case["expected_keywords"] if kw.lower() in response.lower())
        quality_score = (keywords_found / len(test_case["expected_keywords"])) * 100

        result = {
            "success": True,
            "response": response,
            "response_time": end_time - start_time,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "cost": cost,
            "quality_score": quality_score,
            "error": None
        }

    except Exception as e:
        end_time = time.time()
        result = {
            "success": False,
            "response": None,
            "response_time": end_time - start_time,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost": 0.0,
            "quality_score": 0.0,
            "error": str(e)
        }

    # Restore original environment
    if original_provider:
        os.environ['SECONDARY_LLM_PROVIDER'] = original_provider
    if original_model:
        os.environ['SECONDARY_LLM_MODEL'] = original_model

    return result


async def run_all_tests():
    """Run comprehensive tests across all providers and test cases"""
    print_header("ResearchFlow Multi-Provider LLM Testing")

    print(f"{YELLOW}Testing Configuration:{RESET}")
    print(f"  Providers: Claude (Anthropic), OpenAI (GPT-4o), Ollama (llama3:8b)")
    print(f"  Test Cases: {len(TEST_CASES)}")
    print(f"  Total Tests: {len(TEST_CASES) * 3}\n")

    # Results storage
    results = {}

    # Test configurations
    test_configs = [
        {"provider": "anthropic", "model": None, "name": "Claude 3.5 Sonnet"},
        {"provider": "openai", "model": "gpt-4o", "name": "OpenAI GPT-4o"},
        {"provider": "ollama", "model": "llama3:8b", "name": "Ollama Llama 3 8B"}
    ]

    test_num = 0
    total_tests = len(TEST_CASES) * len(test_configs)

    for test_name, test_case in TEST_CASES.items():
        results[test_name] = {}

        for config in test_configs:
            test_num += 1
            print_test_case(test_num, total_tests, f"{test_case['description']} - {config['name']}")

            # Determine task type based on test case
            task_type = "calendar" if "calendar" in test_name else "delivery"

            result = await test_provider(
                provider=config["provider"],
                model=config["model"],
                test_case=test_case,
                task_type=task_type
            )

            results[test_name][config["name"]] = result

            # Print result summary
            if result["success"]:
                print(f"{GREEN}✓ Success{RESET}")
                print(f"  Response Time: {result['response_time']:.2f}s")
                print(f"  Tokens: {result['total_tokens']} ({result['input_tokens']} in, {result['output_tokens']} out)")
                print(f"  Cost: ${result['cost']:.6f}")
                print(f"  Quality Score: {result['quality_score']:.0f}%")
                print(f"\n  {CYAN}Response Preview:{RESET}")
                preview = result["response"][:200].replace('\n', ' ')
                print(f"  {preview}...\n")
            else:
                print(f"{RED}✗ Failed{RESET}")
                print(f"  Error: {result['error']}\n")

    return results


def generate_comparison_report(results: Dict[str, Any]):
    """Generate comparison report"""
    print_header("COMPARISON REPORT")

    # Calculate aggregates
    provider_stats = {}

    for test_name, test_results in results.items():
        for provider_name, result in test_results.items():
            if provider_name not in provider_stats:
                provider_stats[provider_name] = {
                    "total_tests": 0,
                    "successful_tests": 0,
                    "total_time": 0,
                    "total_tokens": 0,
                    "total_cost": 0,
                    "avg_quality": 0
                }

            stats = provider_stats[provider_name]
            stats["total_tests"] += 1

            if result["success"]:
                stats["successful_tests"] += 1
                stats["total_time"] += result["response_time"]
                stats["total_tokens"] += result["total_tokens"]
                stats["total_cost"] += result["cost"]
                stats["avg_quality"] += result["quality_score"]

    # Print provider comparison
    print(f"{CYAN}Provider Performance Summary:{RESET}\n")

    for provider_name, stats in provider_stats.items():
        print(f"\n{BLUE}{provider_name}:{RESET}")
        print(f"  Success Rate: {stats['successful_tests']}/{stats['total_tests']} ({stats['successful_tests']/stats['total_tests']*100:.0f}%)")

        if stats['successful_tests'] > 0:
            avg_time = stats['total_time'] / stats['successful_tests']
            avg_quality = stats['avg_quality'] / stats['successful_tests']

            print(f"  Avg Response Time: {avg_time:.2f}s")
            print(f"  Total Tokens: {stats['total_tokens']}")
            print(f"  Total Cost: ${stats['total_cost']:.6f}")
            print(f"  Avg Quality Score: {avg_quality:.0f}%")

    # Cost analysis
    print_header("COST ANALYSIS (100 requests/month)")

    for provider_name, stats in provider_stats.items():
        if stats['successful_tests'] > 0:
            avg_cost = stats['total_cost'] / stats['successful_tests']
            monthly_cost = avg_cost * 100 * (stats['total_tests'] / stats['successful_tests'])
            annual_cost = monthly_cost * 12

            print(f"\n{CYAN}{provider_name}:{RESET}")
            print(f"  Per Request: ${avg_cost:.6f}")
            print(f"  Monthly (100 requests): ${monthly_cost:.2f}")
            print(f"  Annual (1,200 requests): ${annual_cost:.2f}")

    # Savings comparison
    if len(provider_stats) > 1:
        costs = {name: (stats['total_cost'] / stats['successful_tests'] * 100 * 3) if stats['successful_tests'] > 0 else 0
                for name, stats in provider_stats.items()}

        baseline = max(costs.values())
        print(f"\n{YELLOW}Potential Savings (vs most expensive):{RESET}\n")

        for provider_name, monthly_cost in costs.items():
            if monthly_cost > 0:
                savings = baseline - monthly_cost
                savings_pct = (savings / baseline) * 100 if baseline > 0 else 0
                print(f"  {provider_name}: ${savings:.2f}/month ({savings_pct:.1f}% savings)")

    # Recommendations
    print_header("RECOMMENDATIONS")

    # Find best provider for each metric
    best_speed = min(provider_stats.items(), key=lambda x: x[1]['total_time'] / max(x[1]['successful_tests'], 1))
    best_cost = min(provider_stats.items(), key=lambda x: x[1]['total_cost'])
    best_quality = max(provider_stats.items(), key=lambda x: x[1]['avg_quality'])

    print(f"{GREEN}Best for Speed:{RESET} {best_speed[0]}")
    print(f"{GREEN}Best for Cost:{RESET} {best_cost[0]}")
    print(f"{GREEN}Best for Quality:{RESET} {best_quality[0]}\n")

    print(f"{YELLOW}Recommended Configuration:{RESET}")
    print(f"  • Use Claude for critical tasks (Requirements, Phenotype, QA)")
    print(f"  • Use {best_cost[0]} for non-critical tasks (Calendar, Delivery)")
    print(f"  • Enable fallback to Claude for reliability\n")


def save_results(results: Dict[str, Any]):
    """Save results to JSON file"""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"multi_provider_test_results_{timestamp}.json"

    with open(filename, 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"{GREEN}✓ Results saved to: {filename}{RESET}\n")


async def main():
    """Main test execution"""
    try:
        # Run tests
        results = await run_all_tests()

        # Generate report
        generate_comparison_report(results)

        # Save results
        save_results(results)

        print_header("TESTING COMPLETE")
        print(f"{GREEN}All tests completed successfully!{RESET}\n")

        return 0

    except Exception as e:
        print(f"\n{RED}Error during testing: {str(e)}{RESET}\n")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
