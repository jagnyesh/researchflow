---
sprint: null
date: 2026-11-09
status: accepted
supersedes: []
superseded_by: null
related: [0033-phenotype-estimate-counts-approved-sql.md]
---

# Formal cohorts with an age criterion count living patients only (#403)

**Problem.** `SQLGenerator.generate_phenotype_sql` (`app/utils/sql_generator.py`) never filtered on `patient_demographics.deceased`. The Formal Portal's gold set (`tests/eval/formal_cases.py`) counts its age cases as living-only, which the repo owner signed off on 2026-11-07 ([#241](https://github.com/jagnyesh/researchflow/issues/241)). Each of those cases failed. On the local corpus, `female_over_65_diabetes_mellitus` selected 13 patients against the oracle's 6.

**Decision (owner, 2026-11-09).** A query gets `p.deceased IS NOT TRUE` exactly when the generator emits an age predicate. That covers age criteria in inclusions and in exclusions, with or without a time period. The generator computes age from today (`AGE(CURRENT_DATE, p.birth_date::date)`), and that age means nothing for a patient who has died. `IS NOT TRUE` keeps a patient whose flag is NULL. A request with no age predicate keeps the deceased, and so does an age criterion the generator can't parse.

**Considered options.**
- Living-only on every query is what #403 first asked for. The two non-age gold cases, `hypertension_without_diabetes_mellitus` and `diabetes_mellitus_and_hypertension`, have signed-off oracles that include the deceased. Every-query filtering would fail both and raise Pass@1 only to 0.30, unless the owner re-approved those two cases.
- An age measured at death, or at a reference date, would give dead patients a real age. The views have no such column, and no request has asked for one.

**Consequences.**
- The decision accepts an inconsistency. A request without an age criterion still counts deceased patients. "Female patients with diabetes" includes the dead, and "female patients over 18 with diabetes" doesn't.
- An age phrase that the generator can't parse, such as `"65 or older"`, gets neither the age bound nor the living filter today. `test_an_unparseable_age_adds_no_living_filter` pins this. The parser fix belongs to [#404](https://github.com/jagnyesh/researchflow/issues/404), and it brings both. The owner hasn't ruled on this case yet.
- Formal Pass@1 on the gold-set replay goes from 0.20 to 0.50 (5/10). Three cases lose their `expected_fail`. `hypertension_65_or_older` and `hypertension_aged_50_to_60` keep one other reason each.
- The extraction agent runs the approved phenotype SQL, so an age cohort's extracted rows are living-only too. The estimate already counts that SQL (ADR 0033).
- The `deceased` column is `deceased.exists()` in `patient_demographics.json`. A FHIR `deceasedBoolean: false` would read as deceased. On the local corpus, every one of the 81 deceased patients has a death date, so this case doesn't occur there yet.

**Non-goal.** A researcher can't request a deceased or mortality cohort yet. No criterion type selects on `deceased`, and an age criterion always removes the dead.
