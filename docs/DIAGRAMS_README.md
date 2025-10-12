# ResearchFlow Architecture Diagrams

This directory contains PlantUML diagrams showing the system architecture and data flow.

## Available Diagrams

### 1. `architecture.puml` - Complete Architecture & Data Flow
**Shows:** All modules, connections, and numbered data flow steps (1-24)

**Key sections:**
- User Interfaces (Researcher Portal, Admin Dashboard)
- Orchestration Layer (Orchestrator, Workflow Engine)
- 6 Specialized Agents
- MCP Server Infrastructure
- Database Layer (6 tables)
- External Systems
- Complete data flow from request to delivery

### 2. `sequence_flow.puml` - Sequence Diagram
**Shows:** Step-by-step interaction between components over time

**Phases:**
1. Request Submission
2. Requirements Gathering (LLM)
3. Phenotype Validation
4. Calendar Scheduling
5. Data Extraction
6. Quality Assurance
7. Data Delivery
8. Completion

### 3. `components.puml` - Component Diagram
**Shows:** High-level component relationships and dependencies

**Layers:**
- Frontend Layer (Streamlit UIs)
- Core Orchestration (Orchestrator, Workflow Engine)
- Agent Layer (6 agents)
- Utilities & Services
- MCP Servers
- Data Layer (Database)
- External Systems

## How to View

### Option 1: Online PlantUML Server (Easiest)

1. Go to http://www.plantuml.com/plantuml/uml/
2. Copy the contents of any `.puml` file
3. Paste into the text box
4. Click "Submit" to render

### Option 2: VS Code Extension

1. Install "PlantUML" extension in VS Code
2. Open any `.puml` file
3. Press `Alt+D` (Windows/Linux) or `Option+D` (Mac) to preview
4. Or right-click → "Preview Current Diagram"

### Option 3: Command Line

```bash
# Install PlantUML
brew install plantuml # macOS
# or download from https://plantuml.com/download

# Generate PNG images
plantuml architecture.puml
plantuml sequence_flow.puml
plantuml components.puml

# This creates:
# - architecture.png
# - sequence_flow.png
# - components.png
```

### Option 4: IntelliJ/PyCharm Plugin

1. Install "PlantUML integration" plugin
2. Open `.puml` file
3. View diagram in side panel

### Option 5: Online Editors

- **PlantText:** https://www.planttext.com/
- **PlantUML QEditor:** https://plantuml-editor.kkeisuke.com/
- **Gravizo:** http://gravizo.com/

## Diagram Explanations

### Architecture Diagram Key Points

**Data Flow Trace:**
1. Researcher submits request via UI
2. Orchestrator initializes workflow (state: NEW_REQUEST)
3. Routes to Requirements Agent
4. LLM extracts structured requirements via Claude API
5. Terminology server maps medical concepts to codes
6. Requirements saved to database
7. Routes to Phenotype Agent
8. SQL Generator creates phenotype query
9. SQL Adapter executes COUNT query on data warehouse
10. Feasibility report generated and saved
11. Routes to Calendar Agent (schedules meeting)
12. Routes to Extraction Agent
13-17. Multi-source data extraction (Epic, FHIR servers)
18-20. QA Agent validates quality
21-24. Delivery Agent packages and delivers data

**Color Legend:**
- Blue: Agents
- Gold: Orchestrator
- Green: Database
- 🟠 Orange: MCP Servers
- 🟣 Pink: User Interfaces
- Gray: External Systems

### Sequence Diagram Key Points

Shows **8 phases** of request processing:
- Each phase shows specific API calls and data exchanges
- Timing from submission to delivery: ~23 minutes
- Shows state transitions (e.g., NEW_REQUEST → REQUIREMENTS_GATHERING → ...)
- Highlights agent-to-agent communication

### Component Diagram Key Points

Shows **architectural layers:**
1. Frontend (2 Streamlit apps)
2. Orchestration (coordinator + state machine)
3. Agents (6 specialized agents)
4. Services (LLM, SQL, adapters)
5. MCP (3 server implementations)
6. Data (6 database tables)
7. External (Claude API, data warehouse)

## Understanding the Flow

### Simple Flow Summary:

```
User Request
 ↓
Requirements Agent (LLM conversation)
 ↓
Phenotype Agent (SQL generation + feasibility)
 ↓
Calendar Agent (meeting scheduling)
 ↓
Extraction Agent (multi-source data retrieval)
 ↓
QA Agent (quality validation)
 ↓
Delivery Agent (packaging + notification)
 ↓
Data Delivered
```

### Agent-to-Agent (A2A) Communication:

Each agent:
1. Receives task from orchestrator
2. Executes task with error handling
3. Returns result with `next_agent` and `next_task`
4. Orchestrator routes to next agent
5. Workflow engine manages state transitions

### Workflow States (15 total):

1. `new_request` - Initial submission
2. `requirements_gathering` - LLM conversation
3. `requirements_complete` - Structured data extracted
4. `feasibility_validation` - Checking if feasible
5. `feasible` / `not_feasible` - Validation result
6. `schedule_kickoff` - Calendar scheduling
7. `kickoff_complete` - Meeting scheduled
8. `data_extraction` - Retrieving data
9. `extraction_complete` - Data retrieved
10. `qa_validation` - Quality checks
11. `qa_passed` / `qa_failed` - QA result
12. `data_delivery` - Packaging data
13. `delivered` - Data sent to researcher
14. `complete` - Workflow finished
15. `failed` / `human_review` - Error states

## NOTE: Tips

1. **Start with `components.puml`** - Get high-level overview
2. **Then view `sequence_flow.puml`** - See step-by-step interaction
3. **Finally `architecture.puml`** - Complete detailed view

4. **To trace a specific data element:**
 - Find it in sequence diagram
 - Follow the arrows chronologically
 - See which agents transform it
 - Track database saves

5. **To understand agent responsibilities:**
 - Look at component diagram
 - See which services each agent uses
 - Follow connections to database tables

## Updating Diagrams

If you modify the code, update corresponding diagrams:

```bash
# After changing agent logic
# Update: sequence_flow.puml and architecture.puml

# After adding new components
# Update: components.puml and architecture.puml

# After changing workflow states
# Update: All diagrams (workflow_engine referenced in all)
```

## Use Cases

**For Developers:**
- Understand system architecture
- Debug data flow issues
- Plan new features
- Onboard new team members

**For Stakeholders:**
- See how data moves through system
- Understand agent responsibilities
- Review security boundaries
- Verify compliance workflows

**For Documentation:**
- Include in technical specs
- Export as PNG for presentations
- Reference in PRD
- Share with reviewers

---

Enjoy visualizing ResearchFlow! 
