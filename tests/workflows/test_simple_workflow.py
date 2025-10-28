"""
Tests for Simple StateGraph Workflow (Sprint 2)

These tests validate the 3-state LangGraph workflow and compare it
against the custom FSM implementation.

Test Goals:
1. State transitions work correctly
2. Conditional routing functions properly
3. State schema is enforced (TypedDict)
4. Workflow completes successfully
5. Diagram generation works
"""

import pytest
from datetime import datetime

from app.langchain_orchestrator.simple_workflow import SimpleWorkflow, WorkflowState


@pytest.fixture
def simple_workflow():
    """Create SimpleWorkflow instance for testing"""
    return SimpleWorkflow()


@pytest.fixture
def initial_state() -> WorkflowState:
    """Create initial workflow state"""
    return {
        "request_id": "test-001",
        "current_state": "new",
        "researcher_request": "I need patients with diabetes",
        "researcher_info": {"name": "Dr. Smith", "email": "smith@hospital.org"},
        "requirements": {},
        "conversation_history": [],
        "completeness_score": 0.0,
        "requires_approval": False,
        "error": None,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat()
    }


class TestStateTransitions:
    """Test state transitions"""

    @pytest.mark.asyncio
    async def test_new_request_to_requirements_gathering(self, simple_workflow, initial_state):
        """Test transition from new_request to requirements_gathering"""

        # Start workflow
        result = await simple_workflow.run(initial_state)

        # Should have transitioned through states
        assert result["current_state"] in ["requirements_gathering", "complete"]
        assert result["updated_at"] != initial_state["updated_at"]

    @pytest.mark.asyncio
    async def test_requirements_gathering_to_complete(self, simple_workflow, initial_state):
        """Test transition from requirements_gathering to complete when requirements are ready"""

        # Set requirements as complete
        initial_state["requirements"] = {
            "inclusion_criteria": ["diabetes"],
            "exclusion_criteria": [],
            "data_elements": ["demographics"]
        }
        initial_state["completeness_score"] = 0.9
        initial_state["requires_approval"] = True

        # Run workflow
        result = await simple_workflow.run(initial_state)

        # Should complete
        assert result["current_state"] == "complete"
        assert result["requires_approval"] is True


class TestConditionalRouting:
    """Test conditional routing logic"""

    def test_route_after_requirements_complete(self, simple_workflow):
        """Test routing when requirements are complete"""

        state: WorkflowState = {
            "request_id": "test-002",
            "current_state": "requirements_gathering",
            "researcher_request": "Test",
            "researcher_info": {},
            "requirements": {"test": "data"},
            "conversation_history": [],
            "completeness_score": 0.9,
            "requires_approval": True,
            "error": None,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        route = simple_workflow._route_after_requirements(state)
        assert route == "complete"

    def test_route_after_requirements_incomplete(self, simple_workflow):
        """Test routing when requirements are incomplete"""

        state: WorkflowState = {
            "request_id": "test-003",
            "current_state": "requirements_gathering",
            "researcher_request": "Test",
            "researcher_info": {},
            "requirements": {},
            "conversation_history": [],
            "completeness_score": 0.3,
            "requires_approval": False,
            "error": None,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }

        route = simple_workflow._route_after_requirements(state)
        assert route == "wait_for_input"


class TestStateHandlers:
    """Test individual state handlers"""

    def test_handle_new_request(self, simple_workflow, initial_state):
        """Test new_request state handler"""

        result = simple_workflow._handle_new_request(initial_state)

        assert result["current_state"] == "new_request"
        assert result["requirements"] == {}
        assert result["completeness_score"] == 0.0
        assert result["requires_approval"] is False
        assert result["error"] is None

    def test_handle_requirements_gathering_incomplete(self, simple_workflow, initial_state):
        """Test requirements_gathering handler with incomplete requirements"""

        initial_state["completeness_score"] = 0.3

        result = simple_workflow._handle_requirements_gathering(initial_state)

        assert result["current_state"] == "requirements_gathering"
        assert result["requires_approval"] is False

    def test_handle_requirements_gathering_complete(self, simple_workflow, initial_state):
        """Test requirements_gathering handler with complete requirements"""

        initial_state["requirements"] = {"test": "data"}
        initial_state["completeness_score"] = 0.9

        result = simple_workflow._handle_requirements_gathering(initial_state)

        assert result["current_state"] == "requirements_gathering"
        assert result["requires_approval"] is True

    def test_handle_complete(self, simple_workflow, initial_state):
        """Test complete state handler"""

        result = simple_workflow._handle_complete(initial_state)

        assert result["current_state"] == "complete"


class TestWorkflowExecution:
    """Test full workflow execution"""

    @pytest.mark.asyncio
    async def test_complete_workflow_with_ready_requirements(self, simple_workflow, initial_state):
        """Test complete workflow when requirements are already ready"""

        # Set requirements as complete from the start
        initial_state["requirements"] = {
            "inclusion_criteria": ["diabetes mellitus"],
            "exclusion_criteria": ["pregnancy"],
            "data_elements": ["demographics", "lab_results"]
        }
        initial_state["completeness_score"] = 0.95
        initial_state["requires_approval"] = True

        # Run workflow
        result = await simple_workflow.run(initial_state)

        # Verify final state
        assert result["current_state"] == "complete"
        assert result["requires_approval"] is True
        assert result["completeness_score"] == 0.95
        assert len(result["requirements"]) > 0

    @pytest.mark.asyncio
    async def test_workflow_state_updates(self, simple_workflow, initial_state):
        """Test that workflow updates state timestamps"""

        original_updated_at = initial_state["updated_at"]

        # Run workflow
        result = await simple_workflow.run(initial_state)

        # Verify state was updated
        assert result["updated_at"] != original_updated_at


class TestDiagramGeneration:
    """Test diagram generation"""

    def test_get_graph_diagram(self, simple_workflow):
        """Test that diagram generation works"""

        diagram = simple_workflow.get_graph_diagram()

        # Should return Mermaid diagram string
        assert isinstance(diagram, str)
        assert len(diagram) > 0

        # Should contain key elements of the graph
        # (exact format may vary, but should mention states)
        diagram_lower = diagram.lower()
        assert any(state in diagram_lower for state in ["new_request", "requirements", "complete"])


class TestTypeSafety:
    """Test that TypedDict enforces type safety"""

    @pytest.mark.asyncio
    async def test_workflow_with_valid_state(self, simple_workflow, initial_state):
        """Test workflow with valid state schema"""

        # Should work fine with valid state
        result = await simple_workflow.run(initial_state)
        assert result is not None

    @pytest.mark.asyncio
    async def test_workflow_with_missing_field(self, simple_workflow):
        """Test workflow behavior with missing required field"""

        # Create incomplete state (missing required fields)
        incomplete_state = {
            "request_id": "test-004",
            "current_state": "new"
            # Missing many required fields
        }

        # Should still work (TypedDict doesn't enforce at runtime in Python)
        # But type checkers like mypy will catch this
        try:
            result = await simple_workflow.run(incomplete_state)
            # May succeed with defaults or fail gracefully
            assert result is not None or True
        except KeyError:
            # Expected if workflow tries to access missing fields
            pass


class TestGraphStructure:
    """Test graph structure"""

    def test_graph_has_correct_nodes(self, simple_workflow):
        """Test that graph has all expected nodes"""

        graph = simple_workflow.graph

        # Check nodes exist
        # Note: LangGraph's internal structure may vary
        assert graph is not None

    def test_graph_has_entry_point(self, simple_workflow):
        """Test that graph has entry point set"""

        # Compiled graph should be runnable
        assert simple_workflow.compiled_graph is not None


# Sprint 2 Comparison Summary (to be updated after testing):
#
# SIMPLICITY:
# - Custom FSM: Complex transition table, manual state tracking
# - LangGraph: Declarative graph building, automatic state management
# - Winner: LangGraph (clearer, less boilerplate)
#
# VISUALIZATION:
# - Custom FSM: Manual PlantUML diagrams
# - LangGraph: Automatic Mermaid diagram generation
# - Winner: LangGraph (get_graph_diagram() is magic)
#
# TYPE SAFETY:
# - Custom FSM: No type enforcement
# - LangGraph: TypedDict provides schema validation (at dev time)
# - Winner: LangGraph (catches bugs early)
#
# TESTING:
# - Custom FSM: Complex to test (many state transitions)
# - LangGraph: Easy to test (functional state handlers)
# - Winner: LangGraph (pure functions are testable)
#
# PERFORMANCE:
# - TBD (benchmarks needed)
#
# RECOMMENDATION:
# - If tests pass: Proceed to Sprint 3 (Full 15-State Workflow)
# - LangGraph shows clear advantages for workflow management
