# Text-to-SQL Flow in ResearchFlow

**Document Version:** 1.0
**Date:** 2025-10-07
**Purpose:** Explain how LLM conversations convert to SQL queries

---

## Table of Contents

1. [Overview](#overview)
2. [Complete Flow Diagram](#complete-flow-diagram)
3. [Phase-by-Phase Breakdown](#phase-by-phase-breakdown)
4. [Two Text2SQL Approaches](#two-text2sql-approaches)
5. [Key Implementation Details](#key-implementation-details)
6. [Code Examples](#code-examples)
7. [Security Considerations](#security-considerations)

---

## Overview

ResearchFlow uses a **safe, multi-step approach** to convert natural language requests into SQL queries. This is fundamentally different from naive "LLM directly writes SQL" approaches.

**Key Design Principle:**
> **LLM is used ONLY for structured extraction, NEVER for direct SQL generation**

The flow involves 5 distinct phases:
1. **LLM Conversation** - Multi-turn dialogue with researcher
2. **Structured Extraction** - LLM outputs validated JSON
3. **Medical Concept Extraction** - Identify and validate medical terms
4. **Template-Based SQL Generation** - Deterministic SQL construction
5. **Query Execution** - Sandboxed, audited execution

---

## Complete Flow Diagram

```

 RESEARCHER INPUT 
 "I need patients with diabetes who are over 65 and have HbA1c > 7.5" 

 PHASE 1: LLM CONVERSATION (Requirements Agent) 

 File: app/agents/requirements_agent.py 

 Multi-turn conversation: 
 • User: "I need diabetic patients over 65..." 
 • Agent: "What IRB number should I use?" 
 • User: "IRB-2024-12345" 
 • Agent: "What time period?" 
 • User: "January 2020 to December 2023" 

 Conversation stored as: 
 [{role: "user", content: "..."}, {role: "assistant", content: "..."}] 

 llm_client.extract_requirements(conversation_history, ...)

 PHASE 2: STRUCTURED EXTRACTION (LLM → JSON) 

 File: app/utils/llm_client.py::extract_requirements() 

 LLM analyzes conversation and outputs STRUCTURED JSON: 

 { 
 "extracted_requirements": { 
 "study_title": "Diabetes HbA1c Study", 
 "irb_number": "IRB-2024-12345", 
 "inclusion_criteria": [ 
 "patients with diabetes", 
 "age over 65", 
 "HbA1c > 7.5" 
 ], 
 "time_period": {"start": "2020-01-01", "end": "2023-12-31"}, 
 "data_elements": ["demographics", "lab_results"], 
 "phi_level": "de-identified" 
 }, 
 "completeness_score": 0.85, 
 "ready_for_submission": true 
 } 

 [x] JSON is validated and parsed 
 [x] NOT raw SQL - still in semantic form 

 requirements_agent._criteria_to_structured()

 PHASE 3: MEDICAL CONCEPT EXTRACTION 

 File: app/utils/llm_client.py::extract_medical_concepts() 

 For each criterion, LLM extracts medical concepts: 

 Input: "patients with diabetes" 
 Output: { 
 "concepts": [ 
 { 
 "term": "diabetes", 
 "type": "condition", 
 "details": "diabetes mellitus (any type)" 
 } 
 ] 
 } 

 Input: "age over 65" 
 Output: { 
 "concepts": [ 
 { 
 "term": "age", 
 "type": "demographic", 
 "details": "> 65" 
 } 
 ] 
 } 

 WARNING: Currently: No terminology validation (concepts might be wrong) 
 [x] Future: Validate against SNOMED/LOINC via terminology server 

 Structured requirements passed to Phenotype Agent
 orchestrator.route_task(agent="phenotype_agent", ...)

 PHASE 4: TEMPLATE-BASED SQL GENERATION 

 File: app/utils/sql_generator.py::generate_phenotype_sql() 

 [x] DETERMINISTIC SQL construction (NOT LLM-generated!) 

 Process: 
 1. Build SELECT clause (count_only or full) 
 2. Build FROM clause (patient table + joins) 
 3. Build WHERE clauses from structured criteria: 
 • Inclusion criteria → EXISTS subqueries 
 • Exclusion criteria → NOT EXISTS subqueries 
 • Demographics → direct WHERE conditions 
 • Time periods → date range filters 
 4. Combine with AND logic 

 Generated SQL: 
 ```sql 
 SELECT DISTINCT 
 p.id as patient_id, 
 p.birthDate, 
 p.gender 
 FROM patient p 
 WHERE EXISTS ( 
 SELECT 1 FROM condition c 
 WHERE c.patient_id = p.id 
 AND LOWER(c.code_display) LIKE LOWER('%diabetes%') 
 ) 
 AND EXTRACT(YEAR FROM AGE(CURRENT_DATE, p.birthDate)) > 65 
 AND EXISTS ( 
 SELECT 1 FROM observation o 
 WHERE o.patient_id = p.id 
 AND LOWER(o.code_display) LIKE LOWER('%hba1c%') 
 AND o.value > 7.5 
 ) 
 AND p.lastUpdated BETWEEN '2020-01-01' AND '2023-12-31' 
 ``` 

 Security: 
 • Template-based construction prevents SQL injection 
 • No direct string interpolation from user input 
 • Parameters are validated before use 

 sql_adapter.execute_sql(sql)

 PHASE 5: QUERY EXECUTION 

 File: app/adapters/sql_on_fhir.py::execute_sql() 

 Sandboxed execution: 
 1. Validate: Only SELECT queries allowed 
 2. Execute on async database connection 
 3. Return results as list of dicts 

 Results: [ 
 {"patient_id": "123", "birthDate": "1955-03-15", "gender": "male"}, 
 {"patient_id": "456", "birthDate": "1950-07-22", "gender": "female"},
 ... 
 ] 

 WARNING: Current limitations: 
 • No query cost estimation 
 • No timeout enforcement 
 • No audit logging 
 [x] Future: Add all security controls from Phase 1 roadmap 

```

---

## Phase-by-Phase Breakdown

### Phase 1: LLM Conversation (Requirements Agent)

**File:** `app/agents/requirements_agent.py:43-160`

**Purpose:** Conduct multi-turn dialogue to extract all necessary information

**How it works:**

1. Researcher submits initial request
2. Requirements Agent maintains conversation state
3. LLM analyzes conversation to identify missing information
4. Agent asks follow-up questions until completeness score > threshold
5. Conversation history stored as list of role/content messages

**Key Code:**
```python
# Line 101-104
analysis = await self.llm_client.extract_requirements(
 conversation_history=conversation_history,
 current_requirements=state['requirements']
)

# Line 125-146 - Check if complete
if analysis['ready_for_submission']:
 final_requirements = await self._validate_and_structure_requirements(...)
 return {
 "requirements_complete": True,
 "structured_requirements": final_requirements,
 "next_agent": "phenotype_agent", # HANDOFF HERE
 "next_task": "validate_feasibility"
 }
```

**Conversation State Example:**
```python
{
 "requirements": {
 "study_title": "Diabetes Study",
 "irb_number": "IRB-2024-001",
 "inclusion_criteria": ["diabetes", "age > 65"],
 "time_period": {"start": "2020-01-01", "end": "2023-12-31"},
 "phi_level": "de-identified"
 },
 "completeness_score": 0.85,
 "questions_asked": ["What is your IRB number?", "What time period?"]
}
```

---

### Phase 2: Structured Extraction (LLM → JSON)

**File:** `app/utils/llm_client.py:117-180`

**Purpose:** Convert natural language conversation into validated JSON schema

**How it works:**

1. LLM receives conversation history + current requirements
2. Detailed prompt engineering guides extraction
3. LLM outputs JSON with specific schema
4. JSON is parsed and validated
5. Markdown code blocks stripped if present

**Prompt Structure:**
```python
prompt = f"""You are a clinical research data request specialist.

Current conversation history:
{json.dumps(conversation_history, indent=2)}

Current extracted requirements:
{json.dumps(current_requirements, indent=2)}

Analyze the conversation and:
1. Extract any new requirement information
2. Identify what critical fields are still missing
3. Generate the next question to ask
4. Calculate completeness score

Required fields:
- study_title, irb_number, inclusion_criteria, data_elements, time_period, phi_level

Return JSON with this exact structure:
{{
 "extracted_requirements": {{...}},
 "missing_fields": [...],
 "next_question": "...",
 "completeness_score": 0.85,
 "ready_for_submission": false
}}"""
```

**Critical Safety:**
- [x] JSON schema enforced
- [x] Output is parsed and validated
- [x] NO direct SQL generation
- WARNING: Need validation against terminology (gap identified in roadmap)

---

### Phase 3: Medical Concept Extraction

**File:** `app/utils/llm_client.py:182-215`

**Purpose:** Extract medical concepts from each criterion

**How it works:**

1. For each inclusion/exclusion criterion (e.g., "patients with diabetes")
2. LLM identifies medical concepts and classifies them
3. Concepts categorized by type: condition, medication, lab, procedure, demographic
4. Returns structured list of concepts

**Example:**

Input: `"patients with type 2 diabetes on metformin"`

Output:
```json
{
 "concepts": [
 {
 "term": "type 2 diabetes",
 "type": "condition",
 "details": "diabetes mellitus type 2"
 },
 {
 "term": "metformin",
 "type": "medication",
 "details": "currently taking metformin"
 }
 ]
}
```

**Current Gap:**
- [ ] Concepts NOT validated against terminology servers
- [ ] No code expansion (diabetes → all SNOMED codes)
- [ ] LLM could hallucinate non-existent medical terms

**Future Enhancement (Phase 1):**
```python
# After LLM extraction, validate and expand:
for concept in concepts:
 # 1. Validate term exists in SNOMED/LOINC/RxNorm
 codes = await terminology_server.search_snomed(concept['term'])
 if not codes:
 raise InvalidConceptError(f"Unknown term: {concept['term']}")

 # 2. Expand to all child concepts
 expanded_codes = await terminology_server.expand_concept(codes[0]['code'])

 # 3. Store validated codes
 concept['codes'] = expanded_codes
```

---

### Phase 4: Template-Based SQL Generation

**File:** `app/utils/sql_generator.py:18-240`

**Purpose:** Generate SQL using deterministic templates (NOT LLM!)

** KEY DESIGN DECISION:**
> **This is NOT Text2SQL in the traditional sense!**
> The LLM never sees SQL. It only outputs structured JSON.
> SQL generation is done by a deterministic Python function.

**How it works:**

1. Receive structured requirements (validated JSON)
2. Build SQL components using templates:

```python
# Line 38-78 - SQL Construction
if count_only:
 select_clause = "SELECT COUNT(DISTINCT p.id) as patient_count"
else:
 select_clause = """SELECT DISTINCT
 p.id as patient_id,
 p.birthDate,
 p.gender"""

from_clause = "FROM patient p"

# Build WHERE clauses from criteria
where_clauses = []
for criterion in inclusion_criteria:
 condition = self._build_condition_clause(criterion['term'], include=True)
 where_clauses.append(condition)

# Combine
sql = f"{select_clause}\n{from_clause}\nWHERE {' AND '.join(where_clauses)}"
```

**Template Methods:**

1. `_build_condition_clause()` - EXISTS subquery for conditions
2. `_build_demographic_clause()` - Direct WHERE for age/gender
3. `_build_lab_clause()` - EXISTS for observations
4. `_build_time_conditions()` - Date range filters

**Example Template:**
```python
# Line 142-146 - Condition template
def _build_condition_clause(self, condition_term: str, include: bool) -> str:
 operator = "EXISTS" if include else "NOT EXISTS"
 return f"""{operator} (
 SELECT 1 FROM condition c
 WHERE c.patient_id = p.id
 AND LOWER(c.code_display) LIKE LOWER('%{condition_term}%')
 )"""
```

**Current Limitations:**
- WARNING: Uses string matching (`LIKE '%diabetes%'`) instead of code-based queries
- WARNING: No temporal logic (index dates, lookback windows)
- WARNING: No complex boolean expressions

**Should Be (after Phase 1 enhancements):**
```python
def _build_condition_clause(self, concept_codes: list, include: bool) -> str:
 operator = "EXISTS" if include else "NOT EXISTS"
 code_list = "', '".join(concept_codes)
 return f"""{operator} (
 SELECT 1 FROM condition c
 WHERE c.patient_id = p.id
 AND c.code IN ('{code_list}')
 AND c.system = 'http://snomed.info/sct'
 )"""
```

---

### Phase 5: Query Execution

**File:** `app/adapters/sql_on_fhir.py:18-25`

**Purpose:** Execute SQL in sandboxed environment

**How it works:**

```python
async def execute_sql(self, sql: str):
 # Security check: Only SELECT allowed
 if not sql.strip().lower().startswith("select"):
 raise ValueError("Only SELECT queries allowed")

 # Execute with async SQLAlchemy
 async with self.async_session() as session:
 result = await session.execute(text(sql))
 rows = [dict(row._mapping) for row in result]
 return rows
```

**Current Limitations:**
- [ ] No audit logging (who ran what query?)
- [ ] No cost estimation (query could be expensive)
- [ ] No timeout enforcement
- [ ] No result size limits

**Phase 1 Enhancements Needed:**
```python
async def execute_sql(self, sql: str, user_id: str, justification: str):
 # 1. Validate SQL syntax
 parsed = sqlglot.parse_one(sql)

 # 2. Estimate cost
 cost = self.cost_estimator.estimate(parsed)
 if cost > THRESHOLD:
 raise QueryTooExpensiveError()

 # 3. Audit log
 await self.audit_logger.log(user_id, sql, justification)

 # 4. Execute with timeout
 with timeout(30):
 result = await session.execute(text(sql))

 # 5. Log results
 await self.audit_logger.log_results(user_id, len(result))

 return rows
```

---

## Two Text2SQL Approaches

ResearchFlow has **two different Text2SQL implementations**:

### Approach 1: Legacy Text2SQL API (NOT RECOMMENDED)

**Files:** `app/api/text2sql.py`, `app/services/text2sql.py`

**How it works:**
```python
# User sends raw prompt
POST /text2sql {"prompt": "patients with hemoglobin < 12"}

# Dummy provider returns hardcoded SQL
if "hemoglobin" in prompt.lower():
 return "SELECT patient_id, value FROM observation WHERE code = 'hb' AND value < 12"
```

**Problems:**
- [ ] No validation
- [ ] No conversation
- [ ] No structured requirements
- [ ] Single-shot, no context
- [ ] Hardcoded responses (not real Text2SQL)

**Status:** Stub/demo only, not used in production workflow

---

### Approach 2: Production Multi-Agent System (RECOMMENDED)

**Files:** Requirements Agent → Phenotype Agent → SQL Generator

**How it works:**
```
Conversation → Structured JSON → Validated Concepts → Template SQL → Execution
```

**Advantages:**
- [x] Multi-turn conversation gathers complete requirements
- [x] Structured intermediate representation (JSON)
- [x] Medical concept extraction and validation
- [x] Template-based SQL (not LLM-generated)
- [x] Human-in-the-loop approval
- [x] Workflow state machine with error handling

**This is the approach ResearchFlow uses in practice.**

---

## Key Implementation Details

### Orchestrator Routing

**File:** `app/orchestrator/orchestrator.py:81-157`

The orchestrator routes tasks between agents:

```python
# Line 67-78 - Start workflow with Requirements Agent
await self.route_task(
 agent_id='requirements_agent',
 task='gather_requirements',
 context={'request_id': request_id, 'initial_request': researcher_request}
)

# Line 128-150 - Determine next step
next_step = self.workflow_engine.determine_next_step(
 completed_agent=agent_id,
 completed_task=task,
 result=result
)

if next_step and next_step['next_agent']:
 # Continue to next agent (e.g., phenotype_agent)
 await self.route_task(
 agent_id=next_step['next_agent'],
 task=next_step['next_task'],
 context={**context, **result.get('additional_context', {})}
 )
```

**Handoff Flow:**
1. Requirements Agent completes → returns `next_agent: "phenotype_agent"`
2. Orchestrator routes to Phenotype Agent
3. Phenotype Agent receives structured requirements
4. Phenotype Agent calls SQL Generator
5. SQL executes, results return to Orchestrator

---

### Workflow State Transitions

**File:** `app/orchestrator/workflow_engine.py:52-115`

```python
workflow_rules = {
 ('requirements_agent', 'gather_requirements'): {
 'condition': lambda r: r.get('requirements_complete') == True,
 'next_agent': 'phenotype_agent', # HANDOFF
 'next_task': 'validate_feasibility',
 'next_state': WorkflowState.FEASIBILITY_VALIDATION
 },

 ('phenotype_agent', 'validate_feasibility'): {
 'condition': lambda r: r.get('feasible') == True,
 'next_agent': 'calendar_agent',
 'next_task': 'schedule_kickoff_meeting',
 'next_state': WorkflowState.SCHEDULE_KICKOFF
 },
 # ... more transitions
}
```

---

## Code Examples

### Example 1: Complete Flow

```python
# 1. User submits request
orchestrator = ResearchRequestOrchestrator()
request_id = await orchestrator.process_new_request(
 researcher_request="I need diabetic patients over 65",
 researcher_info={"name": "Dr. Smith", "email": "..."}
)

# 2. Requirements Agent starts conversation
# (Behind the scenes)
requirements_agent = RequirementsAgent()
result = await requirements_agent._gather_requirements({
 'request_id': request_id,
 'initial_request': "I need diabetic patients over 65"
})

# 3. LLM extracts structured requirements
# (Inside requirements_agent._gather_requirements)
analysis = await llm_client.extract_requirements(
 conversation_history=[
 {"role": "user", "content": "I need diabetic patients over 65"},
 {"role": "assistant", "content": "What IRB number?"},
 {"role": "user", "content": "IRB-2024-001"}
 ],
 current_requirements={...}
)
# Returns: {"extracted_requirements": {...}, "ready_for_submission": True}

# 4. Medical concepts extracted for each criterion
# (Inside requirements_agent._criteria_to_structured)
concepts = await llm_client.extract_medical_concepts("patients with diabetes")
# Returns: {"concepts": [{"term": "diabetes", "type": "condition"}]}

# 5. Orchestrator routes to Phenotype Agent
await orchestrator.route_task(
 agent_id='phenotype_agent',
 task='validate_feasibility',
 context={'requirements': final_requirements}
)

# 6. Phenotype Agent generates SQL
# (Inside phenotype_agent._validate_feasibility)
sql = sql_generator.generate_phenotype_sql(requirements, count_only=True)
# Returns: "SELECT COUNT(DISTINCT p.id) FROM patient p WHERE ..."

# 7. SQL executed
result = await sql_adapter.execute_sql(sql)
# Returns: [{"patient_count": 1234}]
```

### Example 2: LLM Prompt Engineering

**File:** `app/utils/llm_client.py:137-176`

```python
prompt = f"""You are a clinical research data request specialist.

Current conversation history:
[
 {{"role": "user", "content": "I need patients with diabetes"}},
 {{"role": "assistant", "content": "What IRB number?"}},
 {{"role": "user", "content": "IRB-2024-001"}}
]

Analyze the conversation and:
1. Extract any new requirement information
2. Identify what critical fields are still missing
3. Generate the next question to ask

Required fields:
- study_title, irb_number, inclusion_criteria, data_elements, time_period, phi_level

Return JSON with this exact structure:
{{
 "extracted_requirements": {{
 "study_title": "string or null",
 "irb_number": "IRB-2024-001",
 "inclusion_criteria": ["patients with diabetes"],
 "data_elements": [],
 "time_period": {{"start": null, "end": null}},
 "phi_level": null
 }},
 "missing_fields": ["time_period", "data_elements", "phi_level"],
 "next_question": "What time period should I use for this cohort?",
 "completeness_score": 0.4,
 "ready_for_submission": false
}}"""

# LLM processes this and returns valid JSON
# JSON is parsed: json.loads(response.strip())
```

---

## Security Considerations

### What ResearchFlow Does Right [x]

1. **No Direct LLM→SQL**
 - LLM never generates SQL directly
 - Always goes through structured JSON intermediate
 - SQL built from validated templates

2. **SELECT-Only Sandbox**
 - Only SELECT queries allowed
 - Prevents INSERT, UPDATE, DELETE, DROP

3. **Multi-Stage Validation**
 - Conversation → JSON (validated)
 - JSON → Concepts (extracted)
 - Concepts → SQL (templates)

4. **Human-in-the-Loop**
 - Requirements reviewed before execution
 - Feasibility scores calculated
 - Escalation on errors

### What Needs Improvement WARNING:

1. **No SQL Injection Protection**
 - Current: String interpolation in templates
 - Need: Parameterized queries or proper escaping

2. **No Terminology Validation**
 - LLM could extract fake medical terms
 - Need: Validate against SNOMED/LOINC

3. **No Audit Logging**
 - No record of who ran what query
 - Need: Comprehensive audit trail

4. **No Cost Controls**
 - Expensive queries could run unchecked
 - Need: Cost estimation and limits

**See `docs/GAP_ANALYSIS_AND_ROADMAP.md` Phase 1 for full security enhancement plan.**

---

## File Reference Summary

| File | Purpose | Lines |
|------|---------|-------|
| `app/agents/requirements_agent.py` | LLM conversation management | 43-247 |
| `app/utils/llm_client.py` | Claude API wrapper, prompt engineering | 117-215 |
| `app/utils/sql_generator.py` | Template-based SQL construction | 18-240 |
| `app/adapters/sql_on_fhir.py` | SQL execution sandbox | 18-25 |
| `app/orchestrator/orchestrator.py` | Agent routing and coordination | 33-231 |
| `app/orchestrator/workflow_engine.py` | State machine transitions | 45-115 |
| `app/services/text2sql.py` | Legacy Text2SQL (not used) | 10-29 |
| `app/api/text2sql.py` | Legacy API endpoint (stub) | 12-16 |

---

## Comparison: Naive vs. ResearchFlow Approach

### [ ] Naive Approach (DANGEROUS)

```python
# User input directly to LLM
user_input = "Show me diabetic patients"

# LLM generates SQL directly
sql = llm.complete(f"Generate SQL for: {user_input}")
# Returns: "SELECT * FROM patients WHERE condition = 'diabetes'"

# Execute without validation
results = db.execute(sql) # SQL injection risk!
```

**Problems:**
- SQL injection vulnerability
- No validation
- No concept resolution
- Brittle (LLM hallucination)
- No audit trail
- No human review

### [x] ResearchFlow Approach (SAFE)

```python
# 1. Multi-turn conversation
conversation = [
 {"role": "user", "content": "Show me diabetic patients"},
 {"role": "assistant", "content": "What time period?"},
 {"role": "user", "content": "2020-2023"}
]

# 2. Structured extraction
requirements = llm.extract_requirements(conversation)
# Returns validated JSON, NOT SQL

# 3. Medical concept extraction
concepts = llm.extract_medical_concepts("diabetic patients")
# Returns: {"concepts": [{"term": "diabetes", "type": "condition"}]}

# 4. Template-based SQL generation (deterministic)
sql = sql_generator.generate_phenotype_sql(requirements)
# Built from templates, not LLM

# 5. Validation and execution
if sql.startswith("SELECT"): # Sandbox
 results = await db.execute(sql)
```

**Advantages:**
- No SQL injection (templates)
- Validated concepts
- Human review possible
- Auditable
- Testable

---

## Conclusion

ResearchFlow's Text-to-SQL implementation is **fundamentally different** from naive LLM→SQL approaches:

1. **LLM Role:** Structured extraction ONLY, never SQL generation
2. **Intermediate Representation:** Validated JSON schema
3. **SQL Generation:** Deterministic templates, not LLM output
4. **Safety:** Multi-stage validation, sandboxing, human review

**This design prevents the major pitfalls identified in `docs/add_params.md`:**
- [x] No LLM hallucination in SQL
- [x] No direct SQL injection
- [x] Human-in-the-loop approval
- WARNING: Still needs: terminology validation, temporal logic, audit logging (see Phase 1 roadmap)

**Next Steps:**
- Implement Phase 1 enhancements (terminology, audit logging, RBAC)
- Add temporal logic engine
- Complete security controls

---

**Related Documentation:**
- `docs/GAP_ANALYSIS_AND_ROADMAP.md` - Production readiness gaps
- `docs/add_params.md` - SQL-on-FHIR best practices
- `docs/RESEARCHFLOW_README.md` - Full system architecture
