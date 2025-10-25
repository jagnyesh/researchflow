# LangChain/LangGraph vs Custom Orchestrator Evaluation

**Feature Branch:** `feature/langchain-langgraph-exploration`
**Status:** 🚧 In Progress - Experimental
**Started:** 2025-10-25

---

## Purpose

Evaluate whether migrating from our custom orchestrator to LangChain/LangGraph would provide benefits for ResearchFlow's multi-agent workflow system.

---

## Current System (Baseline)

### Custom Orchestrator Architecture

**Components:**
- `app/orchestrator/orchestrator.py` - Central A2A coordinator (500+ lines)
- `app/orchestrator/workflow_engine.py` - 15-state FSM
- `app/agents/base_agent.py` - Base class with retry logic, state management
- 6 specialized agents (Requirements, Phenotype, Calendar, Extraction, QA, Delivery)

**Workflow States (15 total):**
```
new_request → requirements_gathering → requirements_review →
feasibility_validation → phenotype_review → schedule_kickoff →
data_extraction → qa_validation → data_delivery → delivered → complete

(+ error states, waiting states)
```

**Key Features:**
- ✅ Human-in-loop approvals at key stages
- ✅ Database persistence of all state transitions
- ✅ Agent execution logging
- ✅ Error handling with retry logic
- ✅ A2A (Agent-to-Agent) message passing
- ✅ Conditional routing based on approval outcomes
- ✅ All tests passing (21/21)

**Strengths:**
- Full control over workflow logic
- No external dependencies beyond basic libraries
- Optimized for our specific use case
- Well-understood by team

**Weaknesses:**
- Custom code requires maintenance
- Limited built-in tooling for debugging/tracing
- No standard patterns for agent communication
- Reinventing some wheels (retry logic, state persistence)

---

## LangChain/LangGraph Proposal

### What We'll Explore

1. **LangGraph StateGraph** (replace `workflow_engine.py`)
   - State machine with typed states
   - Conditional edges for branching logic
   - Built-in checkpointing/persistence
   - Visualization tools

2. **LangChain Agents** (enhance current agents)
   - `AgentExecutor` with built-in retry
   - Tool integration for MCP servers
   - Memory for conversational agents
   - Structured output parsing

3. **LangChain Expression Language (LCEL)** (orchestration)
   - Chain composition
   - Parallel execution
   - Error handling pipelines

4. **LangSmith** (observability)
   - Distributed tracing
   - Performance monitoring
   - Debugging tools

---

## Evaluation Criteria

### 1. Code Complexity

**Metrics:**
- Lines of code (custom vs LangChain)
- Number of files
- Conceptual complexity

**Current Custom:**
- orchestrator.py: ~500 lines
- workflow_engine.py: ~300 lines
- base_agent.py: ~200 lines
- **Total: ~1000 lines** core orchestration code

**LangChain Target:**
- TBD

**Winner:** TBD

---

### 2. Performance

**Metrics:**
- Agent execution time
- State transition latency
- Memory usage
- Throughput (requests/sec)

**Baseline (Custom):**
- Average request processing: TBD
- State transition overhead: TBD
- Memory footprint: TBD

**LangChain:**
- TBD

**Winner:** TBD

---

### 3. Maintainability

**Metrics:**
- Learning curve for new developers
- Documentation quality
- Community support
- Debugging ease

**Custom:**
- ✅ Full control and understanding
- ✅ No dependency on external project roadmap
- ❌ Custom documentation required
- ❌ Limited debugging tools

**LangChain:**
- ✅ Standard patterns, well-documented
- ✅ Large community, many examples
- ✅ Built-in tracing/debugging (LangSmith)
- ❌ Learning curve for LangGraph concepts
- ❌ Dependency on external library updates

**Winner:** TBD

---

### 4. Feature Parity

**Required Features:**
- [x] 15-state workflow FSM
- [x] Human-in-loop approvals
- [x] Database persistence
- [x] Agent execution logging
- [x] Retry logic with exponential backoff
- [x] Conditional routing
- [x] Error escalation to humans
- [x] A2A message passing
- [x] Parallel agent execution
- [x] LLM integration (Claude, Ollama, OpenAI)

**Custom Orchestrator:**
- All features: ✅ Implemented

**LangChain/LangGraph:**
- TBD

**Winner:** TBD

---

### 5. Integration Effort

**Migration Complexity:**
- Minimal (parallel implementation): Low risk, high effort
- Gradual (agent-by-agent): Medium risk, medium effort
- Full rewrite: High risk, lower effort (clean slate)

**Recommended Approach:**
- ✅ **Parallel Implementation** (current strategy)
  - Keep custom orchestrator working
  - Build LangGraph version alongside
  - Compare side-by-side
  - Choose winner or hybrid

**Estimated Effort:**
- Initial prototype: 2-4 days
- Full migration: 1-2 weeks
- Testing & validation: 1 week

---

## Experimental Implementation Plan

### Phase 1: Proof of Concept (1-2 days)

**Goal:** Implement 1 agent with LangChain to test concepts

**Tasks:**
- [x] Install dependencies (langchain, langgraph, langsmith)
- [x] Create `app/langchain_orchestrator/` directory
- [ ] Implement Requirements Agent wrapper using LangChain
- [ ] Create simple 3-state LangGraph workflow
- [ ] Test basic execution

**Deliverable:** Working prototype of Requirements Agent

---

### Phase 2: Full Workflow (3-5 days)

**Goal:** Implement complete 15-state workflow

**Tasks:**
- [ ] Convert all 6 agents to LangChain format
- [ ] Build full StateGraph with all states
- [ ] Implement conditional routing
- [ ] Add database persistence
- [ ] Add human-in-loop approval nodes

**Deliverable:** Feature-complete LangGraph orchestrator

---

### Phase 3: Comparison (1-2 days)

**Goal:** Benchmark and evaluate

**Tasks:**
- [ ] Run same test requests through both orchestrators
- [ ] Measure performance metrics
- [ ] Compare code complexity
- [ ] Assess maintainability
- [ ] Document findings

**Deliverable:** This document completed with recommendation

---

## Decision Criteria

**Migrate to LangChain IF:**
- ✅ 30%+ reduction in code complexity
- ✅ Better debugging/observability tools
- ✅ Equivalent or better performance
- ✅ Lower maintenance burden
- ✅ Feature parity achieved

**Keep Custom Orchestrator IF:**
- ❌ LangChain adds significant overhead
- ❌ Migration effort outweighs benefits
- ❌ Performance degradation
- ❌ Loss of critical features
- ❌ Team prefers custom control

**Hybrid Approach IF:**
- 🔄 Some agents benefit from LangChain (e.g., Requirements with conversational memory)
- 🔄 State machine better with LangGraph
- 🔄 But core orchestration stays custom

---

## Next Steps

1. ✅ Create feature branch
2. ✅ Install dependencies
3. ⬜ Build Requirements Agent prototype with LangChain
4. ⬜ Implement 3-state StateGraph
5. ⬜ Test end-to-end
6. ⬜ Measure and document findings
7. ⬜ Make recommendation

---

## Useful Resources

- [LangChain Docs](https://python.langchain.com/docs/get_started/introduction)
- [LangGraph Docs](https://langchain-ai.github.io/langgraph/)
- [LangChain Multi-Agent Tutorial](https://python.langchain.com/docs/use_cases/agent_simulations/multi_agent)
- [LangGraph StateGraph Guide](https://langchain-ai.github.io/langgraph/tutorials/introduction/)
- [LangSmith Tracing](https://docs.smith.langchain.com/)

---

**Last Updated:** 2025-10-25
**Status:** 🚧 Experimental - Evaluation in progress
