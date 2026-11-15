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

- **A condition concept marked `family history` fails, in either list.** The extraction prompt writes `details: "family history"` so that downstream code can query FamilyMemberHistory, the FHIR resource for a relative's condition. `sqlonfhir` has no view over FamilyMemberHistory, and the local HAPI server holds 0 such resources. An inclusion built on the patient's own condition selects the wrong patients. An exclusion built the same way removes the wrong patients. A request fails when a condition concept's term or details say `family history` (also with a hyphen or underscore, or as `family medical history` or `family hx`), `maternal history`, `paternal history` or `first-degree relative`, in any case. `familial` and `FH` don't count, because they also name a diagnosis of the patient's own, as in familial hypercholesterolemia.
- **A gender concept builds only when it names exactly one value and isn't negated.** The generator reads the term and the details together. It builds `p.gender = :v` when they name exactly one of `male` and `female`, as whole words in the singular or plural, and contain no negation word. Anything else fails: `not male`, `male or female`, `non-binary`, `anything but male`.
- **A negated age fails.** That covers every age phrase, two-bound or not: `not over 65` used to build `> 65`, and `excluding those under 18 or over 65` built the patients it meant to exclude. The researcher writes the age as an exclusion criterion instead.
- **Gender and age share one list of negation words.** The list is a denylist, `SQLGenerator._NEGATION`:
  - the words `not`, `no`, `non`, `but`, `never`, `nobody`, `none`, `cannot`, `minus`, `besides`, `without`, `ineligible` and `w/o`;
  - the phrases `other than`, `aside from`, `rather than` and `instead of`;
  - any word that starts with `except`, `exclu`, `omit`, `disqualif` or `remov`, the abbreviation `excl`, and any `n't` with a straight or curly apostrophe.

  `excluded` isn't on the list, because inside an exclusion criterion it restates the list it's in (ADR 0036).
- **An age with two bounds builds both, joined the way the details join them.** When the details hold exactly two numbers, the generator splits them at the one `and` or `or` between the numbers and reads each side as a single bound. An `or older`, `or over`, `or above`, `or younger`, `or under` or `or below` right after the first number belongs to the first bound when no comparison comes before that number, as in `18 or older and under 65`. In `under 18 or over 65` the first bound already has `under`, so `or over` starts the second bound.
  - One side must be a lower bound (`>` or `>=`) and the other an upper bound (`<` or `<=`). The generator compares them in whole years of age, so `> 18` admits 19 and up, and `< 65` admits 64 and down.
  - `and` builds `(age > :lo AND age < :hi)` when at least one whole year meets both bounds. `>= 18 and <= 18` builds the 18-year-olds, and `> 18 and < 19` fails.
  - `or` builds `(age < :lo OR age > :hi)` when at least one whole year meets neither bound. `under 18 or over 18` builds everyone but the 18-year-olds, and `<= 17 or >= 18` fails.
  - The operators keep their strictness as written. `>= 18 and <= 65` stays inclusive.
- **Any other age with two or more numbers fails.** That covers inverted bounds such as `> 65 and < 18`, which counts no one. It also covers bounds such as `> 18 or < 65`, which count everyone with a birth date, and phrasings with no connective, such as `18 to 65`. The parser used to take the first number. `between X and Y` is unchanged, because the generator reads it before it counts numbers.
- **The fresh-context review widened four rules before merge.** The first draft had no age negation, a shorter negation list, a family-history match on details only, and a shape check that compared the numbers as written. Each still let a close variant build the wrong cohort, such as `exclude males` building `male`, so the owner approved the wider rules above. A second pass found more off-script variants, such as `omit males` and `nobody over 65`, and the owner chose to extend the denylists.

**Considered options.**

- *Build the negation and the list.* `not male` would build `p.gender <> 'male'` and `male or female` would build `p.gender IN ('male', 'female')`. More requests would build. Cohort meaning would then rest on a negation word the LLM writes into free text, which ADR 0036 declined to do for `excluded`. On the local corpus every patient is `male` or `female`, so `male or female` filters nothing and failing tells the researcher to drop it.
- *Build `and`, fail `or`.* The researcher could write an outside-the-range age as an exclusion of `between 18 and 65`. The `or` form is a small extension of the same split, so the generator builds it.
- *Build two bounds without the shape check.* A cohort of no one or of everyone would run without an error. The check is a few comparisons.
- *An allowlist instead of the denylists.* An age or gender would build only when its details hold nothing beyond value words, comparison words and known filler. That shape survives wording the lists don't name. It also fails the extraction prompt's own example `< 18 (pediatric)` unless the filler words are chosen with care, so it gets an issue of its own, [#517](https://github.com/jagnyesh/researchflow/issues/517). The denylists catch the prompt's canonical forms and every variant the review reproduced.
- *Build a FamilyMemberHistory view now.* It would match 0 patients locally, and a view is a new ViewDefinition plus a materialization, outside this change.

**Consequences.**

- Requests with these phrasings now fail at the phenotype step instead of counting the wrong cohort. G2 shows the estimate as unavailable with `ValueError (ref: …)` until [#454](https://github.com/jagnyesh/researchflow/issues/454) shows the reason. Each error names only the concept's type.
- An age that has two numbers for another reason now fails, such as `> 65 within the last 6 months`. The parser used to build `> 65`.
- A phrase with a negation word fails even where the word negates nothing. `over 18 but under 65` means both bounds, `no older than 65` means `<= 65`, and a gender with details `no restriction` filters nothing. Each now fails with an error, and none builds a wrong cohort.
- Single-bound age phrasings such as `65+` still fail, which is [#431](https://github.com/jagnyesh/researchflow/issues/431). Lab thresholds are still ignored, which is [#297](https://github.com/jagnyesh/researchflow/issues/297).
- A two-bound age is an age criterion, so ADR 0035's living-only filter applies. An excluded two-bound age keeps a patient whose birth date is NULL, per ADR 0036.
- A family-history criterion can't run until a FamilyMemberHistory view exists, and the local corpus has none to count. No issue tracks that view yet.
