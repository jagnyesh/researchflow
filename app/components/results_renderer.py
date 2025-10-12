"""
Results Renderer Component

Renders query results in notebook-style cells with tables, charts, and stats
"""

import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from typing import List, Dict, Any, Optional
import json
from datetime import datetime

from ..utils.stats_calculator import StatsCalculator, SummaryStats


class ResultsRenderer:
    """
    Renders query results in interactive notebook cells

    Features:
    - Top N results table with sorting/filtering
    - Summary statistics display
    - Data visualizations (charts)
    - Download options (CSV, JSON)
    - Expandable details
    """

    @staticmethod
    def render_query_cell(
        cell_number: int,
        query_intent: Any,
        execution_time_ms: float = 0.0,
        sql_queries: Optional[Dict[str, str]] = None
    ):
        """
        Render query details cell

        Args:
            cell_number: Cell number in notebook
            query_intent: QueryIntent object with query details
            execution_time_ms: Query execution time
            sql_queries: Dict mapping view_name to SQL query string
        """
        with st.container():
            col1, col2 = st.columns([3, 1])

            with col1:
                st.markdown(f"### Query Cell [{cell_number}]")

            with col2:
                if execution_time_ms > 0:
                    st.caption(f"Execution time: {execution_time_ms:.0f}ms")

            # SQL Queries Section - Show the actual SQL executed
            if sql_queries:
                ResultsRenderer._render_sql_queries(sql_queries)

            # Query details in expandable section
            with st.expander("Query Details", expanded=False):
                col1, col2 = st.columns(2)

                with col1:
                    st.markdown("**ViewDefinitions:**")
                    for vd in query_intent.view_definitions:
                        st.code(vd, language="text")

                    if query_intent.search_params:
                        st.markdown("**FHIR Search Parameters:**")
                        st.json(query_intent.search_params)

                with col2:
                    st.markdown("**Filters:**")
                    if query_intent.filters:
                        for key, value in query_intent.filters.items():
                            st.text(f"• {key}: {value}")
                    else:
                        st.text("None")

                    if query_intent.post_filters:
                        st.markdown("**Post-Filters:**")
                        for pf in query_intent.post_filters:
                            st.text(f"• {pf.get('condition_name', pf.get('field'))}")

            # Explanation
            st.info(f"{query_intent.explanation}")

            st.markdown("---")

    @staticmethod
    def _render_sql_queries(sql_queries: Dict[str, str]):
        """
        Render SQL queries in an expandable section

        Args:
            sql_queries: Dict mapping view_name to SQL query string
        """
        with st.expander("SQL Queries Executed", expanded=True):
            st.markdown("The following SQL queries were executed against the FHIR database:")

            for view_name, sql_query in sql_queries.items():
                st.markdown(f"**{view_name}:**")
                st.code(sql_query, language="sql")
                st.markdown("")  # Add spacing

    @staticmethod
    def render_results_cell(
        cell_number: int,
        rows: List[Dict[str, Any]],
        resource_type: str = "Patient",
        max_display: int = 20,
        show_stats: bool = True,
        show_charts: bool = True
    ):
        """
        Render results cell with data table, stats, and visualizations

        Args:
            cell_number: Cell number in notebook
            rows: Query result rows
            resource_type: Type of FHIR resource
            max_display: Maximum rows to display
            show_stats: Show summary statistics
            show_charts: Show visualizations
        """
        with st.container():
            st.markdown(f"### Results Cell [{cell_number}]")

            if not rows:
                st.warning("No results found")
                return

            # Calculate statistics
            stats = StatsCalculator.calculate_stats(rows, resource_type)

            # Summary Statistics Section
            if show_stats:
                ResultsRenderer._render_summary_stats(stats)

            # Results Table Section
            st.markdown("#### Top Results")

            # Convert to DataFrame
            df = pd.DataFrame(rows[:max_display])

            # Show record count info
            total_records = len(rows)
            displayed_records = min(max_display, total_records)

            if total_records > max_display:
                st.caption(f"Showing {displayed_records} of {total_records:,} total records")
            else:
                st.caption(f"Showing all {total_records:,} records")

            # Display table
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=False,
                height=400
            )

            # Download buttons
            ResultsRenderer._render_download_buttons(rows, df, cell_number)

            # Visualizations
            if show_charts and len(rows) > 1:
                ResultsRenderer._render_visualizations(df, stats)

            st.markdown("---")

    @staticmethod
    def _render_summary_stats(stats: SummaryStats):
        """Render summary statistics in metric cards"""
        st.markdown("#### Summary Statistics")

        # Create metric columns
        cols = st.columns(4)

        # Total count
        with cols[0]:
            st.metric("Total Records", f"{stats.total_count:,}")

        # Gender distribution
        if stats.gender_distribution:
            total = stats.total_count
            gender_text = " | ".join([
                f"{g.capitalize()}: {c} ({c/total*100:.0f}%)"
                for g, c in sorted(stats.gender_distribution.items())
            ])
            with cols[1]:
                st.metric("Gender", gender_text)

        # Age statistics
        if stats.age_stats:
            age = stats.age_stats
            age_text = f"{age['min']:.0f}-{age['max']:.0f} yrs"
            with cols[2]:
                st.metric(
                    "Age Range",
                    age_text,
                    delta=f"μ={age['mean']:.1f}"
                )

        # Date range
        if stats.date_range:
            date_info = stats.date_range
            span_days = date_info['span_days']
            span_text = f"{span_days} days" if span_days < 365 else f"{span_days//365} yrs"
            with cols[3]:
                st.metric("Date Span", span_text)

        # Condition prevalence (if present)
        if stats.condition_prevalence:
            st.markdown("**Top Conditions:**")
            cond_cols = st.columns(min(3, len(stats.condition_prevalence)))
            for idx, (condition, count) in enumerate(list(stats.condition_prevalence.items())[:3]):
                with cond_cols[idx]:
                    st.metric(
                        condition[:30] + "..." if len(condition) > 30 else condition,
                        f"{count} ({count/stats.total_count*100:.0f}%)"
                    )

    @staticmethod
    def _render_download_buttons(rows: List[Dict], df: pd.DataFrame, cell_number: int):
        """Render download buttons for data export"""
        col1, col2, col3 = st.columns([1, 1, 3])

        with col1:
            # CSV download
            csv = df.to_csv(index=False)
            st.download_button(
                label="Download CSV",
                data=csv,
                file_name=f"results_cell_{cell_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv"
            )

        with col2:
            # JSON download
            json_str = json.dumps(rows, indent=2)
            st.download_button(
                label="Download JSON",
                data=json_str,
                file_name=f"results_cell_{cell_number}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
                mime="application/json"
            )

    @staticmethod
    def _render_visualizations(df: pd.DataFrame, stats: SummaryStats):
        """Render data visualizations"""
        with st.expander("Visualizations", expanded=False):
            viz_cols = st.columns(2)

            # Gender distribution pie chart
            if stats.gender_distribution and len(stats.gender_distribution) > 1:
                with viz_cols[0]:
                    st.markdown("**Gender Distribution**")
                    fig = px.pie(
                        values=list(stats.gender_distribution.values()),
                        names=[g.capitalize() for g in stats.gender_distribution.keys()],
                        title="Gender Distribution"
                    )
                    st.plotly_chart(fig, use_container_width=True)

            # Age distribution histogram
            if stats.age_stats and 'birth_date' in df.columns:
                with viz_cols[1]:
                    st.markdown("**Age Distribution**")

                    # Calculate ages
                    current_year = datetime.now().year
                    ages = []
                    for bd in df['birth_date'].dropna():
                        try:
                            birth_year = int(str(bd)[:4])
                            age = current_year - birth_year
                            if 0 <= age <= 150:
                                ages.append(age)
                        except:
                            continue

                    if ages:
                        fig = px.histogram(
                            x=ages,
                            nbins=20,
                            title="Age Distribution",
                            labels={'x': 'Age (years)', 'y': 'Count'}
                        )
                        st.plotly_chart(fig, use_container_width=True)

            # Condition prevalence bar chart
            if stats.condition_prevalence:
                st.markdown("**Condition Prevalence**")
                top_conditions = dict(list(stats.condition_prevalence.items())[:10])

                fig = px.bar(
                    x=list(top_conditions.values()),
                    y=list(top_conditions.keys()),
                    orientation='h',
                    title="Top 10 Conditions",
                    labels={'x': 'Count', 'y': 'Condition'}
                )
                fig.update_layout(height=400)
                st.plotly_chart(fig, use_container_width=True)

    @staticmethod
    def render_error_cell(cell_number: int, error_message: str):
        """Render error cell"""
        with st.container():
            st.markdown(f"### Error Cell [{cell_number}]")
            st.error(f"**Error:** {error_message}")
            st.markdown("---")

    @staticmethod
    def render_thinking_cell(message: str):
        """Render thinking/processing cell"""
        with st.container():
            with st.spinner(message):
                st.info(f"{message}")
