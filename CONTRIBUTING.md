# Contributing to ResearchFlow

Thank you for your interest in contributing to ResearchFlow! This document provides guidelines and instructions for contributing to the project.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Process](#development-process)
- [Reporting Bugs](#reporting-bugs)
- [Suggesting Features](#suggesting-features)
- [Pull Request Process](#pull-request-process)
- [Code Style Guidelines](#code-style-guidelines)
- [Testing Requirements](#testing-requirements)
- [Documentation Requirements](#documentation-requirements)

## Code of Conduct

This project and everyone participating in it is governed by our Code of Conduct. By participating, you are expected to uphold this code. Please report unacceptable behavior to the project maintainers.

## Getting Started

### Prerequisites

- Python 3.9 or higher
- PostgreSQL (optional, SQLite supported for development)
- Anthropic API key (Claude)

### Development Setup

1. Fork the repository
2. Clone your fork:
   ```bash
   git clone https://github.com/yourusername/researchflow.git
   cd researchflow
   ```

3. Create a virtual environment:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

4. Install dependencies:
   ```bash
   pip install -r config/requirements.txt
   pip install -r config/requirements-dev.txt
   ```

5. Set up environment variables:
   ```bash
   cp config/.env.example .env
   # Edit .env and add your ANTHROPIC_API_KEY
   ```

6. Run tests to verify setup:
   ```bash
   pytest
   ```

## Development Process

### Branching Strategy

- `main` - Production-ready code
- `develop` - Development branch (default target for PRs)
- `feature/*` - Feature branches
- `bugfix/*` - Bug fix branches
- `hotfix/*` - Urgent production fixes

### Creating a Feature Branch

```bash
git checkout develop
git pull origin develop
git checkout -b feature/your-feature-name
```

### Making Changes

1. Make your changes in your feature branch
2. Write or update tests for your changes
3. Ensure all tests pass: `pytest`
4. Run linters: `black app/` and `flake8 app/`
5. Update documentation if needed
6. Commit your changes with clear, descriptive commit messages

### Commit Message Guidelines

Follow the conventional commits specification:

```
<type>(<scope>): <description>

[optional body]

[optional footer]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation only changes
- `style`: Code style changes (formatting, no code change)
- `refactor`: Code refactoring (no feature change)
- `perf`: Performance improvement
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**
```
feat(phenotype): add SQL query validation before execution

fix(orchestrator): resolve circular import in approval workflow

docs(readme): update installation instructions for Docker
```

## Reporting Bugs

### Before Submitting a Bug Report

- Check the [documentation](docs/) to ensure it's not a configuration issue
- Check [existing issues](https://github.com/yourusername/researchflow/issues) to avoid duplicates
- Collect relevant information:
  - ResearchFlow version
  - Python version
  - Operating system
  - Database type (PostgreSQL/SQLite)
  - Error messages and stack traces

### Submitting a Bug Report

Use the bug report template when creating an issue. Include:

1. **Clear title** - Brief description of the problem
2. **Description** - Detailed explanation of the bug
3. **Steps to reproduce** - Exact steps to reproduce the behavior
4. **Expected behavior** - What should happen
5. **Actual behavior** - What actually happens
6. **Screenshots** - If applicable
7. **Environment** - System information
8. **Logs** - Relevant log excerpts

## Suggesting Features

### Before Submitting a Feature Request

- Check [existing issues](https://github.com/yourusername/researchflow/issues) for similar proposals
- Consider whether the feature aligns with ResearchFlow's goals
- Think about how the feature would benefit multiple users

### Submitting a Feature Request

Use the feature request template when creating an issue. Include:

1. **Clear title** - Brief description of the feature
2. **Problem statement** - What problem does this solve?
3. **Proposed solution** - Detailed description of your proposed solution
4. **Alternatives** - Alternative solutions you've considered
5. **Use cases** - Real-world scenarios where this would be useful
6. **Impact** - Who would benefit from this feature?

## Pull Request Process

### Before Submitting a Pull Request

1. **Update tests** - Ensure test coverage for your changes
2. **Run full test suite** - All tests must pass
3. **Run linters** - Code must pass `black` and `flake8`
4. **Update documentation** - Include relevant documentation changes
5. **Update CHANGELOG.md** - Add entry describing your changes
6. **Rebase on develop** - Ensure your branch is up-to-date

### Submitting a Pull Request

1. Push your changes to your fork:
   ```bash
   git push origin feature/your-feature-name
   ```

2. Create a pull request from your fork to `develop` branch

3. Fill out the pull request template completely:
   - Description of changes
   - Related issues
   - Type of change (feature, fix, etc.)
   - Testing performed
   - Screenshots (if UI changes)
   - Checklist completion

4. Ensure CI/CD checks pass

5. Respond to review comments promptly

### Pull Request Review Process

- At least one maintainer must approve the PR
- All CI/CD checks must pass
- No unresolved review comments
- Code must follow style guidelines
- Tests must achieve minimum 80% coverage
- Documentation must be updated

### After PR Approval

- Maintainers will merge using squash and merge
- Your changes will be included in the next release
- You will be credited in the CHANGELOG

## Code Style Guidelines

### Python Style

- Follow [PEP 8](https://pep8.org/) style guide
- Use [Black](https://black.readthedocs.io/) for code formatting (line length: 100)
- Use [flake8](https://flake8.pycqa.org/) for linting
- Use type hints for function parameters and return values

### Code Organization

```python
# Module docstring
"""
Brief description of module.

Longer description if needed.
"""

# Imports (grouped: stdlib, third-party, local)
import os
from typing import Dict, List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from ..database import get_db_session


# Constants
MAX_RETRIES = 3
DEFAULT_TIMEOUT = 30


# Classes and functions
class ExampleClass:
    """Class docstring following Google style."""

    def __init__(self, name: str):
        """Initialize with name."""
        self.name = name

    def example_method(self, param: int) -> str:
        """
        Method docstring.

        Args:
            param: Description of parameter

        Returns:
            Description of return value

        Raises:
            ValueError: When param is negative
        """
        if param < 0:
            raise ValueError("param must be non-negative")
        return f"{self.name}: {param}"
```

### Naming Conventions

- **Classes**: PascalCase (e.g., `RequirementsAgent`)
- **Functions/Methods**: snake_case (e.g., `extract_requirements`)
- **Constants**: UPPER_SNAKE_CASE (e.g., `MAX_RETRIES`)
- **Private methods**: Leading underscore (e.g., `_internal_method`)
- **Async functions**: Prefix with async (e.g., `async def fetch_data()`)

### Documentation Strings

Use Google-style docstrings:

```python
def calculate_feasibility(cohort_size: int, data_completeness: float) -> float:
    """
    Calculate feasibility score for a research request.

    The feasibility score combines cohort size adequacy with data
    completeness to determine if a request is feasible.

    Args:
        cohort_size: Number of patients in the cohort
        data_completeness: Fraction of complete data (0.0-1.0)

    Returns:
        Feasibility score between 0.0 and 1.0

    Raises:
        ValueError: If data_completeness is not between 0 and 1

    Example:
        >>> calculate_feasibility(100, 0.95)
        0.87
    """
    pass
```

## Testing Requirements

### Test Coverage

- Minimum 80% code coverage required
- All new features must include tests
- All bug fixes must include regression tests

### Test Organization

```
tests/
├── unit/              # Unit tests (fast, isolated)
│   ├── test_agents.py
│   ├── test_services.py
│   └── test_utils.py
├── integration/       # Integration tests (slower, dependencies)
│   ├── test_workflow.py
│   └── test_api.py
└── fixtures/          # Shared test fixtures
    └── conftest.py
```

### Writing Tests

```python
import pytest
from app.agents.requirements_agent import RequirementsAgent


@pytest.mark.asyncio
async def test_requirements_extraction():
    """Test requirements extraction from natural language."""
    agent = RequirementsAgent()

    # Arrange
    request = "I need female patients over 50 with diabetes"

    # Act
    result = await agent.extract_requirements(request)

    # Assert
    assert result["inclusion_criteria"]
    assert "female" in str(result["inclusion_criteria"]).lower()
    assert "diabetes" in str(result["inclusion_criteria"]).lower()


@pytest.fixture
def mock_anthropic_client():
    """Fixture for mocked Anthropic API client."""
    # Implementation
    pass
```

### Running Tests

```bash
# All tests
pytest

# With coverage report
pytest --cov=app --cov-report=html

# Specific test file
pytest tests/unit/test_agents.py

# Specific test
pytest tests/unit/test_agents.py::test_requirements_extraction

# Integration tests only
pytest tests/integration/
```

## Documentation Requirements

### Code Documentation

- All public classes and functions must have docstrings
- Complex logic should include inline comments
- Use type hints for clarity

### User Documentation

When adding features, update relevant documentation:

- `README.md` - User-facing features
- `docs/` - Detailed guides and technical documentation
- API documentation - FastAPI automatic docs via docstrings

### Architecture Documentation

For architectural changes, update:

- `diagrams/architecture.puml` - System architecture
- `diagrams/components.puml` - Component relationships
- `diagrams/sequence_flow.puml` - Sequence diagrams

Generate updated PNGs:
```bash
plantuml diagrams/*.puml
```

## Questions?

- Open a [discussion](https://github.com/yourusername/researchflow/discussions) for questions
- Join our community chat (if applicable)
- Check the [documentation](docs/)

Thank you for contributing to ResearchFlow!
