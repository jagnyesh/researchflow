"""#266: data_delivery goes straight to complete.

The post-delivery meeting branch (schedule_kickoff) could never run: nothing
wrote schedule_post_delivery_meeting, and FullWorkflowState didn't declare it.
"""

from app.langchain_orchestrator.langgraph_workflow import FullWorkflow


def test_delivery_goes_straight_to_complete():
    graph = FullWorkflow().compiled_graph.get_graph()

    assert "schedule_kickoff" not in graph.nodes
    assert {e.target for e in graph.edges if e.source == "data_delivery"} == {"complete"}
