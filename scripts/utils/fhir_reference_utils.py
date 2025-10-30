#!/usr/bin/env python3
"""
FHIR Reference Utilities

Helper functions for handling FHIR references in materialized views.

FHIR references follow the pattern: "{ResourceType}/{id}"
Examples:
  - "Patient/12345"
  - "Practitioner/abc-def"
  - "Organization/12345"

This module provides utilities to:
1. Extract resource IDs from FHIR references
2. Generate SQL expressions for reference extraction
3. Validate reference formats
"""

import re
from typing import Optional, Tuple


class FHIRReferenceUtils:
    """Utilities for working with FHIR references"""

    # FHIR reference pattern: ResourceType/id
    REFERENCE_PATTERN = re.compile(r'^([A-Z][a-zA-Z]+)/(.+)$')

    @staticmethod
    def extract_id(reference: Optional[str]) -> Optional[str]:
        """
        Extract ID from FHIR reference

        Args:
            reference: FHIR reference (e.g., "Patient/12345")

        Returns:
            Extracted ID (e.g., "12345") or None if invalid

        Examples:
            >>> FHIRReferenceUtils.extract_id("Patient/12345")
            "12345"
            >>> FHIRReferenceUtils.extract_id("Observation/abc-def-123")
            "abc-def-123"
            >>> FHIRReferenceUtils.extract_id(None)
            None
        """
        if not reference:
            return None

        # Try to split on '/'
        parts = reference.split('/')
        if len(parts) == 2:
            return parts[1]

        return None

    @staticmethod
    def extract_resource_type(reference: Optional[str]) -> Optional[str]:
        """
        Extract resource type from FHIR reference

        Args:
            reference: FHIR reference (e.g., "Patient/12345")

        Returns:
            Resource type (e.g., "Patient") or None if invalid

        Examples:
            >>> FHIRReferenceUtils.extract_resource_type("Patient/12345")
            "Patient"
        """
        if not reference:
            return None

        parts = reference.split('/')
        if len(parts) == 2:
            return parts[0]

        return None

    @staticmethod
    def parse_reference(reference: Optional[str]) -> Optional[Tuple[str, str]]:
        """
        Parse FHIR reference into (resource_type, id) tuple

        Args:
            reference: FHIR reference (e.g., "Patient/12345")

        Returns:
            Tuple of (resource_type, id) or None if invalid

        Examples:
            >>> FHIRReferenceUtils.parse_reference("Patient/12345")
            ("Patient", "12345")
        """
        if not reference:
            return None

        match = FHIRReferenceUtils.REFERENCE_PATTERN.match(reference)
        if match:
            return (match.group(1), match.group(2))

        return None

    @staticmethod
    def is_valid_reference(reference: Optional[str]) -> bool:
        """
        Check if string is a valid FHIR reference

        Args:
            reference: String to validate

        Returns:
            True if valid FHIR reference format

        Examples:
            >>> FHIRReferenceUtils.is_valid_reference("Patient/12345")
            True
            >>> FHIRReferenceUtils.is_valid_reference("12345")
            False
            >>> FHIRReferenceUtils.is_valid_reference(None)
            False
        """
        if not reference:
            return False

        return FHIRReferenceUtils.REFERENCE_PATTERN.match(reference) is not None

    @staticmethod
    def build_reference(resource_type: str, resource_id: str) -> str:
        """
        Build FHIR reference from resource type and ID

        Args:
            resource_type: FHIR resource type (e.g., "Patient")
            resource_id: Resource ID (e.g., "12345")

        Returns:
            FHIR reference (e.g., "Patient/12345")

        Examples:
            >>> FHIRReferenceUtils.build_reference("Patient", "12345")
            "Patient/12345"
        """
        return f"{resource_type}/{resource_id}"

    @staticmethod
    def get_sql_extract_id_expression(column_name: str) -> str:
        """
        Generate SQL expression to extract ID from FHIR reference column

        Args:
            column_name: Name of column containing FHIR reference

        Returns:
            SQL expression string

        Examples:
            >>> FHIRReferenceUtils.get_sql_extract_id_expression("patient_ref")
            "SPLIT_PART(patient_ref, '/', 2)"
        """
        return f"SPLIT_PART({column_name}, '/', 2)"

    @staticmethod
    def get_sql_extract_resource_type_expression(column_name: str) -> str:
        """
        Generate SQL expression to extract resource type from FHIR reference

        Args:
            column_name: Name of column containing FHIR reference

        Returns:
            SQL expression string

        Examples:
            >>> FHIRReferenceUtils.get_sql_extract_resource_type_expression("subject")
            "SPLIT_PART(subject, '/', 1)"
        """
        return f"SPLIT_PART({column_name}, '/', 1)"

    @staticmethod
    def get_sql_function_definition() -> str:
        """
        Get SQL function definition for extracting IDs from FHIR references

        Returns:
            SQL CREATE FUNCTION statement

        Usage:
            await conn.execute(FHIRReferenceUtils.get_sql_function_definition())
        """
        return """
CREATE OR REPLACE FUNCTION sqlonfhir.extract_fhir_id(ref TEXT)
RETURNS TEXT AS $$
BEGIN
    IF ref IS NULL THEN
        RETURN NULL;
    END IF;

    RETURN SPLIT_PART(ref, '/', 2);
END;
$$ LANGUAGE plpgsql IMMUTABLE;
"""


# Convenience functions for direct use

def extract_patient_id_from_reference(reference: Optional[str]) -> Optional[str]:
    """
    Extract patient ID from FHIR Patient reference

    Args:
        reference: Patient reference (e.g., "Patient/12345")

    Returns:
        Patient ID or None

    Examples:
        >>> extract_patient_id_from_reference("Patient/12345")
        "12345"
    """
    parsed = FHIRReferenceUtils.parse_reference(reference)
    if parsed and parsed[0] == 'Patient':
        return parsed[1]
    return None


def sql_extract_id(column_name: str) -> str:
    """
    Shorthand for SQL ID extraction expression

    Args:
        column_name: Column containing FHIR reference

    Returns:
        SQL expression

    Examples:
        >>> sql_extract_id("patient_ref")
        "SPLIT_PART(patient_ref, '/', 2)"
    """
    return FHIRReferenceUtils.get_sql_extract_id_expression(column_name)


# SQL template for views with FHIR references
SQL_DUAL_COLUMN_TEMPLATE = """
-- Extract both full reference and ID for easy JOINs
{reference_column_expression} as {reference_column_name},
{id_extract_expression} as {id_column_name}
"""


def generate_dual_column_sql(
    source_expression: str,
    reference_column_name: str = "patient_ref",
    id_column_name: str = "patient_id"
) -> str:
    """
    Generate SQL for dual column (reference + extracted ID)

    Args:
        source_expression: Source JSONB expression
        reference_column_name: Name for full reference column
        id_column_name: Name for extracted ID column

    Returns:
        SQL string with both columns

    Examples:
        >>> generate_dual_column_sql(
        ...     "v.res_text_vc::jsonb->'subject'->>'reference'",
        ...     "patient_ref",
        ...     "patient_id"
        ... )
        Generates SQL with both patient_ref and patient_id columns
    """
    id_expression = f"SPLIT_PART({source_expression}, '/', 2)"

    return f"""{source_expression} as {reference_column_name},
            {id_expression} as {id_column_name}"""
