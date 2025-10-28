"""
Simple 3-State Workflow using LangGraph (Sprint 2)

This is a proof-of-concept to evaluate LangGraph's StateGraph
as an alternative to the custom workflow FSM.

States:
1. new_request - Initial state when request is created
2. requirements_gathering - Requirements Agent is gathering requirements
3. complete - Requirements gathered and approved

Purpose: Evaluate if LangGraph provides advantages over custom FSM
Status: Experimental - Sprint 2
"""

import logging
from typing import TypedDict, Annotated, Literal
from datetime import datetime

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

logger = logging.getLogger(__name__)


# Define the state schema
class WorkflowState(TypedDict):
    """
    State schema for the simple workflow

    LangGraph uses TypedDict to define state shape.
    This replaces the manual state tracking in custom workflow_engine.py
    """
    request_id: str
    current_state: str
    researcher_request: str
    researcher_info: dict
    requirements: dict
    conversation_history: Annotated[list, add_messages]  # LangGraph's message handling
    completeness_score: float
    requires_approval: bool
    error: str | None
    created_at: str
    updated_at: str


class SimpleWorkflow:
    """
    Simple 3-state workflow using LangGraph

    Comparison Goals:
    1. Is StateGraph simpler than custom FSM? (LOC, complexity)
    2. Is conditional routing easier? (routing logic clarity)
    3. Is visualization automatic? (diagram generation)
    4. Is state management cleaner? (TypedDict vs manual tracking)

    This replaces a subset of app/orchestrator/workflow_engine.py
    """

    def __init__(self):
        """Initialize the workflow graph"""
        self.graph = self._build_graph()
        self.compiled_graph = self.graph.compile()

    def _build_graph(self) -> StateGraph:
        """
        Build the StateGraph with 3 states

        States:
        - new_request: Entry point
        - requirements_gathering: Gathering requirements
        - complete: Final state

        This is much more declarative than the custom FSM's
        transition table in workflow_engine.py
        """
        # Create graph with WorkflowState schema
        graph = StateGraph(WorkflowState)

        # Add nodes (states)
        graph.add_node("new_request", self._handle_new_request)
        graph.add_node("requirements_gathering", self._handle_requirements_gathering)
        graph.add_node("complete", self._handle_complete)

        # Set entry point
        graph.set_entry_point("new_request")

        # Add edges (transitions)
        # new_request always goes to requirements_gathering
        graph.add_edge("new_request", "requirements_gathering")

        # requirements_gathering has conditional routing
        graph.add_conditional_edges(
            "requirements_gathering",
            self._route_after_requirements,
            {
                "complete": "complete",
                "wait_for_input": END  # Wait for more user input (don't loop)
            }
        )

        # complete is terminal
        graph.add_edge("complete", END)

        return graph

    def _handle_new_request(self, state: WorkflowState) -> WorkflowState:
        """
        Handle new request state

        Simply initializes the request and prepares for requirements gathering.
        In custom workflow, this is scattered across orchestrator.py
        """
        logger.info(f"[SimpleWorkflow] Processing new request: {state['request_id']}")

        # Update state
        state["current_state"] = "new_request"
        state["updated_at"] = datetime.now().isoformat()

        # Initialize empty requirements if not already present
        if not state.get("requirements"):
            state["requirements"] = {}
        if "completeness_score" not in state:
            state["completeness_score"] = 0.0
        if "requires_approval" not in state:
            state["requires_approval"] = False
        if "error" not in state:
            state["error"] = None

        logger.info(f"[SimpleWorkflow] New request initialized, moving to requirements_gathering")

        return state

    def _handle_requirements_gathering(self, state: WorkflowState) -> WorkflowState:
        """
        Handle requirements gathering state

        This is where the Requirements Agent would be invoked.
        For Sprint 2, we simulate the agent's behavior.
        Sprint 3 will integrate the actual LangChain Requirements Agent.
        """
        logger.info(f"[SimpleWorkflow] Gathering requirements for {state['request_id']}")

        # Update state
        state["current_state"] = "requirements_gathering"
        state["updated_at"] = datetime.now().isoformat()

        # Simulate requirements gathering
        # In Sprint 3, this will call the actual LangChain Requirements Agent

        # Check if requirements are already marked as ready (from pre-structured)
        if not state.get("requires_approval", False):
            # For now, check if we have requirements (simulated)
            if state.get("requirements") and state.get("completeness_score", 0) >= 0.8:
                # Requirements are complete
                state["requires_approval"] = True
                logger.info(f"[SimpleWorkflow] Requirements complete (score: {state['completeness_score']:.1%})")
            else:
                # Need more conversation
                logger.info(f"[SimpleWorkflow] Requirements incomplete (score: {state['completeness_score']:.1%})")
        else:
            logger.info(f"[SimpleWorkflow] Requirements already marked as ready")

        return state

    def _route_after_requirements(self, state: WorkflowState) -> Literal["complete", "wait_for_input"]:
        """
        Conditional routing after requirements gathering

        This is LangGraph's way of handling conditional transitions.
        Much cleaner than the custom FSM's if/elif chains.

        Returns:
            "complete" if requirements are ready for approval
            "wait_for_input" if more conversation needed (stops and waits for user)
        """
        if state.get("requires_approval", False):
            logger.info(f"[SimpleWorkflow] Routing to complete")
            return "complete"
        else:
            logger.info(f"[SimpleWorkflow] Routing to END - waiting for more user input")
            return "wait_for_input"

    def _handle_complete(self, state: WorkflowState) -> WorkflowState:
        """
        Handle complete state

        Requirements have been gathered and approved.
        This is the terminal state for this simple workflow.
        """
        logger.info(f"[SimpleWorkflow] Workflow complete for {state['request_id']}")

        # Update state
        state["current_state"] = "complete"
        state["updated_at"] = datetime.now().isoformat()

        return state

    async def run(self, initial_state: WorkflowState) -> WorkflowState:
        """
        Run the workflow from initial state to completion

        Args:
            initial_state: Initial workflow state

        Returns:
            Final workflow state
        """
        logger.info(f"[SimpleWorkflow] Starting workflow for {initial_state['request_id']}")

        # Run the compiled graph
        final_state = await self.compiled_graph.ainvoke(initial_state)

        logger.info(f"[SimpleWorkflow] Workflow ended in state: {final_state['current_state']}")

        return final_state

    def get_graph_diagram(self) -> str:
        """
        Get Mermaid diagram of the workflow

        LangGraph automatically generates visual diagrams.
        This is a major advantage over the custom FSM which requires
        manual diagram creation.

        Returns:
            Mermaid diagram string
        """
        try:
            return self.compiled_graph.get_graph().draw_mermaid()
        except Exception as e:
            logger.error(f"Failed to generate diagram: {e}")
            return "Diagram generation failed"


# Comparison Notes (Sprint 2):
#
# CODE COMPLEXITY:
# - Custom FSM (workflow_engine.py): ~300 lines, 15 states, complex transition table
# - LangGraph Simple (simple_workflow.py): ~200 lines, 3 states, declarative
# - Verdict: LangGraph is more concise and readable
#
# STATE TRANSITIONS:
# - Custom: Manual if/elif chains, error-prone
# - LangGraph: Declarative add_edge(), add_conditional_edges()
# - Verdict: LangGraph clearer and less error-prone
#
# VISUALIZATION:
# - Custom: No automatic visualization (manual PlantUML)
# - LangGraph: Automatic Mermaid diagram generation
# - Verdict: LangGraph wins (get_graph().draw_mermaid())
#
# TYPE SAFETY:
# - Custom: No type checking on state
# - LangGraph: TypedDict enforces state schema
# - Verdict: LangGraph wins (catches bugs at dev time)
#
# CONDITIONAL ROUTING:
# - Custom: Scattered logic in orchestrator.py
# - LangGraph: Centralized in routing functions
# - Verdict: LangGraph is clearer
#
# EXTENDABILITY:
# - Custom: Adding states requires updating multiple places
# - LangGraph: Add node, add edges, done
# - Verdict: LangGraph easier to extend
#
# LEARNING CURVE:
# - Custom: Low (just Python dicts and functions)
# - LangGraph: Medium (need to understand StateGraph concepts)
# - Verdict: Custom is simpler to learn
#
# PERFORMANCE:
# - TBD (Sprint 2 tests will measure)
#
# OVERALL (Sprint 2 Assessment):
# - LangGraph provides clear advantages for state machine management
# - Automatic visualization is valuable
# - Type safety catches bugs early
# - Recommend proceeding to Sprint 3 (Full 15-State Workflow)
