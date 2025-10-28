# Sprint 05: LangSmith Observability

**Duration:** 1 week
**Status:** 🚧 In Progress
**Branch:** `feature/langchain-langgraph-exploration`
**Sprint Goal:** Add comprehensive observability to LangGraph workflow using LangSmith
**Completion Date:** TBD

---

## Goal

Implement LangSmith observability across the entire LangGraph workflow to enable:
- Real-time workflow execution tracing
- Agent performance monitoring
- Error tracking and debugging
- Cost tracking (LLM API usage)
- Visualization of workflow state transitions

**Key Questions:**
1. How do we trace the entire 23-state workflow execution?
2. What metrics should we monitor for each agent?
3. How do we visualize workflow state transitions in LangSmith?

---

## Deliverables

- [ ] **LangSmith Configuration:** Environment setup and API key configuration
- [ ] **Workflow Tracing:** Enable tracing in `langgraph_workflow.py`
- [ ] **Agent Tracing:** Add `@traceable` decorators to all 6 agents
- [ ] **Custom Metadata:** Add workflow-specific metadata (state, request_id, agent)
- [ ] **Dashboard Guide:** Documentation on using LangSmith dashboard
- [ ] **E2E Test with Tracing:** Run E2E tests with LangSmith enabled
- [ ] **Sprint Summary:** `SPRINT_05_LANGSMITH_OBSERVABILITY.md` ✅ (this document)

---

## Implementation Plan

### Phase 1: LangSmith Setup (30 min)

**1.1 Environment Configuration**
```bash
# Add to .env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
LANGCHAIN_API_KEY=<your-api-key>
LANGCHAIN_PROJECT=researchflow-production

# Optional: Set project tags
LANGSMITH_TAGS=production,langgraph,research
```

**1.2 Install LangSmith Client**
```bash
pip install langsmith  # Already installed (0.4.38)
```

**1.3 Verify Installation**
```python
from langsmith import Client
client = Client()
print(client.info())  # Should show project info
```

### Phase 2: Workflow Tracing (1 hour)

**2.1 Add Tracing to FullWorkflow**

Modify `app/langchain_orchestrator/langgraph_workflow.py`:

```python
from langsmith import traceable
from langchain_core.runnables import RunnableConfig

class FullWorkflow:
    @traceable(
        run_type="chain",
        name="ResearchFlow_FullWorkflow",
        tags=["workflow", "langgraph", "research"],
        metadata={"version": "1.0.0", "states": 23}
    )
    async def run(
        self,
        initial_state: FullWorkflowState,
        config: Optional[RunnableConfig] = None
    ) -> FullWorkflowState:
        """Run workflow with LangSmith tracing"""

        # Add request_id to config metadata
        if config is None:
            config = RunnableConfig(
                metadata={
                    "request_id": initial_state.get("request_id"),
                    "initial_state": initial_state.get("current_state")
                }
            )

        # Invoke compiled graph with config
        final_state = await self.compiled_graph.ainvoke(
            initial_state,
            config=config
        )

        return final_state
```

**2.2 Add State Transition Logging**

Add custom events for each state transition:

```python
from langsmith import trace

def _handle_new_request(self, state: FullWorkflowState) -> FullWorkflowState:
    """Handle new_request state"""

    # Log state transition
    trace.log(
        "state_transition",
        {
            "from": "START",
            "to": "new_request",
            "request_id": state.get("request_id")
        }
    )

    # Existing logic...
    return state
```

### Phase 3: Agent Tracing (1.5 hours)

**3.1 Add @traceable to LangChain Agents**

Modify `app/langchain_orchestrator/langchain_agents.py`:

```python
from langsmith import traceable

class LangChainRequirementsAgent:
    @traceable(
        run_type="agent",
        name="RequirementsAgent",
        tags=["agent", "requirements", "llm"],
        metadata={"agent_type": "requirements", "llm": "claude-3-5-sonnet"}
    )
    async def execute_task(
        self,
        task: str,
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Execute requirements gathering task with tracing"""

        # Add custom metadata
        trace_metadata = {
            "task": task,
            "request_id": context.get("request_id"),
            "conversation_length": len(context.get("conversation_history", []))
        }

        # Existing logic with tracing...
        result = await self._execute_with_tracing(task, context, trace_metadata)

        return result
```

**3.2 Wrap All 6 Agents:**
- ✅ LangChainRequirementsAgent
- ✅ LangChainPhenotypeAgent
- ✅ LangChainCalendarAgent
- ✅ LangChainExtractionAgent
- ✅ LangChainQAAgent
- ✅ LangChainDeliveryAgent

### Phase 4: Custom Metadata (30 min)

**4.1 Add Workflow Metrics**

Track custom metrics for observability:

```python
# In each node handler
@traceable(metadata={
    "state": current_state,
    "elapsed_time": elapsed_time,
    "transition_count": transition_count,
    "agent_executions": len(agents_involved)
})
def _handle_requirements_gathering(self, state: FullWorkflowState):
    # ...
```

**4.2 Add Cost Tracking**

Track LLM API usage:

```python
from langsmith import track_costs

@track_costs
async def _call_llm(self, prompt: str):
    # LLM call
    response = await self.llm.ainvoke(prompt)
    return response
```

### Phase 5: Dashboard & Monitoring (1 hour)

**5.1 Create LangSmith Project**
- Project name: `researchflow-production`
- Tags: `production`, `langgraph`, `research`
- Auto-tagging by environment

**5.2 Dashboard Views**
1. **Workflow Executions:** List all workflow runs
2. **Agent Performance:** Average execution time per agent
3. **Error Tracking:** Failed runs and exceptions
4. **Cost Analysis:** LLM API usage and costs
5. **State Transitions:** Sankey diagram of state flows

**5.3 Alerts**
- Set up alerts for:
  * Workflow failures
  * Long-running agents (> 30 sec)
  * High LLM costs (> $1 per request)
  * Terminal error states (not_feasible, qa_failed)

### Phase 6: Testing (1 hour)

**6.1 Run E2E Tests with Tracing**

```bash
# Enable tracing
export LANGCHAIN_TRACING_V2=true
export LANGCHAIN_API_KEY=<your-key>
export LANGCHAIN_PROJECT=researchflow-e2e-testing

# Run tests
PYTHONPATH=/Users/jagnyesh/Development/FHIR_PROJECT \
  pytest tests/e2e/test_langgraph_workflow_e2e.py -v -s
```

**6.2 Verify Traces in LangSmith**
- Check that workflow runs appear in dashboard
- Verify agent execution traces
- Confirm state transition metadata
- Validate error tracking

**6.3 Performance Baseline**
- Measure tracing overhead (< 5% expected)
- Confirm no API slowdowns
- Validate async tracing works correctly

---

## Success Criteria

### Must Have
- [x] LangSmith configured in .env
- [ ] All workflow runs traced in LangSmith
- [ ] All 6 agents instrumented with @traceable
- [ ] Custom metadata captured (request_id, state, agent)
- [ ] E2E tests running with tracing enabled
- [ ] Documentation created

### Nice to Have
- [ ] Cost tracking dashboard
- [ ] Automated alerts for failures
- [ ] Slack integration for notifications
- [ ] Historical trend analysis (7-day retention)

### Performance Targets
- Tracing overhead: < 5%
- Dashboard load time: < 2 seconds
- Trace data latency: < 10 seconds

---

## Technical Details

### LangSmith Architecture

```
┌─────────────────┐
│  LangGraph      │
│  Workflow       │
│  (Traced)       │
└────────┬────────┘
         │
         │ Traces sent async
         │
         ▼
┌─────────────────┐
│  LangSmith      │
│  API            │
│  (Cloud)        │
└────────┬────────┘
         │
         │ Dashboard
         │
         ▼
┌─────────────────┐
│  LangSmith      │
│  Dashboard      │
│  (Web UI)       │
└─────────────────┘
```

### Trace Structure

```json
{
  "run_id": "uuid",
  "name": "ResearchFlow_FullWorkflow",
  "run_type": "chain",
  "start_time": "2025-10-26T00:00:00Z",
  "end_time": "2025-10-26T00:00:15Z",
  "inputs": {
    "request_id": "REQ-E2E-123",
    "current_state": "new_request"
  },
  "outputs": {
    "current_state": "not_feasible",
    "feasibility_score": 0.2
  },
  "metadata": {
    "request_id": "REQ-E2E-123",
    "states_traversed": 4,
    "agents_executed": 1,
    "total_duration_ms": 330
  },
  "tags": ["workflow", "langgraph", "research"],
  "child_runs": [
    {
      "run_id": "uuid-child",
      "name": "RequirementsAgent",
      "run_type": "agent",
      "metadata": {
        "agent_type": "requirements",
        "llm": "claude-3-5-sonnet"
      }
    }
  ]
}
```

### Environment Variables

```bash
# Required
LANGCHAIN_TRACING_V2=true                    # Enable tracing
LANGCHAIN_API_KEY=<your-api-key>            # LangSmith API key
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com

# Optional
LANGCHAIN_PROJECT=researchflow-production    # Project name
LANGSMITH_TAGS=production,langgraph          # Auto-tagging
LANGCHAIN_HUB_API_URL=https://api.hub.langchain.com
```

---

## Testing Strategy

### Unit Tests
- Test @traceable decorator doesn't break agents
- Verify metadata is captured correctly
- Confirm async tracing works

### Integration Tests
- Run E2E workflow with tracing
- Verify all agents are traced
- Check state transitions logged

### Performance Tests
- Measure tracing overhead
- Benchmark with/without tracing
- Validate async behavior

---

## Risks & Mitigations

| Risk | Impact | Probability | Mitigation | Status |
|------|--------|-------------|------------|--------|
| Tracing overhead too high | High | Low | Async tracing, sampling | ⏳ Monitor |
| Network failures | Medium | Medium | Retry logic, queue traces | ⏳ Monitor |
| API key exposure | High | Low | Env vars, secrets manager | ✅ Mitigated |
| LangSmith costs | Medium | Low | Set usage limits, alerts | ⏳ Monitor |

---

## Next Steps (After Sprint 5)

**Sprint 6: Security Baseline**
- Input validation
- SQL injection prevention
- PHI audit logging
- Security documentation

---

## References

- [LangSmith Docs](https://docs.smith.langchain.com/)
- [LangGraph Observability](https://langchain-ai.github.io/langgraph/how-tos/human_in_the_loop/time-travel/)
- [Tracing Best Practices](https://docs.smith.langchain.com/tracing)

---

**Sprint Started:** 2025-10-26
**Sprint Completed:** TBD
**Total Tests:** TBD
**Decision:** TBD

