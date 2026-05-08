# Security Setup Guide

This document explains the security measures implemented in ResearchFlow to prevent accidental exposure of secrets and sensitive data.

## Pre-commit Hooks

Pre-commit hooks automatically scan your code before each commit to catch security issues early.

### Installation

```bash
# Install pre-commit
pip install pre-commit

# Install the git hook scripts
pre-commit install

# (Optional) Run against all files
pre-commit run --all-files
```

### What Gets Checked

1. **Secret Detection** (`detect-secrets`)
   - Scans for API keys, tokens, passwords
   - Uses baseline file (`.secrets.baseline`) to track known false positives
   - Blocks commits containing potential secrets

2. **Private Key Detection**
   - Checks for SSH keys, certificates, PEM files
   - Prevents accidental commits of private keys

3. **Code Quality** (`black`)
   - Formats Python code consistently
   - Auto-fixes formatting issues

4. **Security Analysis** (`bandit`)
   - Scans for common security issues
   - Checks for SQL injection, command injection, etc.

5. **File Checks**
   - Prevents large files (>1MB)
   - Fixes trailing whitespace
   - Ensures files end with newline
   - Validates YAML/JSON syntax

### Bypassing Hooks (Use Sparingly)

```bash
# Only use when absolutely necessary
git commit --no-verify -m "message"
```

**⚠️ Warning:** Bypassing hooks can lead to security issues. Only do this if you're certain the flagged content is safe.

## GitHub Actions Security Scanning

Automated security scans run on every push and pull request.

### Workflows

1. **Secret Scanning** (`.github/workflows/security-scan.yml`)
   - **Gitleaks**: Scans git history for secrets
   - **detect-secrets**: Validates baseline and scans new code
   - Runs on: Push, PR, weekly schedule

2. **Dependency Scanning**
   - **Safety**: Checks for known vulnerabilities in Python packages
   - **pip-audit**: Audits dependencies for security issues

3. **Code Security Analysis**
   - **Bandit**: Static analysis for Python security issues
   - Generates reports uploaded as artifacts

4. **Container Scanning** (on main branch)
   - **Trivy**: Scans for vulnerabilities in dependencies and containers
   - Results uploaded to GitHub Security tab

### Viewing Results

1. Go to your repository on GitHub
2. Click "Actions" tab
3. Click on the latest workflow run
4. View logs and artifacts for security reports

## Secret Management Best Practices

### DO:
- ✅ Use `.env` files for local development (gitignored)
- ✅ Store secrets in environment variables
- ✅ Use placeholders in documentation (e.g., `your-key-here`)
- ✅ Rotate keys immediately if exposed
- ✅ Use GitHub Secrets for CI/CD variables

### DON'T:
- ❌ Hardcode API keys in source code
- ❌ Commit `.env` files
- ❌ Share secrets in commit messages
- ❌ Use real keys in example files
- ❌ Disable security hooks without review

## Configuration Files

### `.pre-commit-config.yaml`
Defines pre-commit hooks and their configuration.

### `.secrets.baseline`
Tracks known false positives for `detect-secrets`. If you add legitimate code that triggers false positives:

```bash
# Update baseline
detect-secrets scan > .secrets.baseline

# Audit baseline (mark false positives)
detect-secrets audit .secrets.baseline
```

### `pyproject.toml`
Configuration for Bandit security scanning and code quality tools.

### `.github/workflows/security-scan.yml`
GitHub Actions workflow for automated security scanning.

## Responding to Security Findings

### If Pre-commit Blocks Your Commit:

1. **Review the output** - Understand what was detected
2. **Remove the secret** - Replace with environment variable
3. **Update baseline if false positive**:
   ```bash
   detect-secrets scan > .secrets.baseline
   detect-secrets audit .secrets.baseline
   ```
4. **Try committing again**

### If Secret Was Already Committed:

1. **DO NOT just delete it in a new commit** - it's still in git history
2. **Follow these steps**:
   ```bash
   # Use git-filter-repo or BFG Repo-Cleaner to remove from history
   # OR rewrite history with interactive rebase (for recent commits)
   git rebase -i HEAD~N  # N = number of commits back

   # Force push (⚠️ coordinate with team)
   git push --force-with-lease
   ```
3. **Rotate the exposed secret immediately**
4. **Monitor for unauthorized usage**

### If GitHub Actions Fails:

1. Check the Actions tab for detailed logs
2. Review the specific security findings
3. Fix issues in your code
4. Push the fixes
5. Verify the checks pass

## API Key Rotation Checklist

If a secret is exposed:

- [ ] Revoke/rotate the exposed key immediately
- [ ] Update `.env` file with new key
- [ ] Update CI/CD secrets (GitHub Secrets)
- [ ] Monitor for unauthorized usage
- [ ] Review access logs
- [ ] Document the incident
- [ ] Update team members

## Resources

- [detect-secrets documentation](https://github.com/Yelp/detect-secrets)
- [pre-commit documentation](https://pre-commit.com/)
- [Gitleaks documentation](https://github.com/gitleaks/gitleaks)
- [GitHub Secret Scanning](https://docs.github.com/en/code-security/secret-scanning)
- [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)

## Questions?

If you encounter issues with the security setup, please:
1. Check this documentation
2. Review tool-specific documentation
3. Open an issue with details about the problem
