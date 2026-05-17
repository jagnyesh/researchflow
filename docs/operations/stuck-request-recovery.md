# Stuck-request recovery (LangGraph era)

Quick reference for operators when a `research_request` row is stuck.

## What changed in Sprint 7.2

The A2A orchestrator era had four recovery scripts using `orchestrator.route_task(...)` to manually push work between agents:

- `scripts/recover_stuck_request.py` (deleted)
- `scripts/process_stuck_requests.py` (deleted)
- `scripts/trigger_delivery.py` (deleted)
- `scripts/advance_workflow.py` (deleted — used `WorkflowEngine.transition` directly)

LangGraph doesn't support manual task routing — `LangGraphRequestFacade.route_task` is a documented no-op (see `app/langchain_orchestrator/request_facade.py:598-642`). Instead, LangGraph uses **checkpointer-based workflow resume**: the workflow paused at an approval gate, the gate is resolved, the workflow resumes from the checkpoint.

## The new recovery model

**99% of stuck requests are stuck at an approval gate.** The recovery procedure is:

1. **Identify the pending approval** for the request — via admin dashboard at port 8503, or SQL:
   ```sql
   SELECT id, approval_type, status, submitted_at
   FROM approvals
   WHERE request_id = 'REQ-...'
   ORDER BY created_at DESC;
   ```

2. **Resolve the approval** — for an approved-but-stuck case (approval row marked `approved` but workflow never advanced):
   ```bash
   python scripts/fix_stuck_approval.py --request-id REQ-...
   ```

3. **For a specifically stuck delivery approval** (Sprint 6 era `approve_delivery()` bypass bug):
   ```bash
   python scripts/fix_stuck_delivery_approvals.py [--dry-run]
   ```

4. **For a specifically stuck preview-extraction** (phenotype_sql approved but preview never ran):
   ```bash
   python scripts/trigger_preview_extraction.py REQ-...
   ```

All three scripts call `LangGraphRequestFacade.process_approval_response(approval_id, decision="approve")` under the hood. That's the LG-supported API: it persists the approval status and resumes the workflow from the checkpoint.

## What if the request is stuck WITHOUT a pending approval?

Rare (1% case). Causes:
- Workflow crashed mid-agent before reaching the next gate
- Database row exists but checkpointer has no state (orphaned row)

LangGraph exposes a checkpointer API for state inspection + manual update (`workflow.compiled_graph.aget_state(config)`, `aupdate_state(...)`). This is **not** wrapped in a CLI script today. If you encounter this case:

1. Read the row's `current_state` to know which checkpoint you're recovering from
2. Open a Python shell, instantiate `LangGraphRequestFacade`, and use the checkpointer directly
3. Document the procedure in this doc so future operators don't have to re-derive it

If this becomes common enough, file a follow-on issue for a "rebuild orphan workflow state" script.

## Why the old route_task model is gone

A2A's `route_task` was a direct push-to-agent primitive: the orchestrator could hand any task to any agent at any time. LangGraph's StateGraph is more constrained — only transitions defined by conditional edges fire. The constraint is intentional: LangGraph workflows can't be corrupted by out-of-band task injection, but it does mean recovery is approval-driven, not task-driven.

Per `docs/decisions/0024-sprint-7-2-a2a-fsm-closeout.md` (Phase 1 close section): the Path-0 diagnostic confirmed LangGraph workflows reach terminal state correctly when AUTO_APPROVE_FOR_DEV is enabled, fire the documented approval gates, and persist `current_state` correctly. Stuck workflows in production should mostly correspond to pending HITL approvals — recover by resolving the approval.
