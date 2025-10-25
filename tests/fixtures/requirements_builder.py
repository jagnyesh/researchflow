"""
Requirements Builder for Tests

Helper class to build requirements in the exact format expected by SQLGenerator.
This matches the structure produced by Requirements Agent's _criteria_to_structured() method.

Usage:
    from tests.fixtures import RequirementsBuilder as RB

    requirements = RB.build_requirements(
        inclusion=[
            RB.build_condition('diabetes mellitus'),
            RB.build_condition('heart failure')
        ],
        exclusion=[
            RB.build_condition('pregnancy')
        ],
        time_period={'start': '2024-01-01', 'end': '2024-12-31'}
    )
"""

from typing import List, Dict, Any, Optional


class RequirementsBuilder:
    """
    Helper class to build test requirements in production-accurate format

    The SQLGenerator expects criteria in this format:
    {
        'description': 'diabetes mellitus',
        'concepts': [{'type': 'condition', 'term': 'diabetes'}],
        'codes': []
    }

    This matches the output from Requirements Agent's _criteria_to_structured() method.
    """

    @staticmethod
    def build_condition(
        description: str,
        term: Optional[str] = None,
        concept_type: str = 'condition'
    ) -> Dict[str, Any]:
        """
        Build a single condition criterion

        Args:
            description: Human-readable description (e.g., 'diabetes mellitus')
            term: Term to use in SQL (defaults to description)
            concept_type: Type of concept ('condition', 'lab', 'procedure')

        Returns:
            Structured criterion dict

        Example:
            RB.build_condition('diabetes mellitus')
            RB.build_condition('HbA1c > 8', term='HbA1c', concept_type='lab')
        """
        if term is None:
            term = description

        return {
            'description': description,
            'concepts': [
                {
                    'type': concept_type,
                    'term': term
                }
            ],
            'codes': []
        }

    @staticmethod
    def build_demographic(
        description: str,
        term: Optional[str] = None,
        details: str = ''
    ) -> Dict[str, Any]:
        """
        Build a demographic criterion (age, gender, race, etc.)

        Args:
            description: Human-readable description (e.g., 'age > 65')
            term: Term for SQL (defaults to description)
            details: Additional details (e.g., '> 65' for age criteria)

        Returns:
            Structured criterion dict

        Example:
            RB.build_demographic('age > 65', term='age', details='> 65')
            RB.build_demographic('female', term='female')
        """
        if term is None:
            term = description

        return {
            'description': description,
            'concepts': [
                {
                    'type': 'demographic',
                    'term': term,
                    'details': details
                }
            ],
            'codes': []
        }

    @staticmethod
    def build_lab(
        description: str,
        term: Optional[str] = None,
        operator: str = '',
        value: str = ''
    ) -> Dict[str, Any]:
        """
        Build a lab value criterion

        Args:
            description: Human-readable description (e.g., 'HbA1c > 8')
            term: Lab name (defaults to description)
            operator: Comparison operator (>, <, =, etc.)
            value: Threshold value

        Returns:
            Structured criterion dict

        Example:
            RB.build_lab('HbA1c > 8', term='HbA1c', operator='>', value='8')
        """
        if term is None:
            term = description

        concept = {
            'type': 'lab',
            'term': term
        }

        if operator:
            concept['operator'] = operator
        if value:
            concept['value'] = value

        return {
            'description': description,
            'concepts': [concept],
            'codes': []
        }

    @staticmethod
    def build_requirements(
        inclusion: Optional[List[Dict]] = None,
        exclusion: Optional[List[Dict]] = None,
        time_period: Optional[Dict[str, str]] = None,
        data_elements: Optional[List[str]] = None,
        study_title: Optional[str] = None,
        principal_investigator: Optional[str] = None,
        irb_number: Optional[str] = None,
        phi_level: Optional[str] = None,
        delivery_format: Optional[str] = None,
        estimated_cohort_size: Optional[int] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Build complete requirements dict

        Args:
            inclusion: List of inclusion criteria (use build_condition/demographic/lab)
            exclusion: List of exclusion criteria
            time_period: {'start': 'YYYY-MM-DD', 'end': 'YYYY-MM-DD'}
            data_elements: List of data elements ['demographics', 'lab_results', ...]
            study_title: Study title
            principal_investigator: PI name
            irb_number: IRB approval number
            phi_level: PHI level ('de-identified', 'limited', 'full')
            delivery_format: Delivery format ('CSV', 'JSON', etc.)
            estimated_cohort_size: Estimated cohort size
            **kwargs: Additional fields

        Returns:
            Complete requirements dict ready for SQLGenerator

        Example:
            requirements = RB.build_requirements(
                inclusion=[
                    RB.build_condition('diabetes'),
                    RB.build_demographic('age > 65', term='age', details='> 65')
                ],
                exclusion=[
                    RB.build_condition('pregnancy')
                ],
                time_period={'start': '2024-01-01', 'end': '2024-12-31'},
                data_elements=['demographics', 'lab_results']
            )
        """
        requirements = {
            'inclusion_criteria': inclusion or [],
            'exclusion_criteria': exclusion or [],
            'time_period': time_period or {},
            'data_elements': data_elements or []
        }

        # Add optional fields if provided
        if study_title:
            requirements['study_title'] = study_title
        if principal_investigator:
            requirements['principal_investigator'] = principal_investigator
        if irb_number:
            requirements['irb_number'] = irb_number
        if phi_level:
            requirements['phi_level'] = phi_level
        if delivery_format:
            requirements['delivery_format'] = delivery_format
        if estimated_cohort_size:
            requirements['estimated_cohort_size'] = estimated_cohort_size

        # Add any additional kwargs
        requirements.update(kwargs)

        return requirements

    @staticmethod
    def build_simple_requirements(
        inclusion_str: Optional[List[str]] = None,
        exclusion_str: Optional[List[str]] = None,
        time_period: Optional[Dict[str, str]] = None,
        data_elements: Optional[List[str]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """
        Build requirements from simple string lists (convenience method)

        Automatically converts string criteria to structured format.
        Assumes all criteria are conditions (not demographics or labs).

        Args:
            inclusion_str: List of inclusion criteria as strings
            exclusion_str: List of exclusion criteria as strings
            time_period: Time period dict
            data_elements: Data elements list
            **kwargs: Additional fields

        Returns:
            Complete requirements dict

        Example:
            requirements = RB.build_simple_requirements(
                inclusion_str=['diabetes', 'heart failure'],
                exclusion_str=['pregnancy'],
                time_period={'start': '2024-01-01'}
            )
        """
        # Convert strings to structured criteria
        inclusion = [
            RequirementsBuilder.build_condition(crit)
            for crit in (inclusion_str or [])
        ]

        exclusion = [
            RequirementsBuilder.build_condition(crit)
            for crit in (exclusion_str or [])
        ]

        return RequirementsBuilder.build_requirements(
            inclusion=inclusion,
            exclusion=exclusion,
            time_period=time_period,
            data_elements=data_elements,
            **kwargs
        )
