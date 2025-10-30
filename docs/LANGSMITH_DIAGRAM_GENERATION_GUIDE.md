# LangSmith & LangGraph Diagram Generation Guide

**Purpose**: Complete guide to generating and viewing workflow diagrams from LangGraph
**Audience**: Developers working with ResearchFlow's LangGraph implementation

---

## Quick Answer: Can LangSmith Generate Diagrams?

**YES! ✅** LangGraph has **automatic diagram generation** built-in. You can:

1. Generate Mermaid flowcharts directly from your `StateGraph` code
2. View execution graphs in the LangSmith dashboard
3. Convert to PNG/SVG for documentation
4. Render in GitHub, VS Code, or online tools

**No manual drawing required—diagrams stay in sync with your code automatically!**

---

## Method 1: Auto-Generate Mermaid Diagrams from Code

### Step 1: Generate Mermaid Diagram

Create a script to generate the diagram:

```python
# scripts/generate_workflow_diagram.py
from app.langchain_orchestrator.langgraph_workflow import FullWorkflow

# Initialize workflow
workflow = FullWorkflow()

# Generate Mermaid diagram
mermaid_diagram = workflow.compiled_graph.get_graph().draw_mermaid()

# Save to file
output_path = 'docs/architecture/langgraph_workflow.mmd'
with open(output_path, 'w') as f:
    f.write(mermaid_diagram)

print(f"✅ Diagram saved to: {output_path}")
print("\nPreview (first 20 lines):")
print('\n'.join(mermaid_diagram.split('\n')[:20]))
```

**Run it:**

```bash
cd /Users/jagnyesh/Development/FHIR_PROJECT
python scripts/generate_workflow_diagram.py
```

**Output**: `docs/architecture/langgraph_workflow.mmd`

---

### Step 2: View the Generated Diagram

You already have a generated diagram at:
```
docs/sprints/langgraph_workflow_diagram.mmd
```

**View Options:**

#### Option A: GitHub (Easiest)

1. Commit the `.mmd` file
2. Create a markdown file that embeds it:

```markdown
<!-- docs/WORKFLOW_DIAGRAM.md -->
# ResearchFlow Workflow Diagram

\`\`\`mermaid
graph TD;
    __start__ --> new_request;
    new_request --> requirements_gathering;
    requirements_gathering --> requirements_review;
    # ... (paste content from .mmd file)
\`\`\`
```

3. Push to GitHub—it renders automatically!

**Example**: View your current diagram at:
https://github.com/jagnyesh/researchflow/blob/main/docs/sprints/langgraph_workflow_diagram.mmd

#### Option B: Mermaid Live Editor (Fastest)

1. Go to https://mermaid.live
2. Paste the contents of `langgraph_workflow_diagram.mmd`
3. Edit/export on the fly

#### Option C: VS Code (For Development)

1. Install extension: "Markdown Preview Mermaid Support"
2. Open `langgraph_workflow_diagram.mmd` in VS Code
3. Press `Cmd+Shift+V` (Mac) or `Ctrl+Shift+V` (Windows) to preview

#### Option D: Convert to PNG/SVG

Install Mermaid CLI:
```bash
npm install -g @mermaid-js/mermaid-cli
```

Generate images:
```bash
# PNG with transparent background
mmdc -i docs/sprints/langgraph_workflow_diagram.mmd \
     -o docs/architecture/workflow_diagram.png \
     -b transparent \
     -w 2000 \
     -H 2000

# SVG (scalable)
mmdc -i docs/sprints/langgraph_workflow_diagram.mmd \
     -o docs/architecture/workflow_diagram.svg \
     -b transparent
```

---

## Method 2: View Diagrams in LangSmith Dashboard

### Step 1: Run Workflow with Tracing

Ensure LangSmith tracing is enabled in your `.env`:

```bash
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_...
LANGCHAIN_PROJECT=researchflow-production
```

### Step 2: Execute a Workflow

```python
# Example: Run a test workflow
from app.langchain_orchestrator.langgraph_workflow import FullWorkflow

workflow = FullWorkflow()
result = workflow.compiled_graph.invoke({
    "request_id": "TEST-001",
    "researcher_request": "I need diabetes patient data",
    "researcher_info": {"name": "Dr. Test"},
    # ... other required fields
})
```

Or run an existing test:
```bash
PYTHONPATH=/Users/jagnyesh/Development/FHIR_PROJECT pytest \
  tests/e2e/test_langgraph_workflow_e2e.py::test_happy_path_langgraph_workflow -v
```

### Step 3: View in LangSmith Dashboard

1. Go to https://smith.langchain.com
2. Select your project: **researchflow-production**
3. Find your recent trace in the list
4. Click on the trace to open details
5. **Click the "Graph" tab** at the top

**You'll see**:
- Visual graph of your workflow execution
- Green nodes: executed successfully
- Red nodes: errors
- Gray nodes: not executed
- Click any node to see inputs/outputs/timing

### Step 4: Share Diagrams

In LangSmith, you can:
- **Export as image**: Screenshot the graph view
- **Share trace URL**: Generate shareable link for your team
- **Embed in docs**: Export to Mermaid format

---

## Method 3: Programmatic Diagram Customization

### Customize Mermaid Output

You can customize the generated diagram:

```python
from app.langchain_orchestrator.langgraph_workflow import FullWorkflow

workflow = FullWorkflow()
graph = workflow.compiled_graph.get_graph()

# Generate with custom config
mermaid_config = """
---
config:
  theme: forest
  flowchart:
    curve: basis
    nodeSpacing: 50
    rankSpacing: 50
---
"""

mermaid_diagram = graph.draw_mermaid()

# Add custom styling
custom_diagram = mermaid_config + mermaid_diagram + """
classDef agentNode fill:#e1f5e1,stroke:#4caf50,stroke-width:3px
classDef approvalNode fill:#fff3cd,stroke:#ffc107,stroke-width:3px
classDef terminalNode fill:#ffcdd2,stroke:#f44336,stroke-width:3px

class new_request,requirements_gathering,data_extraction agentNode
class requirements_review,phenotype_review,qa_review approvalNode
class complete,not_feasible,qa_failed terminalNode
"""

# Save customized diagram
with open('docs/architecture/workflow_styled.mmd', 'w') as f:
    f.write(custom_diagram)
```

---

## Method 4: Compare Diagrams (Old vs. New Architecture)

### Generate Side-by-Side Comparison

Create a comparison document:

```markdown
# Workflow Architecture Comparison

## Old Architecture (Custom FSM)

\`\`\`mermaid
graph TD
    A[Orchestrator] --> B[Requirements Agent]
    B --> C[Phenotype Agent]
    C --> D[Calendar Agent]
    D --> E[Extraction Agent]
    E --> F[QA Agent]
    F --> G[Delivery Agent]
\`\`\`

Manual transitions, 15 states, no visibility.

## New Architecture (LangGraph)

\`\`\`mermaid
<!-- Insert generated langgraph_workflow_diagram.mmd content here -->
\`\`\`

Automatic diagram generation, 23 states, full observability.
```

---

## Practical Examples

### Example 1: Generate Diagram for Documentation

```bash
#!/bin/bash
# scripts/update_workflow_diagrams.sh

echo "Generating LangGraph workflow diagrams..."

# Generate Mermaid diagram
python -c "
from app.langchain_orchestrator.langgraph_workflow import FullWorkflow
workflow = FullWorkflow()
mermaid = workflow.compiled_graph.get_graph().draw_mermaid()
with open('docs/architecture/langgraph_workflow.mmd', 'w') as f:
    f.write(mermaid)
print('✅ Mermaid diagram saved')
"

# Convert to PNG
if command -v mmdc &> /dev/null; then
    mmdc -i docs/architecture/langgraph_workflow.mmd \
         -o docs/architecture/langgraph_workflow.png \
         -b transparent \
         -w 2000
    echo "✅ PNG diagram generated"
else
    echo "⚠️  mmdc not installed. Run: npm install -g @mermaid-js/mermaid-cli"
fi

# Add to git
git add docs/architecture/langgraph_workflow.*
echo "✅ Diagrams ready for commit"
```

### Example 2: Verify Diagram Matches Code

```python
# tests/test_workflow_diagram.py
def test_diagram_is_up_to_date():
    """Ensure generated diagram matches current workflow definition"""
    from app.langchain_orchestrator.langgraph_workflow import FullWorkflow
    import os

    # Generate current diagram
    workflow = FullWorkflow()
    current_diagram = workflow.compiled_graph.get_graph().draw_mermaid()

    # Read saved diagram
    diagram_path = 'docs/architecture/langgraph_workflow.mmd'
    if os.path.exists(diagram_path):
        with open(diagram_path, 'r') as f:
            saved_diagram = f.read()

        # Compare
        assert current_diagram == saved_diagram, \
            "Workflow diagram is out of date! Run scripts/update_workflow_diagrams.sh"
    else:
        # Save if missing
        with open(diagram_path, 'w') as f:
            f.write(current_diagram)
        print(f"⚠️  Diagram generated for first time: {diagram_path}")
```

### Example 3: Interactive Diagram Explorer

```python
# scripts/explore_workflow.py
from app.langchain_orchestrator.langgraph_workflow import FullWorkflow
import json

workflow = FullWorkflow()
graph = workflow.compiled_graph.get_graph()

# Print workflow statistics
print("=" * 60)
print("WORKFLOW STATISTICS")
print("=" * 60)

nodes = graph.nodes
edges = graph.edges

print(f"\nTotal States: {len(nodes)}")
print(f"Total Transitions: {len(edges)}")

print("\n📊 States by Type:")
state_types = {
    "Agent States": [n for n in nodes if any(x in n for x in ['gathering', 'validation', 'extraction', 'qa', 'delivery'])],
    "Approval States": [n for n in nodes if 'review' in n or 'approval' in n],
    "Terminal States": [n for n in nodes if n in ['complete', 'not_feasible', 'qa_failed', 'human_review']]
}

for state_type, states in state_types.items():
    print(f"  {state_type}: {len(states)}")
    for state in states:
        print(f"    - {state}")

print("\n🔀 Conditional Branches:")
conditional_edges = [e for e in edges if e.get('conditional')]
for edge in conditional_edges[:5]:  # Show first 5
    print(f"  {edge.get('source')} → {edge.get('condition')}")

print("\n📝 Generate diagram: python -c \"from app.langchain_orchestrator.langgraph_workflow import FullWorkflow; print(FullWorkflow().compiled_graph.get_graph().draw_mermaid())\"")
```

Run it:
```bash
python scripts/explore_workflow.py
```

---

## Common Issues & Solutions

### Issue 1: "mmdc command not found"

**Solution**:
```bash
# Install Mermaid CLI
npm install -g @mermaid-js/mermaid-cli

# Verify installation
mmdc --version
```

### Issue 2: "Module 'langgraph' not found"

**Solution**:
```bash
# Ensure you're in virtual environment
source .venv/bin/activate

# Install LangGraph
pip install langgraph

# Verify
python -c "import langgraph; print(langgraph.__version__)"
```

### Issue 3: LangSmith Dashboard Shows No Graphs

**Checklist**:
1. ✅ `LANGCHAIN_TRACING_V2=true` in `.env`
2. ✅ `LANGCHAIN_API_KEY` is valid
3. ✅ Workflow was actually executed (not just imported)
4. ✅ Wait 5-10 seconds for traces to upload
5. ✅ Refresh LangSmith dashboard

**Test**:
```python
from langsmith import Client
client = Client()  # Should not raise errors
```

### Issue 4: Diagram Too Large to View

**Solution A: Zoom Out**
- In Mermaid Live Editor: Use browser zoom (Cmd/Ctrl + -)

**Solution B: Horizontal Layout**
```python
# Modify graph orientation
mermaid = graph.draw_mermaid()
mermaid = mermaid.replace("graph TD", "graph LR")  # Left-to-right instead of top-down
```

**Solution C: Split into Sections**
- Generate separate diagrams for each workflow phase
- Example: Requirements phase, Extraction phase, QA phase

---

## Best Practices

### 1. **Keep Diagrams in Version Control**

```bash
# scripts/pre-commit-hook.sh
#!/bin/bash
# Regenerate diagrams before commit

python scripts/generate_workflow_diagram.py

if [ -f "docs/architecture/langgraph_workflow.mmd" ]; then
    git add docs/architecture/langgraph_workflow.mmd
fi
```

### 2. **Document Diagram Generation in CI/CD**

```yaml
# .github/workflows/docs.yml
name: Generate Documentation

on:
  push:
    branches: [main]

jobs:
  diagrams:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Generate workflow diagrams
        run: |
          python scripts/generate_workflow_diagram.py
          npm install -g @mermaid-js/mermaid-cli
          mmdc -i docs/architecture/langgraph_workflow.mmd \
               -o docs/architecture/langgraph_workflow.png
      - name: Commit diagrams
        run: |
          git add docs/architecture/*.png docs/architecture/*.mmd
          git commit -m "docs: update workflow diagrams" || true
```

### 3. **Link Diagrams in README**

```markdown
## Workflow Architecture

View the complete workflow diagram:

**Interactive (Mermaid)**:
- [GitHub Rendering](docs/architecture/langgraph_workflow.mmd)
- [Mermaid Live Editor](https://mermaid.live)

**Static Images**:
- [PNG Diagram](docs/architecture/langgraph_workflow.png)

**LangSmith Dashboard**:
- [View Live Executions](https://smith.langchain.com/o/YOUR_ORG/projects/p/researchflow-production)
```

---

## Next Steps for Your Project

### Immediate Actions (Today)

1. **Generate Current Diagram**
```bash
python -c "
from app.langchain_orchestrator.langgraph_workflow import FullWorkflow
workflow = FullWorkflow()
mermaid = workflow.compiled_graph.get_graph().draw_mermaid()
with open('docs/architecture/current_langgraph_workflow.mmd', 'w') as f:
    f.write(mermaid)
print('✅ Saved to docs/architecture/current_langgraph_workflow.mmd')
"
```

2. **View in Mermaid Live**
   - Go to https://mermaid.live
   - Paste the contents of `current_langgraph_workflow.mmd`
   - Export as PNG/SVG

3. **Add to README**
   - Create `docs/WORKFLOW_DIAGRAM.md`
   - Embed the Mermaid diagram
   - Commit and view on GitHub

### This Week

4. **Run Workflow with Tracing**
   - Execute `test_langgraph_workflow_e2e.py`
   - View in LangSmith dashboard
   - Take screenshots for documentation

5. **Convert to PNG**
   - Install `mmdc` CLI tool
   - Generate PNG versions
   - Add to documentation

### This Month

6. **Automate Diagram Updates**
   - Add pre-commit hook
   - Set up CI/CD to regenerate diagrams
   - Add tests to verify diagram freshness

---

## Summary

**LangGraph + LangSmith provides automatic diagram generation!**

✅ **What You Get**:
- Auto-generated Mermaid flowcharts
- Diagrams always match code
- Interactive visualization in LangSmith
- Export to PNG/SVG for docs
- No manual drawing required!

✅ **What You Should Do**:
1. Generate diagrams regularly
2. Keep them in version control
3. View executions in LangSmith dashboard
4. Share with your team

**Your existing Mermaid diagram** (`docs/sprints/langgraph_workflow_diagram.mmd`) **is already generated by LangGraph!** Just use the steps above to view/convert/share it.
