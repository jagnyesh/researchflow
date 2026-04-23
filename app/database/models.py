"""
Database Models for ResearchFlow

SQLAlchemy models for request tracking, workflow state, and agent execution.
"""

from sqlalchemy import Column, Integer, String, DateTime, JSON, Float, ForeignKey, Text, Boolean
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class ResearchRequest(Base):
    """Main research data request tracking"""

    __tablename__ = "research_requests"

    id = Column(String, primary_key=True)  # REQ-YYYYMMDD-XXXXXXXX
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    completed_at = Column(DateTime, nullable=True)

    # Researcher info
    researcher_name = Column(String, nullable=False)
    researcher_email = Column(String, nullable=False)
    researcher_department = Column(String)
    irb_number = Column(String)

    # Request data
    initial_request = Column(Text, nullable=False)  # Natural language request
    current_state = Column(String, nullable=False)  # Workflow state
    final_state = Column(String, nullable=True)
    error_message = Column(Text, nullable=True)

    # Workflow tracking
    current_agent = Column(String, nullable=True)
    agents_involved = Column(JSON, default=[])  # List of agents and tasks
    state_history = Column(JSON, default=[])  # State transition history

    # Relationships
    requirements = relationship("RequirementsData", back_populates="request", uselist=False)
    feasibility_report = relationship("FeasibilityReport", back_populates="request", uselist=False)
    agent_executions = relationship("AgentExecution", back_populates="request")
    escalations = relationship("Escalation", back_populates="request")
    approvals = relationship("Approval", back_populates="request")
    delivery = relationship("DataDelivery", back_populates="request", uselist=False)


class RequirementsData(Base):
    """Structured requirements extracted from researcher"""

    __tablename__ = "requirements_data"

    id = Column(Integer, primary_key=True)
    request_id = Column(String, ForeignKey("research_requests.id"), unique=True)
    created_at = Column(DateTime, default=datetime.now)

    # Study metadata
    study_title = Column(String)
    principal_investigator = Column(String)
    irb_number = Column(String)

    # Criteria
    inclusion_criteria = Column(JSON, default=[])  # List of structured criteria with codes
    exclusion_criteria = Column(JSON, default=[])  # List of structured criteria with codes

    # Data elements requested
    data_elements = Column(JSON, default=[])  # e.g., ["clinical_notes", "lab_results", "imaging"]

    # Time period
    time_period_start = Column(DateTime)
    time_period_end = Column(DateTime)

    # Cohort
    estimated_cohort_size = Column(Integer)
    minimum_cohort_size = Column(Integer)

    # Delivery preferences
    delivery_format = Column(String)  # CSV, FHIR, REDCap
    phi_level = Column(String)  # identified, limited_dataset, de-identified

    # Completeness
    completeness_score = Column(Float, default=0.0)
    is_complete = Column(Boolean, default=False)

    # Relationship
    request = relationship("ResearchRequest", back_populates="requirements")


class FeasibilityReport(Base):
    """Phenotype validation and feasibility analysis results"""

    __tablename__ = "feasibility_reports"

    id = Column(Integer, primary_key=True)
    request_id = Column(String, ForeignKey("research_requests.id"), unique=True)
    created_at = Column(DateTime, default=datetime.now)

    # Feasibility
    is_feasible = Column(Boolean, nullable=False)
    feasibility_score = Column(Float, nullable=False)

    # Cohort estimation
    estimated_cohort_size = Column(Integer)
    confidence_interval_low = Column(Integer)
    confidence_interval_high = Column(Integer)

    # Data availability
    data_availability = Column(JSON)  # Availability by data element
    overall_availability = Column(Float)

    # Generated SQL
    phenotype_sql = Column(Text)

    # Timing
    estimated_extraction_time_hours = Column(Float)

    # Issues and recommendations
    warnings = Column(JSON, default=[])
    recommendations = Column(JSON, default=[])

    # Relationship
    request = relationship("ResearchRequest", back_populates="feasibility_report")


class AgentExecution(Base):
    """Individual agent task execution log"""

    __tablename__ = "agent_executions"

    id = Column(Integer, primary_key=True)
    request_id = Column(String, ForeignKey("research_requests.id"))
    created_at = Column(DateTime, default=datetime.now)

    # Agent info
    agent_id = Column(String, nullable=False)
    task = Column(String, nullable=False)

    # Execution
    started_at = Column(DateTime, nullable=False)
    completed_at = Column(DateTime)
    status = Column(String)  # success, failed, retrying
    duration_seconds = Column(Float)

    # Context and results
    context = Column(JSON)  # Input context
    result = Column(JSON)  # Output result
    error = Column(Text)

    # Retry tracking
    retry_count = Column(Integer, default=0)

    # Relationship
    request = relationship("ResearchRequest", back_populates="agent_executions")


class Escalation(Base):
    """Human review escalations - both reactive (errors) and proactive (timeouts, complexity)"""

    __tablename__ = "escalations"

    id = Column(Integer, primary_key=True)
    request_id = Column(String, ForeignKey("research_requests.id"))
    created_at = Column(DateTime, default=datetime.now)
    resolved_at = Column(DateTime, nullable=True)

    # Escalation details
    agent = Column(String, nullable=False)
    error = Column(Text, nullable=True)  # Nullable for proactive escalations
    context = Column(JSON)
    task = Column(JSON)

    # NEW: Proactive escalation fields
    escalation_reason = Column(
        String, nullable=True
    )  # timeout, low_feasibility, complexity, approval_pending, error
    severity = Column(String, default="medium")  # low, medium, high, critical
    recommended_action = Column(Text, nullable=True)  # AI-suggested next steps
    auto_resolved = Column(Boolean, default=False)
    resolution_agent = Column(String, nullable=True)  # Which agent resolved it

    # Review
    status = Column(
        String, default="pending_review"
    )  # pending_review, approved, rejected, modified, auto_resolved
    reviewed_by = Column(String, nullable=True)
    review_notes = Column(Text, nullable=True)
    resolution = Column(JSON, nullable=True)

    # Relationship
    request = relationship("ResearchRequest", back_populates="escalations")


class Approval(Base):
    """Human approval tracking for critical decision points"""

    __tablename__ = "approvals"

    id = Column(Integer, primary_key=True)
    request_id = Column(String, ForeignKey("research_requests.id"))
    created_at = Column(DateTime, default=datetime.now)

    # Approval type
    approval_type = Column(
        String, nullable=False
    )  # requirements, phenotype_sql, extraction, qa, scope_change

    # Request details
    submitted_at = Column(DateTime, default=datetime.now, nullable=False)
    submitted_by = Column(String, nullable=False)  # agent_id that submitted for approval
    approval_data = Column(JSON, nullable=False)  # What needs approval (SQL, requirements, etc.)

    # Review status
    status = Column(
        String, default="pending", nullable=False
    )  # pending, approved, rejected, modified, timeout
    reviewed_at = Column(DateTime, nullable=True)
    reviewed_by = Column(String, nullable=True)  # user_id or email of reviewer
    review_notes = Column(Text, nullable=True)
    modifications = Column(JSON, nullable=True)  # Modified data if approved with changes

    # Timeout handling
    timeout_at = Column(DateTime, nullable=True)  # When approval times out
    timed_out = Column(Boolean, default=False)

    # Escalation tracking
    escalated = Column(Boolean, default=False)
    escalation_id = Column(Integer, ForeignKey("escalations.id"), nullable=True)

    # Relationship
    request = relationship("ResearchRequest", back_populates="approvals")


class DataDelivery(Base):
    """Data delivery tracking"""

    __tablename__ = "data_deliveries"

    id = Column(Integer, primary_key=True)
    request_id = Column(String, ForeignKey("research_requests.id"), unique=True)
    created_at = Column(DateTime, default=datetime.now)

    # Delivery info
    delivery_location = Column(String)  # S3 URL, file path, etc.
    delivery_format = Column(String)  # CSV, FHIR, REDCap
    cohort_size = Column(Integer)

    # Package contents
    data_elements = Column(JSON, default=[])
    file_list = Column(JSON, default=[])

    # Preview extraction (NEW - Sprint X)
    preview_data = Column(JSON, nullable=True)  # Preview extraction results (10 rows per element)
    preview_qa_report = Column(JSON, nullable=True)  # QA report from preview validation

    # Delivery metadata (renamed from 'metadata' to avoid SQLAlchemy conflict)
    delivery_metadata = Column(JSON)  # Extraction date, methods, etc.
    data_dictionary = Column(JSON)
    qa_report = Column(JSON)  # Full data QA report

    # Delivery approval (NEW - Sprint X)
    delivery_approved_by = Column(String, nullable=True)  # Informatician who approved delivery
    delivery_approved_at = Column(DateTime, nullable=True)  # When delivery was approved

    # Notification
    notification_sent = Column(Boolean, default=False)
    notification_sent_at = Column(DateTime, nullable=True)

    # Relationship
    request = relationship("ResearchRequest", back_populates="delivery")


class User(Base):
    """User authentication and authorization"""

    __tablename__ = "users"

    id = Column(String, primary_key=True)  # USR-XXXXXXXX
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)

    # Profile
    full_name = Column(String, nullable=False)
    department = Column(String)
    role = Column(String, nullable=False, default="researcher")  # researcher, data_steward, admin

    # Status
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False)  # Email verification status

    # Timestamps
    created_at = Column(DateTime, default=datetime.now, nullable=False)
    updated_at = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    last_login_at = Column(DateTime, nullable=True)

    # Security
    failed_login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)  # Account lockout timestamp

    # Preferences
    notification_preferences = Column(JSON, default={})  # Email, SMS preferences

    def __repr__(self):
        return f"<User(email='{self.email}', role='{self.role}', active={self.is_active})>"


class AuditLog(Base):
    """
    HIPAA-Compliant Audit Log for PHI Access Tracking

    Tracks all system events with emphasis on PHI access per HIPAA requirements.
    Append-only table for compliance and forensic analysis.

    Standard Event Types:
    - PHI_VIEW: Viewed PHI data (patient records, observations, etc.)
    - PHI_EXPORT: Exported PHI data to external system
    - PHI_SEARCH: Searched for patients/PHI data
    - REQUEST_CREATE: Created new research request
    - REQUEST_APPROVE: Approved research request
    - REQUEST_REJECT: Rejected research request
    - USER_LOGIN: User authentication
    - USER_LOGOUT: User logged out
    - USER_CREATE: New user created
    - USER_UPDATE: User profile updated
    - USER_DELETE: User deleted
    - QUERY_EXECUTE: SQL-on-FHIR query executed
    - DATA_EXTRACT: Data extraction performed
    - DATA_DELIVER: Data delivered to researcher
    - AGENT_STARTED: AI agent started execution
    - AGENT_COMPLETED: AI agent completed execution
    - AGENT_FAILED: AI agent failed
    - STATE_CHANGED: Workflow state transition
    - ERROR_OCCURRED: System error
    """

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.now, nullable=False, index=True)

    # User tracking (HIPAA required)
    user_id = Column(String, ForeignKey("users.id"), nullable=True, index=True)

    # Request tracking
    request_id = Column(String, ForeignKey("research_requests.id"), nullable=True, index=True)

    # Event details
    event_type = Column(
        String, nullable=False, index=True
    )  # PHI_VIEW, REQUEST_CREATE, USER_LOGIN, etc. (see docstring)
    action = Column(
        String, nullable=True, index=True
    )  # Specific action: view, create, update, delete, export
    agent_id = Column(String, nullable=True)

    # Resource tracking (what was accessed)
    resource_type = Column(
        String, nullable=True, index=True
    )  # Patient, Observation, Condition, ResearchRequest, User
    resource_id = Column(String, nullable=True)  # ID of the specific resource accessed

    # PHI access flag (HIPAA critical - indexed for fast queries)
    phi_accessed = Column(Boolean, default=False, nullable=False, index=True)

    # Request metadata (HIPAA audit trail)
    ip_address = Column(String, nullable=True)  # Client IP address
    user_agent = Column(String, nullable=True)  # Browser/client user agent

    # Result tracking
    result = Column(String, nullable=True)  # success, failure, partial, error

    # Event data (flexible JSON for different event types)
    event_data = Column(JSON, default={})

    # Legacy context field (kept for backwards compatibility)
    triggered_by = Column(String, nullable=True)  # user_id, agent_id, system

    # Severity (for filtering and alerting)
    severity = Column(String, default="info")  # debug, info, warning, error, critical


class MaterializedViewMetadata(Base):
    """Metadata for materialized views in sqlonfhir schema"""

    __tablename__ = "materialized_view_metadata"

    id = Column(Integer, primary_key=True)
    view_name = Column(
        String, unique=True, nullable=False, index=True
    )  # Name of the materialized view
    created_at = Column(
        DateTime, default=datetime.now, nullable=False
    )  # When view was first created
    last_refreshed_at = Column(DateTime, nullable=True)  # When view was last refreshed
    next_refresh_at = Column(DateTime, nullable=True)  # Scheduled next refresh time

    # View size and content metrics
    row_count = Column(Integer, nullable=True)  # Number of rows in view
    size_bytes = Column(Integer, nullable=True)  # Size of view in bytes
    column_count = Column(Integer, nullable=True)  # Number of columns

    # Performance metrics
    refresh_duration_ms = Column(Float, nullable=True)  # Last refresh duration in milliseconds
    last_query_time_ms = Column(Float, nullable=True)  # Last query execution time
    query_count = Column(Integer, default=0)  # Total queries against this view

    # Health and status
    status = Column(String, default="active", nullable=False)  # active, stale, refreshing, failed
    is_stale = Column(Boolean, default=False)  # True if data is considered stale
    staleness_hours = Column(Float, nullable=True)  # Hours since last refresh
    error_message = Column(Text, nullable=True)  # Last error message if refresh failed

    # Configuration
    auto_refresh_enabled = Column(Boolean, default=True)  # Enable automatic refresh
    refresh_interval_hours = Column(Integer, default=24)  # Refresh frequency in hours

    # ViewDefinition reference
    view_definition_name = Column(String, nullable=True)  # Source ViewDefinition name
    resource_type = Column(String, nullable=True)  # FHIR resource type (Patient, Observation, etc.)

    # Indexes and dependencies
    index_count = Column(Integer, default=0)  # Number of indexes on view
    depends_on = Column(JSON, default=[])  # List of tables/views this view depends on

    def __repr__(self):
        return f"<MaterializedViewMetadata(view_name='{self.view_name}', status='{self.status}', row_count={self.row_count})>"

    @property
    def is_healthy(self) -> bool:
        """Check if view is in healthy state"""
        return self.status == "active" and not self.is_stale

    @property
    def needs_refresh(self) -> bool:
        """Check if view needs refresh based on staleness"""
        if self.auto_refresh_enabled and self.staleness_hours:
            return self.staleness_hours >= self.refresh_interval_hours
        return False
