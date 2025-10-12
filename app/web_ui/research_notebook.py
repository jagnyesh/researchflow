"""
Research Notebook - Interactive Query Interface

Jupyter notebook-style interface for natural language queries against FHIR data.
Seamlessly translates queries to SQL-on-FHIR ViewDefinitions and displays results.
"""

import streamlit as st
import asyncio
import sys
import os
from datetime import datetime
from typing import List, Dict, Any
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from app.services.query_interpreter import QueryInterpreter, QueryIntent
from app.clients.analytics_client import AnalyticsClient, QueryResult
from app.components.results_renderer import ResultsRenderer
from app.sql_on_fhir.view_definition_manager import ViewDefinitionManager
from app.utils.view_definition_sql import view_definition_to_sql


# Page config
st.set_page_config(
    page_title="ResearchFlow - Interactive Research Notebook",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for better notebook styling
st.markdown("""
<style>
    /* Chat message styling - improved contrast */
    [data-testid="stChatMessageContent"][data-testid*="user"] {
        background-color: #e3f2fd !important;
        border-radius: 10px;
        padding: 12px;
        margin: 5px 0;
        border: 1px solid #90caf9;
    }

    [data-testid="stChatMessageContent"][data-testid*="assistant"] {
        background-color: #f5f5f5 !important;
        border-radius: 10px;
        padding: 12px;
        margin: 5px 0;
        border: 1px solid #e0e0e0;
    }

    /* Notebook cell styling */
    .notebook-cell {
        background-color: white;
        border: 1px solid #e0e0e0;
        border-radius: 8px;
        padding: 20px;
        margin: 15px 0;
    }

    /* Query code styling */
    .query-code {
        background-color: #f5f5f5;
        border-left: 4px solid #1f77b4;
        padding: 10px;
        font-family: monospace;
    }

    /* SQL code block styling */
    .sql-query-box {
        background-color: #2e3440;
        color: #d8dee9;
        padding: 15px;
        border-radius: 5px;
        font-family: 'Courier New', monospace;
        font-size: 13px;
        overflow-x: auto;
        margin: 10px 0;
    }
</style>
""", unsafe_allow_html=True)


def initialize_session_state():
    """Initialize session state variables"""
    if 'messages' not in st.session_state:
        st.session_state.messages = []

    if 'notebook_cells' not in st.session_state:
        st.session_state.notebook_cells = []

    if 'cell_counter' not in st.session_state:
        st.session_state.cell_counter = 0

    if 'query_interpreter' not in st.session_state:
        st.session_state.query_interpreter = QueryInterpreter()

    if 'analytics_client' not in st.session_state:
        st.session_state.analytics_client = AnalyticsClient()


async def process_query(user_query: str):
    """
    Process natural language query end-to-end

    Steps:
    1. Interpret query using LLM
    2. Execute ViewDefinitions
    3. Post-process and filter results
    4. Display in notebook cell
    """
    # Increment cell counter
    st.session_state.cell_counter += 1
    cell_num = st.session_state.cell_counter

    try:
        # Step 1: Interpret query
        with st.status("Interpreting query...", expanded=True) as status:
            st.write("Analyzing natural language query...")
            query_intent = await st.session_state.query_interpreter.interpret_query(user_query)
            st.write(f"Identified ViewDefinitions: {', '.join(query_intent.view_definitions)}")
            status.update(label="Query interpreted", state="complete")

        # Step 2: Load ViewDefinitions and generate SQL representations
        view_manager = ViewDefinitionManager()
        sql_queries = {}

        for view_name in query_intent.view_definitions:
            try:
                view_def = view_manager.load(view_name)
                sql_repr = view_definition_to_sql(view_def, query_intent.search_params)
                sql_queries[view_name] = sql_repr
            except Exception as e:
                st.warning(f"Could not load ViewDefinition '{view_name}': {e}")

        # Step 3: Execute ViewDefinitions
        with st.status("Executing SQL-on-FHIR queries...", expanded=True) as status:
            results = {}
            total_time = 0

            for view_name in query_intent.view_definitions:
                st.write(f"Executing {view_name}...")
                result = await st.session_state.analytics_client.execute_view_definition(
                    view_name=view_name,
                    search_params=query_intent.search_params,
                    max_resources=1000  # Get up to 1000 resources
                )
                results[view_name] = result
                total_time += result.execution_time_ms
                st.write(f"{view_name}: {result.row_count} rows in {result.execution_time_ms:.0f}ms")

            status.update(label=f"Executed {len(results)} ViewDefinitions in {total_time:.0f}ms", state="complete")

        # Step 3: Post-process results
        with st.status("Processing results...", expanded=False) as status:
            # Join results if multiple ViewDefinitions
            if len(results) == 1:
                final_rows = list(results.values())[0].rows
                resource_type = list(results.values())[0].resource_type
            else:
                # Join on patient_id
                primary_result = results.get('patient_demographics') or list(results.values())[0]
                final_rows = primary_result.rows
                resource_type = primary_result.resource_type

                # Join with other results
                for view_name, result in results.items():
                    if view_name != 'patient_demographics':
                        final_rows = await st.session_state.analytics_client.join_results(
                            QueryResult(
                                view_name="joined",
                                resource_type=resource_type,
                                row_count=len(final_rows),
                                rows=final_rows,
                                schema={}
                            ),
                            result
                        )

            # Apply post-filters
            if query_intent.post_filters:
                for post_filter in query_intent.post_filters:
                    filter_spec = {
                        "field": post_filter.get("field"),
                        "value": post_filter.get("value"),
                        "operator": "eq"
                    }
                    final_rows = await st.session_state.analytics_client.filter_rows(
                        final_rows,
                        [filter_spec]
                    )
                st.write(f"Applied {len(query_intent.post_filters)} post-filters: {len(final_rows)} rows remain")

            status.update(label=f"Processed {len(final_rows)} final results", state="complete")

        # Step 4: Display results
        st.success(f"Query completed! Found {len(final_rows)} matching records.")

        # Store in notebook cells
        notebook_cell = {
            'cell_number': cell_num,
            'query': user_query,
            'query_intent': query_intent,
            'results': final_rows,
            'resource_type': resource_type,
            'execution_time_ms': total_time,
            'sql_queries': sql_queries
        }
        st.session_state.notebook_cells.append(notebook_cell)

        # Render query cell
        ResultsRenderer.render_query_cell(
            cell_number=cell_num,
            query_intent=query_intent,
            execution_time_ms=total_time,
            sql_queries=sql_queries
        )

        # Render results cell
        ResultsRenderer.render_results_cell(
            cell_number=cell_num,
            rows=final_rows,
            resource_type=resource_type,
            max_display=20,  # Top 20 results
            show_stats=True,
            show_charts=True
        )

    except Exception as e:
        st.error(f"Error processing query: {str(e)}")
        ResultsRenderer.render_error_cell(cell_num, str(e))


def render_sidebar():
    """Render sidebar with session info and controls"""
    with st.sidebar:
        st.header("Notebook Session")

        # Session info
        st.metric("Total Queries", len(st.session_state.notebook_cells))
        st.metric("Total Cells", st.session_state.cell_counter)

        # Quick actions
        st.markdown("### Quick Actions")

        if st.button("Clear Notebook", use_container_width=True):
            st.session_state.notebook_cells = []
            st.session_state.messages = []
            st.session_state.cell_counter = 0
            st.rerun()

        if st.button("Export Session", use_container_width=True):
            import json
            session_data = {
                'cells': st.session_state.notebook_cells,
                'messages': st.session_state.messages,
                'timestamp': datetime.now().isoformat()
            }
            st.download_button(
                label="Download JSON",
                data=json.dumps(session_data, indent=2, default=str),
                file_name=f"research_session_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )

        # Example queries
        st.markdown("### Example Queries")
        example_queries = [
            "How many patients are available?",
            "Show me all male patients under age 30",
            "Give me all male patients under the age of 30 with type 2 diabetes",
            "Show me patients with hypertension",
            "Get female patients with diabetes and their lab results",
        ]

        for example in example_queries:
            if st.button(f"{example[:40]}...", key=f"example_{example[:20]}", use_container_width=True):
                st.session_state.example_query = example
                st.rerun()

        # System info
        st.markdown("---")
        st.caption("Powered by SQL-on-FHIR v2")
        st.caption("Claude API for query interpretation")


def main():
    """Main application"""
    # Initialize
    initialize_session_state()

    # Header
    st.title("ResearchFlow - Interactive Research Notebook")
    st.caption("Ask questions in natural language, get instant answers from FHIR data")

    # Sidebar
    render_sidebar()

    # Main chat interface
    st.markdown("### Natural Language Query Interface")

    # Display chat messages
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Display notebook cells
    if st.session_state.notebook_cells:
        st.markdown("---")
        st.markdown("### Notebook Cells")

        for cell in st.session_state.notebook_cells:
            # Query cell
            ResultsRenderer.render_query_cell(
                cell_number=cell['cell_number'],
                query_intent=cell['query_intent'],
                execution_time_ms=cell['execution_time_ms'],
                sql_queries=cell.get('sql_queries')
            )

            # Results cell
            ResultsRenderer.render_results_cell(
                cell_number=cell['cell_number'],
                rows=cell['results'],
                resource_type=cell.get('resource_type', 'Patient'),
                max_display=20,
                show_stats=True,
                show_charts=True
            )

    # Chat input
    user_query = st.chat_input("Ask a question about patient data...")

    # Handle example query from sidebar
    if 'example_query' in st.session_state:
        user_query = st.session_state.example_query
        del st.session_state.example_query

    # Process user input
    if user_query:
        # Add user message to chat
        st.session_state.messages.append({"role": "user", "content": user_query})

        # Display user message
        with st.chat_message("user"):
            st.markdown(user_query)

        # Process query
        with st.chat_message("assistant"):
            asyncio.run(process_query(user_query))

        # Add assistant response to chat
        st.session_state.messages.append({
            "role": "assistant",
            "content": f"Executed query and created Cell [{st.session_state.cell_counter}]"
        })

        # Rerun to update UI
        st.rerun()


if __name__ == "__main__":
    main()
