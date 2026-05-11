#!/usr/bin/env bash
# Seed the HAPI FHIR server with the test fixture used by service-dependent CI tests.
#
# Loads tests/fixtures/hapi_seed/bundle.json (one FHIR transaction bundle, 18
# resources covering 5 patients) into HAPI via the REST API. The bundle uses
# PUT semantics with deterministic IDs so the harness fixture in
# tests/fixtures/transpiler_expected_outputs.py can assert exact values.
#
# Idempotent: PUT semantics upsert. Re-running won't duplicate resources.
#
# Usage:
#   ./scripts/seed.sh                       # default HAPI at localhost:8081
#   ./scripts/seed.sh http://hapi:8080/fhir # custom URL (CI uses container DNS)

set -euo pipefail

HAPI_URL="${1:-http://localhost:8081/fhir}"
BUNDLE_FILE="tests/fixtures/hapi_seed/bundle.json"

if [ ! -f "$BUNDLE_FILE" ]; then
  echo "ERROR: $BUNDLE_FILE not found. Run from project root." >&2
  exit 1
fi

# Wait for HAPI to be ready (max 120s). HAPI takes ~30-60s on cold start
# (Flyway migrations + JPA init).
echo "Waiting for HAPI at $HAPI_URL ..."
for i in $(seq 1 60); do
  if curl -fsS -o /dev/null --max-time 3 "$HAPI_URL/metadata"; then
    echo "HAPI ready after ${i} attempts."
    break
  fi
  if [ "$i" = "60" ]; then
    echo "ERROR: HAPI did not become ready within 120s." >&2
    exit 1
  fi
  sleep 2
done

# POST the transaction bundle. HAPI processes PUT entries with explicit IDs
# atomically -- either every resource lands or none do.
echo "Loading bundle ($BUNDLE_FILE) ..."
RESPONSE=$(curl -fsS -X POST \
  -H "Content-Type: application/fhir+json" \
  -H "Accept: application/fhir+json" \
  --data @"$BUNDLE_FILE" \
  "$HAPI_URL")

# Verify: count Patient resources via search
EXPECTED_PATIENTS=5
ACTUAL=$(curl -fsS "$HAPI_URL/Patient?_id=fixture-patient-a,fixture-patient-b,fixture-patient-c,fixture-patient-d,fixture-patient-e&_count=10" \
  | python3 -c "import json,sys; print(json.load(sys.stdin).get('total', 0))")

if [ "$ACTUAL" != "$EXPECTED_PATIENTS" ]; then
  echo "ERROR: expected $EXPECTED_PATIENTS fixture patients, got $ACTUAL" >&2
  echo "Bundle response (first 500 chars):" >&2
  echo "$RESPONSE" | head -c 500 >&2
  echo >&2
  exit 1
fi

echo "Seed complete: $ACTUAL fixture patients present in HAPI."
