# LangGraph Migration Guide

**Last Updated**: 2025-11-03
**Status**: Phase 3 Complete (75% → 100%)
**Target Completion**: Phases 4-5 (2-3 weeks)

This guide provides step-by-step instructions for migrating ResearchFlow from the custom imperative orchestrator to LangGraph declarative state machine.

---

## Table of Contents

1. [Migration Overview](#migration-overview)
2. [Pre-Migration Checklist](#pre-migration-checklist)
3. [Phase-by-Phase Deployment](#phase-by-phase-deployment)
4. [Rollout Strategy](#rollout-strategy)
5. [Rollback Procedures](#rollback-procedures)
6. [Monitoring & Validation](#monitoring--validation)
7. [Troubleshooting](#troubleshooting)
8. [Post-Migration Tasks](#post-migration-tasks)

---

## Migration Overview

### What We're Migrating

**From**: Custom imperative orchestrator (`app/orchestrator/orchestrator.py`)
- Manual agent-to-agent message routing
- Database-backed state management
- Imperative workflow control

**To**: LangGraph declarative state machine (`app/langchain_orchestrator/langgraph_workflow.py`)
- Automatic routing via StateGraph conditional edges
- Checkpointer-based state persistence
- Declarative workflow definition

### Why Migrate?

**Benefits**:
- ✅ **Observability**: Full workflow tracing via LangSmith
- ✅ **Durability**: Automatic state persistence with checkpointing
- ✅ **Maintainability**: Declarative workflow definition (easier to understand/modify)
- ✅ **Industry Standard**: LangChain/LangGraph is widely adopted
- ✅ **Debugging**: Visual workflow graphs and step-by-step replay

**Architecture**:
- **Adapter Pattern**: Reuses existing agents (no business logic changes)
- **API Compatibility**: LangGraphRequestFacade provides same interface as orchestrator
- **Zero Downtime**: Feature flag enables gradual rollout

---

## Pre-Migration Checklist

### ✅ 1. Verify Code Deployed

```bash
# Check LangGraph files exist
ls -la app/langchain_orchestrator/
# Should show:
# - langgraph_workflow.py (23-state workflow)
# - persistence.py (checkpointer setup)
# - agent_adapter.py (BaseAgent bridge)
# - approval_bridge.py (approval sync)
# - request_facade.py (UI compatibility)

# Verify tests passing
pytest tests/integration/test_request_facade.py -v
pytest tests/e2e/test_ui_with_langgraph.py -v
```

**Expected**: All files present, all tests passing

---

### ✅ 2. Database Backup

**Critical**: Back up database before migration!

```bash
# For PostgreSQL:
pg_dump -U postgres researchflow > backup_$(date +%Y%m%d_%H%M%S).sql

# For SQLite:
cp dev.db backup_dev_$(date +%Y%m%d_%H%M%S).db
```

**Verify backup**:
```bash
# PostgreSQL:
psql -U postgres -c "SELECT COUNT(*) FROM research_requests;"

# SQLite:
sqlite3 dev.db "SELECT COUNT(*) FROM research_requests;"
```

---

### ✅ 3. Environment Variables

Add to `.env`:

```bash
# LangGraph Migration Feature Flags
USE_LANGGRAPH_WORKFLOW=false          # Enable LangGraph (start with false)
LANGGRAPH_ROLLOUT_PCT=0               # Gradual rollout percentage (0-100)

# LangSmith Observability (recommended for monitoring)
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=<your-langsmith-key>
LANGCHAIN_PROJECT=researchflow-production
LANGCHAIN_ENDPOINT=https://api.smith.langchain.com
```

**Get LangSmith API key**: https://smith.langchain.com/settings

---

### ✅ 4. Redis Running (for Speed Layer)

```bash
# Check Redis is running
redis-cli ping
# Should return: PONG

# If not running:
redis-server &
```

---

### ✅ 5. Stop New Request Submissions

During migration window:
1. Display maintenance banner in UIs
2. Temporarily disable new request submission
3. Allow existing requests to complete or pause at approval gates

---

## Phase-by-Phase Deployment

### Phase 1: Dry-Run Migration (30 minutes)

**Goal**: Test migration without committing changes

```bash
# Preview migration of all active requests
python scripts/migrate_to_langgraph.py --all --dry-run

# Review output logs
tail -100 migration_*.log
```

**Expected**:
- All requests converted successfully
- No errors in conversion logs
- State JSON looks correct

**If errors**: Fix conversion logic in `convert_orchestrator_state_to_langgraph()`

---

### Phase 2: Migrate Active Requests (1-2 hours)

**Goal**: Convert in-progress requests to LangGraph format

```bash
# Interactive migration (confirm each request)
python scripts/migrate_to_langgraph.py --all --interactive

# OR: Batch migration (auto-confirm)
python scripts/migrate_to_langgraph.py --all

# Validate migration
python scripts/migrate_to_langgraph.py --validate REQ-20250130-ABC123
```

**Expected**:
- All requests migrated successfully
- Checkpoints created for each request
- Database records intact

**If errors**:
1. Check logs: `migration_*.log`
2. Rollback failed requests: `python scripts/migrate_to_langgraph.py --rollback REQ-123`
3. Fix issues and retry

---

### Phase 3: Enable Feature Flag (5 minutes)

**Goal**: Route new requests to LangGraph

```bash
# Update .env
USE_LANGGRAPH_WORKFLOW=true
LANGGRAPH_ROLLOUT_PCT=0   # Start at 0% for testing

# Restart services
# For local:
pkill -f streamlit; pkill -f uvicorn
streamlit run app/web_ui/researcher_portal.py --server.port 8501 &
streamlit run app/web_ui/admin_dashboard.py --server.port 8502 &
uvicorn app.main:app --reload --port 8000 &

# For Docker:
docker-compose restart app
```

**Verify**:
- Visit http://localhost:8501 (Researcher Portal)
- Check for "🆕 Using LangGraph Orchestrator (Beta)" caption
- Submit test request
- Verify in database and LangSmith

---

## Rollout Strategy

### Gradual Rollout (Recommended)

**Week 1**: 10% rollout
```bash
# .env
LANGGRAPH_ROLLOUT_PCT=10
```
- 10% of new requests → LangGraph
- 90% of new requests → legacy
- Monitor for 2-3 days

**Week 2**: 25% rollout
```bash
LANGGRAPH_ROLLOUT_PCT=25
```
- Monitor for 2-3 days

**Week 3**: 50% rollout
```bash
LANGGRAPH_ROLLOUT_PCT=50
```
- Monitor for 1 week

**Week 4**: 100% rollout
```bash
LANGGRAPH_ROLLOUT_PCT=100
# OR: Remove percentage logic, use direct flag
USE_LANGGRAPH_WORKFLOW=true
```

### Monitoring Between Rollouts

**Check**:
1. **Error rates**: Are LangGraph requests failing more than legacy?
2. **Completion times**: Are workflows completing in reasonable time?
3. **Approval workflow**: Are admins able to approve requests?
4. **State persistence**: Do workflows resume after approval?

**Tools**:
- LangSmith dashboard: https://smith.langchain.com
- Database queries:
  ```sql
  SELECT current_state, COUNT(*)
  FROM research_requests
  WHERE created_at > NOW() - INTERVAL '1 day'
  GROUP BY current_state;
  ```

---

## Rollback Procedures

### Emergency Rollback (< 5 minutes)

**If major issues discovered**:

```bash
# 1. Disable LangGraph immediately
# Update .env:
USE_LANGGRAPH_WORKFLOW=false
LANGGRAPH_ROLLOUT_PCT=0

# 2. Restart services
docker-compose restart app
# OR
pkill -f streamlit; pkill -f uvicorn
# ... restart commands

# 3. Verify legacy orchestrator active
curl http://localhost:8000/health
```

**Data Safety**:
- ✅ All requests remain in database (no data loss)
- ✅ Legacy orchestrator can read existing requests
- ✅ In-progress workflows continue from last state

---

### Partial Rollback (Specific Requests)

**If specific requests have issues**:

```bash
# Rollback single request
python scripts/migrate_to_langgraph.py --rollback REQ-20250130-ABC123

# Verify rollback
python scripts/migrate_to_langgraph.py --validate REQ-20250130-ABC123
```

---

### Database Restore (Last Resort)

**Only if catastrophic failure**:

```bash
# Stop all services
docker-compose down

# Restore from backup
# PostgreSQL:
psql -U postgres researchflow < backup_20250130_100000.sql

# SQLite:
cp backup_dev_20250130_100000.db dev.db

# Restart with legacy orchestrator
USE_LANGGRAPH_WORKFLOW=false
docker-compose up
```

---

## Monitoring & Validation

### Key Metrics to Monitor

| Metric | Tool | Target |
|--------|------|--------|
| Request success rate | LangSmith | > 95% |
| Avg completion time | LangSmith | < 5 minutes (stubs) |
| State transition errors | Logs | 0 |
| Approval processing | Database | All approved requests progress |
| Checkpoint persistence | LangSmith | All states saved |

---

### LangSmith Dashboard

**URL**: https://smith.langchain.com/projects/researchflow-production

**Views**:
1. **Traces**: See all workflow executions
2. **Feedback**: Track success/failure
3. **Latency**: Monitor step execution times
4. **Errors**: Debug failures

**Useful Filters**:
- Last 24 hours
- Filter by `request_id`
- Filter by `current_state`

---

### Database Queries

```sql
-- Count requests by state (last 24 hours)
SELECT current_state, COUNT(*)
FROM research_requests
WHERE created_at > NOW() - INTERVAL '1 day'
GROUP BY current_state
ORDER BY COUNT(*) DESC;

-- Find stuck requests (no update in 1 hour)
SELECT id, current_state, updated_at
FROM research_requests
WHERE completed_at IS NULL
  AND updated_at < NOW() - INTERVAL '1 hour'
ORDER BY updated_at ASC;

-- Check approval processing time
SELECT
  a.request_id,
  a.created_at AS approval_created,
  a.reviewed_at AS approval_reviewed,
  EXTRACT(EPOCH FROM (a.reviewed_at - a.created_at))/60 AS minutes_to_review
FROM approvals a
WHERE a.created_at > NOW() - INTERVAL '1 day'
  AND a.status = 'approved'
ORDER BY minutes_to_review DESC;
```

---

## Troubleshooting

### Issue: Requests stuck in "new_request"

**Symptoms**: Workflows don't progress beyond initial state

**Diagnosis**:
```bash
# Check LangGraph logs
tail -100 migration_*.log | grep ERROR

# Check LangSmith traces
# Visit https://smith.langchain.com
```

**Fixes**:
1. Verify workflow compiled: Check `langgraph_workflow.py` for syntax errors
2. Check agent adapters: Ensure agents return correct result format
3. Verify checkpointer: Ensure AsyncSqliteSaver working

---

### Issue: Approval workflow not working

**Symptoms**: Approved requests don't progress

**Diagnosis**:
```sql
SELECT * FROM approvals
WHERE status = 'approved' AND reviewed_at > NOW() - INTERVAL '1 hour'
ORDER BY reviewed_at DESC LIMIT 10;
```

**Fixes**:
1. Check approval bridge: `app/langchain_orchestrator/approval_bridge.py`
2. Verify workflow resumption: Look for "Resuming workflow" in logs
3. Check approval status sync: Ensure `update_approval_status()` working

---

### Issue: State not persisting

**Symptoms**: Workflows restart from beginning after restart

**Diagnosis**:
```bash
# Check checkpoints database
sqlite3 checkpoints.db "SELECT COUNT(*) FROM checkpoints;"
```

**Fixes**:
1. Verify checkpointer initialized: Check `persistence.py`
2. Check checkpoint config: Ensure `thread_id` set correctly
3. Verify database write permissions

---

## Post-Migration Tasks

### Week 1: Monitor Closely

- [ ] Check LangSmith daily for errors
- [ ] Review logs for warnings
- [ ] Verify approval workflow working
- [ ] Confirm state persistence
- [ ] Monitor completion times

---

### Week 2-3: Gradual Rollout

- [ ] Increase `LANGGRAPH_ROLLOUT_PCT` incrementally
- [ ] Monitor each increase for 2-3 days
- [ ] Compare legacy vs LangGraph metrics
- [ ] Address any issues before increasing percentage

---

### Week 4: Full Deployment

- [ ] Set `LANGGRAPH_ROLLOUT_PCT=100`
- [ ] Remove rollout percentage logic (optional)
- [ ] Update documentation
- [ ] Archive legacy orchestrator code

---

### Month 2: Cleanup (Phase 5)

**Once 100% stable**:

```bash
# Archive legacy code
mkdir -p app/legacy
mv app/orchestrator app/legacy/

# Remove unused A2A auth (if not needed)
rm -rf app/a2a/

# Update imports in any remaining files
grep -r "from app.orchestrator" app/

# Update documentation
# - README.md: Update architecture section
# - CLAUDE.md: Mark migration 100% complete
# - Architecture diagrams: Update to show LangGraph
```

---

### Final Checklist

- [ ] All requests using LangGraph (0% legacy)
- [ ] No errors in LangSmith for 1 week
- [ ] Approval workflow 100% functional
- [ ] State persistence verified
- [ ] Performance meets targets
- [ ] Legacy code archived
- [ ] Documentation updated
- [ ] Feature flags removed (optional)
- [ ] Team trained on LangSmith monitoring

---

## Success Criteria

| Criterion | Target | Status |
|-----------|--------|--------|
| All active requests migrated | 100% | ✅ Complete |
| Zero data loss | 0 lost | ✅ Complete |
| LangGraph workflows stable | > 95% success | 🔄 Monitor |
| Approval workflow functional | 100% | 🔄 Monitor |
| Performance acceptable | < 10% degradation | 🔄 Monitor |
| Observability working | LangSmith enabled | ✅ Complete |
| Rollback capability | < 5 min | ✅ Complete |

---

## Contact & Support

**Issues**: Open GitHub issue at https://github.com/org/researchflow/issues

**LangSmith Support**: https://docs.smith.langchain.com

**LangGraph Docs**: https://langchain-ai.github.io/langgraph/

---

**Migration Status**: Phase 3 Complete (75%) → Ready for Phase 4 (Migration & Deployment)

**Last Updated**: 2025-11-03
