# Research Notebook - User Guide

## Interactive Jupyter Notebook-Style Interface for FHIR Data Queries

The Research Notebook provides a revolutionary way to query FHIR data using natural language. Simply ask questions in plain English, and the system seamlessly translates them to SQL-on-FHIR queries, executes them, and displays results in beautiful notebook-style cells with summary statistics and visualizations.

---

## Quick Start

### **Launch the Notebook**

```bash
# Start the Research Notebook on port 8503
streamlit run app/web_ui/research_notebook.py --server.port 8503
```

**Access at**: http://localhost:8503

### **Prerequisites**

Make sure the following are running:
- [x] **HAPI FHIR Server** (port 8081) - `docker compose -f config/docker-compose.yml up -d hapi-fhir`
- [x] **ResearchFlow API** (port 8000) - `uvicorn app.main:app --reload --port 8000`
- [x] **Sample FHIR data loaded** - `python3 load_sample_data.py`

---

## How to Use

### **1. Ask Natural Language Questions**

Type your question in the chat input at the bottom of the page. Examples:

```
How many patients are available?

Show me all male patients under age 30

Give me all male patients under the age of 30 with type 2 diabetes

Get female patients with hypertension

Show me patients with diabetes and their lab results
```

### **2. Watch the Magic Happen**

The system automatically:

1. ** Interprets your query** using Claude AI
 - Extracts demographics (age, gender)
 - Identifies conditions (diabetes, hypertension, etc.)
 - Maps to medical codes (SNOMED, ICD-10)

2. ** Executes SQL-on-FHIR queries**
 - Selects appropriate ViewDefinitions
 - Builds FHIR search parameters
 - Fetches data from HAPI FHIR server

3. ** Processes results**
 - Joins multiple ViewDefinitions
 - Applies post-filters
 - Calculates summary statistics

4. ** Displays in notebook cells**
 - Query cell with details
 - Results cell with top 20 rows
 - Summary statistics
 - Interactive visualizations

### **3. Explore the Results**

Each query creates two cells:

#### **Query Cell**
Shows what the system understood:
- ViewDefinitions used
- Search parameters
- Filters applied
- Execution time

#### **Results Cell**
Displays the data:
- **Summary Statistics**: Total count, gender distribution, age stats
- **Top 20 Results**: Interactive data table
- **Download Options**: CSV and JSON export
- **Visualizations**: Charts and graphs

---

## Example Queries & Expected Results

### **Query 1: "How many patients are available?"**

**What happens:**
- Uses `patient_demographics` ViewDefinition
- Returns total patient count
- Shows gender and age distribution

**Expected output:**
```
Summary Statistics:
• Total: 10 records
• Gender: Male: 5 (50%) | Female: 5 (50%)
• Age: 15-75 years (mean: 45.0, median: 44.5)
```

---

### **Query 2: "Give me all male patients under the age of 30 with type 2 diabetes"**

**What happens:**
1. Interprets:
 - Gender: male
 - Age: < 30 years
 - Condition: Type 2 diabetes (SNOMED: 44054006)

2. Executes:
 - `patient_demographics` with gender=male filter
 - Calculates age from birthDate
 - Joins with `condition_diagnoses`
 - Filters by SNOMED code

3. Returns:
 - Top 20 matching patients
 - Statistics: count, age range, condition info

**Expected output:**
```
Summary Statistics:
• Total: 3 records
• Gender: Male: 3 (100%)
• Age: 22-28 years (mean: 25.3, median: 26.0)
• Top Conditions: Type 2 diabetes mellitus (3)

Top Results:
| ID | Name | Age | Gender | Condition |
|----|------|-----|--------|-----------|
| patient-1 | John D | 28 | male | Type 2 diabetes |
| patient-5 | Mike S | 22 | male | Type 2 diabetes |
| patient-8 | Tom W | 26 | male | Type 2 diabetes |
```

---

### **Query 3: "Show me patients with hypertension"**

**What happens:**
1. Interprets: Condition = Hypertension (SNOMED: 38341003)
2. Executes: `patient_demographics` + `condition_diagnoses`
3. Returns: All patients with hypertension diagnosis

---

### **Query 4: "Get female patients with diabetes and their lab results"**

**What happens:**
1. Executes THREE ViewDefinitions:
 - `patient_demographics` (gender=female)
 - `condition_diagnoses` (diabetes codes)
 - `observation_labs` (lab results for those patients)

2. Joins results on patient_id

3. Shows:
 - Patient demographics
 - Diabetes diagnosis
 - Lab values (glucose, HbA1c, etc.)

---

## UI Features

### **Chat Interface**
- Natural conversation flow
- Message history preserved
- Example queries in sidebar

### **Notebook Cells**
- Jupyter notebook-style layout
- Expandable query details
- Color-coded sections

### **Summary Statistics**
- **Total count** of matching records
- **Gender distribution** with percentages
- **Age statistics** (min, max, mean, median)
- **Top conditions** with prevalence
- **Date ranges** for time-based queries

### **Data Table**
- **Top 20 results** displayed
- **Sortable columns**
- **Scrollable** for large datasets
- **All data available** via download

### **Visualizations**
- **Pie charts** for gender distribution
- **Histograms** for age distribution
- **Bar charts** for condition prevalence
- **Interactive** with Plotly

### **Download Options**
- **CSV format** for Excel/analysis
- **JSON format** for programmatic use
- **Timestamped filenames**

---

## 🧠 How Query Interpretation Works

### **Natural Language → SQL-on-FHIR Pipeline**

```
User Input: "male patients under 30 with diabetes"
 ↓
Claude AI Interpretation:
 ↓
{
 "query_type": "filter",
 "resources": ["Patient", "Condition"],
 "filters": {
 "gender": "male",
 "age_max": 30,
 "conditions": [{
 "name": "Type 2 diabetes",
 "snomed": "44054006",
 "icd10": "E11.9"
 }]
 },
 "view_definitions": [
 "patient_demographics",
 "condition_diagnoses"
 ]
}
 ↓
ViewDefinition Execution:
 ↓
POST /analytics/execute {
 "view_name": "patient_demographics",
 "search_params": {
 "gender": "male",
 "birthdate": "ge1995-01-01" // age < 30
 }
}
 ↓
Post-Processing:
 ↓
- Join with condition_diagnoses
- Filter by SNOMED code 44054006
- Limit to top 20 rows
- Calculate statistics
 ↓
Results Display
```

### **Supported Query Types**

1. **Count Queries**
 - "How many..."
 - "Count..."
 - "Number of..."

2. **Filter Queries**
 - Demographics: age, gender
 - Conditions: diabetes, hypertension, etc.
 - Time periods: "in 2024", "last year"

3. **List Queries**
 - "Show me..."
 - "Get..."
 - "List..."

4. **Aggregate Queries**
 - "Distribution of..."
 - "Statistics for..."

---

## Advanced Features

### **Session Management**

**Clear Notebook**
- Removes all cells
- Resets session
- Starts fresh

**Export Session**
- Downloads JSON with all queries and results
- Includes timestamps
- Can be imported later (future feature)

### **Query History**

All queries are stored in session:
- View previous cells
- Scroll through notebook
- Re-examine results

### **Example Queries**

Sidebar provides quick access to common queries:
- Click to execute
- Learn query patterns
- Explore capabilities

---

## Tips for Best Results

### **Be Specific**
[x] "male patients under 30 with type 2 diabetes"
[ ] "patients with problems"

### **Use Medical Terms**
[x] "hypertension" or "high blood pressure"
[x] "type 2 diabetes" or "diabetes"
[ ] "sugar disease"

### **Combine Filters**
[x] "female patients over 40 with diabetes"
[x] "children under 18 with asthma"

### **Request Data Elements**
[x] "patients with diabetes and their lab results"
[x] "show medications for hypertensive patients"

---

## Supported Medical Conditions

The system recognizes these conditions (and their synonyms):

| Condition | SNOMED Code | ICD-10 Code |
|-----------|-------------|-------------|
| Type 2 Diabetes | 44054006 | E11.9 |
| Hypertension / High Blood Pressure | 38341003 | I10 |
| Hyperlipidemia | 13645005 | E78.5 |
| Asthma | 195967001 | J45.909 |

*More conditions can be added to `app/services/query_interpreter.py`*

---

## Technical Architecture

### **Components**

1. **Query Interpreter** (`app/services/query_interpreter.py`)
 - Uses Claude API for NL understanding
 - Maps to ViewDefinitions
 - Extracts filters and parameters

2. **Analytics Client** (`app/clients/analytics_client.py`)
 - Executes ViewDefinitions
 - Joins multiple results
 - Applies post-filters

3. **Stats Calculator** (`app/utils/stats_calculator.py`)
 - Computes summary statistics
 - Age calculations
 - Distribution analysis

4. **Results Renderer** (`app/components/results_renderer.py`)
 - Displays notebook cells
 - Renders tables and charts
 - Provides downloads

### **Data Flow**

```
User Query → Query Interpreter (Claude AI) → Analytics Client (SQL-on-FHIR)
→ Stats Calculator → Results Renderer → Notebook Cell Display
```

---

## Troubleshooting

### **"No results found"**
- Check if FHIR data is loaded: `curl http://localhost:8081/fhir/Patient?_count=1`
- Reload sample data: `python3 load_sample_data.py`
- Try broader query: "How many patients are available?"

### **"Error processing query"**
- Ensure API server is running: `curl http://localhost:8000/analytics/health`
- Check ANTHROPIC_API_KEY is set in `.env`
- View error details in query cell

### **Slow queries**
- Reduce max_resources in code (default: 1000)
- Use more specific filters
- Check FHIR server performance

### **Missing visualizations**
- Ensure plotly is installed: `pip install plotly==5.14.1`
- Check browser console for errors
- Try refreshing the page

---

## Comparison: Old UI vs New Notebook

### **Old Form-Based UI** (researcher_portal.py)
```

 Fill in form fields: 
 Name: ___________ 
 Email: ___________ 
 IRB: ___________ 

 Data Request: 

 I need heart failure... 

 [Submit Request] 

```

### **New Notebook UI** (research_notebook.py)
```

 Chat Interface 

 You: male patients under 30 with 
 type 2 diabetes 

 Assistant: [x] Found 3 patients 

 Query Cell [1] 
 ViewDefs: patient_demographics, 
 condition_diagnoses 
 Filters: gender=male, age<30, T2D 

 Results Cell [1] 
 Summary: 3 patients, male, age 22-28 

 ID | Name | Age | Condition 
 p1 | John | 28 | Type 2 diabetes 
 p5 | Mike | 22 | Type 2 diabetes 
 p8 | Tom | 26 | Type 2 diabetes 

 [ CSV] [ JSON] [ Charts] 

```

**Benefits:**
- [x] Instant results (no form submission)
- [x] Visual feedback (charts, stats)
- [x] Natural conversation
- [x] Iterative exploration
- [x] Top 20 results + download all
- [x] Summary statistics built-in

---

## Success!

You now have a **state-of-the-art interactive research notebook** that:

[x] Accepts natural language queries
[x] Translates to SQL-on-FHIR automatically
[x] Displays top 20 results with full data export
[x] Shows summary statistics
[x] Provides interactive visualizations
[x] Supports multi-resource joins
[x] Maintains session history

**Access the notebook at**: http://localhost:8503

**Example query to try right now:**
```
Give me all male patients under the age of 30 with type 2 diabetes
```

Enjoy exploring your FHIR data! 
