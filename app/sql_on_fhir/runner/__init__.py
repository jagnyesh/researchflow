"""
ViewDefinition Runners

Runners execute ViewDefinitions to transform FHIR resources into tabular format.

Two implementations:
- InMemoryRunner: Fetches via REST API, processes in Python (slower)
- PostgresRunner: Executes as SQL in database (10-100x faster)
"""

from .in_memory_runner import InMemoryRunner
from .postgres_runner import PostgresRunner, create_postgres_runner

__all__ = ['InMemoryRunner', 'PostgresRunner', 'create_postgres_runner']
