"""#432: the code that writes a request's state agrees with the state registry.

`app/database/workflow_states.py` declares every value that
`research_requests.current_state` can hold. These tests read the graph and the
source under `app/` and fail when a writer and the registry disagree. They open
no database connection and make no LLM call.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.database.workflow_states import STATE_INFO, StateKind, WorkflowState
from app.langchain_orchestrator.approval_bridge import ApprovalBridge
from app.langchain_orchestrator.langgraph_workflow import (
    REVIEW_NODE_BY_APPROVAL_TYPE,
    FullWorkflow,
)

APP_DIR = Path(__file__).resolve().parent.parent / "app"
FIELD = "current_state"

MEMBER_VALUES = {state.value for state in WorkflowState}


def _values_where(keep) -> set[str]:
    """Values of the declared states whose StateInfo passes `keep`."""
    return {state.value for state, info in STATE_INFO.items() if keep(info)}


# Nodes that the graph adds but that no edge leads to. `human_review` has a
# handler and an edge to END, and nothing routes to it.
UNREACHABLE_NODES = {"human_review"}


def _reads_the_field(node: ast.expr) -> bool:
    """True for `x.current_state`, `x["current_state"]` and `x.get("current_state", ...)`."""
    if isinstance(node, ast.Attribute):
        return node.attr == FIELD
    if isinstance(node, ast.Subscript):
        return isinstance(node.slice, ast.Constant) and node.slice.value == FIELD
    if isinstance(node, ast.Call):
        return (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "get"
            and bool(node.args)
            and isinstance(node.args[0], ast.Constant)
            and node.args[0].value == FIELD
        )
    return False


def _values_written_to_the_field(tree: ast.AST):
    """Yield each expression stored in a `current_state` field.

    These forms store one: `x.current_state = v`, `x["current_state"] = v`,
    `setattr(x, "current_state", v)`, `x.setdefault("current_state", v)`, the
    keyword `current_state=v`, and the dict entry `{"current_state": v}`.
    A tuple target (`a.current_state, b = ...`) is yielded whole, so it reads
    as unverifiable. A bare local named `current_state` is not the field.

    Out of the scan's reach: raw SQL text, a field name held in a variable, a
    `Column(default=...)`, and a class attribute default. No code under `app/`
    stores a state in any of them today.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(_reads_the_field(target) for target in node.targets):
                yield node.value
            elif any(
                isinstance(target, (ast.Tuple, ast.List))
                and any(_reads_the_field(element) for element in target.elts)
                for target in node.targets
            ):
                yield node.value
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            args = node.args
            if (
                node.func.attr == "setdefault"
                and len(args) == 2
                and isinstance(args[0], ast.Constant)
                and args[0].value == FIELD
            ):
                yield args[1]
        elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            args = node.args
            if (
                node.func.id == "setattr"
                and len(args) == 3
                and isinstance(args[1], ast.Constant)
                and args[1].value == FIELD
            ):
                yield args[2]
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            if _reads_the_field(node.target) and node.value is not None:
                yield node.value
        elif isinstance(node, ast.keyword) and node.arg == FIELD:
            yield node.value
        elif isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == FIELD:
                    yield value


def _scan_app():
    """Return (literals, unverifiable): what `app/` stores in the field, with where.

    A stored value is a string literal, a copy of another `current_state`, or
    a conditional between those. Anything else is unverifiable, and the test
    fails on it, so a writer cannot hide a new state behind a variable.
    """
    literals: dict[str, list[str]] = {}
    unverifiable: list[str] = []
    for path in sorted(APP_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for stored in _values_written_to_the_field(tree):
            pending = [stored]
            while pending:
                value = pending.pop()
                where = f"{path.relative_to(APP_DIR.parent)}:{value.lineno}"
                if isinstance(value, ast.IfExp):
                    pending += [value.body, value.orelse]
                elif _reads_the_field(value) and isinstance(value, ast.Call):
                    # `x.get("current_state", default)` stores the default when the key is absent.
                    pending += value.args[1:2]
                elif isinstance(value, ast.Constant) and isinstance(value.value, str):
                    literals.setdefault(value.value, []).append(where)
                elif not _reads_the_field(value):
                    unverifiable.append(f"{where}: {ast.unparse(value)}")
    return literals, unverifiable


ASSIGNED, UNVERIFIABLE = _scan_app()


def test_every_graph_node_is_a_registry_member():
    nodes = set(FullWorkflow().compiled_graph.get_graph().nodes) - {"__start__", "__end__"}

    assert nodes, "the graph reported no nodes, so this test would prove nothing"
    assert nodes <= MEMBER_VALUES, (
        f"Graph nodes with no WorkflowState member: {sorted(nodes - MEMBER_VALUES)}. "
        "Add each one to app/database/workflow_states.py."
    )


def test_every_assigned_state_literal_is_a_registry_member():
    assert ASSIGNED, "the scan found no assignment, so this test would prove nothing"
    unknown = {value: where for value, where in ASSIGNED.items() if value not in MEMBER_VALUES}

    assert not unknown, (
        f"Strings assigned to {FIELD} with no WorkflowState member: {unknown}. "
        "Add each one to app/database/workflow_states.py with its kind."
    )


def test_every_assignment_can_be_checked():
    assert not UNVERIFIABLE, (
        f"These store a value in {FIELD} that this test cannot read as a string literal "
        f"or as a copy of another {FIELD}: {UNVERIFIABLE}. Assign a literal, or teach "
        "_scan_app the new form."
    )


def test_every_member_declares_its_kind_and_label():
    undeclared = [state.name for state in WorkflowState if state not in STATE_INFO]

    assert not undeclared, (
        f"WorkflowState members with no STATE_INFO entry: {undeclared}. "
        "Give each one a kind, a label and an owning agent in app/database/workflow_states.py."
    )
    for state in WorkflowState:
        assert isinstance(state.info.kind, StateKind), state.name
        assert state.info.label.strip(), state.name


def test_review_states_are_the_states_the_graph_pauses_after(monkeypatch):
    monkeypatch.setenv("AUTO_APPROVE_FOR_DEV", "false")
    gates = set(FullWorkflow().compiled_graph.interrupt_after_nodes)
    review = _values_where(lambda info: info.kind is StateKind.AWAITING_REVIEW)

    assert gates, "the graph reported no approval gate, so this test would prove nothing"
    assert review == gates, (
        "The registry's awaiting-review states and the graph's approval gates differ: "
        f"only in the registry {sorted(review - gates)}, only in the graph {sorted(gates - review)}."
    )


def test_each_review_state_has_one_approval_type_and_no_other_state_has_one():
    typed = {s.value: info.approval_type for s, info in STATE_INFO.items() if info.approval_type}
    review = _values_where(lambda info: info.kind is StateKind.AWAITING_REVIEW)

    assert set(typed) == review
    assert len(set(typed.values())) == len(typed), f"Two states share an approval type: {typed}"
    unknown = set(typed.values()) - set(ApprovalBridge.APPROVAL_TYPE_TO_STATE)
    assert not unknown, f"Approval types that ApprovalBridge does not know: {sorted(unknown)}"


def test_approval_decisions_resume_the_registry_review_states():
    # Pinned as a literal: a derivation compared with itself cannot catch a swapped pair.
    expected = {
        "requirements": "requirements_review",
        "phenotype_sql": "phenotype_review",
        "preview_qa": "preview_qa_review",
        "delivery": "qa_review",
    }
    typed = {info.approval_type: s.value for s, info in STATE_INFO.items() if info.approval_type}

    assert typed == expected
    assert REVIEW_NODE_BY_APPROVAL_TYPE == expected


def test_the_kind_of_every_state_the_graph_writes_is_pinned():
    # The reader PRs consume this split, so a changed kind must be a deliberate edit here.
    expected = {
        StateKind.IN_PROGRESS: {
            "new_request",
            "requirements_gathering",
            "feasibility_validation",
            "preview_extraction",
            "preview_qa",
            "data_extraction",
            "qa_validation",
            "data_delivery",
        },
        StateKind.AWAITING_REVIEW: {
            "requirements_review",
            "phenotype_review",
            "preview_qa_review",
            "qa_review",
        },
        StateKind.SUCCEEDED: {"complete"},
        StateKind.FAILED: {"not_feasible", "qa_failed", "error", "human_review"},
    }
    actual = {kind: _values_where(lambda info, kind=kind: info.kind is kind) for kind in expected}

    assert actual == expected


def test_a_member_is_legacy_exactly_when_no_code_writes_it():
    not_legacy = _values_where(lambda info: info.kind is not StateKind.LEGACY)
    written = set(ASSIGNED) & MEMBER_VALUES

    assert not_legacy == written, (
        f"Not legacy, yet no code under app/ assigns it: {sorted(not_legacy - written)}. "
        f"Legacy, yet code assigns it: { {v: ASSIGNED[v] for v in written - not_legacy} }. "
        "Change the member's kind in app/database/workflow_states.py."
    )


def test_the_only_nodes_no_edge_leads_to_are_the_named_ones():
    graph = FullWorkflow().compiled_graph.get_graph()
    targets: dict[str, set[str]] = {}
    for edge in graph.edges:
        targets.setdefault(edge.source, set()).add(edge.target)
    reached, pending = set(), ["__start__"]
    while pending:
        node = pending.pop()
        if node not in reached:
            reached.add(node)
            pending += targets.get(node, ())

    assert set(graph.nodes) - reached == UNREACHABLE_NODES, (
        "The nodes that no path from the entry point reaches changed. Wire the node, "
        "or update UNREACHABLE_NODES in this file."
    )


def test_the_registry_names_the_agent_that_the_facade_records():
    from app.langchain_orchestrator.request_facade import LangGraphRequestFacade

    differs = {
        value: (WorkflowState(value).info.agent, facade_agent)
        for value in set(ASSIGNED) & MEMBER_VALUES
        if (facade_agent := LangGraphRequestFacade._get_agent_for_state(None, value))
        != WorkflowState(value).info.agent
    }

    assert not differs, f"state: (registry agent, request_facade agent) {differs}"
