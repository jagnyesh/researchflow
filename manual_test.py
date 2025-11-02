#!/usr/bin/env python3
"""
Manual Agent Testing Script

Run this to test production vs experimental Requirements agents side-by-side.
View full workflow traces in LangSmith.
"""

import asyncio
import json
from datetime import datetime

# Import agents
from app.agents.requirements_agent import RequirementsAgent
from app.langchain_orchestrator.langchain_agents import LangChainRequirementsAgent


async def test_production_agent(user_message: str):
    """Test production Requirements agent"""
    print("\n" + "="*80)
    print("🏭 PRODUCTION AGENT")
    print("="*80)

    agent = RequirementsAgent()

    context = {
        "user_message": user_message,
        "conversation_history": [],
        "current_requirements": {}
    }

    print(f"\n📝 Input: {user_message}")
    print("\n⏳ Processing...")

    start = datetime.now()
    result = await agent.execute_task("gather_requirements", context)
    elapsed = (datetime.now() - start).total_seconds()

    print(f"\n✅ Completed in {elapsed:.2f}s")
    print(f"\n📊 Output:")
    print(json.dumps(result, indent=2))

    return result, elapsed


async def test_experimental_agent(user_message: str):
    """Test experimental LangChain Requirements agent"""
    print("\n" + "="*80)
    print("🧪 EXPERIMENTAL AGENT (LangChain)")
    print("="*80)

    agent = LangChainRequirementsAgent()

    context = {
        "user_message": user_message,
        "conversation_history": [],
        "current_requirements": {}
    }

    print(f"\n📝 Input: {user_message}")
    print("\n⏳ Processing...")

    start = datetime.now()
    result = await agent.execute_task("gather_requirements", context)
    elapsed = (datetime.now() - start).total_seconds()

    print(f"\n✅ Completed in {elapsed:.2f}s")
    print(f"\n📊 Output:")
    print(json.dumps(result, indent=2))

    return result, elapsed


async def compare_agents(user_message: str):
    """Run both agents and compare results"""
    print("\n" + "="*80)
    print("🔬 AGENT COMPARISON TEST")
    print("="*80)
    print(f"\nTest Message: '{user_message}'")
    print(f"Timestamp: {datetime.now().isoformat()}")

    # Run production agent
    prod_result, prod_time = await test_production_agent(user_message)

    # Run experimental agent
    exp_result, exp_time = await test_experimental_agent(user_message)

    # Compare
    print("\n" + "="*80)
    print("📈 COMPARISON")
    print("="*80)
    print(f"\nTiming:")
    print(f"  Production:   {prod_time:.2f}s")
    print(f"  Experimental: {exp_time:.2f}s")
    print(f"  Ratio:        {exp_time/prod_time:.2f}x")

    print(f"\nOutputs Match: {prod_result == exp_result}")

    print("\n" + "="*80)
    print("🔍 VIEW IN LANGSMITH")
    print("="*80)
    print("\n1. Go to: https://smith.langchain.com/")
    print("2. Select project: 'researchflow-production'")
    print("3. Look for the most recent 2 runs (timestamp above)")
    print("4. Compare:")
    print("   - Production run: Only shows LLM call")
    print("   - Experimental run: Shows full workflow (gather_requirements)")
    print("\n")


async def main():
    """Main entry point"""

    # Test scenarios
    scenarios = [
        "I need all patients with type 2 diabetes diagnosed in 2024.",
        "Find diabetic patients on metformin, age 45-65, with HbA1c > 7.5%.",
        "I want patients with heart failure. Exclude anyone on dialysis."
    ]

    print("\n" + "="*80)
    print("🧪 MANUAL AGENT TESTING")
    print("="*80)
    print("\nAvailable test scenarios:")
    for i, scenario in enumerate(scenarios, 1):
        print(f"  {i}. {scenario}")
    print(f"  4. Custom input")

    choice = input("\nSelect scenario (1-4): ").strip()

    if choice == "4":
        user_message = input("\nEnter your test message: ").strip()
    elif choice in ["1", "2", "3"]:
        user_message = scenarios[int(choice) - 1]
    else:
        print("Invalid choice. Using default.")
        user_message = scenarios[0]

    # Run comparison
    await compare_agents(user_message)


if __name__ == "__main__":
    asyncio.run(main())
