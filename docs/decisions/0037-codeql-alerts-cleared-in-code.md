---
sprint: null
date: 2026-11-13
status: accepted
supersedes: []
superseded_by: null
related: [0012-sprint-6-1-phase-2-3-input-validation.md, 0028-sprint-6-7-exploratory-llm-sql-synthesis.md, 0029-api-error-path-phi-safe-500s.md, 0030-viewdefinition-write-admin-only.md]
---

# CodeQL alerts under app/ are cleared in code, and /sql_query is removed (#468)

**Problem.** CodeQL, GitHub's static analyzer, had 24 open alerts under `app/` on 2026-11-13. They fall into three rules: path injection, SQL injection, and clear-text logging of sensitive data. The CodeQL PR check isn't required and is usually red, so it catches nothing. [#469](https://github.com/jagnyesh/researchflow/issues/469) makes it required once `app/` has no open alerts. Some alerts are real flaws:

- `FileStorageService` (`app/services/file_storage.py`) joins any `request_id` and `filename` onto the delivery directory. The extraction agent saves `f"{element_name}.csv"`, and `element_name` comes from the LLM's reading of the researcher's text.
- `FileContextStore` (`app/mcp/store.py`) writes `<request_id>.json` for a body `request_id` from `POST /mcp/context`. An absolute or `../` value writes any `.json` file ([#223](https://github.com/jagnyesh/researchflow/issues/223)).
- `POST /sql_query` runs any `SELECT` on the HAPI database as its owner, for any signed-in role ([#234](https://github.com/jagnyesh/researchflow/issues/234)).
- `SQLonFHIRAdapter.execute_sql` logs its bound parameters at debug level. On the extraction path those include up to 1,000 patient IDs per query.

Other alerts are false positives. `ViewDefinitionManager._path_for` already holds names to a strict regex (#177), and two `SQLGenerator` debug lines log SQL that holds only placeholders.

**Decision (owner, 2026-11-13).**

- **Guards take a shape CodeQL recognizes, so alerts clear in code, not by dismissal.** A path guard resolves the joined path with `os.path.realpath` and checks that it starts with the base directory plus a separator. An existing name regex stays in front of it. A symlinked entry is refused even when it points inside the directory, because a resolved path would let `delete` remove the file the link points at. The false positives in `view_definition_manager.py` get the same guard.
- **`FileStorageService` and `FileContextStore` reject a name that isn't one safe path component.** A write raises `ValueError`. A read returns `None` or an empty list, so a download returns 404. Neither class renames a file to make it safe.
- **`POST /sql_query` is removed.** Its route, its request schema and its audit route-map entry go. Tests that used it as their sample PHI route move to another one. No route now passes caller SQL straight to the HAPI database. A reviewer can still replace the phenotype SQL through `POST /approvals/{id}/respond`, which has no role check ([#248](https://github.com/jagnyesh/researchflow/issues/248)); extraction then runs it (traced in code, not exercised).
- **Logs carry no bound-parameter values and no generated SQL text.** A log line keeps its purpose through parameter names, counts and clause counts. The SQL a researcher's request runs stays reviewable in its approval record.

**Considered options.**

- *Dismiss the false positives.* Each dismissal is an owner action that changes the repo's security record. A refactor that changes an alert's fingerprint reopens it, and once #469 lands that blocks a PR. Four lines of guard cost less than that.
- *Sanitize unsafe names.* Delivery would never fail, but a file would no longer match its data element's name, and two elements could map to one file.
- *Keep `/sql_query` behind an admin role and the read-only `rf_readonly` role.* That narrows the hole, but CodeQL still sees request text reaching `text()`, so alerts 58 and 59 would need a "won't fix" dismissal. No portal, script or agent calls the route.
- *Keep SQL text in debug logs.* It's convenient when debugging, but CodeQL treats the patient-ID column name as sensitive, so every such line stays flagged.

**Consequences.**

- A data element whose name contains a path separator or `..` gets no CSV instead of one written outside its delivery directory. The extraction agent's `_format_data` catches the `ValueError` with a broad `except`, so it also skips the elements after that one and still lists every file in its result. A `/` in the name already failed that way on main, through an `OSError`; a follow-up makes the failure visible.
- Debug logs no longer show the generated SQL. Read it from the approval record or the phenotype step's state.
- README and the API, architecture and HIPAA docs drop `/sql_query`. ADR 0012 used it as its first validated route; that ADR's validation framework is unchanged.
- The CodeQL run on this PR shows whether each guard is recognized. An alert it still reports goes to the owner as a proposed dismissal with the guard's `file:line`.
