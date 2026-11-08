# Lane brief template

Fill every `<…>`. The brief is the lane's only context, so state the why and the limits; don't restate the issue.

```
Issue #<n>: <title> — <issue url>
Tier: <Low|Medium|High> (<the paths that set it>; docs/DAILY_DEV_WORKFLOW.md §1)
Why: <one or two lines on what breaks for whom, from the issue>

Setup, before editing:
- Branch <feat|fix>/<n>-<slug>, cut from origin/main. If you aren't on it:
    git fetch origin main && git switch -c <feat|fix>/<n>-<slug> origin/main
- If there's no .venv, make an isolated one. Never a bare `uv pip sync`, which can rewrite a
  shared env the shell has activated:
    unset VIRTUAL_ENV && uv venv && uv pip sync --python .venv/bin/python config/requirements.lock \
      && uv pip install --python .venv/bin/python -c config/requirements.lock -r config/requirements-dev.lock
- If there's no .env: ln -s <main checkout>/.env .env
  A Streamlit dashboard also needs a copy of <main checkout>/dev.db.

Do:
- Low: /tdd on the issue's acceptance criteria, then /validate-and-ship.
- Medium: the same, and the PR body carries a 5–10 line intent block (what, why, constraints,
  non-goals; §1).
- High: /grill-with-docs with the user first. Write the ADR as docs/decisions/NNNN-<slug>.md
  (frontmatter and numbering per docs/decisions/INDEX.md, with entries in both of its
  sections), not docs/adr/ or DECISIONS.md. Stop and get the user's OK before /tdd. The
  reviewer then checks the diff against that ADR.

Files: stay in <predicted files>. Another lane owns <other lanes' files>. Stop and report
before editing a file outside your set or one another lane owns. If the file you need is on
§1's High list, or the change turns out to be High-category, stop: the tier changes, and a
High lane starts over with /grill-with-docs.

Never:
- Run tests/test_hybrid_runner_freshness.py, tests/test_transpiler_correctness.py,
  tests/test_custom_path_regression.py, tests/test_sqlonfhir_integration.py or
  scripts/materialize_views.py. They rebuild or write the live :5433 views and Redis. Editing
  them is fine. If your evidence needs one run, stop and ask the user. Pass this list to
  your reviewer.
- Make a billed LLM call without the user's OK for that run. Keyless runs use
  `ANTHROPIC_API_KEY= LANGCHAIN_TRACING_V2=false LANGSMITH_TRACING=false` (an unset key gets
  refilled from .env).
- Print a secret, or put real patient or person data in a test, log, commit or screenshot.
- Bypass git hooks, or rebase or force-push after the attestation. Update a stale PR by
  merging origin/main in (validate-and-ship Step 7.4).

Run pytest one file per process.

Done: /validate-and-ship ran to its end. A standing-rule PR is merged. A human-merge PR is
green and attested at its head, and you've handed the user the merge command. Then stop.
- If a merge is refused because the branch is out of date, or you're asked to update it:
  merge origin/main in, then run validate-and-ship Step 7.4. If any 7.4 check fails, do a
  fresh Step 2 review and post a new Step 7 attestation instead. Then re-run Step 8: a
  standing-rule PR merges itself, and a human-merge PR hands the user a fresh command.
- After a merge from a worktree, `gh pr view <n>` confirms both the merge and the remote
  branch delete, because `--delete-branch` can skip the delete there.
- If the user asks you to hold (directly, or relayed by the coordinating session), hold until
  the user says go.
```
