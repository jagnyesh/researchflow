"""
ViewDefinition Runners

Runners execute ViewDefinitions to transform FHIR resources into tabular format.

Available implementations:
- InMemoryRunner: Fetches via REST API, processes in Python (slow but flexible)
- PostgresRunner: Generates + executes SQL in database (fast)
- MaterializedViewRunner: Queries pre-computed views (ultra-fast, 10-100x improvement)
- HybridRunner: Smart routing - uses materialized views when available (RECOMMENDED)

Performance comparison:
- InMemoryRunner: 500-5000ms (REST API overhead)
- PostgresRunner: 50-500ms (transpilation + SQL generation)
- MaterializedViewRunner: 5-10ms (direct query)
- HybridRunner: 5-10ms (when view exists) or 50-500ms (fallback)
"""

from .in_memory_runner import InMemoryRunner
from .postgres_runner import PostgresRunner, create_postgres_runner
from .materialized_view_runner import MaterializedViewRunner
from .hybrid_runner import HybridRunner

__all__ = [
    'InMemoryRunner',
    'PostgresRunner',
    'MaterializedViewRunner',
    'HybridRunner',
    'create_postgres_runner'
]
