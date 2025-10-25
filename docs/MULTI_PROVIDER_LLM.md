# Multi-Provider LLM Implementation

## Overview

ResearchFlow now supports multiple LLM providers through a hybrid architecture that intelligently routes tasks based on criticality:

- **Critical medical tasks** (requirements extraction, SQL generation) → Always use Claude
- **Non-critical tasks** (calendar, delivery notifications) → Use configurable secondary provider
- **Automatic fallback** → Falls back to Claude if secondary provider fails

This implementation uses [AI Suite](https://github.com/andrewyng/aisuite) for unified multi-provider access.

---

## Architecture

### Two-Client System

1. **LLMClient** (`app/utils/llm_client.py`)
   - Direct Claude API integration
   - Used by critical agents: Requirements, Phenotype, QA
   - Medical domain expertise and accuracy

2. **MultiLLMClient** (`app/utils/multi_llm_client.py`)
   - Multi-provider routing via AI Suite
   - Used by non-critical agents: Calendar, Delivery
   - Cost optimization and flexibility

### Task Routing Logic

```python
# Critical tasks → Always Claude
CRITICAL_TASK_TYPES = ["requirements", "phenotype", "medical", "sql_generation"]

# Non-critical tasks → Secondary provider (if configured)
NON_CRITICAL_TASK_TYPES = ["calendar", "delivery", "notification", "scheduling"]
```

### Agent Mapping

| Agent | Client | Rationale |
|-------|--------|-----------|
| Requirements | LLMClient (Claude only) | Medical accuracy critical |
| Phenotype | LLMClient (Claude only) | SQL generation precision |
| QA | LLMClient (Claude only) | Quality validation accuracy |
| Calendar | MultiLLMClient | Agenda generation non-critical |
| Delivery | MultiLLMClient | Notifications non-critical |
| Extraction | N/A | No LLM usage |

---

## Configuration

### Environment Variables

Add to `.env` file:

```bash
# Required: Primary LLM for critical tasks
ANTHROPIC_API_KEY=sk-ant-api03-your-key-here

# Optional: Secondary provider for non-critical tasks
SECONDARY_LLM_PROVIDER=anthropic  # Options: anthropic, openai, ollama
OPENAI_API_KEY=sk-your-openai-key  # Only if using OpenAI
OLLAMA_BASE_URL=http://localhost:11434  # Only if using Ollama
SECONDARY_LLM_MODEL=gpt-4o  # Model name for secondary provider
ENABLE_LLM_FALLBACK=true  # Auto-fallback to Claude on errors
```

### Provider Options

**1. Anthropic (Default)**
```bash
SECONDARY_LLM_PROVIDER=anthropic
# All tasks use Claude - no additional setup needed
```

**2. OpenAI**
```bash
SECONDARY_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-...
SECONDARY_LLM_MODEL=gpt-4o  # or gpt-4-turbo, gpt-3.5-turbo
```

**3. Ollama (Local)**
```bash
# Install: brew install ollama (macOS) or curl https://ollama.ai/install.sh | sh
ollama serve
ollama pull llama3

SECONDARY_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
SECONDARY_LLM_MODEL=llama3  # or mistral, codellama
```

---

## Implementation Details

### Calendar Agent Changes

**File:** `app/agents/calendar_agent.py`

**Changes:**
1. Added `MultiLLMClient` import and initialization
2. Updated `_generate_meeting_agenda()` to use LLM for intelligent agenda generation
3. Fallback to template if LLM fails

**Example:**
```python
from ..utils.multi_llm_client import MultiLLMClient

class CalendarAgent(BaseAgent):
    def __init__(self, orchestrator=None):
        super().__init__(agent_id="calendar_agent", orchestrator=orchestrator)
        self.llm_client = MultiLLMClient()

    async def _generate_meeting_agenda(self, requirements, feasibility_report):
        # Uses secondary provider for agenda generation
        agenda = await self.llm_client.complete(
            prompt=prompt,
            task_type="calendar",  # Non-critical
            temperature=0.7
        )
```

### Delivery Agent Changes

**File:** `app/agents/delivery_agent.py`

**Changes:**
1. Added `MultiLLMClient` import and initialization
2. Updated `_generate_citation_info()` to use LLM
3. Updated `_send_notification()` to generate personalized emails
4. Fallback to templates if LLM fails

**Example:**
```python
async def _send_notification(self, recipient, email, delivery_info):
    # Generate personalized notification
    message = await self.llm_client.complete(
        prompt=prompt,
        task_type="delivery",  # Non-critical
        temperature=0.7
    )
```

---

## Testing

### Run Tests

```bash
# Run all tests
pytest tests/test_multi_llm_client.py -v

# Run specific test class
pytest tests/test_multi_llm_client.py::TestCompleteMethod -v

# Run with coverage
pytest tests/test_multi_llm_client.py --cov=app.utils.multi_llm_client
```

### Test Coverage

The test suite covers:
- ✅ Initialization with different providers
- ✅ Model identifier selection based on task type
- ✅ Critical tasks routing to Claude
- ✅ Non-critical tasks routing to secondary provider
- ✅ Automatic fallback on errors
- ✅ Fallback disable behavior
- ✅ JSON parsing and extraction
- ✅ Wrapper methods delegation
- ✅ Agent integration

---

## Usage Examples

### Example 1: Default Setup (Claude Only)

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-api03-xxx
SECONDARY_LLM_PROVIDER=anthropic
```

**Result:** All agents use Claude. No additional cost or setup.

### Example 2: OpenAI for Non-Critical Tasks

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-api03-xxx
SECONDARY_LLM_PROVIDER=openai
OPENAI_API_KEY=sk-xxx
SECONDARY_LLM_MODEL=gpt-4o
```

**Result:**
- Requirements Agent → Claude (medical accuracy)
- Phenotype Agent → Claude (SQL precision)
- Calendar Agent → GPT-4o (agenda generation)
- Delivery Agent → GPT-4o (notifications)

### Example 3: Local Development with Ollama

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-api03-xxx
SECONDARY_LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
SECONDARY_LLM_MODEL=llama3
```

**Result:**
- Requirements/Phenotype → Claude (API calls)
- Calendar/Delivery → Local Llama 3 (no API costs)

---

## Cost Analysis

### Scenario: 100 Data Requests/Month

**Claude Only (Default):**
- Requirements: ~500K tokens × $15/1M = $7.50
- Phenotype: ~200K tokens × $15/1M = $3.00
- Calendar: ~100K tokens × $15/1M = $1.50
- Delivery: ~100K tokens × $15/1M = $1.50
- **Total: ~$13.50/month**

**Hybrid (Claude + GPT-4o):**
- Requirements: ~500K tokens × $15/1M = $7.50
- Phenotype: ~200K tokens × $15/1M = $3.00
- Calendar: ~100K tokens × $5/1M = $0.50
- Delivery: ~100K tokens × $5/1M = $0.50
- **Total: ~$11.50/month** (15% savings)

**Hybrid (Claude + Ollama):**
- Requirements: ~500K tokens × $15/1M = $7.50
- Phenotype: ~200K tokens × $15/1M = $3.00
- Calendar: Local (free)
- Delivery: Local (free)
- **Total: ~$10.50/month** (22% savings)

---

## Troubleshooting

### Issue: "aisuite not installed"

**Solution:**
```bash
pip install -r config/requirements.txt
# Or specifically:
pip install aisuite==0.1.6
```

### Issue: OpenAI provider fails

**Symptoms:** Logs show "Error with openai:gpt-4o"

**Solutions:**
1. Check API key: `echo $OPENAI_API_KEY`
2. Verify model name: `SECONDARY_LLM_MODEL=gpt-4o` (not `gpt4o`)
3. Check if fallback is working (should auto-switch to Claude)

### Issue: Ollama connection refused

**Symptoms:** "Failed to connect to http://localhost:11434"

**Solutions:**
```bash
# Start Ollama server
ollama serve

# Pull model
ollama pull llama3

# Test connection
curl http://localhost:11434/api/tags
```

### Issue: All tasks using Claude despite secondary provider config

**Cause:** AI Suite initialization failed

**Check logs:**
```bash
# Look for these messages:
# "AI Suite initialized for provider: openai" ✅ Working
# "aisuite not installed - falling back to Claude" ❌ Install AI Suite
# "OPENAI_API_KEY not set - falling back to Claude" ❌ Add API key
```

---

## Future Enhancements

### Potential Additions

1. **Provider Selection in UI**
   - Add dropdown in Research Notebook
   - Let researchers choose model for feasibility checks

2. **Cost Tracking**
   - Log API calls per provider
   - Generate cost reports per request

3. **Performance Metrics**
   - Track latency per provider
   - Compare quality scores

4. **Additional Providers**
   - AWS Bedrock
   - Azure OpenAI
   - Google Vertex AI
   - Cohere

5. **Smart Routing**
   - Auto-select cheapest model based on prompt complexity
   - Load balancing across providers

---

## References

- [AI Suite GitHub](https://github.com/andrewyng/aisuite)
- [Anthropic API Docs](https://docs.anthropic.com/claude/reference/getting-started-with-the-api)
- [OpenAI API Docs](https://platform.openai.com/docs/api-reference)
- [Ollama Docs](https://ollama.ai/docs)

---

## Summary

The multi-provider LLM implementation provides:

✅ **Safety:** Critical medical tasks stay on Claude
✅ **Flexibility:** Choose provider for non-critical tasks
✅ **Cost Savings:** 15-22% reduction in LLM costs
✅ **Reliability:** Automatic fallback prevents failures
✅ **Developer Experience:** Local Ollama for offline dev
✅ **Production Ready:** Comprehensive tests and error handling

Questions? See `docs/SETUP_GUIDE.md` or `CLAUDE.md` for more details.
