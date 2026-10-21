# Workflow gaps vs the AI-Native SDLC Playbook

Point-in-time list (2026-10-20). Each gap is something no skill pack provides: it has to be built in this repo or its CI. Page numbers refer to Anthropic's *AI-Native SDLC Playbook* (Louis Claxton). Review top-down; promote an item to a GitHub issue when you start it.

## 1. Golden-file lock in CI (do first)

- **What:** a CI job that fails a PR when it changes `tests/fixtures/transpiler_expected_outputs.py`, `tests/eval/cases.py`, or `tests/eval/fixtures/**`, unless the PR is explicitly about them (e.g. a label or a `test(golden):` title).
- **Why:** the playbook's "protect the feedback loop" step (p. 32, step 7): an agent fixing code must not be able to weaken the check on that code. "Regenerate expected outputs to match" is how a #76-style silent bug passes.
- **Today:** locked by rule only (`docs/DAILY_DEV_WORKFLOW.md` §7).
- **Done when:** a test PR that edits a golden file without the opt-in fails CI, and one with it passes.

## 2. Evals gate on LLM-touching and config changes

- **What:** run the eval harnesses on PRs that touch LLM call sites (workflow doc §5 trigger list) and on changes to `CLAUDE.md` / `.claude/**`; assert N cases executed.
- **Why:** p. 34: configuration that steers the agent deserves the regression testing code gets.
- **Today:** not built; tracked by #136, #137, #142 (all open). No workflow in `.github/workflows/` triggers on config changes.

## 3. AI review in CI, with a `REVIEW.md`

- **What:** a `REVIEW.md` at the repo root (passes: bugs, security/PHI, compliance with the issue/ADR; what counts as Important vs Nit), and a non-interactive review check on every PR.
- **Why:** p. 37–39: every PR gets the same review passes; the human judges intent and risk.
- **Today:** the fresh-context reviewer runs in-session only via `/validate-and-ship` (workflow doc §5 step 2, §7).

## 4. A repo skill for the PHI/SQL policy, backed by a hook

- **What:** `.claude/skills/phi-boundary/` encoding aggregate-only output, parameterized SQL only, synthetic data only; flip the SQL-interpolation check in `.claude/hooks/PreToolUse.sh` from warn (exit 0) to block (exit 2).
- **Why:** p. 25–26: skills carry institutional knowledge; a policy that must always hold needs a deterministic hook behind it.
- **Today:** the rules live in `CLAUDE.md`, `.claude/architecture.rules` and the global `CLAUDE.md`; the hook only warns on interpolated SQL.

## 5. Trim always-loaded context

- **What:** move `BACKLOG.md` (and possibly `docs/decisions/INDEX.md`) from `@`-import to an on-demand path reference.
- **Why:** p. 23: keep `CLAUDE.md` under a page; stale content takes context for no benefit.
- **Today:** `CLAUDE.md` plus its four `@`-imports is ~62 KB per session (prompt-audit finding 34).

## 6. Auto-file issues from post-merge signals

- **What:** a scheduled job that opens an issue when `main` CI fails, an eval regresses, or cost/drift telemetry (#151) crosses a band.
- **Why:** p. 48–51 (Maintain): detection stays deterministic; the finding re-enters the loop as an intent. Workflow doc §11 already scopes this down from a production loop (no prod deployment yet).
- **Today:** not built.

## Harness issue (not a playbook gap)

- **lean-ctx `hook observe` is back** on 6 global hook events in `~/.claude/settings.json` (`UserPromptSubmit`, `Stop`, `SessionStart`, `SessionEnd`, `PreCompact`, `PostToolUse`). The vetting ledger's 2026-10-06 entry records removing it from all events because it derailed subagents. Auto-named settings backups from 2026-10-19 and 2026-10-20 suggest a setup re-ran. Find what re-wired it, then remove it again and log it in `docs/audits/vetting-ledger.md`.
