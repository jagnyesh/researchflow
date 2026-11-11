---
sprint: null
date: 2026-11-11
status: accepted
supersedes: []
superseded_by: null
related: [0035-formal-age-cohorts-living-only.md, 0033-phenotype-estimate-counts-approved-sql.md]
---

# Every formal criterion concept becomes SQL or the request fails (#310)

**Problem.** `SQLGenerator.generate_phenotype_sql` (`app/utils/sql_generator.py`) builds the Formal Portal's phenotype SQL from extracted concepts. A concept is one typed term, such as `{type: "medication", term: "insulin"}`, that the Requirements Agent extracts from a criterion. The generator built SQL for condition, lab, gender and parseable age concepts and dropped every other concept with only a log line. A medication or procedure criterion next to a condition therefore vanished, and the cohort silently grew. #264 only caught a criteria list that built nothing at all. PR #358 (#310 slice 1) negated exclusion demographics but left the NULL rule unratified.

**Decision (owner, 2026-11-11).**

- **Every concept builds at least one predicate, or the generator raises.** The `ValueError` names the concept's type and never its term or details, which are PHI-adjacent. A concept type the generator doesn't know raises. So does a demographic it has no column for, such as race or postal code. An age phrase the parser can't read also raises. That last case amends ADR 0035, which kept such a request and dropped both the bound and the living filter. A condition, lab, medication or procedure concept whose term is blank or not a string also raises. A blank term builds `LIKE '%%'`, which matches every record.
- **A concept marked `excluded` inside an inclusion criterion raises.** The extraction prompt writes negation into `details`: inclusion "not on warfarin" becomes `{medication, warfarin, details: "excluded"}`. The generator ignored `details` and emitted `EXISTS warfarin`, the inverse of the request. A request now fails when the word `excluded` appears anywhere in the details of an inclusion concept, and the researcher uses the exclusion field instead. Inside an exclusion criterion the marker restates the list it's in, so the generator ignores it.
- **A medication concept that names a drug class raises.** The extraction prompt keeps a class as the term, such as `SSRIs` with details `drug class — …`. No prescription carries a class name, so an inclusion would count 0 and an exclusion would remove no one. A request fails when a medication concept's details say `drug class`, `drug-class` or `drug classes`, in either list.
- **Medication and procedure concepts get builders.** An inclusion emits `EXISTS` and an exclusion emits `NOT EXISTS`, each with a case-insensitive substring match:
  - medications against `sqlonfhir.medication_requests` on `medication_display` and `medication_text`, the gold set's signed-off insulin oracle columns;
  - procedures against `sqlonfhir.procedure_history` on `code_text`, `snomed_display` and `cpt_display`.
- **An excluded demographic keeps patients whose value is unknown.** PR #358's `(<predicate>) IS NOT TRUE` stands. An exclusion removes patients known to match, as `NOT EXISTS` already does for conditions. A patient with a NULL `birth_date` stays in a cohort that excludes `Age < 18`. The same patient drops out of a cohort that includes `Age >= 18`.
- **An excluded age still makes the cohort living-only.** ADR 0035 applies to exclusions unchanged. The generator computes age from today, so a patient who died at 10 reads as 76 and would wrongly survive "exclude under 18". ADR 0035 says the views have no age-at-death column. That is not quite right: `patient_demographics.deceased_date` is set for all 81 deceased patients on the local corpus, so age at death could be computed. No request has asked for it, so the generator keeps one age definition, and removing the deceased is the consistent reading. One local deceased patient died under 18.
- **A multi-concept exclusion criterion stays negated one concept at a time.** The extractor keeps no AND or OR between the concepts of one criterion, so the generator can't tell "no cancer or stroke" from "males over 65". Today's reading removes a patient who matches any concept, which is right for the first and too broad for the second. [#449](https://github.com/jagnyesh/researchflow/issues/449) carries the connective.

**Considered options.**

- *Guard each criterion, not each concept.* This is the issue's literal wording. It still drops a race concept next to a diabetes concept in the same criterion, and the cohort counts every diabetic.
- *Ship the guard and move the builders to their own issue.* Every formal request that mentions a drug or procedure would fail until then. The builders are small, and the gold set already has a signed-off medication oracle to check them against.
- *Exclusions drop unknowns (`NOT (<predicate>)`).* This is the safer error for a protective exclusion, such as minors under an IRB protocol. It also makes demographic exclusions disagree with condition exclusions. The local corpus has 0 NULL genders and 0 NULL birth dates out of 366 patients, so the choice changes no count today.
- *Negate a concept marked `excluded`.* That would do what the researcher meant when the marker is right. It would also key cohort semantics on a free-text word the LLM writes.

**Consequences.**

- Requests that used to run with a dropped criterion now fail at the phenotype step, and G2 shows the estimate as unavailable. Common age phrasings such as `65+` and `65 and older` fail until [#431](https://github.com/jagnyesh/researchflow/issues/431) teaches the parser. A failed request is visible, and the old wrong cohort was not.
- The researcher doesn't see why a request failed. The phenotype node logs only the exception type and a reference, so G2 shows `ValueError (ref: …)` for every one of these failures. [#454](https://github.com/jagnyesh/researchflow/issues/454) shows the generator's reason, which never carries criterion text.
- Name matching still misses some terms without failing. A class term with no `drug class` marker, such as a bare `statins`, matches by name and may match nothing. So does an encounter-type procedure such as `ICU admission`. [#455](https://github.com/jagnyesh/researchflow/issues/455) covers class expansion and encounters.
- Some details still change the cohort without being read: `family history`, a negated gender, and an age with two bounds. [#456](https://github.com/jagnyesh/researchflow/issues/456) tracks them.
- 39% of `medication_requests` rows (7,863 of 20,116) name their drug through `medicationReference` and have no display or text. Until [#337](https://github.com/jagnyesh/researchflow/issues/337) resolves that reference, a medication inclusion undercounts and a medication exclusion keeps some patients who are on the drug. The gold set's insulin oracle has the same gap, so the case scores the builder, not the reference.
- Neither builder filters by date. A medication criterion matches any active, completed or on-hold request on record. A procedure criterion matches any completed or in-progress procedure. The view definitions apply both status filters.
- The #242 predicate checker (`tests/eval/formal_predicates.py`) gains a `("medication", "has" | "lacks", term)` template over the oracle's two columns. The gold case `diabetes_mellitus_not_on_insulin` loses its `expected_fail`. On the local corpus it now passes with 31 patients, its hand-verified count, and formal Pass@1 on the replay goes from 0.60 to 0.70 (7/10).
- ADR 0035's `test_an_unparseable_age_adds_no_living_filter` becomes `test_an_unparseable_age_fails_the_request`.
