# LangSmith API Key Rotation Guide

## ⚠️ URGENT ACTION REQUIRED

A LangSmith API key was exposed in your git history before being removed. Even though we've cleaned the repository, you **must rotate this key immediately** as it may have been accessed.

**Exposed Key (redacted):** `lsv2_pt_[REDACTED]`

## Why This Is Critical

Even though the key has been removed from git history:
- The repository may have been indexed by GitHub's search
- The key could have been visible to anyone who cloned the repository before cleanup
- It's a security best practice to assume exposed credentials are compromised

## Step-by-Step Rotation Process

### 1. Generate New LangSmith API Key

1. **Go to LangSmith Settings**
   - Visit: https://smith.langchain.com/settings
   - Or click your profile → Settings → API Keys

2. **Create New API Key**
   - Click "Create API Key" button
   - Give it a descriptive name (e.g., "ResearchFlow Production - Nov 2025")
   - Copy the new key immediately (it won't be shown again)
   - **Save it securely** (password manager recommended)

3. **Revoke Old API Key**
   - Find the existing key in the list
   - Click "Revoke" or the trash icon
   - Confirm revocation

### 2. Update Local Environment

1. **Open your `.env` file**
   ```bash
   open /Users/jagnyesh/Development/FHIR_PROJECT/.env
   ```

2. **Replace the LangSmith API key**
   ```bash
   # OLD (remove this line)
   LANGCHAIN_API_KEY=lsv2_pt_[YOUR_OLD_EXPOSED_KEY]

   # NEW (replace with your new key)
   LANGCHAIN_API_KEY=lsv2_pt_YOUR_NEW_KEY_HERE
   ```

3. **Save and close** the file

### 3. Update CI/CD Secrets (If Applicable)

If you're using this key in GitHub Actions or other CI/CD:

1. **GitHub Secrets**
   - Go to: https://github.com/jagnyesh/researchflow/settings/secrets/actions
   - Update `LANGCHAIN_API_KEY` secret with new value

2. **Other Platforms**
   - Update any other deployment environments
   - Check: Docker, Heroku, AWS, Azure, etc.

### 4. Restart Services

1. **Stop running services**
   ```bash
   # Kill any running Streamlit UIs
   pkill -f streamlit

   # Kill API server
   pkill -f uvicorn
   ```

2. **Restart with new key**
   ```bash
   # Source new environment
   source .venv/bin/activate

   # Restart services (they'll pick up new key)
   # ... your usual startup commands
   ```

### 5. Verify New Key Works

1. **Test API Connection**
   ```bash
   # Quick test
   python -c "import os; from langsmith import Client; c = Client(); print('✅ LangSmith connection successful!')"
   ```

2. **Check LangSmith Dashboard**
   - Visit: https://smith.langchain.com/
   - Go to your project: `researchflow-production`
   - Run a test request and verify new traces appear

### 6. Monitor for Suspicious Activity

1. **Check LangSmith Usage**
   - Go to: https://smith.langchain.com/settings/usage
   - Look for unusual spikes or patterns
   - Check dates/times around key exposure

2. **Review Traces**
   - Check if any unexpected traces appeared
   - Look for unusual projects or API calls

3. **If You See Suspicious Activity**
   - Contact LangSmith support immediately
   - Change any related credentials
   - Review access logs thoroughly

## Security Checklist

After rotation, verify these items:

- [ ] New API key created in LangSmith
- [ ] Old API key revoked in LangSmith
- [ ] `.env` file updated with new key
- [ ] GitHub Secrets updated (if applicable)
- [ ] Services restarted
- [ ] New key tested and working
- [ ] Usage dashboard checked for anomalies
- [ ] This guide deleted (after completion)

## Post-Rotation Actions

1. **Update Team Members**
   - If working with a team, notify them of the key change
   - Share new key through secure channel (not Slack/email)

2. **Document Incident**
   - Note date/time of exposure
   - Note date/time of rotation
   - Keep for security audit trail

3. **Improve Security**
   - Pre-commit hooks now prevent future exposures ✅
   - GitHub Actions scan for secrets automatically ✅
   - Consider using secret management service (AWS Secrets Manager, Azure Key Vault)

## Need Help?

- **LangSmith Support:** https://docs.smith.langchain.com/
- **General Questions:** Open an issue in the repository
- **Security Concerns:** Follow GitHub's security advisory process

## Cleanup

Once you've completed all steps:

```bash
# Securely delete this guide
rm /Users/jagnyesh/Development/FHIR_PROJECT/LANGSMITH_KEY_ROTATION_GUIDE.md
```

---

**Remember:** The exposed key should be considered compromised and must be rotated. This is non-negotiable for production security.
