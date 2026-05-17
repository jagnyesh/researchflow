---
sprint: 6.1
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Sprint 6.1 — Split human/agent auth, not unified JWT

Agent traffic (`mcp`, `a2a` routes) authenticating with the same JWT issuance flow as humans would 401-itself on every internal call. **Chose: separate `verify_service_token()` helper reusing existing `app/a2a/auth.py` JWT issuance for agent routes;** human routes use `Depends(get_current_user)`. Two auth models, one issuer.
