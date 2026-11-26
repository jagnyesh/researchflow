---
sprint: null
date: 2026-11-25
status: accepted
supersedes: []
superseded_by: null
related: [0039-formal-family-history-gender-two-bound-age.md, 0036-formal-criteria-build-or-fail.md, 0035-formal-age-cohorts-living-only.md]
---

# Inclusive age phrasings build inclusive bounds, and negated ages still fail (#431)

**Problem.** `SQLGenerator._parse_age_bound` (`app/utils/sql_generator.py`) reads one age comparison from a [criterion concept](../../CONTEXT.md)'s details. [ADR 0039](0039-formal-family-history-gender-two-bound-age.md) uses it for each side of a two-bound age. Issue #431 listed phrasings it misreads. A direct call to `_parse_age_details` on `c905b87` gave these results:

| Details | Built | Meant |
|---|---|---|
| `65 and over`, `18 and above`, `65 years and over` | `> 65`, `> 18`, `> 65` | `>=` |
| `18 and under` | `< 18` | `<= 18` |
| `=> 65`, `=< 50` | `> 65`, `< 50` | `>= 65`, `<= 50` |
| `under 18 or 65 and over` | `(< 18 OR > 65)` | `(< 18 OR >= 65)` |
| `65 and older`, `65 and up`, `65+`, `≥ 65`, `65 or more`, `50 or less`, `≤ 50` | fails | `>=` or `<=` |
| `no older than 65`, `not younger than 65`, `no more than 50` | fails | `<= 65`, `>= 65`, `<= 50` |

The first four rows count the wrong cohort without an error. `65 and over` drops every patient who is exactly 65. The rows that fail are honest under [ADR 0036](0036-formal-criteria-build-or-fail.md), but they refuse common wording. The issue's table, filed before ADR 0039, showed the negated rows building the inverted comparison. ADR 0039 made every negated age fail.

**Decision.**

- **A trailing inclusive word builds an inclusive bound.** `N and over`, `N and above`, `N and older` and `N and up` build `>= N`. `N and under`, `N and below` and `N and younger` build `<= N`.
- **Inclusive symbols and `or` forms build inclusive bounds.** `≥ N`, `=> N`, `N+`, `N or more`, `N or greater` and `N or higher` build `>= N`. `≤ N`, `=< N`, `N or less`, `N or fewer` and `N or lower` build `<= N`. `N+` means a `+` right after the number.
- **A single-number phrase that names both directions fails.** The parser used to take the first comparison family it found, in a fixed order. A phrase such as `under 65 and over` has no safe reading, so it fails.
- **A two-bound age reads the same inclusive forms after a bare first number.** ADR 0039 let `or older`, `or over`, `or above`, `or younger`, `or under` and `or below` belong to a first bound that has no comparison before its number. That list is now every form that follows a number, from one constant shared with the single-bound parser. `18+ and under 65`, `18 and over and under 65` and `18 or more and under 65` build `(>= 18 AND < 65)`.
- **A negated age still fails.** ADR 0039 stands. This decision amends #431's acceptance table: `no older than 65`, `not over 65`, `no less than 65`, `not younger than 65` and `no more than 50` fail with an error instead of building `<=` or `>=`. The researcher writes `<= 65` instead.
- **Strict forms keep their meaning.** `over 65`, `older than 65`, `> 65`, `senior over 65`, `under 50` and `< 50` still build `>` or `<`.

**Considered options.**

- *Parse a closed list of negated comparatives.* `no older than N` would build `<= N` through a carve-out that runs before `SQLGenerator._NEGATION`. More requests would build. A misread there reverses the bound's direction, which is worse than moving its boundary, and the extraction prompt asks the model for symbols such as `> 65`, so this wording is off-script. Failing tells the researcher how to rewrite it.
- *Only the issue's words.* `65 and up`, `or higher`, `or lower` and `or fewer` would keep failing. They are common wording, and no reading of them is strict.
- *Keep the check order for mixed phrases.* The diff would be smaller. A phrase naming both directions would then build whichever family the code checks first.
- *Keep ADR 0039's six suffixes for the first bound.* `under 18 or 65 and over` would build, because the new forms reach the second bound. `18+ and under 65` would still fail. Two lists for one idea is how `65 and over` came to read as `> 65` inside a two-bound age.

**Consequences.**

- Every newly parsed phrase is an age criterion, so ADR 0035's living-only filter applies to it.
- `= 65`, `exactly 65` and `aged 65` still fail, although the extraction prompt lists `=` as an age comparison. #431 leaves exact ages out of scope.
- `18 and under 65` fails. It reads both as `<= 18` followed by a stray `65` and as `>= 18 and < 65`, so failing is the safe reading. It failed before this change as well.
- A trailing `-`, as in `50-`, still fails, because it reads as a range dash.
- The ages in the extraction eval recording (`tests/eval/fixtures/extraction_recording.json`) use none of the new forms. They are symbols such as `> 65` and `>= 65 (seniors)`, `between` ranges, `< 18 or > 65`, and `50-59 years old`, so the eval gate reads them as before.
