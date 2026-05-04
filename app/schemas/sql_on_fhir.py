"""Schema for /sql_query — Sprint 6.1 Phase 2.3 Issue #5 tracer bullet.

The endpoint exists to run SQL. Restricting keywords (DROP, DELETE, etc.) is
HIPAA security theater — trivially bypassed and signals to a knowledgeable
reviewer that we don't understand what controls actually do. The right control
layer is DB-level least-privilege (the API user has SELECT-only on the FHIR
schema). This schema enforces:

- type is str (not int, list, etc.)
- length cap 50,000 chars (DoS defense, ~10K LLM tokens)
- no extra fields (defends against {"sql": "...", "is_admin": true})
- whitespace stripped (cosmetic)
"""

from app.schemas import LongText, PHIInputModel


class SQLQueryRequest(PHIInputModel):
    sql: LongText
