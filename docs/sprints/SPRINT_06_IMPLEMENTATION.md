# Sprint 6: Security Baseline - Implementation Plan

**Sprint:** 6
**Duration:** 3 weeks (15 working days)
**Priority:** High (Production Security Requirement)
**Status:** 🚧 In Progress
**Started:** 2026-04-22
**Branch:** `feature/sprint6-security-baseline`

---

## Executive Summary

**Goal**: Implement comprehensive security baseline for ResearchFlow to enable production deployment with HIPAA compliance, proper authentication/authorization, and PHI protection.

**Previous Work (Sprint 7)**: ✅ Complete
- SQL injection prevention (30 vulnerabilities fixed)
- Pre-commit hooks (detect-secrets, bandit, black)
- GitHub Actions security workflow
- Secret exposure remediation

**Current Sprint Scope**:
- JWT authentication for API endpoints
- Role-Based Access Control (RBAC)
- Rate limiting
- Comprehensive PHI audit logging
- Input validation framework
- TLS/HTTPS enforcement
- Data encryption at rest

---

## Implementation Phases

### Phase 1: Authentication & Authorization (Week 1: Days 1-5)

#### Phase 1.1: JWT Authentication Middleware (Days 1-2)
**Goal**: Secure all API endpoints with JWT token validation

**Tasks**:
1. Install dependencies: `python-jose[cryptography]`, `passlib[bcrypt]`, `python-multipart`
2. Create `app/security/auth.py`:
   - JWT token generation functions
   - Token validation middleware
   - Password hashing utilities
3. Create `app/security/dependencies.py`:
   - `get_current_user()` dependency
   - `get_current_active_user()` dependency
   - Role verification dependencies
4. Add JWT secret to environment variables
5. Update API endpoints to require authentication

**Files to Create**:
- `app/security/__init__.py`
- `app/security/auth.py` (~200 lines)
- `app/security/dependencies.py` (~100 lines)
- `app/security/models.py` (~50 lines)

**Files to Modify**:
- `app/main.py` - Add authentication middleware
- `app/api/*.py` - Add authentication dependencies
- `.env.example` - Add JWT_SECRET_KEY, JWT_ALGORITHM

**Acceptance Criteria**:
- [ ] All API endpoints require valid JWT token
- [ ] Login endpoint returns JWT token
- [ ] Invalid tokens return 401 Unauthorized
- [ ] Token expiration works correctly (default: 30 minutes)

#### Phase 1.2: User Management (Days 2-3)
**Goal**: Create user database and management endpoints

**Tasks**:
1. Create `User` database model in `app/database/models.py`:
   - id, email, hashed_password, full_name
   - role (researcher, admin, auditor)
   - is_active, is_superuser
   - created_at, last_login
2. Create user authentication endpoints in `app/api/auth.py`:
   - POST /auth/login - Get JWT token
   - POST /auth/logout - Invalidate token
   - GET /auth/me - Get current user info
   - POST /auth/refresh - Refresh token
3. Create user management endpoints in `app/api/users.py`:
   - POST /users - Create user (admin only)
   - GET /users - List users (admin only)
   - GET /users/{user_id} - Get user details
   - PUT /users/{user_id} - Update user
   - DELETE /users/{user_id} - Delete user (admin only)
4. Create database migration for users table

**Files to Create**:
- `app/api/auth.py` (~150 lines)
- `app/api/users.py` (~200 lines)
- `alembic/versions/xxx_add_users_table.py`

**Files to Modify**:
- `app/database/models.py` - Add User model
- `app/main.py` - Register auth and users routers

**Acceptance Criteria**:
- [ ] Users can login with email/password
- [ ] JWT tokens are returned on successful login
- [ ] Admins can create/update/delete users
- [ ] Researchers can view their own profile
- [ ] Password hashing works correctly (bcrypt)

#### Phase 1.3: Role-Based Access Control (Days 3-4)
**Goal**: Implement RBAC system with role-based permissions

**Tasks**:
1. Define role hierarchy in `app/security/roles.py`:
   - Roles: `researcher`, `admin`, `auditor`, `superuser`
   - Permissions per role
2. Create permission decorators in `app/security/permissions.py`:
   - `require_role(*roles)`
   - `require_permission(permission)`
3. Create RBAC middleware in `app/security/rbac.py`:
   - Check user role against endpoint requirements
   - Handle permission denied responses
4. Apply RBAC to all endpoints:
   - Research endpoints: `researcher` or higher
   - Admin dashboard: `admin` or higher
   - User management: `admin` or higher
   - Audit logs: `auditor` or higher

**Files to Create**:
- `app/security/roles.py` (~100 lines)
- `app/security/permissions.py` (~150 lines)
- `app/security/rbac.py` (~100 lines)

**Files to Modify**:
- All `app/api/*.py` files - Add role requirements

**Acceptance Criteria**:
- [ ] Researchers can submit requests but not approve
- [ ] Admins can approve requests and manage users
- [ ] Auditors can view logs but not modify data
- [ ] Unauthorized access returns 403 Forbidden
- [ ] Role hierarchy is enforced (superuser > admin > researcher)

#### Phase 1.4: Rate Limiting (Day 4)
**Goal**: Prevent API abuse and DoS attacks

**Tasks**:
1. Install dependency: `slowapi`
2. Create rate limiting middleware in `app/security/rate_limit.py`:
   - Default: 100 requests/minute per IP
   - Auth endpoints: 5 requests/minute
   - Heavy queries: 10 requests/minute
3. Apply rate limiting to endpoints:
   - Global rate limit: 100/min
   - `/auth/login`: 5/min (prevent brute force)
   - `/research/submit`: 10/min
   - `/sql_on_fhir/execute`: 10/min
4. Add rate limit headers to responses

**Files to Create**:
- `app/security/rate_limit.py` (~80 lines)

**Files to Modify**:
- `app/main.py` - Add rate limiting middleware
- `app/api/auth.py` - Add stricter limits to login

**Acceptance Criteria**:
- [ ] Rate limits enforced per IP address
- [ ] Rate limit headers in responses (X-RateLimit-*)
- [ ] 429 Too Many Requests returned when exceeded
- [ ] Different limits for different endpoint types

---

### Phase 2: Auditing & Validation (Week 2: Days 6-10)

#### Phase 2.1: PHI Audit Logging Schema (Day 6)
**Goal**: Design comprehensive audit trail for PHI access

**Tasks**:
1. Create `AuditLog` model in `app/database/models.py`:
   - id, timestamp, user_id, action
   - resource_type, resource_id
   - phi_accessed (boolean)
   - request_id, ip_address, user_agent
   - details (JSON), result (success/failure)
2. Define audit event types:
   - PHI_VIEW, PHI_EXPORT, PHI_SEARCH
   - REQUEST_CREATE, REQUEST_APPROVE, REQUEST_REJECT
   - USER_LOGIN, USER_LOGOUT, USER_CREATE
   - QUERY_EXECUTE, DATA_EXTRACT, DATA_DELIVER
3. Create indexes for fast audit queries
4. Create database migration

**Files to Create**:
- `alembic/versions/xxx_add_audit_log_table.py`

**Files to Modify**:
- `app/database/models.py` - Add AuditLog model

**Acceptance Criteria**:
- [ ] AuditLog table created with all required fields
- [ ] Indexes on user_id, timestamp, phi_accessed
- [ ] JSON details field supports flexible metadata

#### Phase 2.2: Audit Logging Infrastructure (Days 6-8)
**Goal**: Implement automatic audit logging for all PHI access

**Tasks**:
1. Create audit service in `app/services/audit_service.py`:
   - `log_phi_access(user, action, resource, details)`
   - `log_request_event(user, request_id, action, details)`
   - `log_authentication(user, action, ip, user_agent)`
   - `get_audit_trail(filters)` - Query audit logs
2. Create audit middleware in `app/security/audit.py`:
   - Automatic logging of all API requests
   - PHI access detection
   - Request/response capture (sanitized)
3. Add audit logging to critical operations:
   - Data extraction agent
   - SQL query execution
   - Data delivery
   - User login/logout
4. Create audit log API in `app/api/audit.py`:
   - GET /audit/logs - Query audit trail (auditor only)
   - GET /audit/phi-access - PHI-specific audit trail
   - GET /audit/users/{user_id} - User activity log

**Files to Create**:
- `app/services/audit_service.py` (~250 lines)
- `app/security/audit.py` (~150 lines)
- `app/api/audit.py` (~200 lines)

**Files to Modify**:
- `app/agents/extraction_agent.py` - Add audit logging
- `app/adapters/sql_on_fhir.py` - Log query execution
- `app/agents/delivery_agent.py` - Log data delivery
- `app/main.py` - Add audit middleware

**Acceptance Criteria**:
- [ ] All PHI access is logged automatically
- [ ] Audit logs include user, timestamp, action, resource
- [ ] Auditors can query logs via API
- [ ] Audit logs are tamper-evident (write-only)
- [ ] Sensitive data in logs is sanitized

#### Phase 2.3: Input Validation Framework (Days 8-10)
**Goal**: Prevent injection attacks and data corruption

**Tasks**:
1. Install dependency: `pydantic[email]`
2. Create validation models in `app/schemas/`:
   - `ResearchRequestSchema` - Validate research requests
   - `RequirementsSchema` - Validate requirements data
   - `UserSchema` - Validate user inputs
   - `SQLQuerySchema` - Validate SQL query parameters
3. Create validation utilities in `app/security/validation.py`:
   - Email validation
   - Phone number validation
   - SQL identifier validation (table/column names)
   - File path validation
   - JSON schema validation
4. Add validation to all API endpoints:
   - Use Pydantic models for request/response validation
   - Custom validators for business logic
   - Sanitize user inputs (XSS prevention)
5. Create validation tests

**Files to Create**:
- `app/schemas/__init__.py`
- `app/schemas/research.py` (~150 lines)
- `app/schemas/users.py` (~100 lines)
- `app/schemas/audit.py` (~80 lines)
- `app/security/validation.py` (~200 lines)
- `tests/test_validation.py` (~300 lines)

**Files to Modify**:
- All `app/api/*.py` files - Add Pydantic schemas

**Acceptance Criteria**:
- [ ] All API inputs validated with Pydantic schemas
- [ ] Invalid inputs return 422 Unprocessable Entity
- [ ] SQL identifiers sanitized (prevent table/column injection)
- [ ] XSS-prone inputs escaped
- [ ] Email addresses validated
- [ ] Comprehensive validation tests pass

---

### Phase 3: Infrastructure Security (Week 3: Days 11-13)

#### Phase 3.1: TLS/HTTPS Enforcement (Day 11)
**Goal**: Encrypt all data in transit

**Tasks**:
1. Create HTTPS redirect middleware in `app/security/https.py`:
   - Redirect HTTP to HTTPS
   - Set Strict-Transport-Security headers
   - Set secure cookie flags
2. Generate self-signed certificates for local dev:
   - Create `scripts/generate_ssl_cert.sh`
   - Add certificates to `.gitignore`
3. Configure uvicorn for HTTPS:
   - Add SSL cert/key paths to environment
   - Update startup commands
4. Update CORS settings for HTTPS:
   - Allow HTTPS origins only
   - Set secure cookie settings
5. Document HTTPS setup in README

**Files to Create**:
- `app/security/https.py` (~100 lines)
- `scripts/generate_ssl_cert.sh` (~30 lines)
- `certs/.gitkeep` (directory)

**Files to Modify**:
- `app/main.py` - Add HTTPS middleware and CORS config
- `.env.example` - Add SSL_CERT_PATH, SSL_KEY_PATH
- `README.md` - Add HTTPS setup instructions
- `.gitignore` - Add certs/

**Acceptance Criteria**:
- [ ] HTTP requests redirect to HTTPS
- [ ] HSTS header set to 1 year
- [ ] Secure cookie flags set
- [ ] Local development works with self-signed cert
- [ ] Production-ready HTTPS configuration

#### Phase 3.2: Data Encryption at Rest (Days 11-13)
**Goal**: Encrypt sensitive data in database

**Tasks**:
1. Install dependencies: `cryptography`
2. Create encryption utilities in `app/security/encryption.py`:
   - AES-256-GCM encryption/decryption
   - Key derivation from master secret
   - Field-level encryption helpers
3. Add encryption to sensitive database fields:
   - `User.email` - Encrypted, searchable hash for lookup
   - `RequirementsData.structured_requirements` - Encrypted JSON
   - `DataDelivery.file_path` - Encrypted file path
   - `Escalation.context` - May contain PHI
4. Create key management system:
   - Master key from environment variable
   - Key rotation support (future)
   - Separate encryption keys per data type
5. Update database models with encryption:
   - Use SQLAlchemy custom types
   - Transparent encryption/decryption
6. Create migration for encrypted fields
7. Document encryption setup

**Files to Create**:
- `app/security/encryption.py` (~300 lines)
- `app/database/encrypted_types.py` (~150 lines)
- `alembic/versions/xxx_add_field_encryption.py`
- `docs/ENCRYPTION_SETUP.md` (~400 lines)

**Files to Modify**:
- `app/database/models.py` - Add encrypted field types
- `.env.example` - Add ENCRYPTION_MASTER_KEY
- `SECURITY_SETUP.md` - Add encryption section

**Acceptance Criteria**:
- [ ] Sensitive fields encrypted in database
- [ ] Encryption transparent to application code
- [ ] Master key stored securely (env var, not in code)
- [ ] Encrypted data can be decrypted correctly
- [ ] Migration preserves existing data
- [ ] Performance impact minimal (<10ms overhead)

---

### Phase 4: Testing & Documentation (Week 3: Days 14-15)

#### Phase 4.1: Security Testing (Day 14)
**Goal**: Verify all security controls work correctly

**Tasks**:
1. Create security test suite in `tests/security/`:
   - `test_authentication.py` - JWT token tests
   - `test_authorization.py` - RBAC tests
   - `test_rate_limiting.py` - Rate limit tests
   - `test_audit_logging.py` - Audit trail tests
   - `test_encryption.py` - Encryption tests
   - `test_validation.py` - Input validation tests
2. Run penetration testing:
   - SQL injection attempts (should fail)
   - XSS attempts (should be escaped)
   - CSRF attempts (should be blocked)
   - Brute force login attempts (should be rate limited)
3. Run security scans:
   - Bandit scan (should pass with 0 high/medium issues)
   - OWASP ZAP scan (if available)
4. Create security test report

**Files to Create**:
- `tests/security/__init__.py`
- `tests/security/test_authentication.py` (~200 lines)
- `tests/security/test_authorization.py` (~250 lines)
- `tests/security/test_rate_limiting.py` (~150 lines)
- `tests/security/test_audit_logging.py` (~200 lines)
- `tests/security/test_encryption.py` (~180 lines)
- `tests/security/test_validation.py` (~300 lines)
- `docs/SECURITY_TEST_REPORT.md` (~500 lines)

**Acceptance Criteria**:
- [ ] All security tests pass
- [ ] No SQL injection vulnerabilities found
- [ ] No XSS vulnerabilities found
- [ ] Rate limiting prevents brute force
- [ ] Audit logs capture all PHI access
- [ ] Encryption/decryption works correctly
- [ ] Security scan passes with 0 critical issues

#### Phase 4.2: Documentation (Day 15)
**Goal**: Document all security features for operations and compliance

**Tasks**:
1. Update `SECURITY_SETUP.md`:
   - Authentication setup instructions
   - RBAC configuration guide
   - Rate limiting configuration
   - Audit logging queries
   - Encryption key management
2. Create `docs/AUTHENTICATION_GUIDE.md`:
   - How to obtain JWT tokens
   - Token expiration and refresh
   - User role management
3. Create `docs/AUDIT_GUIDE.md`:
   - How to query audit logs
   - PHI access reporting
   - Compliance requirements
4. Update `README.md`:
   - Security features overview
   - Quick start with authentication
5. Create API documentation:
   - OpenAPI/Swagger docs for auth endpoints
   - Authentication examples
6. Create compliance documentation:
   - HIPAA compliance checklist
   - Security controls mapping

**Files to Create/Update**:
- `docs/AUTHENTICATION_GUIDE.md` (~300 lines)
- `docs/AUDIT_GUIDE.md` (~400 lines)
- `docs/HIPAA_COMPLIANCE.md` (~600 lines)
- `SECURITY_SETUP.md` - Update with new features
- `README.md` - Update with security overview

**Acceptance Criteria**:
- [ ] All security features documented
- [ ] Setup instructions are clear and complete
- [ ] API documentation includes auth examples
- [ ] Compliance documentation ready for audit
- [ ] Operations team can configure security

---

## Implementation Timeline

```
Week 1: Authentication & Authorization
├─ Day 1-2: JWT Authentication
├─ Day 2-3: User Management
├─ Day 3-4: RBAC
└─ Day 4-5: Rate Limiting

Week 2: Auditing & Validation
├─ Day 6: Audit Schema
├─ Day 6-8: Audit Infrastructure
└─ Day 8-10: Input Validation

Week 3: Infrastructure & Testing
├─ Day 11: TLS/HTTPS
├─ Day 11-13: Encryption at Rest
├─ Day 14: Security Testing
└─ Day 15: Documentation
```

---

## Dependencies

**New Python Packages**:
```txt
python-jose[cryptography]==3.3.0  # JWT tokens
passlib[bcrypt]==1.7.4            # Password hashing
python-multipart==0.0.9           # Form data parsing
slowapi==0.1.9                    # Rate limiting
cryptography==42.0.5              # Encryption
pydantic[email]==2.6.3            # Email validation
```

**Database Migrations**:
- Add `users` table
- Add `audit_logs` table
- Add encrypted field types to existing tables

---

## Success Criteria

### Functional Requirements
- [ ] All API endpoints require authentication
- [ ] JWT tokens work for authentication
- [ ] RBAC enforces role-based permissions
- [ ] Rate limiting prevents abuse
- [ ] All PHI access is audited
- [ ] Input validation prevents injection attacks
- [ ] HTTPS enforced for all connections
- [ ] Sensitive data encrypted at rest

### Non-Functional Requirements
- [ ] Authentication adds <50ms latency
- [ ] Audit logging doesn't block requests
- [ ] Encryption overhead <10ms per operation
- [ ] Rate limiting scales to 1000 req/sec
- [ ] Security tests have >90% coverage

### Compliance Requirements
- [ ] HIPAA audit trail requirements met
- [ ] PHI access logged comprehensively
- [ ] Data encryption meets HIPAA standards
- [ ] Authentication meets security best practices

---

## Risk Management

**High Risks**:
1. **Breaking Changes**: Auth requirements break existing clients
   - Mitigation: Implement in feature branch, test thoroughly
2. **Performance Impact**: Security overhead slows system
   - Mitigation: Benchmark each feature, optimize as needed
3. **Data Migration**: Encrypting existing data is complex
   - Mitigation: Test migration on copy of production data

**Medium Risks**:
1. **Key Management**: Master encryption key exposure
   - Mitigation: Use environment variables, document rotation
2. **Audit Storage**: Audit logs grow unbounded
   - Mitigation: Add retention policy and archival

---

## Rollback Plan

If issues arise during deployment:
1. Disable authentication via feature flag: `ENABLE_AUTH=false`
2. Disable audit logging via flag: `ENABLE_AUDIT=false`
3. Disable encryption via flag: `ENABLE_ENCRYPTION=false`
4. Revert database migrations if needed
5. All features have graceful degradation

---

## Post-Implementation

**Follow-up Work**:
- Secret management with HashiCorp Vault
- Multi-factor authentication (MFA)
- API key management for service accounts
- Advanced threat detection
- Security operations center (SOC) integration

**Monitoring**:
- Track authentication failures
- Monitor rate limit violations
- Alert on PHI access patterns
- Audit log retention and archival
