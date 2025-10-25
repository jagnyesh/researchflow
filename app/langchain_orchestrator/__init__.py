"""
LangChain/LangGraph-based Orchestrator (EXPERIMENTAL)

This module explores using LangChain and LangGraph for orchestrating
the multi-agent research request workflow as an alternative to the
custom orchestrator implementation.

Status: Experimental / Proof of Concept
Purpose: Evaluate if LangChain/LangGraph provides advantages over custom solution

Key Components:
- langgraph_workflow.py: State machine using LangGraph StateGraph
- langchain_agents.py: Agent adapters using LangChain AgentExecutor
- comparison.md: Evaluation findings vs custom orchestrator
"""

__all__ = []
