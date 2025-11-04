#!/bin/bash
#
# Quick Test Script for LangGraph with LangSmith Tracing
#
# Usage:
#   ./scripts/test_with_langsmith.sh exploratory   # Test exploratory portal
#   ./scripts/test_with_langsmith.sh formal        # Test formal portal
#   ./scripts/test_with_langsmith.sh admin         # Test admin dashboard
#   ./scripts/test_with_langsmith.sh all           # Test all portals

set -e  # Exit on error

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"
echo -e "${BLUE}   ResearchFlow LangGraph Testing with LangSmith   ${NC}"
echo -e "${BLUE}═══════════════════════════════════════════════════${NC}"

# Check .env file exists
if [ ! -f .env ]; then
    echo -e "${RED}✗ Error: .env file not found${NC}"
    echo "  Run: cp config/.env.example .env"
    exit 1
fi

# Source .env
export $(cat .env | grep -v '^#' | xargs)

# Verify LangSmith is configured
if [ "$LANGCHAIN_TRACING_V2" != "true" ]; then
    echo -e "${YELLOW}⚠ Warning: LangSmith tracing not enabled${NC}"
    echo "  Set LANGCHAIN_TRACING_V2=true in .env"
    read -p "Continue anyway? (y/n) " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        exit 1
    fi
fi

# Check services are running
echo -e "\n${BLUE}Checking required services...${NC}"

# Check PostgreSQL
if pg_isready -h localhost -p 5434 -U researchflow > /dev/null 2>&1; then
    echo -e "${GREEN}✓ PostgreSQL (ResearchFlow) running${NC}"
else
    echo -e "${RED}✗ PostgreSQL (ResearchFlow) not running${NC}"
    echo "  Run: docker-compose -f config/docker-compose.yml up db -d"
    exit 1
fi

# Check HAPI FHIR database
if pg_isready -h localhost -p 5433 -U hapi > /dev/null 2>&1; then
    echo -e "${GREEN}✓ HAPI PostgreSQL running${NC}"
else
    echo -e "${YELLOW}⚠ HAPI PostgreSQL not running (optional)${NC}"
fi

# Check Redis
if redis-cli ping > /dev/null 2>&1; then
    echo -e "${GREEN}✓ Redis running${NC}"
else
    echo -e "${YELLOW}⚠ Redis not running (speed layer disabled)${NC}"
fi

# Check HAPI FHIR server
if curl -s -f http://localhost:8081/fhir/metadata > /dev/null 2>&1; then
    echo -e "${GREEN}✓ HAPI FHIR server running${NC}"
else
    echo -e "${YELLOW}⚠ HAPI FHIR server not running (optional)${NC}"
fi

# Show LangSmith configuration
echo -e "\n${BLUE}LangSmith Configuration:${NC}"
echo "  Tracing: $LANGCHAIN_TRACING_V2"
echo "  Project: $LANGCHAIN_PROJECT"
echo "  API Key: ${LANGCHAIN_API_KEY:0:20}..."
echo ""
echo -e "  ${GREEN}View traces:${NC} https://smith.langchain.com/projects/$LANGCHAIN_PROJECT"

# Ask which orchestrator to use
echo -e "\n${BLUE}Orchestrator Selection:${NC}"
echo "  1) Legacy orchestrator (default)"
echo "  2) LangGraph orchestrator (NEW - 100% complete)"
read -p "Select orchestrator (1 or 2): " orch_choice

if [ "$orch_choice" == "2" ]; then
    export USE_LANGGRAPH_WORKFLOW=true
    echo -e "${GREEN}✓ Using LangGraph orchestrator${NC}"
else
    export USE_LANGGRAPH_WORKFLOW=false
    echo -e "${GREEN}✓ Using legacy orchestrator${NC}"
fi

# Function to start portal
start_portal() {
    local portal=$1
    local port=$2
    local file=$3

    echo -e "\n${BLUE}Starting $portal on port $port...${NC}"
    echo -e "  URL: ${GREEN}http://localhost:$port${NC}"
    echo ""
    echo -e "${YELLOW}Press Ctrl+C to stop${NC}"
    echo ""

    # Ensure environment variables are exported
    export LANGCHAIN_TRACING_V2
    export LANGCHAIN_API_KEY
    export LANGCHAIN_PROJECT
    export USE_LANGGRAPH_WORKFLOW

    # Start Streamlit
    streamlit run "app/web_ui/$file" --server.port $port
}

# Parse command
case "${1:-all}" in
    exploratory|exp)
        start_portal "Exploratory Portal (Research Notebook)" 8503 "research_notebook.py"
        ;;
    formal|portal)
        start_portal "Formal Request Portal" 8501 "researcher_portal.py"
        ;;
    admin|dashboard)
        start_portal "Admin Dashboard" 8502 "admin_dashboard.py"
        ;;
    all)
        echo -e "\n${BLUE}Starting all portals in background...${NC}"
        echo ""

        # Kill any existing Streamlit processes
        pkill -f streamlit || true
        sleep 2

        # Start all portals in background
        export LANGCHAIN_TRACING_V2 USE_LANGGRAPH_WORKFLOW LANGCHAIN_API_KEY LANGCHAIN_PROJECT

        echo "Starting exploratory portal on 8503..."
        nohup streamlit run app/web_ui/research_notebook.py --server.port 8503 > logs/exploratory_$(date +%Y%m%d_%H%M%S).log 2>&1 &

        echo "Starting formal portal on 8501..."
        nohup streamlit run app/web_ui/researcher_portal.py --server.port 8501 > logs/formal_$(date +%Y%m%d_%H%M%S).log 2>&1 &

        echo "Starting admin dashboard on 8502..."
        nohup streamlit run app/web_ui/admin_dashboard.py --server.port 8502 > logs/admin_$(date +%Y%m%d_%H%M%S).log 2>&1 &

        sleep 3

        echo -e "\n${GREEN}✓ All portals started!${NC}"
        echo ""
        echo "Access portals:"
        echo -e "  • Exploratory: ${GREEN}http://localhost:8503${NC}"
        echo -e "  • Formal:      ${GREEN}http://localhost:8501${NC}"
        echo -e "  • Admin:       ${GREEN}http://localhost:8502${NC}"
        echo ""
        echo "View logs:"
        echo "  tail -f logs/*.log"
        echo ""
        echo "Stop all:"
        echo "  pkill -f streamlit"
        ;;
    *)
        echo -e "${RED}Unknown command: $1${NC}"
        echo ""
        echo "Usage:"
        echo "  $0 exploratory   # Test exploratory portal"
        echo "  $0 formal        # Test formal portal"
        echo "  $0 admin         # Test admin dashboard"
        echo "  $0 all           # Start all portals"
        exit 1
        ;;
esac
