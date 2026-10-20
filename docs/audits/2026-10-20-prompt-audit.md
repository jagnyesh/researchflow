# Prompt audit — ResearchFlow agent configuration (2026-10-20)

**Tool:** `/claude-api prompt-audit` (Claude Code 2.1.303 bundled skill; the `/checkup prompt-audit` alias is not present in this build).
**Target model:** `claude-opus-5-5` (the model running the audit; no audited file pins a model).
**Pass 1 scope:** `CLAUDE.md`, `.claude/skills/validate-and-ship/SKILL.md`, `.claude/skills/ponytail/SKILL.md`.
**Pass 2 scope (files pass 1 skipped):** `CONTEXT.md`, `BACKLOG.md`, `.claude/architecture.rules`, `docs/decisions/INDEX.md` (all `@`-imported by `CLAUDE.md`), `~/.claude/CLAUDE.md` (user-level; edits affect every project).
**Not audited:** the lean-ctx MCP-server instructions (no file in scope; set by the pinned server); `.claude/settings*.json` and `.mcp.json` (may hold secrets; the guide forbids reading them). Groups 3–4 (tool descriptions, request code): not applicable, since there are none in scope.

**Status:** applied 2026-10-20 on branch `chore/prompt-audit-2026-10-20` (uncommitted), with review corrections. See *Applied changes* at the end; `git diff` is the source of truth.

**Proposed patches (`docs/audits/2026-10-20-*.patch`, kept as the original proposal):**
- `prompt-audit.patch`: pass 1 only, 9 hunks.
- `prompt-audit-full.patch`: pass 1 + pass 2 repo fixes, 19 hunks. Also creates `docs/audits/vetting-ledger.md` and `docs/sprints/archive/CONTEXT_HISTORY_through_2026-07.md`.
- `global-claude-md.patch`: 1 hunk to `~/.claude/CLAUDE.md`.
- `git apply --check` passed for both repo patches against the 2026-10-20 working tree. Apply one or the other, not both.

---

## Summary

Little old-model filler: caps-emphasis counts are 0–3 per file, and every remaining caps rule gives a reason or guards a dangerous action. The real problem is **stale facts and files contradicting each other, in content that loads into every session**:

1. **Two retired components are described as current.** `CLAUDE.md:104` and `architecture.rules:15` describe the custom A2A orchestrator under `app/orchestrator/` as production. It was deleted in Sprint 7.2 and the directory no longer exists. `architecture.rules:49` names `QueryInterpreter`, which was retired in Sprint 6.7.
2. **The PR-cadence rules contradict each other.** `CONTEXT.md:325` cites "one cohesive squash PR per sprint". `CLAUDE.md:40` mandates one PR per issue with continuous merge. `CLAUDE.md:125` routes shipping to `/ship` and bypasses `/validate-and-ship`.
3. **About 93 KB of `@`-imports load into every session.** `CONTEXT.md` is 49 KB and calls itself "what is true right now", but ~75% of it is narratives from shipped sprints whose own "kept until X ships" conditions have already passed. `architecture.rules:3` claims it is "loaded only when relevant", but `CLAUDE.md:10` `@`-imports it, so it loads every time.

Counts: Group 1 (dated text): 5 · Group 2 (stale facts / conflicts / history): 22 · Groups 3–4: n/a.

---

## Pass 1 — CLAUDE.md, validate-and-ship, ponytail

| # | Location | Evidence | Pattern | Why obsolete | Conf. | Action |
|---|---|---|---|---|---|---|
| 1 | `validate-and-ship/SKILL.md:29` | ``Co-Authored-By: Claude Fable 5`` | 2 · pinned model name | Session attribution now specifies Opus 5.5; the hardcoded trailer goes stale on every model change | High | rewrite: "the trailer the session's attribution instructions specify" |
| 2 | `CLAUDE.md:103` | "6 specialized agents" | 2 · volatile specifics | 7 `BaseAgent` subclasses exist (`coordinator_agent.py` missing from the list) | High | rewrite, no count |
| 3 | `CLAUDE.md:107` | "6 tables (…)" | 2 · volatile specifics | `models.py` has 10 `(Base)` classes (+Approval, User, AuditLog, MaterializedViewMetadata) | High | rewrite, no count |
| 4 | `CLAUDE.md:108` | "(Sprint 6.1 active work)" | 2 · time-sensitive | Line dates from 2026-05-08; 6.1 has shipped | High | remove |
| 5 | `CLAUDE.md:125` vs `:42` | `/ship or /land-and-deploy` vs `/validate-and-ship` | 2 · contradiction | Line 125 is from 2026-05-08, line 42 from 2026-10-20; `/ship` skips attestation and merge-actor rules | High | rewrite 125 to route to `/validate-and-ship` |
| 6 | `CLAUDE.md:104-105` | "custom A2A orchestrator + 15-state workflow FSM (production)" | 2 · volatile specifics | `app/orchestrator/` doesn't exist; Sprint 7.2 deleted it (CONTEXT.md:68) | High | rewrite: LangGraph is the only orchestrator (*the pass 1 report had this as a low-confidence flag; confirmed in pass 2*) |
| 7 | `CLAUDE.md:113` | "When in doubt, invoke the skill." | 1a · "if in doubt, use [tool]" | Over-triggers on current models | Medium | remove the sentence (it came from gstack's setup; a gstack re-setup may re-add it) |
| 8 | `CLAUDE.md:54-60` | ~5 KB vetting ledger | 2 · history narratives | Loads every session; only 3 lines in it are still actionable | Medium | move to `docs/audits/vetting-ledger.md`; keep 3 rule lines |
| 9 | `validate-and-ship/SKILL.md:3` | "Distilled from Sprint 6.7's…" | 2 · history in trigger text | Description rides in every request; history doesn't help routing | Medium | remove the sentence |
| 10 | `ponytail/SKILL.md:28-29` | "ACTIVE EVERY RESPONSE… Still active if unsure" | 1a · pressure language | Current models over-apply caps and "if unsure" defaults | Medium | rewrite plainly |
| 11 | `ponytail/SKILL.md:68` | "at most three short lines" | 1f · numeric output cap | Caps tuned against older, wordier models | Medium | rewrite without the number |
| 12 | `ponytail/SKILL.md:103-105` | PCA9685 hardware aside | 1c · kitchen-sink padding | Irrelevant to this repo; asides get applied where they don't fit | Medium | remove |
| 13 | `CLAUDE.md:63` vs `validate-and-ship:66` | Harness-internal self-merge list includes vs omits `CLAUDE.md` | 2 · contradiction (merge authority) | Two files disagree on whether a `CLAUDE.md`-only PR may self-merge | High | **flag**: safety rule, you decide |
| 14 | `CLAUDE.md:42` vs `validate-and-ship:14` | Pipeline starts with "/qa" vs "Run the change's tests" | 2 · contradiction | `CLAUDE.md` is newer, but the workflow doc names the skill as authoritative | Medium | **flag** |
| 15 | `CLAUDE.md:50` / `validate-and-ship:75` / workflow §4.1 | Where corrections are written: "CLAUDE.md or architecture.rules" / "memory or architecture.rules" / "CLAUDE.md" | 2 · contradiction | Three destinations; behavior depends on which file loaded | Medium | **flag** |
| 16 | `ponytail:107-112` vs `/tdd` + mutation-test pattern | "No frameworks, no fixtures, no per-function suites unless asked" | 2 · contradiction | Would loosen the repo's test-first and regression rules | Medium | **flag** |
| 17 | `CLAUDE.md:57` | "untested until then" (restart) | 2 · time-sensitive | Probably resolved; not recorded | Low | flag |

**Ponytail hunks (10–12)** invalidate the sha256 pin recorded in `CLAUDE.md:58`. Alternative: leave the vendored file untouched and put a repo-level override in `CLAUDE.md`, or report the issues upstream.

---

## Pass 2 — skipped files

### `.claude/architecture.rules`

| # | Location | Evidence | Pattern | Why obsolete | Conf. | Action |
|---|---|---|---|---|---|---|
| 18 | `:3` vs `CLAUDE.md:10` | "loaded via `@.claude/architecture.rules` only when relevant" | 2 · contradiction | `CLAUDE.md` `@`-imports it, so it loads every session | High | **flag**: choose always-loaded (fix line 3) or on-demand (drop the `@`) |
| 19 | `:15` | "Two orchestrators coexist: custom (`app/orchestrator/`) is production" | 2 · stale fact | Directory deleted in Sprint 7.2 | High | rewrite |
| 20 | `:39` | "6 tables… Sprint 6.1 adds `User` and `audit_logs`" | 2 · stale fact | 10 tables; 6.1 shipped | High | rewrite |
| 21 | `:49` | "Chat UI uses the `QueryInterpreter` (`app/services/query_interpreter.py`)" | 2 · stale fact | File is gone; `research_notebook.py:316` says "QueryInterpreter… was retired" | High | rewrite to `sql_synthesis` + `SQLValidator` |
| 22 | `:53` | `app/legacy/` no-go zone, "reserved for… custom orchestrator archive" | 2 · stale fact | Directory doesn't exist and the orchestrator it was meant to archive is deleted | High | remove |
| 23 | `:65-74` | Middleware order: HTTPSRedirect → CORS → Auth → Audit → RateLimit; "Sprint 6.1 in flight" | 2 · stale fact | No `HTTPSRedirectMiddleware` or `CORSMiddleware` in `app/`. The real stack is TrustedHost + TLS (`app/security/tls.py:51,86`) and audit + body-size (`app/main.py:148,153`) | High | rewrite as a pointer to the registration sites |
| 24 | `:47` | "full 6-agent workflow" | 2 · volatile count | 7 agent classes | Medium | rewrite, no count |
| 25 | `:54` | "Sprint 6.1 PreToolUse hook will block writes" | 2 · time-sensitive | Future tense for a shipped sprint; `tests/synthetic_phi/` doesn't exist. Whether the hook exists means reading settings, which is off-limits | Low | flag |

### `CONTEXT.md` (49 KB, loaded every session)

| # | Location | Evidence | Pattern | Why obsolete | Conf. | Action |
|---|---|---|---|---|---|---|
| 26 | `:24-275`, `:329-441` | Narratives for shipped sprints 6.5, 7.2, 6.4, 8.3, 8.4, 8.2, 6.2, 6.1; e.g. `:145` "kept for context until Sprint 6.4 ships", `:329` "kept… until Sprint 8.1 ships" | 2 · history narratives | Self-declared retention conditions passed months ago; the file calls itself "what is true right now" | High | move to `docs/sprints/archive/CONTEXT_HISTORY_through_2026-07.md` (49 KB → 12 KB) |
| 27 | `:298-309` | "Production agents bypass [HybridRunner]… `feasibility_service` uses `JoinQueryBuilder`" | 2 · stale fact | Sprint 6.5 made `phenotype_agent` a HybridRunner caller; `JoinQueryBuilder` was retired in 6.7 (#100) | High | remove (the patch drops it; git history keeps it — archive it instead if you prefer) |
| 28 | `:325` | Cadence rule: "one cohesive squash PR per sprint" | 2 · contradiction | Contradicts per-issue continuous merge (`CLAUDE.md:40`) | High | remove |
| 29 | `:158,255,259,323,325` | `DECISIONS.md` references | 2 · dead path | `DECISIONS.md` doesn't exist; ADRs moved to `docs/decisions/` | High | rewrite (`:323`); the rest moves to the archive with #26 |
| 30 | `:425-441` | "Agents: 6", "15 in custom FSM", `~/.gstack/…` design-doc paths, "Open GitHub issues for Phase 2.2: #1, #2, #3 (all complete, awaiting merge)" | 2 · stale facts | Custom FSM is deleted; issues are merged; paths are outside the repo | High | move to archive with #26 |

### `BACKLOG.md` (26 KB, loaded every session)

| # | Location | Evidence | Pattern | Why obsolete | Conf. | Action |
|---|---|---|---|---|---|---|
| 31 | `:22` | `- [ ] Sprint 6.5 — wire agents through HybridRunner… Next sprint.` | 2 · contradiction | `CONTEXT.md` says 6.5 SHIPPED 2026-05-17 as `d457fe8` | High | rewrite to `[x]` shipped |
| 32 | `:3` | "History lives in `DECISIONS.md`" | 2 · dead path | Moved to `docs/decisions/` | High | rewrite |
| 33 | `:8,11,13,18` | Paragraph-long histories inside checked items | 2 · history narratives | File describes itself as "forward plan only" | Medium | **flag**: trim to one line plus ADR link (not in the patch; judgment call on what to keep) |
| 34 | `CLAUDE.md:9` | `@BACKLOG.md` | 2 · load cost | 26 KB forward plan loads into every session, including narrow tasks | Low | **flag**: consider a plain path (on-demand) instead of `@` |

### `docs/decisions/INDEX.md`
Clean. It's an append-only index with no stale paths found.

### `~/.claude/CLAUDE.md` (user-level; affects every project)

| # | Location | Evidence | Pattern | Why obsolete | Conf. | Action |
|---|---|---|---|---|---|---|
| 35 | `:69` | "use `ctx_edit(path, old_string, new_string)`" | 2 · dead tool name | lean-ctx exposes `ctx_patch`; there is no `ctx_edit` | High | rewrite (`global-claude-md.patch`). This block sits inside `<!-- lean-ctx -->` markers; lean-ctx's setup rewrites it, and that setup is what `lean-ctx update` triggers (still a no-go command) |
| 36 | `:70` vs the lean-ctx MCP instructions | "Write, Delete, Glob — use normally" vs "ctx_glob > native Glob (denied by hook)" | 2 · contradiction | One says use native Glob; the other says the hook denies it | Medium | **flag**: the MCP side can't be edited without changing the pin |
| 37 | `:64` | "Always prefer lean-ctx MCP tools over native equivalents" | 1a + your own measurement | Your memory records lean-ctx as net token-negative on short-command sessions; "always" removes judgment | Low | flag |
| — | rest of file | — | — | Clean: plain register, reasons attached, no fossils | — | — |

---

## Verification notes

**Verified against the repo:** every path, count and contradiction marked High above. Checks used: path existence, `grep` of `models.py`/`app/agents`, `git grep` for middleware/QueryInterpreter, and `git blame` dates for findings 5 and 7.

**Not verified:**
- No before/after behavior probes were run for any Group 1 removal (findings 7, 10–12). Those removals are hypotheses until you see a session behave the same without them.
- Whether the Sprint 6.1 PHI-write hook (finding 25) exists. Checking would mean reading settings, which is off-limits.

**Ordering note:** `prompt-audit-full.patch` touches `validate-and-ship/SKILL.md` and `CLAUDE.md`'s merge-adjacent sections, so under your self-amendment rule it is a human-merge PR.

---

## Applied changes (2026-10-20)

Applied `prompt-audit-full.patch` (all 19 hunks, findings 1–12, 19–24, 26–32) plus the global fix (finding 35). These review corrections depart from the patch:

| Change | Why |
|---|---|
| `architecture.rules`: kept the reverse-proxy rule, retargeted from `HTTPSRedirectMiddleware` to `tls_enforcement_middleware`; `FORWARDED_ALLOW_IPS=*` only when the container isn't internet-reachable | The patch deleted it, but `app/security/tls.py:35` 308-redirects any non-`https` scheme, so the rule still matters behind a proxy; the `*` caveat matches `maybe_warn_about_forwarded_allow_ips` |
| `architecture.rules`: added the SlowAPI pointer (`app/security/rate_limit.py`) | The patch dropped the only mention of rate limiting |
| `CONTEXT.md` "Architectural reality" section **archived** instead of deleted | No content loss: every original line is in either `CONTEXT.md` or the archive, except the two intentional removals (findings 28, 29) |
| Archive: two `docs/decisions/` links rewritten to `../../decisions/` | Root-relative links break once the file is moved into `docs/sprints/archive/` |
| `BACKLOG.md:22`: removed trailing "Next sprint." | Contradicted the `[x]` shipped marker |
| `docs/DAILY_DEV_WORKFLOW.md:184`: now cites `docs/audits/vetting-ledger.md` | It cited "CLAUDE.md's install-ledger entries", which moved |
| Ponytail local edits recorded in `docs/audits/vetting-ledger.md` (new sha256 `81e5fafd…`) and in the `CLAUDE.md` rule line | The edits invalidate the recorded `552acd5` checksum |
| Global `~/.claude/CLAUDE.md:69`: text is "use `ctx_patch` instead (hash-anchored: `ctx_read(mode="anchored")` first, then `set_line`/`replace_lines`)" | `ctx_patch` is hash-anchored, not `old_string`/`new_string`; the shorter proposed wording would mislead. Backup: `~/.claude/CLAUDE.md.bak-20261020-prompt-audit` |

**Not applied (flags, your decision):** 13, 14, 15, 16, 17, 18, 25, 33, 34, 36, 37.

**Found during application, outside the audit's scope:**
- `docs/agents/domain.md` (lines 8–55) is still built around a root `DECISIONS.md`, which no longer exists; line 11 tells skills to report a missing one as an anomaly.
- `.claude/architecture.rules:62` gives `app/schemas/research_request.py` as its example; the actual file is `research.py`.
- `CLAUDE.md:36` heading still says "Throughput workflow"; the workflow doc is now the Risk-Tiered Edition.

**Checks run:** `git apply --check`; no content lost from `CONTEXT.md`; both `SKILL.md` front-matters parse as YAML; every backticked repo path in the edited files exists (except placeholders, history, and finding 25); repo pre-commit hooks pass on all changed files (end-of-file-fixer trimmed a blank line in `CONTEXT.md` on the first run). No pytest run: no code changed, and no test reads these files.
