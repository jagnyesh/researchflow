---
sprint: 6.3
date: 2026-05-14
status: superseded
supersedes: []
superseded_by: 0020-sprint-6-3-verdict-revision-go-sqlonfhir.md
related: []
---

# Sprint 6.3 — DuckDB-FHIR spike verdict: GO Pathling (with sqlonfhir captured for Sprint 6.5+ recheck)

Spike executed 2026-05-14, well within the 2-day hard cap. Three FHIRPath constructs empirically evaluated against samples + synthetic data. Pre-committed numeric thresholds applied strictly. The override mechanism (`pre-commit defends against bias, not against information`) was deliberately considered for sqlonfhir and did NOT fire — the row-count match against HAPI oracle was 2/3, not the 3/3 the override required.

### Measured outcomes vs pre-committed thresholds

**Named Primary `sql-on-fhir-v2` Python ref impl:** does not exist as a Python package. The HL7 ref impl is JavaScript (`sof-js`). Primary tier eliminated by non-existence.

**Named Secondary "DuckDB community FHIR extension":** does not exist (0 GitHub search hits). Secondary tier eliminated by non-existence. DuckDB-FHIR candidate set is empty; methodology triggers Pathling evaluation.

**Mid-spike discovery — `sqlonfhir` (one word, missed in D4):** SAS Healthcare's Python implementation. Apache 2.0. Pure-Python (`fhirpathpy~=2.1.0`). User-directed deep evaluation against the 4 thresholds within a 45-min hard cap.

| | sqlonfhir | Pathling |
|---|---|---|
| C1 — construct coverage (3/3 expected) | 2/3 by row-count match; **3/3 by construct-correctness** (synthetic test confirms forEach cardinality math) | not empirically tested — Spark init failed on Mac under PySpark 4.0; ≥90% prior that procedure_history is shared 0-row |
| C2 — integration shape | ✅ Pure Python, no JVM, no Spark | ⚠️ "Native Python lib" tier per pre-commit but real cost: Java 17 hard requirement, PySpark 4.0 with known Mac/Spark init issues, ~430MB deployment surface |
| C3 — maturity (pass requires ALL 4) | ❌ FAIL 2/4: 2025-09-29 release (7.5 months), 7 GitHub stars | ✅ PASS 3/4 measured (release 2026-04-23, commits today, 126 stars); maintainer responsiveness deferred |
| C4 — performance | not measured | not measured |

**Verdict trigger:** sqlonfhir fails C3 strict pre-commit (2/4 thresholds). procedure_history row-count fails the 3/3 override gate (HAPI oracle = 66,448; sqlonfhir against Synthea = 0). Override does NOT fire. Per user-pre-committed framework ("If 1 or 2 view-defs work but procedure_history doesn't, verdict stays GO Pathling but the recheck has measured data"): **GO Pathling.**

### Why the override did not fire — discipline note

The override evaluation was real, not pro-forma. sqlonfhir has unambiguous technical merit: it handles all 3 target FHIRPath constructs correctly (verified empirically), has the cleanest possible Python integration shape, vendor backing, and active commits. The Sprint 6.2 Phase 1.5 Q1 refinement pattern (cataloged-bug fixes are scope, not pivot triggers) was the precedent for considering override.

What the override DID NOT do: change the C3 reading. The "≥ 50 stars" + "≤ 6mo release" thresholds proxy for community stress-testing maturity. **Construct correctness is necessary but not sufficient for production adoption.** A library can be technically correct AND insufficiently stress-tested. The pre-commit catches that.

What the override could have done: fire if all 3 view-defs matched (3/3 → "demonstrated construct coverage IS the maturity proxy I needed"). Got 2/3 plus a shared-issue interpretation for procedure_history. The strict gate held.

### Pathling's C2 surprises (warrant Sprint 6.4 mitigation)

Pathling 9.6.0 pulls in PySpark 4.0.2 which requires Java 17 specifically. Spark init failed on Mac (M-series Apple Silicon, OpenJDK 17.0.19) with `BlockManagerId.executorId()` NPE. Pathling cannot be downgraded to PySpark 3.x (imports `pyspark.sql.classic` which is 4.0-only namespace). Sprint 6.4 implementation must:
1. Pin Java 17 in deployment env (not Java 11 currently in docker-compose stack)
2. Resolve PySpark 4.0 Spark-init issue on whatever platform Sprint 6.4 deploys (likely needs `SPARK_LOCAL_IP` or hostname-resolution config)
3. Accept the ~430MB deployment surface increase from PySpark wheel + Pathling library-runtime JARs

The pre-committed C2 reading still says PASS ("Subprocess / CLI invocation acceptable"). The cost is real and goes into the Sprint 6.4 risk register.

### Side-finding to file separately

**`procedure_history` view-def is structurally broken** regardless of engine. Three `forEach` blocks over `performer` / `reasonCode` / `bodySite` arrays empty in 100% of Synthea Procedures. Per FHIRPath spec, `forEach` over empty = 0 rows. Fix: change `"forEach"` → `"forEachOrNull"` in the 3 nested select blocks. Not in scope for the engine spike; filed as separate issue.

### sqlonfhir captured for Sprint 6.5+ recheck (deferred follow-on)

If by 2026-11-14 sqlonfhir has shipped v0.1.0+ with a real release cadence and >50 stars, Sprint 6.5+ should re-evaluate. The measured evidence base from this spike (FHIRPath constructs work, pure-Python integration) gives a strong starting point.

### Time-box honored

Total spike effort: ~30 min Day 1. Well within 2-day hard cap. Pathling-debugging time-cap consideration was correctly applied: ~15 min sunk on Spark init before accepting the data gap and proceeding to verdict.

### Downstream issues filed

- Sprint 6.4 implementation: Pathling integration + Java 17 + PySpark 4.0 ops setup + port 3 zero-row MVs + plumb dispatch in MaterializedViewRunner
- Side-finding: procedure_history view-def needs `forEachOrNull` (separate from engine choice)
- Sprint 6.5+ recheck candidate: re-evaluate sqlonfhir at 2026-11-14 or upon v0.1.0+ release
