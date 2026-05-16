---
status: shipped
supersedes: []
superseded_by: null
related: []
---

# Workflow — PR cadence: one cohesive squash PR per sprint, opened only when the sprint's gate has fired

One squash PR per sprint, opened only when the sprint's pre-committed gate has fired. No mid-sprint PRs — even when a sub-phase looks clean enough to ship in isolation. Rationale: this is a solo portfolio project; the audience is async readers reviewing the repo history later (recruiters, collaborators, future-me), not synchronous reviewers approving incremental diffs. A single PR per sprint with a coherent narrative — design doc → grilling → /tdd cycles → /cso/codex review → /qa → squash → merge — reads cleanly six months from now. A churn of 5–10 mid-sprint PRs forces the reader to reconstruct the arc from PR metadata that nobody wrote with that audience in mind. The downside (one big diff, less bisect granularity) is bounded by gstack discipline: each /tdd cycle is its own commit on the feature branch, the squash preserves the *story* in the PR body, and the in-branch commit log is still bisectable for post-merge regression hunts.

Supersedes: the implicit PR-A / PR-B split from `/plan-eng-review` CQ2 (issue #25) — under this rule, both stop being separate PRs and become sub-phases of the same sprint PR. The feature branch for issue #25 stays open until the rest of the sprint's gate fires.
