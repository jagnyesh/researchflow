# 2026-07-19 — Pipeline audit: last-10-PR review-artifact + merge-actor audit

**Trigger:** #128. A last-10-PR audit of the continuous-merge pipeline asked "who merges, and on what evidence?" — and found the answer was defined nowhere.

**Top finding:** 0/10 audited PRs carried an independent review artifact, and the merge actor was undefined — the workflow doc said "merge on green" without saying *who* (§4.0 implied the human, §5.8 implied the pipeline stops at reporting). Agent sessions and human sessions are indistinguishable in GitHub history because the agent runs under the owner's credentials; one session was observed deciding "CI green. Merging #127" itself while feature lanes waited for the human.

## Ranked gaps and disposition

| # | Gap | Disposition |
|---|-----|-------------|
| 1 | Merge gate had no defined actor | **SHIPPED** PR #130 (`3f28b90`): CLAUDE.md §5.8 merge-actor rule — pipeline reports green + posts verdict + waits; human merges behavior-touching PRs; docs-only and harness-internal PRs may self-merge under the standing rule with a visible `Merged-By: pipeline (standing-rule: <class>)` trailer; self-amendment carve-out (merge-policy changes are always human-merge) |
| 2 | Review verdict was not an artifact bound to a SHA | **SHIPPED** PR #130: reviewer posts verdict + findings + reviewed commit SHA as a PR comment; merge requires attestation SHA == `headRefOid`, enforced with `gh pr merge --match-head-commit`; post-attestation push voids the attestation |
| 3 | Testing-evidence artifacts depended on human discipline (1/10 present) | **SHIPPED** PR #130: evidence generation moved inside `/validate-and-ship` (UI-touching → screenshot step; wire-level claims → trace link/payload); `docs:` PRs skip evidence by rule, not by inconsistency |
| 4 | Cycle-time dials uncomputed; review-debt guardrail was vibes | **SHIPPED** PR #130: `scripts/dials.sh` computes open→green (pipeline health) and green→merge (merge-gate latency) per merge day, session-windowed |
| 5 | lean-ctx entered the toolchain without its §5.5 vet (mid-task adoption) | **#132** (this PR): retroactive six-point vet — **verdict: FAIL** (see section below); vetting ledger started in CLAUDE.md §5.5; keep/pin/remove decision pending with the human |
| 6 | Audit findings had no durable home; ramp position not in CONTEXT.md | **#132** (this PR): this file + CONTEXT.md ramp line |
| 7 | Harness changes lacked sandbox-first verification (2026-07-18 uv-pip-sync hijacked `healthcare_env`) | Restore chore: **#129**. Standing rule extension to §5.5: **#132** (this PR) |
| 8 | Stage-2 exit clock unstarted — everything buildable is built; the criterion now only accrues from human-attended sessions | **Appointment, not a task.** Calendar block; first `claude` in each window typed by the human. If after an honest week fully-orchestrated (agent-attended) operation is the deliberate permanent mode, amend the workflow doc — decide it, don't let defaults decide |

## Dogfood note

PR #130 was itself the first PR through the regime it defines: fresh-context review posted a SHA-bound attestation (Verdict: SHIP, Reviewed-Commit `4fb8fec`), CI went green, and — because a PR changing the merge policy is always human-merge under its own carve-out — the human merged it with `--match-head-commit`. The review pass also caught and fixed two real findings pre-merge (dials.sh negative open→green on PR #84; `app/**/*.md` double-classification).

## lean-ctx §5.5 retroactive vet (gap 5) — verdict: FAIL

Vetted 2026-07-19 by a fresh-context agent (read-only pass). FAIL is against §5.5 as written — on unauditability and posture, not observed malice.

- **Install:** MCP server at `~/.local/bin/lean-ctx` — an 82 MB stripped release binary (Rust; strings analysis only). Source-available upstream at `yvgude/lean-ctx`, but the installed binary is unchecksummed and its provenance vs the published source is unverifiable. Skill + hooks + rules under `~/.claude/`; seven hook classes wired into `~/.claude/settings.json`, including a `PreToolUse` matcher that rewrites every `Bash` call through itself.
- **Version:** 3.9.12, **floating** — installer fetches GitHub `releases/latest` (no pin, no checksum); runtime update check active (phoned `api.github.com` the day of the vet); `--self-update` capability present.
- **Maintainer:** pseudonymous GitHub handle (`yvgude`) + commercial site (leanctx.com) only; no named human. Fails the named-maintainer bar.
- **Install path:** SKILL.md setup is literally `curl -fsSL … | bash`, and the skill auto-installs if absent — the exact patterns §5.5 prohibits. Addon registry pulls third-party packages (`uv tool install` / `npx` / `uvx`) — transitive supply chain.
- **Network/telemetry:** endpoints exist for `leanctx.com/metrics`, cloud sync, Datadog/CloudZero/Vantage push, and a full LLM-provider proxy — all observed **off/opt-in** in current config. References `ANTHROPIC_API_KEY` / `OPENROUTER_API_KEY` / `POSTGRES_PASSWORD` etc. tied to those opt-in features; redaction claims unverifiable without source.
- **Scope creep:** modified `~/.claude/settings.json`, appended to global CLAUDE.md, injects MANDATORY-usage instructions and memory blocks into every session — far beyond "context compression."
- **Audit caveat:** lean-ctx's own hooks mediated parts of the vet's shell commands; a hostile binary could theoretically filter what an in-session audit sees. Cross-checked file contents were consistent.
- **Mitigations observed:** telemetry/cloud/proxy off; tidy installer with backups; local hash-chained audit trail; no evidence of exfiltration.
- **Recommended follow-ups:** pin to a checksummed release; decide whether hook-level Bash rewriting is acceptable for a PHI-adjacent codebase; monitor the binary's outbound traffic once. Decision (keep / pin / remove) is the human's.

## Convention

Audits get a dated file here, same append-only spirit as `docs/decisions/`. An audit that evaporates is an artifact-less review one level up.
