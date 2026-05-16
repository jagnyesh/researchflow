---
sprint: 6.3
date: 2026-05-14
status: shipped
supersedes:
  - 0019-sprint-6-3-duckdb-fhir-verdict-go-pathling.md
superseded_by: null
related: []
---

# Sprint 6.3 — VERDICT REVISION 2026-05-14: GO sqlonfhir (Q1-refinement applied)

Same-day revision. Original verdict "GO Pathling" was reached by strict enforcement of the 3/3 row-count gate. User-directed re-examination surfaced that the gate's premise was broken: `procedure_history`'s 0-row state under the original view-def is an engine-independent bug (see #41), not a sqlonfhir-specific failure. Pathling produces the same 0 against the same view-def + Synthea data.

Sprint 6.2 Phase 1.5 Q1 refinement is the precedent: pre-commits are updated, not blindly enforced, when new information reveals the rule was based on a wrong premise. Q1 there was "cataloged-bug fixes are Phase 1.2 scope, NOT pivot triggers." Q1 here is **"the gate is evaluated against the fixed view-def, not the broken one."**

### Re-test against patched view-def (#41 `forEach` → `forEachOrNull`)

```
30 Synthea Procedures (all 0×0×0)  →  30 rows  ✓ (30/30 distinct Procedure IDs)
Synth 2×1×1                         →  2 rows  ✓
Synth 1×0×0                         →  1 row   ✓ (outer-join surfaces row with NULL columns)
Synth 0×0×0 (Synthea shape)         →  1 row   ✓ (outer-join surfaces row with NULL columns)
```

**3/3 view-defs now pass Criterion 1:**
- observation_labs 19/19 ✓
- condition_diagnoses 50/50 ✓
- procedure_history 30/30 distinct Procedure IDs ✓ (under `forEachOrNull` semantics)

Projecting to the full HAPI corpus: 66,448 Procedures → 66,448 distinct IDs in the MV, matching the HAPI REST oracle. (Full-corpus exact-match validation deferred to Sprint 6.4 implementation.)

### Override of C3 maturity proxies — now fires

User's explicit rationale: *"The override rationale isn't 'we found a shinier object'; it's 'the rule's premise was wrong, the rule is updated with corrected information, the override against C3 proxies is justified by direct evidence (vendor backing, active commits, Apache 2.0, verified coverage) being stronger than indirect proxies (stars, release age).'"*

Direct evidence accumulated:
- **Vendor backing:** SAS Institute (legitimate analytics vendor, $3B+ annual revenue, ~14k employees)
- **Active commits:** `sassoftware/sqlonfhir` pushed 2026-05-07 (1 week ago, source `__version__ = "0.1.1-alpha"` ahead of PyPI's 0.0.2)
- **License:** Apache 2.0 (compatible)
- **Construct coverage:** 3/3 view-defs empirically verified — `category.coding.where(system=X and code=Y).exists()` + `status in (...)` + `clinicalStatus.coding.code.where($this in (...)).exists()` + `forEachOrNull` (outer-join cardinality, including the all-empty case)

Indirect proxies (the C3 thresholds):
- Stars (7) and release age (7.5 months since last PyPI) proxy for *community stress-testing* and *release cadence health*. They are not zero-information — but they are weaker evidence than direct empirical confirmation of construct coverage against the actual view-defs Sprint 6.4 needs to ship.

### Comparison with Pathling — also relevant to the revision

The original verdict assumed Pathling was the safe fallback. Pathling was never validated against the same gate sqlonfhir was held to:
- ❌ Pathling C1 (construct coverage): **never tested** — Spark init failed on dev machine
- ⚠️ Pathling C2 (integration shape): nominally PASS, but real cost is Java 17 hard requirement + PySpark 4.0 + Mac Spark init NPE + ~430MB deployment surface
- ✅ Pathling C3 (maturity proxies): PASS 3/4 measured

Pathling has *better proxies* but *no direct construct-coverage evidence*. sqlonfhir has *worse proxies* but *direct construct-coverage evidence on the exact view-defs this project ships*. The override correctly weights direct evidence over proxy evidence.

### Revised verdict: GO sqlonfhir

- Sprint 6.4 implementation target: **sqlonfhir + dispatch plumbing** (issue #40 retargets)
- Pathling deferred as fallback if sqlonfhir proves unresponsive during Sprint 6.4 (the override is reversible: empirical evidence about library responsiveness during real implementation work would justify reversal)
- Side-finding #41 (procedure_history `forEachOrNull`) lands as part of Sprint 6.3 spike PR — it's load-bearing for the verdict
- Sprint 6.5+ recheck closed (sqlonfhir is the chosen engine; recheck N/A)
- Pathling 6-month recheck added: if sqlonfhir proves problematic mid-Sprint 6.4, Pathling is the documented fallback. Java 17 ops setup work captured in Sprint 6.4 issue body as deferred-if-needed scope.

### Discipline note

This revision is not "I changed my mind because I wanted to." The strict-reading verdict was reached procedurally and the override was deliberately rejected. The user re-examined the verdict's reasoning, identified that the gate's premise was broken (the 3/3 was unreachable in its literal form because of a view-def bug, not engine choice), and directed a re-test with the corrected premise. That re-test produced new information (3/3 PASS). The Q1 refinement pattern applies: the rule is updated with the corrected premise, the override fires.

Sprint 6.2 Phase 1.5 used the Q1 refinement to AVOID a Pathling pivot when uncataloged bugs surfaced. Sprint 6.3 uses the same pattern to PIVOT TO sqlonfhir when the gate's premise was revealed broken. The pattern works in both directions — that's what makes it discipline, not bias.
