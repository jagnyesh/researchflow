# Pull Request

## Description
Brief description of changes made in this PR.

## Related Issues
Closes #(issue number)
Relates to #(issue number)

## Type of Change
Please check the relevant option:

- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Code refactoring (no functional changes)
- [ ] Performance improvement
- [ ] Test addition or update
- [ ] Configuration change

## Changes Made
Detailed list of changes:
- Change 1
- Change 2
- Change 3

## Testing Performed
Describe the tests you ran to verify your changes:

### Unit Tests
```bash
pytest tests/unit/test_...
```

### Integration Tests
```bash
pytest tests/integration/test_...
```

### Manual Testing
1. Step 1
2. Step 2
3. Step 3

## Test Coverage
- [ ] Added tests for new functionality
- [ ] Updated existing tests
- [ ] All tests pass locally
- [ ] Coverage remains above 80%

```bash
# Paste coverage report summary
Coverage: 85%
```

## Screenshots (if applicable)
Add screenshots to demonstrate UI changes or new features.

## Checklist
Please ensure all items are completed before requesting review:

### Code Quality
- [ ] Code follows the project's style guidelines (PEP 8, Black, flake8)
- [ ] Self-review of code completed
- [ ] Code is commented, particularly in hard-to-understand areas
- [ ] No unnecessary console logs or debug code
- [ ] No hardcoded secrets or API keys

### Testing
- [ ] All existing tests pass
- [ ] New tests added for new functionality
- [ ] Edge cases considered and tested
- [ ] Integration tests pass (if applicable)

### Documentation
- [ ] README.md updated (if needed)
- [ ] API documentation updated (docstrings)
- [ ] CHANGELOG.md updated with changes
- [ ] Architecture diagrams updated (if applicable)
- [ ] User guides updated (if applicable)

### Database Changes
- [ ] No database changes
- [ ] Migration scripts created (if applicable)
- [ ] Migration tested locally
- [ ] Migration tested on staging (if applicable)

### Security
- [ ] No new security vulnerabilities introduced
- [ ] Input validation implemented
- [ ] SQL injection prevention confirmed
- [ ] PHI data handling follows policy (if applicable)
- [ ] Authentication/authorization checks in place (if applicable)

### Performance
- [ ] No performance degradation
- [ ] Performance improvements measured (if applicable)
- [ ] Query optimization considered (if applicable)

## Breaking Changes
If this PR contains breaking changes, please describe:
- What breaks?
- Migration path for users?
- Deprecation warnings added?

## Deployment Notes
Special considerations for deployment:
- Environment variables to add/update
- Configuration changes required
- Database migrations to run
- Service restarts needed

## Reviewer Notes
Anything specific you want reviewers to focus on?

## Post-Deployment Verification
Steps to verify after deployment:
1. Step 1
2. Step 2
3. Step 3

## Additional Context
Add any other context about the PR here.
