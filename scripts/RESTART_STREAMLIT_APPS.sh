#!/bin/bash

# RESTART_STREAMLIT_APPS.sh
# Kill all running Streamlit processes and restart the apps with the fixed code

echo "="
echo "Restarting Streamlit Apps with Fixed Code"
echo "="
echo ""

# Step 1: Kill all existing Streamlit processes
echo "[1/3] Killing existing Streamlit processes..."
pkill -f "streamlit run" || echo "No existing Streamlit processes found"
sleep 2

# Step 2: Start Researcher Portal
echo ""
echo "[2/3] Starting Researcher Portal on port 8501..."
streamlit run app/web_ui/researcher_portal.py --server.port 8501 &
PORTAL_PID=$!
echo "Researcher Portal started with PID: $PORTAL_PID"

# Give it time to initialize
sleep 3

# Step 3: Start Admin Dashboard
echo ""
echo "[3/3] Starting Admin Dashboard on port 8502..."
HAPI_DB_URL=postgresql://hapi:hapi@localhost:5433/hapi \
streamlit run app/web_ui/admin_dashboard.py --server.port 8502 &
DASHBOARD_PID=$!
echo "Admin Dashboard started with PID: $DASHBOARD_PID"

echo ""
echo "="
echo "✅ Apps restarted successfully!"
echo "="
echo ""
echo "Researcher Portal: http://localhost:8501"
echo "Admin Dashboard: http://localhost:8502"
echo ""
echo "To check status: ps aux | grep streamlit"
echo "To view logs: tail -f ~/.streamlit/logs/*.log"
echo ""
