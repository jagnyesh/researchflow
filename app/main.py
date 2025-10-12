from fastapi import FastAPI
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

from .api.health import router as health_router
from .api.text2sql import router as t2s_router
from .api.sql_on_fhir import router as sql_router
from .api.mcp import router as mcp_router
from .api.a2a import router as a2a_router
from .api.analytics import router as analytics_router
from .api.approvals import router as approvals_router

app = FastAPI(title="FHIR Phenotyping & Data Delivery Starter")

app.include_router(health_router)
app.include_router(t2s_router)
app.include_router(sql_router)
app.include_router(mcp_router)
app.include_router(a2a_router)
app.include_router(analytics_router)
app.include_router(approvals_router)
