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

## Addendum (2026-07-19, same day) — decision executed: PIN via source build; the `update --help` incident

The keep/pin/remove decision above resolved to **PIN**, executed the same day (#134) via the option the original vet didn't list: the Rust source is public, so a `cargo build` from the pinned tag with self-update disabled yields a binary whose provenance is controlled by construction.

**The incident that raised the urgency.** During read-only recon for the pin, `lean-ctx update --help` did not print help — it executed the updater's setup-refresh path, rewriting `~/.zshrc` (shell hook + agent aliases injecting `BASH_ENV` so every agent `bash -c` exec-replaces through the binary), replacing the global CLAUDE.md lean-ctx block with a stricter "Replace Mode v6", reinstalling Claude/Codex hooks (6→7 hook classes), and bouncing the daemon. Root cause, confirmed in source: the `update` dispatch arm has no `--help` guard (`rust/src/cli/dispatch/mod.rs:669`) — its sibling `uninstall` explicitly guards against exactly this (upstream #476); `--help` is skipped as an unknown flag and the already-up-to-date branch falls into `post_update_rewire`. **`lean-ctx update` is a standing no-go command; upgrades happen by rebuilding from a newer tag.**

**Pin execution record.** Tag `v3.9.12` = commit `54e0a66bcbb9a6695e45848d3ea97a491a0b5275`; `cargo build --release --locked` (rustc 1.97.1) — the same command, features, and lockfile the upstream release CI uses, with the in-tree `[patch.crates-io]` picked up automatically. Sandbox-first verification (throwaway `HOME` + data dir): version/help/MCP-stdio all correct, write-diff showed zero escapes — and demonstrated the MCP server self-installs its skill files into `HOME` at every startup (they track the binary). Installed sha256 `dba8532b61c46c3a4411721e22373362015c6259bd3b1237696df20d9bd4678a`; release binary retained as `lean-ctx-3.9.12-release.bak`. Update check disabled in both config files — the split-brain is real and source-confirmed: the MCP server (non-standard `LEAN_CTX_DATA_DIR`) reads `~/.config/lean-ctx/config.toml` while hooks and plain CLI resolve legacy `~/.lean-ctx/config.toml` — plus `LEAN_CTX_NO_UPDATE_CHECK=1` in the MCP env (presence-only, source-confirmed guard). The auto-update LaunchAgent is absent and can only be installed by an explicit flag or an interactive "y" — the pin cannot be silently undone.

**Evidence the floating risk was live, not theoretical:** the binary had self-updated 3.5.14 → 3.9.12 at 01:09 the same morning (prior-version backup found on disk).

**Collateral decisions (owner, per-item):** shell-level rewire removed (`.zshrc` blocks stripped, `.zshenv`/`.bashenv` deleted — one interception layer, the auditable settings.json hooks, instead of two); global CLAUDE.md block restored to the chosen Context Runtime text; the 7-class hook set kept. Build checkout retained at `~/Development/vendor/lean-ctx` for future rebuilds and audits.
