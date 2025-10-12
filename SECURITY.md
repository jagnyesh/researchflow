# Security Policy

## Supported Versions

The following versions of ResearchFlow are currently supported with security updates:

| Version | Supported          |
| ------- | ------------------ |
| 2.x.x   | :white_check_mark: |
| 1.x.x   | :x:                |
| < 1.0   | :x:                |

## Reporting a Vulnerability

We take the security of ResearchFlow seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### Please Do Not

- Open a public GitHub issue for security vulnerabilities
- Disclose the vulnerability publicly before it has been addressed

### Please Do

1. **Email Security Team**: Send details to [security@yourorg.com](mailto:security@yourorg.com)
2. **Include Details**:
   - Type of vulnerability
   - Full paths of source file(s) related to the vulnerability
   - Location of the affected source code (tag/branch/commit or direct URL)
   - Step-by-step instructions to reproduce the issue
   - Proof-of-concept or exploit code (if possible)
   - Impact of the vulnerability
   - Potential mitigations

3. **Response Timeline**:
   - **Within 48 hours**: We will acknowledge receipt of your report
   - **Within 7 days**: We will provide a detailed response with next steps
   - **Within 30 days**: We will work with you to address the vulnerability

### What to Expect

- Confirmation of vulnerability receipt
- Regular updates on our progress
- Credit in the security advisory (if desired)
- Public disclosure coordination after the fix is deployed

## Security Best Practices

### For Administrators

#### API Key Management

1. **Never commit API keys to version control**
   ```bash
   # Always use .env files (gitignored)
   ANTHROPIC_API_KEY=sk-ant-api03-...
   ```

2. **Rotate API keys regularly**
   - Rotate Anthropic API keys every 90 days
   - Rotate database credentials every 180 days
   - Rotate JWT secrets annually

3. **Use environment-specific keys**
   - Development environment: Limited scope keys
   - Staging environment: Separate keys from production
   - Production environment: Full scope, highly secured

4. **Monitor API key usage**
   - Enable API usage monitoring
   - Set up alerts for unusual activity
   - Review access logs regularly

#### Database Security

1. **Use strong passwords**
   ```bash
   # Generate secure passwords
   openssl rand -base64 32
   ```

2. **Enable SSL/TLS for database connections**
   ```python
   DATABASE_URL=postgresql+asyncpg://user:pass@host/db?ssl=require
   ```

3. **Implement database access controls**
   - Principle of least privilege
   - Separate read-only and read-write users
   - Restrict network access to database server

4. **Regular backups**
   - Automated daily backups
   - Encrypted backup storage
   - Test backup restoration monthly

#### PHI Data Handling

ResearchFlow handles Protected Health Information (PHI) and must comply with HIPAA regulations:

1. **Data at Rest**
   - Encrypt database volumes (AES-256)
   - Encrypt backup files
   - Secure file system permissions

2. **Data in Transit**
   - Always use HTTPS/TLS for API communication
   - Encrypt database connections
   - Use VPN for internal network communication

3. **Data Access Logging**
   - Log all PHI data access
   - Include user, timestamp, and action
   - Retain logs for minimum 7 years (HIPAA requirement)
   - Encrypt log files

4. **De-identification**
   - Apply appropriate de-identification based on PHI level
   - Validate de-identification before delivery
   - Document de-identification methods used

5. **Data Retention**
   - Define retention policies
   - Securely delete data after retention period
   - Document deletion with audit trail

#### Authentication & Authorization

1. **Current Limitations** (Development Phase)
   - Streamlit UIs currently lack authentication
   - API endpoints use basic JWT tokens
   - Admin dashboard has no role-based access control

2. **Production Requirements** (Before Deployment)
   - Implement OAuth2/OIDC authentication
   - Add role-based access control (RBAC)
   - Enable multi-factor authentication (MFA)
   - Integrate with institutional SSO

3. **Approval Workflow Security**
   - SQL queries cannot execute without informatician approval
   - All approval decisions are logged
   - Reviewer identity is tracked
   - Timeouts trigger automatic escalation

#### Network Security

1. **Firewall Configuration**
   ```
   Allow:
   - Port 443 (HTTPS) - Public
   - Port 8000 (API) - Internal network only
   - Port 8501/8502 (Streamlit) - Internal network only
   - Port 5432 (PostgreSQL) - Database server only

   Block:
   - All other inbound traffic
   ```

2. **Rate Limiting**
   - Implement rate limiting on API endpoints
   - Protect against DDoS attacks
   - Monitor for unusual traffic patterns

3. **VPC/Network Isolation**
   - Deploy in private subnet
   - Use bastion host for SSH access
   - Enable VPC flow logs

### For Developers

#### Secure Coding Practices

1. **Input Validation**
   ```python
   from pydantic import BaseModel, validator

   class ResearchRequest(BaseModel):
       researcher_email: str

       @validator('researcher_email')
       def email_must_be_valid(cls, v):
           if '@' not in v:
               raise ValueError('Invalid email')
           return v
   ```

2. **SQL Injection Prevention**
   - Always use parameterized queries
   - Never concatenate user input into SQL
   - Use ORM (SQLAlchemy) for queries

   ```python
   # Good
   query = select(Patient).where(Patient.id == patient_id)

   # Bad - Never do this!
   query = f"SELECT * FROM patients WHERE id = {patient_id}"
   ```

3. **Secrets Management**
   ```python
   import os
   from dotenv import load_dotenv

   # Good
   load_dotenv()
   api_key = os.getenv('ANTHROPIC_API_KEY')

   # Bad - Never hardcode secrets!
   # api_key = "sk-ant-api03-..."
   ```

4. **Error Handling**
   - Don't expose stack traces to users
   - Log errors securely
   - Return generic error messages

   ```python
   try:
       result = process_data(data)
   except Exception as e:
       logger.error(f"Processing failed: {str(e)}", exc_info=True)
       raise HTTPException(status_code=500, detail="Processing failed")
   ```

#### Dependency Security

1. **Keep dependencies updated**
   ```bash
   pip install --upgrade pip
   pip list --outdated
   pip install -U <package>
   ```

2. **Scan for vulnerabilities**
   ```bash
   pip install safety
   safety check

   # Or use GitHub Dependabot (enabled in repository)
   ```

3. **Pin dependency versions**
   ```
   # requirements.txt
   fastapi==0.104.1  # Pinned version
   anthropic==0.7.0  # Pinned version
   ```

#### Code Review Security Checklist

Before approving pull requests, verify:

- [ ] No hardcoded secrets or API keys
- [ ] Input validation on all user inputs
- [ ] SQL queries use parameterized queries
- [ ] Error messages don't expose sensitive information
- [ ] PHI data is handled according to policy
- [ ] New endpoints have authentication checks
- [ ] Dependencies are up-to-date and secure
- [ ] Logging doesn't include PHI data
- [ ] Tests cover security scenarios

### For Users

#### Researcher Security

1. **Protect your account**
   - Use strong, unique passwords
   - Enable MFA when available
   - Don't share credentials

2. **Data handling**
   - Download delivered data to secure location
   - Encrypt data on your local machine
   - Delete data when research is complete

3. **Report suspicious activity**
   - Unusual approval requests
   - Unexpected data access
   - System anomalies

#### Informatician Security

1. **SQL Review Process**
   - Verify SQL queries before approval
   - Check for potential data leakage
   - Ensure appropriate filters are applied
   - Validate cohort size is reasonable

2. **Approval Decisions**
   - Document reasoning for rejections
   - Flag suspicious requests
   - Report unusual patterns

## Known Security Limitations

### Current Limitations

1. **No Authentication on UIs** (v2.0)
   - Streamlit portals lack authentication
   - Planned for v2.1 release
   - Use VPN/network isolation as mitigation

2. **Basic JWT Implementation** (v2.0)
   - Simple JWT tokens without refresh
   - No OAuth2/OIDC integration
   - Planned for v2.1 release

3. **Limited Audit Logging** (v2.0)
   - Basic audit trail implemented
   - Enhanced logging planned for v2.2

### Planned Security Enhancements

#### Version 2.1 (Q1 2026)
- OAuth2/OIDC authentication
- Role-based access control (RBAC)
- Multi-factor authentication (MFA)
- Session management improvements

#### Version 2.2 (Q2 2026)
- Comprehensive audit logging
- Advanced PHI detection and scrubbing
- Data lineage tracking
- Encryption at rest for all data

#### Version 3.0 (Q3 2026)
- Zero-trust architecture
- Advanced threat detection
- Automated security scanning
- Compliance dashboard

## Compliance

### HIPAA Compliance

ResearchFlow is designed to support HIPAA-compliant deployments:

- **Encryption**: Data encrypted at rest and in transit
- **Access Controls**: Approval workflow ensures proper authorization
- **Audit Logs**: All data access is logged and traceable
- **De-identification**: Automated PHI removal based on level
- **BAA**: Business Associate Agreement required for production use

### Additional Resources

- [HIPAA Security Rule](https://www.hhs.gov/hipaa/for-professionals/security/index.html)
- [NIST Cybersecurity Framework](https://www.nist.gov/cyberframework)
- [OWASP Top 10](https://owasp.org/www-project-top-ten/)

## Security Contact

For security-related questions or concerns:

- **Email**: [security@yourorg.com](mailto:security@yourorg.com)
- **PGP Key**: [Download public key](https://yourorg.com/security.asc)
- **Response Time**: 48 hours for acknowledgment

## Attribution

We would like to thank the following individuals for responsibly disclosing security issues:

- (No reports yet)

Thank you for helping keep ResearchFlow secure!
