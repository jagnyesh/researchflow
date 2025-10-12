"""
SQL-on-FHIR v2 Implementation

Provides ViewDefinition management and execution for transforming
FHIR resources into tabular format.
"""

from .view_definition_manager import ViewDefinitionManager

__all__ = ['ViewDefinitionManager']
