# Sprint 6: Security Baseline - TECHNICAL PLAN

**Sprint:** 6
**Duration:** 3 weeks
**Priority:** High (Production Security Requirement)
**Status:** ⏳ Planning
**Created:** 2025-10-28

---

## Executive Summary

**Goal**: Establish comprehensive security baseline for ResearchFlow to ensure HIPAA compliance, prevent SQL injection, protect PHI data, and implement proper authentication/authorization.

**Current Situation**:
- ✅ **Architecture**: LangChain/LangGraph migration complete
- ✅ **Performance**: Lambda architecture with 10-100x speedup
- ✅ **Observability**: LangSmith full workflow tracing
- ❌ **Security**: No formal security controls, SQL injection risks, PHI audit gaps
- ❌ **Authentication**: No auth layer on API endpoints
- ❌ **Authorization**: No role-based access control (RBAC)

**Target Outcome**:
- ✅ SQL injection prevention (parameterized queries)
- ✅ Input validation and sanitization
- ✅ PHI audit logging (comprehensive)
- ✅ API authentication (JWT tokens)
- ✅ Role-based access control (RBAC)
- ✅ Security testing and penetration testing baseline

---

## Background

### Problem Statement

**Current Security Risks**:
1. **SQL Injection**: Text-to-SQL conversion may generate unsafe SQL
2. **PHI Exposure**: Insufficient audit logging for PHI access
3. **Authentication**: API endpoints are unauthenticated
4. **Authorization**: No granular permissions (researcher vs admin)
5. **Input Validation**: Limited validation on user inputs
6. **Data Encryption**: PHI data not encrypted at rest/in transit

**Business Impact**:
- Cannot deploy to production without HIPAA compliance
- Risk of data breaches and regulatory penalties
- No audit trail for research data access
- Cannot support multi-tenant deployments

**Compliance Requirements**:
- **HIPAA**: PHI access logging, encryption, access controls
- **GDPR**: Data privacy, right to deletion, consent tracking
- **Institutional**: IRB requirements, data governance

### Proposed Solution: Multi-Layered Security

```
┌─────────────────────────────────────────────────┐
│           Security Layers                       │
├─────────────────────────────────────────────────┤
│ 1. API Layer                                    │
│    - JWT Authentication                         │
│    - Rate Limiting                              │
│    - Request Validation                         │
├─────────────────────────────────────────────────┤
│ 2. Application Layer                            │
│    - RBAC (Role-Based Access Control)           │
│    - Input Sanitization                         │
│    - SQL Injection Prevention                   │
├─────────────────────────────────────────────────┤
│ 3. Data Layer                                   │
│    - Parameterized Queries                      │
│    - PHI Audit Logging                          │
│    - Encryption at Rest                         │
├─────────────────────────────────────────────────┤
│ 4. Infrastructure Layer                         │
│    - TLS/HTTPS Enforcement                      │
│    - Secret Management (Vault)                  │
│    - Network Segmentation                       │
└─────────────────────────────────────────────────┘
```

### Key Design Decisions

1. **Why JWT for Authentication?**
   - Stateless (no session storage)
   - Standard industry approach
   - Easily integrated with FastAPI
   - Supports claims-based authorization

2. **Why RBAC over ABAC?**
   - Simpler to implement initially
   - Sufficient for current use case (researcher, admin, auditor)
   - Can evolve to ABAC later if needed

3. **Why Parameterized Queries?**
   - Industry standard for SQL injection prevention
   - Already supported by SQLAlchemy
   - Minimal performance overhead

4. **Why Audit Logging Everything?**
   - HIPAA requirement
   - Research reproducibility
   - Security incident investigation

---

## Architecture

### Security Component Diagram

```
┌────────────────────────────────────────────────────┐
│              Client (Researcher)                    │
└───────────────────┬────────────────────────────────┘
                    │ HTTPS
                    ▼
┌────────────────────────────────────────────────────┐
│           API Gateway / FastAPI                     │
│  ┌──────────────────────────────────────────────┐ │
│  │  Authentication Middleware                    │ │
│  │  - JWT Token Validation                       │ │
│  │  - User Identity Extraction                   │ │
│  └──────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────┐ │
│  │  Authorization Middleware                     │ │
│  │  - RBAC Permission Check                      │ │
│  │  - Endpoint Access Control                    │ │
│  └──────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────┐ │
│  │  Input Validation Middleware                  │ │
│  │  - Schema Validation (Pydantic)               │ │
│  │  - SQL Injection Prevention                   │ │
│  │  - XSS Protection                             │ │
│  └──────────────────────────────────────────────┘ │
└───────────────────┬────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────┐
│        Application Layer (Agents)                   │
│  ┌──────────────────────────────────────────────┐ │
│  │  PHI Audit Logger                             │ │
│  │  - Log ALL PHI access                         │ │
│  │  - Timestamp, User, Resource, Action          │ │
│  │  - Immutable audit trail                      │ │
│  └──────────────────────────────────────────────┘ │
└───────────────────┬────────────────────────────────┘
                    │
                    ▼
┌────────────────────────────────────────────────────┐
│         Data Layer (FHIR + ResearchFlow DB)         │
│  ┌──────────────────────────────────────────────┐ │
│  │  SQL Query Builder                            │ │
│  │  - Parameterized Queries ONLY                 │ │
│  │  - SQL Injection Prevention                   │ │
│  │  - Query Whitelisting                         │ │
│  └──────────────────────────────────────────────┘ │
│  ┌──────────────────────────────────────────────┐ │
│  │  Audit Log Database                           │ │
│  │  - Append-only table                          │ │
│  │  - Encrypted at rest                          │ │
│  │  - Retention policy (7 years)                 │ │
│  └──────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────┘
```

---

## Week 1: Authentication & Authorization

### Goal
Implement JWT-based authentication and role-based access control (RBAC).

### Deliverables

#### 1.1 Authentication Infrastructure
- [ ] `app/security/auth.py` - JWT token generation and validation
- [ ] `app/security/models.py` - User, Role, Permission models
- [ ] `app/security/password.py` - Password hashing (bcrypt)
- [ ] `app/api/auth.py` - Login, logout, token refresh endpoints

#### 1.2 RBAC Implementation
- [ ] `app/security/rbac.py` - Role-based permission checking
- [ ] `app/security/decorators.py` - `@require_role()`, `@require_permission()`
- [ ] Database migrations - Users, Roles, Permissions tables
- [ ] Seed data - Admin, Researcher, Auditor roles

#### 1.3 Middleware Integration
- [ ] `app/middleware/auth_middleware.py` - JWT validation middleware
- [ ] `app/middleware/rbac_middleware.py` - Permission checking middleware
- [ ] Update FastAPI app - Apply middleware to all routes
- [ ] Exempt public endpoints - `/health`, `/docs`, `/login`

#### 1.4 Testing
- [ ] `tests/security/test_auth.py` - Authentication tests (15+ tests)
- [ ] `tests/security/test_rbac.py` - RBAC tests (10+ tests)
- [ ] `tests/e2e/test_authenticated_workflow.py` - E2E with auth

#### 1.5 Documentation
- [ ] `docs/AUTHENTICATION.md` - Auth setup and usage guide
- [ ] `docs/RBAC.md` - Roles and permissions reference
- [ ] API documentation - Update with auth requirements

**Success Criteria**:
- ✅ JWT authentication working on all API endpoints
- ✅ 3 roles implemented (admin, researcher, auditor)
- ✅ RBAC middleware blocks unauthorized access
- ✅ Test coverage >80% for auth/RBAC
- ✅ Documentation complete

---

## Week 2: SQL Injection Prevention & Input Validation

### Goal
Eliminate SQL injection vulnerabilities and implement comprehensive input validation.

### Deliverables

#### 2.1 SQL Injection Prevention
- [ ] `app/security/sql_validator.py` - SQL query validation
- [ ] Update `app/sql_on_fhir/query_builder.py` - Parameterized queries ONLY
- [ ] Update `app/adapters/sql_on_fhir.py` - Query whitelisting
- [ ] Audit all SQL generation - Ensure no string concatenation

#### 2.2 Input Validation
- [ ] `app/security/input_validator.py` - Input sanitization
- [ ] Update all Pydantic models - Add strict validation
- [ ] `app/security/xss_protection.py` - XSS prevention
- [ ] `app/security/path_traversal.py` - Path traversal prevention

#### 2.3 Request Validation Middleware
- [ ] `app/middleware/validation_middleware.py` - Request validation
- [ ] Schema validation - Enforce Pydantic schemas
- [ ] Size limits - Max request body size (10MB)
- [ ] Rate limiting - Prevent DoS attacks

#### 2.4 Security Testing
- [ ] `tests/security/test_sql_injection.py` - SQL injection attempts
- [ ] `tests/security/test_input_validation.py` - Malicious input tests
- [ ] `tests/security/test_xss.py` - Cross-site scripting tests
- [ ] Penetration testing - Manual security audit

#### 2.5 Documentation
- [ ] `docs/SQL_INJECTION_PREVENTION.md` - Security measures
- [ ] `docs/INPUT_VALIDATION.md` - Validation rules reference
- [ ] `docs/SECURITY_TESTING.md` - Testing guide

**Success Criteria**:
- ✅ Zero SQL injection vulnerabilities
- ✅ All inputs validated with Pydantic
- ✅ XSS protection enabled
- ✅ Penetration testing passed
- ✅ Test coverage >90% for security

---

## Week 3: PHI Audit Logging & Encryption

### Goal
Implement comprehensive PHI audit logging and encryption (HIPAA compliance).

### Deliverables

#### 3.1 PHI Audit Logging
- [ ] `app/security/audit_logger.py` - Comprehensive audit logger
- [ ] Database schema - `audit_log` table (append-only)
- [ ] Audit ALL PHI access:
  - Patient resource retrieval
  - Condition/Observation queries
  - Data extractions
  - Export/delivery events
- [ ] Audit log fields:
  - `timestamp` - When
  - `user_id` - Who
  - `action` - What (read/write/delete/export)
  - `resource_type` - Which resource
  - `resource_id` - Specific resource
  - `ip_address` - From where
  - `success` - Result (true/false)
  - `failure_reason` - If failed, why

#### 3.2 Encryption at Rest
- [ ] Database encryption - PostgreSQL TDE (Transparent Data Encryption)
- [ ] File encryption - Encrypted data deliveries (AES-256)
- [ ] Redis encryption - Enable TLS and encryption

#### 3.3 Encryption in Transit
- [ ] HTTPS enforcement - TLS 1.3 only
- [ ] Certificate management - Let's Encrypt automation
- [ ] HAPI FHIR connection - TLS required

#### 3.4 Secret Management
- [ ] `app/security/secrets.py` - Secret management (HashiCorp Vault or AWS Secrets Manager)
- [ ] Environment variables - Remove secrets from .env
- [ ] API keys - Rotate regularly
- [ ] Database credentials - Secure storage

#### 3.5 Security Auditing
- [ ] `tests/security/test_audit_logging.py` - Audit log tests
- [ ] `tests/security/test_encryption.py` - Encryption tests
- [ ] Security audit report - Document findings
- [ ] Compliance checklist - HIPAA compliance verification

#### 3.6 Documentation
- [ ] `docs/PHI_AUDIT_LOGGING.md` - Audit logging guide
- [ ] `docs/ENCRYPTION.md` - Encryption setup and configuration
- [ ] `docs/HIPAA_COMPLIANCE.md` - HIPAA compliance checklist
- [ ] `docs/SECURITY_AUDIT.md` - Security audit report

**Success Criteria**:
- ✅ ALL PHI access logged to immutable audit log
- ✅ Encryption at rest and in transit
- ✅ HIPAA compliance checklist 100% complete
- ✅ Security audit passed
- ✅ Zero critical vulnerabilities

---

## Testing Strategy

### Unit Tests (40+ tests)
- Authentication (JWT generation/validation)
- RBAC (role/permission checks)
- SQL injection prevention
- Input validation
- Audit logging
- Encryption

### Integration Tests (20+ tests)
- Authenticated API calls
- RBAC permission enforcement
- SQL injection attempts (blackbox)
- Audit log generation
- Encrypted data storage

### E2E Tests (10+ tests)
- Full workflow with authentication
- Multi-user scenarios
- Security breach simulations
- Audit trail verification

### Penetration Testing
- Manual security audit
- SQL injection attempts
- XSS attacks
- CSRF attacks
- Authentication bypass attempts

---

## Security Checklist

### HIPAA Compliance
- [ ] PHI access logging (all access, all users)
- [ ] Encryption at rest (database, files)
- [ ] Encryption in transit (HTTPS, TLS)
- [ ] Access controls (RBAC, least privilege)
- [ ] Audit retention (7 years minimum)
- [ ] Breach notification procedures
- [ ] Business Associate Agreements (BAAs)

### OWASP Top 10 Protection
- [ ] A01: Broken Access Control → RBAC
- [ ] A02: Cryptographic Failures → Encryption
- [ ] A03: Injection → Parameterized queries
- [ ] A04: Insecure Design → Security by design
- [ ] A05: Security Misconfiguration → Hardened configs
- [ ] A06: Vulnerable Components → Dependency scanning
- [ ] A07: Authentication Failures → JWT + bcrypt
- [ ] A08: Data Integrity Failures → Audit logging
- [ ] A09: Logging Failures → Comprehensive logging
- [ ] A10: SSRF → Input validation

### Additional Security Measures
- [ ] Rate limiting (prevent DoS)
- [ ] CORS configuration (restrict origins)
- [ ] Security headers (CSP, HSTS, X-Frame-Options)
- [ ] Dependency vulnerability scanning (Snyk, Dependabot)
- [ ] Secret scanning (gitleaks, trufflehog)
- [ ] API versioning (support breaking changes safely)

---

## Dependencies

### Required Infrastructure
- PostgreSQL with TDE (Transparent Data Encryption)
- Redis with TLS
- HashiCorp Vault or AWS Secrets Manager
- TLS certificates (Let's Encrypt)

### Required Libraries
```
# Authentication
pyjwt>=2.8.0
passlib[bcrypt]>=1.7.4
python-multipart>=0.0.6

# Security
cryptography>=41.0.0
python-jose>=3.3.0

# Validation
pydantic[email]>=2.5.0

# Rate Limiting
slowapi>=0.1.9
```

### Completed Prerequisites
- ✅ LangChain/LangGraph migration complete
- ✅ Lambda architecture implemented
- ✅ LangSmith observability
- ✅ Testing infrastructure

---

## Risk Register

| Risk | Impact | Probability | Mitigation | Status |
|------|--------|-------------|------------|--------|
| JWT secret compromise | Critical | Low | Rotate secrets regularly, use Vault | ⏳ |
| SQL injection bypass | Critical | Medium | Comprehensive testing, code review | ⏳ |
| PHI audit log tampering | Critical | Low | Append-only table, blockchain hash | ⏳ |
| Authentication bypass | Critical | Low | Thorough testing, security audit | ⏳ |
| Performance degradation | Medium | Medium | Benchmark auth middleware | ⏳ |

---

## Success Metrics

### Security Metrics
- **Zero SQL Injection** vulnerabilities (penetration testing)
- **100% PHI Audit** coverage (all access logged)
- **<5ms Auth Overhead** (JWT validation time)
- **HIPAA Compliant** (all checklist items complete)
- **>80% Test Coverage** for security code

### Compliance Metrics
- HIPAA compliance checklist: 100% complete
- OWASP Top 10 protection: 100% coverage
- Security audit: Passed (zero critical findings)

---

## Next Sprint

**Sprint 7:** Advanced Tool Integration (2 weeks)
- MCP server implementation (Epic, Calendar, FHIR)
- Real FHIR Subscription resources
- External API integrations
- Tool observability

---

## Notes

### Key Decisions
- JWT for stateless authentication
- RBAC for authorization (admin/researcher/auditor)
- Parameterized queries ONLY (no string concatenation)
- Append-only audit log (immutable)

### Security Principles
1. **Defense in Depth**: Multiple security layers
2. **Least Privilege**: Minimal permissions by default
3. **Fail Secure**: Default to deny access
4. **Audit Everything**: Log all PHI access
5. **Zero Trust**: Verify every request

### Blockers
- None currently (all dependencies available)

---

**Last Updated:** 2025-10-28
**Next Review:** After Week 1 deliverables
