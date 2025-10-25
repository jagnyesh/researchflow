# ResearchFlow Demo Guide

Complete step-by-step instructions to demo the ResearchFlow proof of concept.

## Prerequisites

- Python 3.10+ installed
- Terminal access
- Web browser
- ANTHROPIC_API_KEY set in `.env` file

## Quick Start (3 Terminals Method)

### Terminal 1: Start the Researcher Portal

```bash
# From project root
cd /Users/jagnyesh/Development/FHIR_PROJECT

# Activate virtual environment
source .venv/bin/activate

# Run Researcher Portal on port 8501
streamlit run app/web_ui/researcher_portal.py --server.port 8501
```

**Expected Output:**
```
You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8501
  Network URL: http://192.168.x.x:8501
```

**Browser:** Opens automatically at http://localhost:8501

---

### Terminal 2: Start the Admin Dashboard

```bash
# From project root (NEW TERMINAL)
cd /Users/jagnyesh/Development/FHIR_PROJECT

# Activate virtual environment
source .venv/bin/activate

# Run Admin Dashboard on port 8502
streamlit run app/web_ui/admin_dashboard.py --server.port 8502
```

**Expected Output:**
```
You can now view your Streamlit app in your browser.

  Local URL: http://localhost:8502
  Network URL: http://192.168.x.x:8502
```

**Browser:** Open manually at http://localhost:8502

---

### Terminal 3: Start the FastAPI Backend (Optional)

```bash
# From project root (NEW TERMINAL)
cd /Users/jagnyesh/Development/FHIR_PROJECT

# Activate virtual environment
source .venv/bin/activate

# Run FastAPI server
make run
# OR: uvicorn app.main:app --reload --port 8000
```

**Expected Output:**
```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process
INFO:     Started server process
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**Browser:** API docs at http://localhost:8000/docs

---

## Understanding the Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Your Local Machine                    │
├─────────────────────────────────────────────────────────┤
│                                                           │
│  Terminal 1              Terminal 2           Terminal 3  │
│  ┌─────────────┐        ┌─────────────┐     ┌─────────┐ │
│  │ Streamlit   │        │ Streamlit   │     │ FastAPI │ │
│  │ Process 1   │        │ Process 2   │     │ Server  │ │
│  │             │        │             │     │         │ │
│  │ researcher_ │        │ admin_      │     │ API     │ │
│  │ portal.py   │        │ dashboard.py│     │ Backend │ │
│  └─────────────┘        └─────────────┘     └─────────┘ │
│       │                      │                    │      │
│       ↓                      ↓                    ↓      │
│   Port 8501             Port 8502            Port 8000   │
│                                                           │
└─────────────────────────────────────────────────────────┘
         │                      │                    │
         ↓                      ↓                    ↓
    Web Browser           Web Browser          API Clients
    (Researchers)      (Administrators)      (Optional)
```

---

## Demo Scenario: Submit and Track a Research Request

### Step 1: Researcher Submits Request (Port 8501)

1. **Open Researcher Portal:** http://localhost:8501
2. **Fill out the form:**
   - **Project Title:** "Diabetes Medication Adherence Study"
   - **Initial Request:** "I need patients with Type 2 Diabetes on Metformin, aged 40-65, who had at least 2 A1C measurements in the past year"
   - **Contact Email:** your.email@example.com
   - Click **Submit Request**

3. **Watch the Conversation:**
   - Requirements Agent will ask clarifying questions
   - Answer questions like:
     - "What time period?" → "January 2023 to December 2023"
     - "PHI level needed?" → "Limited dataset (no names/addresses)"
     - "Additional data elements?" → "Demographics, medications, lab results"

4. **View Progress:**
   - Workflow moves through states: `requirements_gathering` → `requirements_review` → `feasibility_validation`

### Step 2: Administrator Reviews Request (Port 8502)

1. **Open Admin Dashboard:** http://localhost:8502
2. **Navigate to "Pending Approvals" tab**
3. **See the request waiting for review:**
   - Request ID
   - Current state: `REQUIREMENTS_REVIEW` or `PHENOTYPE_REVIEW`
   - Generated SQL query (if in phenotype review)

4. **Review and Approve:**
   - Click "View Details"
   - Review the requirements or SQL query
   - Click "Approve" or "Reject with feedback"

5. **Monitor System Metrics:**
   - Go to "System Metrics" tab
   - See agent execution counts
   - View success/failure rates
   - Check average execution times

### Step 3: Track Request Progress (Port 8501)

1. **Back to Researcher Portal:** http://localhost:8501
2. **Navigate to "Track Requests" tab**
3. **View your request status:**
   - Current workflow state
   - Execution history (which agents ran)
   - Feasibility report (if generated)
   - Estimated completion time

---

## Key Features to Demo

### Researcher Portal (8501) Features:

✅ **Natural Language Request Submission**
- Type free-form research questions
- AI extracts structured requirements

✅ **Conversational Requirements Gathering**
- LLM asks clarifying questions
- Iterative refinement of criteria

✅ **Real-time Request Tracking**
- See current workflow state
- View agent execution history
- Track progress through 20+ states

✅ **Feasibility Reports**
- Estimated cohort size
- Data availability assessment
- Feasibility score (0.0-1.0)

### Admin Dashboard (8502) Features:

✅ **Approval Workflows**
- Review extracted requirements
- Approve/reject SQL queries
- Authorize data extractions
- Validate QA results

✅ **System Monitoring**
- Agent execution metrics
- Success/failure rates
- Performance statistics
- System health

✅ **Escalation Management**
- View requests needing human review
- Handle errors and edge cases
- Manage scope changes

✅ **Audit Trail**
- Complete execution history
- Who approved what and when
- State transition logs

---

## Common Issues and Troubleshooting

### Issue 1: Port Already in Use

**Error:** `OSError: [Errno 48] Address already in use`

**Solution:**
```bash
# Find process using the port
lsof -i :8501  # or 8502, 8000

# Kill the process
kill -9 <PID>

# Or use a different port
streamlit run app/web_ui/researcher_portal.py --server.port 8503
```

### Issue 2: Module Import Errors

**Error:** `ModuleNotFoundError: No module named 'app'`

**Solution:**
```bash
# Make sure you're running from project root
pwd  # Should show: /Users/jagnyesh/Development/FHIR_PROJECT

# Make sure virtual environment is activated
source .venv/bin/activate

# Verify packages installed
pip list | grep streamlit
```

### Issue 3: Missing ANTHROPIC_API_KEY

**Error:** `No ANTHROPIC_API_KEY found in environment`

**Solution:**
```bash
# Check .env file exists
cat .env | grep ANTHROPIC_API_KEY

# Should show:
# ANTHROPIC_API_KEY=sk-ant-api03-...

# If missing, copy from template
cp config/.env.example .env
# Edit .env and add your key
```

### Issue 4: Database Errors

**Error:** `sqlalchemy.exc.OperationalError: unable to open database file`

**Solution:**
```bash
# Initialize database (creates dev.db)
python -c "from app.database import init_db; import asyncio; asyncio.run(init_db())"

# Or just run one of the UIs - they auto-initialize
```

### Issue 5: Streamlit Shows "Please wait..."

**Issue:** UI loads but shows loading spinner indefinitely

**Solution:**
- Check terminal for error messages
- Ensure ANTHROPIC_API_KEY is valid
- Try refreshing the browser (Ctrl+R or Cmd+R)
- Check if virtual environment is activated

---

## Alternative: Docker Demo (Single Command)

If you want everything running automatically:

```bash
# Start all services (backend + postgres + FHIR server)
make docker-up
# OR: docker-compose -f config/docker-compose.yml up --build
```

**Note:** Docker setup does NOT include Streamlit UIs currently. You'll still need to run those manually:

```bash
# Terminal 1
streamlit run app/web_ui/researcher_portal.py --server.port 8501

# Terminal 2
streamlit run app/web_ui/admin_dashboard.py --server.port 8502
```

---

## Minimal Demo (Just Streamlit UIs)

If you only want to demo the UIs without the full backend:

```bash
# Terminal 1: Researcher Portal
streamlit run app/web_ui/researcher_portal.py --server.port 8501

# Terminal 2: Admin Dashboard
streamlit run app/web_ui/admin_dashboard.py --server.port 8502
```

The Streamlit apps have **embedded orchestrator** - they work standalone without needing the FastAPI backend running.

---

## What to Show in Your Demo

### For Technical Audiences:

1. **Multi-Agent Orchestration**
   - Show agent execution logs in Admin Dashboard
   - Explain state transitions in workflow
   - Point out approval gates (human-in-loop)

2. **LLM Integration**
   - Demo conversational requirements extraction
   - Show how AI asks clarifying questions
   - Display structured output (JSON requirements)

3. **SQL-on-FHIR Generation**
   - Show generated SQL in Admin Dashboard
   - Explain how natural language → SQL query
   - Point out validation/approval step

4. **Architecture Diagrams**
   - Open `diagrams/ResearchFlow Architecture.png`
   - Walk through 7 agents and their roles
   - Explain orchestrator coordination

### For Non-Technical Audiences:

1. **Time Savings**
   - "This used to take weeks, now takes hours"
   - Show the simple researcher interface
   - Contrast with manual process complexity

2. **Quality Assurance**
   - Show approval workflows in Admin Dashboard
   - Emphasize "humans still validate everything"
   - Point out QA validation step

3. **Transparency**
   - Show request tracking in Researcher Portal
   - Display workflow state visibility
   - Demonstrate audit trail

---

## Post-Demo: Shutting Down

### Stop Streamlit Apps:

In each terminal running Streamlit:
```bash
Ctrl+C  # or Cmd+C on Mac
```

### Stop FastAPI Server:

```bash
Ctrl+C  # in the terminal running uvicorn
```

### Stop Docker (if used):

```bash
docker-compose -f config/docker-compose.yml down
```

---

## Quick Reference: All URLs

| Service | URL | Purpose |
|---------|-----|---------|
| Researcher Portal | http://localhost:8501 | Submit and track requests |
| Admin Dashboard | http://localhost:8502 | Monitor and approve requests |
| FastAPI Docs | http://localhost:8000/docs | API documentation (optional) |
| HAPI FHIR Server | http://localhost:8081/fhir | FHIR data server (Docker only) |

---

## Next Steps After Demo

1. **Show GitHub Repository:**
   - https://github.com/jagnyesh/researchflow
   - Point out documentation in `docs/`
   - Highlight MIT license

2. **Discuss Production Requirements:**
   - Reference `docs/GAP_ANALYSIS_AND_ROADMAP.md`
   - Explain 8-month roadmap to production
   - Identify integration points (Epic, IRB systems, etc.)

3. **Gather Feedback:**
   - What workflows resonate?
   - What features are most valuable?
   - What's missing for their use case?

---

## Pro Tips

💡 **Open both UIs side-by-side:** Arrange browser windows so you can see researcher actions trigger admin notifications

💡 **Use realistic data:** Copy actual research questions from your work experience for authenticity

💡 **Emphasize the meta-story:** "I used AI coding tools to build this AI system"

💡 **Show the code:** Open `app/agents/requirements_agent.py` to show how simple the LLM integration is

💡 **Highlight open source:** "Anyone can use this, modify it, learn from it - MIT licensed"
