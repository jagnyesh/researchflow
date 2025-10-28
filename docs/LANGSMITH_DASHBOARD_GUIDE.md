# LangSmith Observability Dashboard Guide

**Sprint 5 Deliverable** | **Updated:** 2025-10-26

This guide explains how to use the LangSmith dashboard to monitor and debug your ResearchFlow LangGraph workflow.

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Dashboard Overview](#dashboard-overview)
3. [Finding Your Traces](#finding-your-traces)
4. [Understanding Trace Hierarchy](#understanding-trace-hierarchy)
5. [Key Metrics to Monitor](#key-metrics-to-monitor)
6. [Filtering and Searching](#filtering-and-searching)
7. [Debugging with Traces](#debugging-with-traces)
8. [Cost Tracking](#cost-tracking)
9. [Best Practices](#best-practices)

---

## Getting Started

### Accessing LangSmith

1. **Visit:** https://smith.langchain.com
2. **Sign in** with your account
3. **Navigate to:** Projects → `researchflow-production`

### Project Configuration

Your ResearchFlow traces are sent to the `researchflow-production` project, configured in `.env`:

```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_PROJECT=researchflow-production
LANGCHAIN_API_KEY=lsv2_pt_...
```

---

## Dashboard Overview

### Main Dashboard Elements

When you open the `researchflow-production` project, you'll see:

1. **Run Count** - Total number of workflow executions
2. **Error Rate** - Percentage of failed runs (target: 0%)
3. **P50/P99 Latency** - Performance metrics (median and 99th percentile)
4. **Recent Runs** - List of latest workflow executions
5. **Feedback** - User-provided ratings (if configured)

### Project View

```
┌─────────────────────────────────────────────────────────┐
│  researchflow-production                                │
├─────────────────────────────────────────────────────────┤
│  Runs: 42    Error Rate: 2.4%    P50: 1.2s   P99: 7.8s │
├─────────────────────────────────────────────────────────┤
│  Recent Runs:                                           │
│  ✅ ResearchFlow_FullWorkflow  2025-10-26 14:37  0.09s  │
│  ✅ ResearchFlow_FullWorkflow  2025-10-26 13:22  0.11s  │
│  ❌ ResearchFlow_FullWorkflow  2025-10-26 12:15  2.34s  │
└─────────────────────────────────────────────────────────┘
```

---

## Finding Your Traces

### Identifying Workflow Runs

Each workflow execution creates a top-level trace with:

- **Name:** `ResearchFlow_FullWorkflow`
- **Type:** Chain
- **Tags:** `workflow`, `langgraph`, `research`
- **Environment Tag:** `e2e-test` OR `production`

### Request ID Mapping

Each trace includes metadata with the ResearchFlow request ID:

```json
{
  "request_id": "REQ-E2E-1761507426",
  "initial_state": "new_request",
  "researcher": "Dr. Smith",
  "timestamp": "2025-10-26T14:37:06.174669"
}
```

Use this to correlate LangSmith traces with requests in your database.

---

## Understanding Trace Hierarchy

### 3-Level Trace Architecture

ResearchFlow uses hierarchical tracing:

```
Level 1: Workflow Trace
└── ResearchFlow_FullWorkflow (@traceable on run() method)
    │
    ├── Level 2: Agent Traces
    │   ├── RequirementsAgent (@traceable on execute_task())
    │   │   └── Level 3: LLM Calls
    │   │       └── ChatAnthropic.ainvoke() [auto-traced]
    │   │
    │   ├── PhenotypeAgent (@traceable on execute_task())
    │   │   └── ChatAnthropic.ainvoke() [auto-traced]
    │   │
    │   ├── CalendarAgent (@traceable on execute_task())
    │   ├── ExtractionAgent (@traceable on execute_task())
    │   ├── QAAgent (@traceable on execute_task())
    │   └── DeliveryAgent (@traceable on execute_task())
    │       └── ChatAnthropic.ainvoke() [auto-traced]
```

### Example Trace View

When you click on a workflow trace, you'll see:

```
ResearchFlow_FullWorkflow (90ms) ✅
├─ RequirementsAgent (45ms) ✅
│  └─ ChatAnthropic (42ms) ✅
│     Input: 3,245 tokens
│     Output: 512 tokens
│     Cost: $0.0234
├─ PhenotypeAgent (12ms) ✅
│  └─ ChatAnthropic (10ms) ✅
│     Input: 2,100 tokens
│     Output: 324 tokens
│     Cost: $0.0156
├─ CalendarAgent (8ms) ✅
├─ ExtractionAgent (6ms) ✅
├─ QAAgent (5ms) ✅
└─ DeliveryAgent (14ms) ✅
   └─ ChatAnthropic (11ms) ✅
      Input: 1,850 tokens
      Output: 278 tokens
      Cost: $0.0142
```

---

## Key Metrics to Monitor

### 1. Workflow Performance

**Where:** Top-level `ResearchFlow_FullWorkflow` trace

**Metrics:**
- **Duration:** Total workflow execution time (target: < 10 seconds)
- **Status:** Success/Failure
- **State Transitions:** Number of states executed (typical: 8-11 states)

**What to Watch:**
- ⚠️ Duration > 30 seconds → Investigate slow agents
- ❌ Failure rate > 5% → Check error logs
- 🔍 State count anomalies → Workflow logic issues

### 2. Agent Performance

**Where:** Individual agent traces (RequirementsAgent, PhenotypeAgent, etc.)

**Metrics:**
- **Agent Duration:** Time spent in each agent (typical: 5-50ms for non-LLM agents)
- **Task Success Rate:** Percentage of successful agent executions
- **Error Messages:** Exception details if agent fails

**What to Watch:**
- ⚠️ RequirementsAgent > 60s → LLM timeout or complex conversation
- ⚠️ PhenotypeAgent > 30s → SQL generation taking too long
- ❌ Agent errors → Check agent logs for root cause

### 3. LLM Usage & Costs

**Where:** `ChatAnthropic` child traces (auto-traced by LangChain)

**Metrics:**
- **Token Counts:** Input + Output tokens per call
- **Cost:** Per-call and cumulative costs
- **Latency:** LLM API response time
- **Model:** Which Claude model was used

**What to Watch:**
- 💰 Cost > $1 per workflow → Optimize prompts or use smaller models
- ⚠️ Input tokens > 10,000 → Context too large, consider summarization
- 🕐 Latency > 20s → API throttling or network issues

### 4. Error Tracking

**Where:** Failed traces (marked with ❌)

**Information Captured:**
- **Exception Type:** Python exception class
- **Stack Trace:** Full traceback for debugging
- **State at Failure:** Which workflow state caused the error
- **Request Context:** request_id, researcher, requirements

**What to Watch:**
- 🔍 Repeated errors → Systemic issue requiring code fix
- 🔍 Intermittent failures → Network or API issues
- 🔍 Terminal states (`not_feasible`, `qa_failed`) → Expected workflow outcomes

---

## Filtering and Searching

### Using Tags

ResearchFlow uses consistent tagging for easy filtering:

**Filter by Environment:**
```
Tag: e2e-test     → E2E test runs only
Tag: production   → Production workflow runs
```

**Filter by Component:**
```
Tag: workflow     → Top-level workflow traces
Tag: agent        → Agent-level traces
Tag: requirements → Requirements Agent only
Tag: phenotype    → Phenotype Agent only
Tag: llm          → LLM-based agents only
```

### Advanced Filters

**Time Range:**
- Last 1 hour → Recent test runs
- Last 24 hours → Daily monitoring
- Last 7 days → Weekly trends

**Status:**
- Success only → Healthy workflows
- Errors only → Debugging failures
- By duration → Performance issues

**Metadata Search:**
```
request_id: "REQ-12345"         → Find specific request
researcher: "Dr. Smith"         → Filter by researcher
initial_state: "new_request"    → Workflow entry point
```

---

## Debugging with Traces

### Scenario 1: Workflow Fails at Feasibility Stage

**Steps:**
1. Filter traces by Tag: `phenotype` and Status: `error`
2. Click on failed PhenotypeAgent trace
3. Expand to see:
   - Input context (requirements)
   - SQL generation output
   - Error stack trace
4. Check metadata for `estimated_cohort_size` and `feasible` flag
5. Investigate:
   - Was SQL invalid? → Check SQL generator logic
   - Was cohort size = 0? → Requirements too restrictive
   - Did LLM timeout? → Check LLM latency metrics

### Scenario 2: Slow Workflow Execution

**Steps:**
1. Find slow trace (duration > 30s)
2. Expand full trace hierarchy
3. Sort child traces by duration (longest first)
4. Identify bottleneck:
   - If RequirementsAgent is slow → LLM conversation taking too long
   - If ExtractionAgent is slow → Data retrieval issue (FHIR API, DB query)
   - If QAAgent is slow → Large dataset validation
5. Optimize the bottleneck component

### Scenario 3: Unexpected State Transitions

**Steps:**
1. Find trace with unexpected final state
2. Check metadata:
   - `current_state`: Final workflow state
   - `initial_state`: Starting state
3. Look for:
   - Terminal states (`not_feasible`, `qa_failed`) → Expected workflow outcomes
   - Approval gates → Check `*_approved` flags in metadata
4. Review routing logic in `langgraph_workflow.py`

---

## Cost Tracking

### Viewing LLM Costs

**Per-Trace Costs:**
1. Click on workflow trace
2. Expand LLM child traces (`ChatAnthropic`)
3. Each trace shows:
   - Input tokens × rate
   - Output tokens × rate
   - Total cost for that call

**Cumulative Costs:**
- LangSmith automatically sums costs across all LLM calls in a trace
- View totals at the workflow level

### Cost Optimization Tips

**1. Reduce Token Usage:**
- ✅ Use smaller prompts (remove unnecessary context)
- ✅ Summarize long conversation histories
- ✅ Use structured outputs instead of verbose responses

**2. Use Appropriate Models:**
- ✅ Critical tasks (Requirements, Phenotype) → Claude 3.5 Sonnet
- ✅ Non-critical tasks (Calendar, Delivery) → Cheaper models (Haiku, Ollama)
- ✅ Enable multi-provider LLM fallback (already configured)

**3. Batch Operations:**
- ✅ Combine multiple small LLM calls into one larger call
- ✅ Cache frequently used prompts/responses

**Expected Costs:**
- Typical workflow: $0.05 - $0.15 per request
- Complex conversations: $0.20 - $0.50 per request
- Monthly (1000 requests): $50 - $150

---

## Best Practices

### 1. Tagging Strategy

**Always Include:**
- Environment tag (`e2e-test` or `production`)
- Component type tag (`workflow`, `agent`)
- Specific agent tag (`requirements`, `phenotype`, etc.)

**Optional Tags:**
- User ID or researcher name
- Feature flags (`multi-llm-enabled`, `cache-enabled`)
- Deployment version (`v1.0.0`, `staging`)

### 2. Metadata Best Practices

**Include in Workflow Metadata:**
- `request_id`: Unique request identifier
- `researcher`: Researcher name or ID
- `timestamp`: Execution start time
- `version`: Workflow version
- `duration_ms`: Total execution time

**Include in Agent Metadata:**
- `agent_type`: Agent category
- `task`: Task being executed
- `llm`: Model used (if LLM-based)
- `capability`: Agent capability description

### 3. Monitoring Cadence

**Daily:**
- Check error rate (target: < 2%)
- Review slow workflows (> 30s)
- Monitor LLM costs (daily budget)

**Weekly:**
- Analyze P50/P99 latency trends
- Review most expensive workflows
- Identify optimization opportunities

**Monthly:**
- Cumulative cost analysis
- Performance regression testing
- User feedback correlation

### 4. Alert Setup (Future Enhancement)

**Recommended Alerts:**
- ❌ Error rate > 5% in last hour
- ⏱️ P99 latency > 60 seconds
- 💰 Daily cost > $100
- 🔥 Specific agent failure rate > 10%

**How to Set Up:**
1. LangSmith Settings → Alerts
2. Configure threshold and notification channel
3. Test alert with intentional failure

---

## Troubleshooting

### Traces Not Appearing

**Issue:** No traces showing up in `researchflow-production` project

**Solutions:**
1. Check `.env` configuration:
   ```bash
   LANGCHAIN_TRACING_V2=true
   LANGCHAIN_PROJECT=researchflow-production
   LANGCHAIN_API_KEY=lsv2_pt_...
   ```
2. Verify API key is valid (test with `langsmith.Client()`)
3. Check for firewall blocking `api.smith.langchain.com`
4. Wait 5-10 seconds for traces to appear (async upload)
5. Refresh dashboard page

### Missing LLM Traces

**Issue:** Agent traces appear but no LLM child traces

**Solutions:**
1. Ensure `LANGCHAIN_TRACING_V2=true` is set BEFORE importing LangChain
2. Verify using `ChatAnthropic` from `langchain_anthropic`
3. Check that LLM is actually being called (not cached/mocked)

### High Costs

**Issue:** LLM costs higher than expected

**Solutions:**
1. Review token counts per trace
2. Check for repeated/redundant LLM calls
3. Optimize prompts to reduce input tokens
4. Use cheaper models for non-critical tasks
5. Enable caching for repeated queries

---

## Next Steps

### Explore Advanced Features

1. **Custom Dashboards** - Create project-specific views
2. **Datasets** - Save test cases for regression testing
3. **Evaluators** - Automate quality checks on LLM outputs
4. **Feedback** - Collect user ratings on workflow results
5. **Annotations** - Add notes to traces for team collaboration

### Resources

- **LangSmith Docs:** https://docs.smith.langchain.com
- **LangChain Tracing:** https://python.langchain.com/docs/langsmith/walkthrough
- **ResearchFlow Architecture:** `docs/RESEARCHFLOW_README.md`
- **Sprint 5 Plan:** `docs/sprints/SPRINT_05_LANGSMITH_OBSERVABILITY.md`

---

## Summary

LangSmith provides comprehensive observability for your ResearchFlow workflow:

✅ **Workflow Visibility** - See every execution from start to finish
✅ **Agent Performance** - Track individual agent execution times
✅ **LLM Monitoring** - Monitor token usage, costs, and latency
✅ **Error Tracking** - Debug failures with full stack traces
✅ **Cost Control** - Understand and optimize LLM expenses

**Key Takeaway:** Use LangSmith daily to monitor production workflows and ensure ResearchFlow is running smoothly and cost-effectively.

---

**Updated:** 2025-10-26 | **Sprint:** 5 | **Status:** ✅ Complete
