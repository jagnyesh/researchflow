---
sprint: null
date: 2026-11-18
status: accepted
supersedes: []
superseded_by: null
related: [0028-sprint-6-7-exploratory-llm-sql-synthesis.md, 0035-formal-age-cohorts-living-only.md, 0036-formal-criteria-build-or-fail.md, 0040-extraction-eval-scores-concepts-as-the-generator-reads-them.md]
---

# Predicate survival is checked in the SQL's AST on both paths, and #142 closes on four additions (#142)

**Problem.** #142 asks that every demographic predicate a request states, such as "female" or "under 50", appear in the SQL that comes out. A request that says "women under 50" must not quietly become a cohort of everyone. The issue was written while #51 (formal) and #76 (exploratory) were open. Both are closed now.

Most of the formal half already exists under other issue numbers. The formal gold set (`tests/eval/formal_cases.py`, #239 and #241) holds 10 approved cases. `tests/eval/formal_predicates.py` (#242) reads each predicate from the SQL's abstract syntax tree (AST) with sqlglot and asserts the exact set. Expected failures use a strict `xfail`. `tests/eval/test_formal_predicates.py` runs without an API key or database in CI's base job.

A read of `main` at `bc230e5` on 2026-11-18 found four gaps:

1. The formal set has no gender-only case.
2. The formal checker has no template for an age range. The generator already emits `EXTRACT(YEAR FROM AGE(...)) BETWEEN :age_lo AND :age_hi`, but the checker accepts one placeholder per predicate and reports the range as unrecognized. So `hypertension_aged_50_to_60` is an expected failure because of the checker, not the generator.
3. The exploratory eval (`tests/eval/harness.py`) checks only that a count equals a same-run oracle count. On CI's 5-patient seed several cases collapse to 0 = 0, so a dropped predicate can pass. The formal checker can't be reused: it rejects joins, expects bound parameters, and doesn't know the exploratory age form `p.birth_date::date > CURRENT_DATE - INTERVAL '65 years'`.
4. Neither path reports how often predicates survive.

**Decision (owner, 2026-11-18).**

- **#142 closes on these four additions.** Every other criterion is already met or moot. The PR body maps each original criterion to where it is met.
- **A gender-only formal case, `women_with_hypertension`.** The request is "Female patients with hypertension", with the inclusion criteria `female` and `hypertension`. The required predicates are `("gender", "=", "female")` and `("condition", "has", "hypertension")`. There's no living filter: [ADR 0035](0035-formal-age-cohorts-living-only.md)'s living-only rule applies to age cohorts, and the generator emits none here. The oracle is `p.gender = 'female'` plus the three-column hypertension match. Its `seed_count` is 2, so it isn't vacuous in CI. The owner signed it off on 2026-11-18.
- **Only the new case is recorded.** `record()` re-records every approved case, which would make about 22 billed calls and rewrite the 10 existing recordings. An `only=` option records the one case, about 2 calls, and merges it into `tests/eval/fixtures/recorded_requirements_formal.json`. The other entries stay byte-identical. The 2026-11-18 run recorded the case for $0.023872, and the case passed on the local corpus with 20 patients. The suite's pinned case counts in `test_formal_replay.py` and `test_formal_scorer.py` go from 10 to 11, with the owner's approval.
- **The formal checker reads an age range.** A `BETWEEN` template maps both bound values to `("age", "between", (lo, hi))`. The `expected_fail` on `hypertension_aged_50_to_60` is removed. This is a changed expectation, approved by the owner. The two hba1c expected failures stay.
- **The exploratory path gets its own AST check** in `tests/eval/exploratory_predicates.py`. It covers gender and age only; the oracle already checks conditions, whose column sets vary from case to case. A predicate survives only as a top-level `WHERE` conjunct on a `patient_demographics` column, with table aliases resolved across joins. An age maps to a canonical predicate only where the form is exact for whole-year ages:
  - `birth_date <= CURRENT_DATE - INTERVAL 'N years'` is `("age", ">=", N)`.
  - `birth_date > CURRENT_DATE - INTERVAL 'N years'` is `("age", "<", N)`.
  - `EXTRACT(YEAR FROM AGE(...)) op N` is `("age", op, N)`.

  The `<` and `>=` forms on `birth_date` are wrong by one day, for people whose birthday is today, so they don't count as surviving. The 8 scored cases whose request states a gender or an age carry required predicates that follow their approved oracles, so "over 18" is `("age", ">=", 18)`. A test without a key or database asserts that each case's required predicates are a subset of what the recorded Sonnet SQL (`tests/eval/fixtures/recorded_sql_claude-sonnet-4-6.json`) carries.
- **The predicate survival rate** is the share of cases with a required-predicate list where none of the required predicates is missing from the SQL. Expected-fail cases stay in the denominator, as they do for Pass@1. An extra predicate doesn't lower survival, because survival measures drops. On the formal path an extra predicate already fails Pass@1. Each path prints one line, `Predicate survival: 0.xx (n/m)`: the formal one in `formal_record.summary()`, the exploratory one in `run_record.py` from `run_eval`'s summary. No threshold is set. Thresholds belong to #244.

**Rejected.**

- **A matched-count-below-total check (`M < N_total`).** Both paths already require the count to equal a same-run oracle count, and both now read each stated predicate from the AST. That catches a dropped predicate even when the counts can't tell it apart, so `M < N_total` adds nothing.
- **Race, ethnicity and language predicates.** No `sqlonfhir` view has those columns (`app/sql_on_fhir/view_definitions/`). The formal generator fails a race criterion instead of dropping it ([ADR 0036](0036-formal-criteria-build-or-fail.md), pinned in `tests/sql_on_fhir/test_sql_generator_concept_guard.py`). They are out of scope and get no follow-up issue until a view adds a column.
- **Reusing the formal checker on the exploratory path.** Its exact-shape templates are what make it strict on generated SQL. Loosening them for model-written SQL would weaken the formal check.
- **Checking conditions on the exploratory path.** Model-written condition matches vary in their column sets, so a template would track wording, not survival.

**Consequences.** Both paths now fail a case when a stated gender or age disappears, whatever the corpus size. The exploratory check reads recorded SQL, so it guards the recording, not the live model. A prompt regression shows up only after a re-record. The exploratory age mapping is deliberately narrow: a correct but unlisted form, such as `AGE(birth_date) < INTERVAL '65 years'`, counts as not surviving until a template is added.
