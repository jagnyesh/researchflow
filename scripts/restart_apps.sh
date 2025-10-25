#!/bin/bash

# ResearchFlow - Restart All Streamlit Apps
# Use this script after theme configuration changes

echo "🛑 Stopping all Streamlit apps..."

# Kill all streamlit processes
pkill -f "streamlit run"

# Wait a moment for cleanup
sleep 2

echo "✅ Stopped all apps"
echo ""
echo "🚀 Starting apps..."

# Change to project directory
cd "$(dirname "$0")/.."

# Activate virtual environment if it exists
if [ -d ".venv" ]; then
    source .venv/bin/activate
    echo "✅ Activated virtual environment"
fi

# Start Researcher Portal (port 8501)
echo "🔬 Starting Researcher Portal on port 8501..."
streamlit run app/web_ui/researcher_portal.py --server.port 8501 > logs/portal.log 2>&1 &
PORTAL_PID=$!

# Start Admin Dashboard (port 8502)
echo "⚙️  Starting Admin Dashboard on port 8502..."
streamlit run app/web_ui/admin_dashboard.py --server.port 8502 > logs/dashboard.log 2>&1 &
DASHBOARD_PID=$!

# Start Research Notebook (port 8503)
echo "🤖 Starting Research Notebook on port 8503..."
streamlit run app/web_ui/research_notebook.py --server.port 8503 > logs/notebook.log 2>&1 &
NOTEBOOK_PID=$!

# Wait a moment for startup
sleep 3

echo ""
echo "✅ All apps started!"
echo ""
echo "📊 Process IDs:"
echo "   Researcher Portal: $PORTAL_PID"
echo "   Admin Dashboard:   $DASHBOARD_PID"
echo "   Research Notebook: $NOTEBOOK_PID"
echo ""
echo "🌐 Access URLs:"
echo "   Researcher Portal: http://localhost:8501"
echo "   Admin Dashboard:   http://localhost:8502"
echo "   Research Notebook: http://localhost:8503"
echo ""
echo "📝 Logs:"
echo "   Portal:    tail -f logs/portal.log"
echo "   Dashboard: tail -f logs/dashboard.log"
echo "   Notebook:  tail -f logs/notebook.log"
echo ""
echo "💡 Tip: Hard refresh your browser (Ctrl+Shift+R or Cmd+Shift+R) to clear cache"
