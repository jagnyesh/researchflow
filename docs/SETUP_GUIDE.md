# ResearchFlow Setup Guide

## Quick Start (3 steps)

### Step 1: Add Your API Key

Edit the `.env` file and replace `your-key-here` with your actual Anthropic API key:

```bash
# Open .env file in your editor
nano .env

# Or use echo
echo 'ANTHROPIC_API_KEY=sk-ant-api03-your-actual-key-here' > .env
```

**Where to get your API key:**
1. Go to https://console.anthropic.com/
2. Sign in or create an account
3. Navigate to "API Keys"
4. Create a new key or copy an existing one
5. It starts with `sk-ant-api03-`

### Step 2: Install Dependencies

```bash
# Create virtual environment (if not already done)
python3 -m venv .venv
source .venv/bin/activate # On Windows: .venv\Scripts\activate

# Install all packages
pip install -r requirements.txt
```

### Step 3: Run the Application

**Option A: Run Researcher Portal**
```bash
streamlit run app/web_ui/researcher_portal.py --server.port 8501
```
Then open http://localhost:8501 in your browser

**Option B: Run Admin Dashboard**
```bash
streamlit run app/web_ui/admin_dashboard.py --server.port 8502
```
Then open http://localhost:8502 in your browser

**Option C: Run Both (separate terminals)**
```bash
# Terminal 1
streamlit run app/web_ui/researcher_portal.py --server.port 8501

# Terminal 2
streamlit run app/web_ui/admin_dashboard.py --server.port 8502
```

---

## Verify Your Setup

### Test API Key

```bash
# Quick test
python -c "
from dotenv import load_dotenv
import os
load_dotenv()
key = os.getenv('ANTHROPIC_API_KEY')
print(f'API Key loaded: {key[:20]}...' if key else 'ERROR: No API key found')
"
```

Should output: `API Key loaded: sk-ant-api03-xxxxx...`

### Test Import

```bash
python -c "
from app.agents import RequirementsAgent
from app.orchestrator import ResearchRequestOrchestrator
print('[x] All imports successful!')
"
```

---

## Troubleshooting

### Issue: "ANTHROPIC_API_KEY not set"

**Solution:** The `.env` file isn't being loaded. Either:

1. **Set environment variable manually:**
 ```bash
 export ANTHROPIC_API_KEY="sk-ant-api03-your-key"
 streamlit run app/web_ui/researcher_portal.py
 ```

2. **Or load .env in Python:**
 Add this to the top of the Streamlit files:
 ```python
 from dotenv import load_dotenv
 load_dotenv()
 ```

### Issue: "Module not found"

**Solution:** Make sure you're in the project root and virtual env is activated:
```bash
cd /Users/jagnyesh/Development/FHIR_PROJECT
source .venv/bin/activate
pip install -r requirements.txt
```

### Issue: "Port already in use"

**Solution:** Change the port number:
```bash
streamlit run app/web_ui/researcher_portal.py --server.port 8503
```

---

## Running Without API Key (Testing Mode)

The LLM client has a fallback dummy mode if no API key is set. It will return mock responses for testing the workflow without making actual API calls.

**Limited functionality:**
- [x] Workflow routing works
- [x] Agents execute
- [x] UI displays correctly
- [ ] No real LLM conversation
- [ ] No intelligent requirement extraction

---

## Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | Yes* | None | Claude API key (sk-ant-...) |
| `DATABASE_URL` | No | SQLite | Database connection string |
| `A2A_JWT_SECRET` | No | `devsecret` | JWT signing secret |

*Required for full LLM functionality. System works in limited mode without it.

---

## Next Steps

1. [x] Set API key in `.env`
2. [x] Install dependencies
3. [x] Run Researcher Portal
4. Try submitting a test request:
 ```
 I need clinical notes for heart failure patients
 admitted in 2024. De-identified data is fine.
 ```
5. View request progress in real-time
6. Open Admin Dashboard to see agent metrics

---

## Production Deployment

For production use, consider:

1. **Secure Secrets Management**
 - Use AWS Secrets Manager, Azure Key Vault, or HashiCorp Vault
 - Never commit `.env` to git (already in .gitignore)

2. **Database Migration**
 - Switch from SQLite to PostgreSQL
 - Run Alembic migrations: `alembic upgrade head`

3. **Environment-Specific Configs**
 - `.env.development`
 - `.env.staging`
 - `.env.production`

4. **Docker Deployment**
 ```bash
 docker-compose up --build
 ```

---

## Support

- **Documentation:** See `RESEARCHFLOW_README.md`
- **Architecture:** See `CLAUDE.md`
- **PRD Reference:** See `ResearchFlow PRD.md`

Enjoy automating your research data requests! 
