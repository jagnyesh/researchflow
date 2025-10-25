# LangChain/LangGraph Orchestrator (Experimental)

🚧 **Status:** Experimental - Proof of Concept
🎯 **Purpose:** Evaluate Lang Chain/LangGraph as alternative to custom orchestrator

---

## Overview

This directory contains an experimental implementation of ResearchFlow's orchestrator using Lang Chain and LangGraph. This is a **parallel implementation** that runs alongside the existing custom orchestrator for comparison.

**Goal:** Determine if LangChain/LangGraph provides advantages over our custom solution.

---

## Architecture

### Current Custom Orchestrator (Baseline)

```
app/orchestrator/
├── orchestrator.py           # A2A coordinator (500+ lines)
└── workflow_engine.py         # 15-state FSM (300+ lines)

app/agents/
├── base_agent.py             # Base class with retry logic
├── requirements_agent.py
├── phenotype_agent.py
└── ... (4 more agents)
```

### LangChain Alternative (Experimental)

```
app/langchain_orchestrator/
├── __init__.py
├── README.md                  # This file
├── langgraph_workflow.py      # StateGraph (15 states)
├── langchain_agents.py        # Agent adapters
├── tools.py                   # MCP tool integrations
└── comparison.md              # Findings vs custom
```

---

## Key Questions to Answer

### 1. Code Complexity
- **Q:** Is LangGraph simpler than custom FSM?
- **Metric:** Lines of code, conceptual complexity

### 2. Performance
- **Q:** Does LangChain add overhead?
- **Metric:** Agent execution time, state transition latency

### 3. Maintainability
- **Q:** Is it easier to debug/extend with LangChain?
- **Metric:** Developer experience, tooling quality

### 4. Feature Parity
- **Q:** Can LangGraph support all our features?
- **Required:**
  - 15-state workflow
  - Human-in-loop approvals
  - Database persistence
  - Conditional routing
  - Error handling

---

## Implementation Approach

### Phase 1: Single Agent Prototype

**Goal:** Test LangChain concepts with 1 agent

**Files to Create:**
- `langchain_agents.py` - Requirements Agent wrapper
- `simple_workflow.py` - 3-state StateGraph

**What We're Testing:**
- LangChain AgentExecutor
- Tool calling
- Memory/conversation history
- LangGraph state transitions

### Phase 2: Full Workflow

**Goal:** Implement complete 15-state workflow

**Files to Create:**
- `langgraph_workflow.py` - Full StateGraph
- `tools.py` - MCP server tools
- `persistence.py` - Database integration

**What We're Testing:**
- All 6 agents
- Conditional routing
- Human-in-loop nodes
- Error handling
- Database persistence

### Phase 3: Comparison

**Goal:** Benchmark and decide

**Files to Create:**
- `comparison.md` - Findings document
- `benchmarks/` - Performance tests

**What We're Testing:**
- Side-by-side execution
- Performance metrics
- Code maintainability
- Migration effort

---

## Dependencies

```python
# Installed in feature branch
langchain>=1.0.0
langchain-core>=1.0.0
langchain-community>=0.4
langchain-anthropic>=1.0.0
langgraph>=1.0.0
langsmith>=0.4.0
```

---

## Usage

### Running Custom Orchestrator (Baseline)

```python
from app.orchestrator.orchestrator import ResearchRequestOrchestrator

orchestrator = ResearchRequestOrchestrator()
request_id = await orchestrator.process_new_request(
    researcher_request="I need diabetes patients...",
    researcher_info={...}
)
```

### Running LangChain Orchestrator (Experimental)

```python
# TBD - Will be similar API
from app.langchain_orchestrator import LangGraphOrchestrator

orchestrator = LangGraphOrchestrator()
request_id = await orchestrator.process_new_request(
    researcher_request="I need diabetes patients...",
    researcher_info={...}
)
```

---

## Comparison Metrics

We'll compare on these dimensions:

| Metric | Custom | LangChain | Winner |
|--------|--------|-----------|--------|
| Lines of Code | ~1000 | TBD | TBD |
| Execution Time | TBD | TBD | TBD |
| Memory Usage | TBD | TBD | TBD |
| Debug Ease | ⭐⭐⭐ | TBD | TBD |
| Maintainability | ⭐⭐⭐ | TBD | TBD |
| Learning Curve | Low | Medium | TBD |

---

## Decision Framework

**Migrate to LangChain IF:**
- ✅ 30%+ code reduction
- ✅ Better observability (LangSmith)
- ✅ Equivalent performance
- ✅ Feature parity

**Keep Custom IF:**
- ❌ Significant overhead
- ❌ Performance degradation
- ❌ Missing critical features
- ❌ High migration cost

**Hybrid Approach IF:**
- 🔄 Mix of both provides best results

---

## Testing

### Custom Orchestrator Tests (Baseline)

```bash
# All 21 tests passing
pytest tests/test_nlp_to_sql_workflow.py -v
pytest tests/test_admin_dashboard_updates.py -v
```

### LangChain Tests (To Be Created)

```bash
pytest tests/test_langchain_orchestrator.py -v
pytest tests/test_langgraph_workflow.py -v
```

---

## Documentation

- **Evaluation Plan:** `docs/LANGCHAIN_EVALUATION.md`
- **LangChain Docs:** https://python.langchain.com/
- **LangGraph Docs:** https://langchain-ai.github.io/langgraph/
- **Our Custom Orchestrator:** `docs/RESEARCHFLOW_README.md`

---

## Status

- [x] Feature branch created
- [x] Dependencies installed
- [x] Directory structure created
- [ ] Requirements Agent prototype
- [ ] Simple 3-state workflow
- [ ] Full 15-state workflow
- [ ] Performance benchmarks
- [ ] Comparison document
- [ ] Final recommendation

---

**Created:** 2025-10-25
**Branch:** `feature/langchain-langgraph-exploration`
**Status:** 🚧 Experimental
