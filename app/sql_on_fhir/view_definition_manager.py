"""
ViewDefinition Manager

Manages SQL-on-FHIR v2 ViewDefinition resources:
- Load/save ViewDefinitions from JSON
- Validate ViewDefinition structure
- CRUD operations
- ViewDefinition composition and reuse
"""

import json
import os
import logging
from typing import Dict, Any, List, Optional
from pathlib import Path

logger = logging.getLogger(__name__)


class ViewDefinitionManager:
    """
    Manager for SQL-on-FHIR v2 ViewDefinition resources

    Responsibilities:
    - Load ViewDefinitions from JSON files
    - Validate ViewDefinition structure
    - Provide CRUD operations
    - Manage ViewDefinition library
    """

    def __init__(self, view_definitions_dir: Optional[str] = None):
        """
        Initialize ViewDefinition manager

        Args:
            view_definitions_dir: Directory containing ViewDefinition JSON files
                                 Defaults to app/sql_on_fhir/view_definitions/
        """
        if view_definitions_dir is None:
            # Default to view_definitions directory in same package
            current_dir = Path(__file__).parent
            view_definitions_dir = current_dir / "view_definitions"

        self.view_definitions_dir = Path(view_definitions_dir)
        self.view_definitions_dir.mkdir(parents=True, exist_ok=True)

        # In-memory cache of loaded ViewDefinitions
        self._cache: Dict[str, Dict[str, Any]] = {}

        logger.info(f"Initialized ViewDefinitionManager with directory: {self.view_definitions_dir}")

    def load(self, name: str) -> Dict[str, Any]:
        """
        Load a ViewDefinition by name

        Args:
            name: ViewDefinition name (without .json extension)

        Returns:
            ViewDefinition resource as dict

        Raises:
            FileNotFoundError: If ViewDefinition file not found
            ValueError: If ViewDefinition is invalid
        """
        # Check cache first
        if name in self._cache:
            logger.debug(f"Loading ViewDefinition '{name}' from cache")
            return self._cache[name]

        # Load from file
        file_path = self.view_definitions_dir / f"{name}.json"

        if not file_path.exists():
            raise FileNotFoundError(f"ViewDefinition file not found: {file_path}")

        logger.debug(f"Loading ViewDefinition from file: {file_path}")

        try:
            with open(file_path, 'r') as f:
                view_def = json.load(f)

            # Validate
            self.validate(view_def)

            # Cache
            self._cache[name] = view_def

            logger.info(f"Loaded ViewDefinition '{name}' for resource type '{view_def.get('resource')}'")
            return view_def

        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON in ViewDefinition file: {e}")

    def save(self, view_definition: Dict[str, Any], name: Optional[str] = None) -> str:
        """
        Save a ViewDefinition to file

        Args:
            view_definition: ViewDefinition resource as dict
            name: Optional name for the file (defaults to view_definition['name'])

        Returns:
            Name of saved ViewDefinition

        Raises:
            ValueError: If ViewDefinition is invalid
        """
        # Validate first
        self.validate(view_definition)

        # Determine name
        if name is None:
            name = view_definition.get('name')
            if not name:
                raise ValueError("ViewDefinition must have 'name' field or name must be provided")

        file_path = self.view_definitions_dir / f"{name}.json"

        logger.debug(f"Saving ViewDefinition to: {file_path}")

        try:
            with open(file_path, 'w') as f:
                json.dump(view_definition, f, indent=2)

            # Update cache
            self._cache[name] = view_definition

            logger.info(f"Saved ViewDefinition '{name}'")
            return name

        except Exception as e:
            logger.error(f"Error saving ViewDefinition: {e}")
            raise

    def delete(self, name: str) -> bool:
        """
        Delete a ViewDefinition

        Args:
            name: ViewDefinition name

        Returns:
            True if deleted, False if not found
        """
        file_path = self.view_definitions_dir / f"{name}.json"

        if not file_path.exists():
            logger.warning(f"ViewDefinition file not found: {file_path}")
            return False

        try:
            file_path.unlink()

            # Remove from cache
            self._cache.pop(name, None)

            logger.info(f"Deleted ViewDefinition '{name}'")
            return True

        except Exception as e:
            logger.error(f"Error deleting ViewDefinition: {e}")
            raise

    def list(self) -> List[str]:
        """
        List all available ViewDefinition names

        Returns:
            List of ViewDefinition names
        """
        json_files = self.view_definitions_dir.glob("*.json")
        names = [f.stem for f in json_files]

        logger.debug(f"Found {len(names)} ViewDefinitions")
        return sorted(names)

    def load_all(self) -> Dict[str, Dict[str, Any]]:
        """
        Load all ViewDefinitions in directory

        Returns:
            Dict mapping names to ViewDefinition resources
        """
        names = self.list()
        view_defs = {}

        for name in names:
            try:
                view_defs[name] = self.load(name)
            except Exception as e:
                logger.warning(f"Failed to load ViewDefinition '{name}': {e}")

        logger.info(f"Loaded {len(view_defs)} ViewDefinitions")
        return view_defs

    def validate(self, view_definition: Dict[str, Any]) -> bool:
        """
        Validate ViewDefinition structure

        Args:
            view_definition: ViewDefinition resource to validate

        Returns:
            True if valid

        Raises:
            ValueError: If ViewDefinition is invalid
        """
        # Check required fields
        if view_definition.get('resourceType') != 'ViewDefinition':
            raise ValueError("resourceType must be 'ViewDefinition'")

        if 'resource' not in view_definition:
            raise ValueError("ViewDefinition must have 'resource' field")

        if 'name' not in view_definition:
            raise ValueError("ViewDefinition must have 'name' field")

        # Validate name format (must be database-friendly)
        name = view_definition['name']
        if not name[0].isalpha():
            raise ValueError("ViewDefinition name must start with a letter")

        if not all(c.isalnum() or c == '_' for c in name):
            raise ValueError("ViewDefinition name must contain only letters, numbers, and underscores")

        # Check select structure
        if 'select' not in view_definition:
            raise ValueError("ViewDefinition must have 'select' field")

        select = view_definition['select']
        if not isinstance(select, list) or len(select) == 0:
            raise ValueError("ViewDefinition 'select' must be a non-empty array")

        # Validate each select element
        for i, select_elem in enumerate(select):
            self._validate_select_element(select_elem, i)

        logger.debug(f"ViewDefinition validation passed: {view_definition.get('name')}")
        return True

    def _validate_select_element(self, select_elem: Dict[str, Any], index: int):
        """
        Validate a single select element

        Args:
            select_elem: Select element to validate
            index: Index in select array (for error messages)

        Raises:
            ValueError: If select element is invalid
        """
        # Must have either 'column', 'select', or 'unionAll'
        if 'column' not in select_elem and 'select' not in select_elem and 'unionAll' not in select_elem:
            raise ValueError(f"Select element {index} must have 'column', 'select', or 'unionAll'")

        # Validate columns if present
        if 'column' in select_elem:
            columns = select_elem['column']
            if not isinstance(columns, list):
                raise ValueError(f"Select element {index} 'column' must be an array")

            for col_idx, column in enumerate(columns):
                self._validate_column(column, index, col_idx)

        # Validate forEach if present
        if 'forEach' in select_elem:
            if not isinstance(select_elem['forEach'], str):
                raise ValueError(f"Select element {index} 'forEach' must be a string")

            # forEach requires column
            if 'column' not in select_elem:
                raise ValueError(f"Select element {index} with 'forEach' must have 'column'")

        # Validate forEachOrNull if present
        if 'forEachOrNull' in select_elem:
            if not isinstance(select_elem['forEachOrNull'], str):
                raise ValueError(f"Select element {index} 'forEachOrNull' must be a string")

            # Can't have both forEach and forEachOrNull
            if 'forEach' in select_elem:
                raise ValueError(f"Select element {index} cannot have both 'forEach' and 'forEachOrNull'")

    def _validate_column(self, column: Dict[str, Any], select_idx: int, col_idx: int):
        """
        Validate a column definition

        Args:
            column: Column definition to validate
            select_idx: Index of parent select element
            col_idx: Index of column in columns array

        Raises:
            ValueError: If column is invalid
        """
        # Must have 'name' and 'path'
        if 'name' not in column:
            raise ValueError(f"Column {col_idx} in select {select_idx} must have 'name'")

        if 'path' not in column:
            raise ValueError(f"Column {col_idx} in select {select_idx} must have 'path'")

        # Validate column name
        name = column['name']
        if not name[0].isalpha():
            raise ValueError(f"Column name '{name}' must start with a letter")

        if not all(c.isalnum() or c == '_' for c in name):
            raise ValueError(f"Column name '{name}' must contain only letters, numbers, and underscores")

        # Path must be string
        if not isinstance(column['path'], str):
            raise ValueError(f"Column '{name}' path must be a string")

    def get_resource_type(self, name: str) -> str:
        """
        Get the FHIR resource type for a ViewDefinition

        Args:
            name: ViewDefinition name

        Returns:
            FHIR resource type (e.g., "Patient", "Observation")
        """
        view_def = self.load(name)
        return view_def.get('resource')

    def create_from_template(
        self,
        resource_type: str,
        name: str,
        columns: List[Dict[str, str]],
        where: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        Create a ViewDefinition from a simple template

        Args:
            resource_type: FHIR resource type
            name: ViewDefinition name
            columns: List of column definitions [{"name": "col1", "path": "field1"}, ...]
            where: Optional list of FHIRPath where clauses

        Returns:
            ViewDefinition resource

        Example:
            view_def = manager.create_from_template(
                resource_type="Patient",
                name="active_patients",
                columns=[
                    {"name": "id", "path": "id"},
                    {"name": "gender", "path": "gender"}
                ],
                where=["active = true"]
            )
        """
        view_definition = {
            "resourceType": "ViewDefinition",
            "resource": resource_type,
            "name": name,
            "select": [
                {
                    "column": columns
                }
            ]
        }

        if where:
            view_definition["where"] = [{"path": w} for w in where]

        # Validate
        self.validate(view_definition)

        logger.info(f"Created ViewDefinition '{name}' for {resource_type}")
        return view_definition
