---
sprint: null
date: 2026-11-14
status: accepted
supersedes: []
superseded_by: null
related: [0036-formal-criteria-build-or-fail.md, 0035-formal-age-cohorts-living-only.md]
---

# Family history fails, gender takes one value, and two-bound ages build both bounds (#456)

**Problem.** `SQLGenerator.generate_phenotype_sql` (`app/utils/sql_generator.py`) builds the Formal Portal's phenotype SQL from extracted [criterion concepts](../../CONTEXT.md). [ADR 0036](0036-formal-criteria-build-or-fail.md) made every concept build a predicate or fail the request. It left five phrasings that build a predicate with the wrong meaning, so the cohort changes without an error:

| Concept | Built | Meant |
|---|---|---|
| condition, details `family history` | the patient's own condition | a family member's condition |
| gender, details `not male` | `p.gender = 'male'` | not male |
| gender, details `male or female` | `p.gender = 'female'` | either |
| age, details `> 18 and < 65` | `> 18` only | both bounds |
| age, details `under 18 or over 65` | `>= 18` | outside 18 to 65 |

The age parser took the first number in the details and the first comparison word it recognized. In `under 18 or over 65` it read `or over` as the inclusive `18 or over`.

**Decision (owner, 2026-11-14).**

- **A condition concept marked `family history` fails, in either list.** The extraction prompt writes `details: "family history"` so that downstream code can query FamilyMemberHistory, the FHIR resource for a relative's condition. `sqlonfhir` has no view over FamilyMemberHistory, and the local HAPI server holds 0 such resources. An inclusion built on the patient's own condition selects the wrong patients. An exclusion built the same way removes the wrong patients. A request fails when a condition concept's details match `family history`, case-insensitive, with any whitespace between the words.
- **A gender concept builds only when it names exactly one value and isn't negated.** The generator reads the term and the details together. It builds `p.gender = :v` when they name exactly one of `male` and `female`, as whole words, and contain none of `not`, `non`, `no`, `except`, `excluding`, `other than` or `without`. Anything else fails: `not male`, `male or female`, `non-binary`. `excluded` isn't on the list, because inside an exclusion criterion it restates the list it's in (ADR 0036).
- **An age with two bounds builds both, joined the way the details join them.** When the details hold exactly two numbers, the generator splits them at the one `and` or `or` between the numbers and reads each side as a single bound. An `or older`, `or over`, `or above`, `or younger`, `or under` or `or below` right after the first number belongs to the first bound when no comparison comes before that number, as in `18 or older and under 65`. In `under 18 or over 65` the first bound already has `under`, so `or over` starts the second bound.
  - `and` builds `(age > :lo AND age < :hi)` when one side is a lower bound (`>` or `>=`), the other an upper bound (`<` or `<=`), and the lower number is below the upper one.
  - `or` builds `(age < :lo OR age > :hi)` when one side is an upper bound, the other a lower bound, and the upper bound's number is below the lower bound's.
  - The operators keep their strictness as written. `>= 18 and <= 65` stays inclusive.
- **Any other age with two or more numbers fails.** That covers inverted bounds such as `> 65 and < 18`, which counts no one. It also covers bounds such as `> 18 or < 65`, which count everyone with a birth date, and phrasings with no connective, such as `18 to 65`. The parser used to take the first number. `between X and Y` is unchanged, because the generator reads it before it counts numbers.

**Considered options.**

- *Build the negation and the list.* `not male` would build `p.gender <> 'male'` and `male or female` would build `p.gender IN ('male', 'female')`. More requests would build. Cohort meaning would then rest on a negation word the LLM writes into free text, which ADR 0036 declined to do for `excluded`. On the local corpus every patient is `male` or `female`, so `male or female` filters nothing and failing tells the researcher to drop it.
- *Build `and`, fail `or`.* The researcher could write an outside-the-range age as an exclusion of `between 18 and 65`. The `or` form is a small extension of the same split, so the generator builds it.
- *Build two bounds without the shape check.* A cohort of no one or of everyone would run without an error. The check is a few comparisons.
- *Build a FamilyMemberHistory view now.* It would match 0 patients locally, and a view is a new ViewDefinition plus a materialization, outside this change.

**Consequences.**

- Requests with these phrasings now fail at the phenotype step instead of counting the wrong cohort. G2 shows the estimate as unavailable with `ValueError (ref: …)` until [#454](https://github.com/jagnyesh/researchflow/issues/454) shows the reason. Each error names only the concept's type.
- An age that has two numbers for another reason now fails, such as `> 65 within the last 6 months`. The parser used to build `> 65`.
- Single-bound age phrasings such as `65+` still fail, which is [#431](https://github.com/jagnyesh/researchflow/issues/431). Lab thresholds are still ignored, which is [#297](https://github.com/jagnyesh/researchflow/issues/297).
- A two-bound age is an age criterion, so ADR 0035's living-only filter applies. An excluded two-bound age keeps a patient whose birth date is NULL, per ADR 0036.
- A family-history criterion can't run until a FamilyMemberHistory view exists, and the local corpus has none to count. No issue tracks that view yet.
