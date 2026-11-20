#!/usr/bin/env bash
# The review-attestation reader. One copy, called by .github/workflows/attestation.yml
# and by .claude/skills/validate-and-ship (Steps 7.4, 7.5 and 8), so the two can't drift.
#
#   attestation.sh read   <pr>          print the 7.5 reader's lines (EDITED, NEWEST, ROOT, MISSING, IGNORED)
#   attestation.sh carry  <pr> <root>   run the 7.4 carry-forward checks against the PR's head
#   attestation.sh status <pr>          decide the `attestation` status: prints "<state>\t<head-sha>\t<description>"
#   attestation.sh set-status <pr>      run `status` and POST the result as the `attestation` commit status
#
# Needs gh (authenticated; GH_REPO selects the repo when not run inside a clone of it). `carry` and
# `status` also need a clone with `origin` pointing at the repo. Nothing here checks out, builds or
# runs the PR's code: it reads comments through the API and runs git plumbing on fetched objects.
set -euo pipefail

usage() {
  sed -n '2,11p' "$0" | sed 's/^# \{0,1\}//' >&2
  exit 2
}

cmd=${1:-}
pr=${2:-}
[[ $pr =~ ^[0-9]+$ ]] || usage

# Runs gh, retrying only a 5xx response (up to 3 tries, 2s then 4s apart; ATTESTATION_RETRY_SLEEP
# overrides the base delay). Any other failure, a 4xx included, returns at once, so retrying can't
# turn a refusal into a success. Callers still decide what a failure means.
gh_retry() {
  local try=1 out err rc
  err=$(mktemp)
  while :; do
    # rc is read right after the command: an `if` that falls through would reset $? to 0.
    out=$(gh "$@" 2>"$err") && {
      rm -f "$err"
      printf '%s\n' "$out"
      return 0
    }
    rc=$?
    if [ "$try" -lt 3 ] && grep -Eq 'HTTP 5[0-9]{2}' "$err"; then
      echo "gh: HTTP 5xx, retrying ($try of 3 tries used)" >&2
      sleep $((${ATTESTATION_RETRY_SLEEP:-2} * try))
      try=$((try + 1))
      continue
    fi
    cat "$err" >&2
    rm -f "$err"
    return "$rc"
  done
}

# Counts a comment only when the repo owner posted it and nobody has edited it since. The owner's
# login comes from the PR's own URL, and authorAssociation must be OWNER (gh prints a GitHub App's
# login without its [bot] suffix, so the login alone can't tell the owner from an app of that name).
read_attestations() {
  gh_retry pr view "$pr" --json headRefOid,url,comments -q 'def v($k): [capture("(?m)^- \($k): (?<v>[^\r\n]*)")] | .[0].v // "none"; def own($o): .author.login == $o and .authorAssociation == "OWNER"; .headRefOid as $h | (.url | split("/")[3]) as $owner | [.comments[] | select(.body | test("^## Review attestation"))] as $a | ($a[] | select(own($owner) and .includesCreatedEdit != false) | "EDITED \(.url)"), ([$a[] | select(own($owner) and .includesCreatedEdit == false) | .body] as $o | ($o | last) as $new | ([$o[] | select(test("(?m)^- Carried-From:") | not)] | last) as $root | if $new == null then "MISSING" else ($new | v("Reviewed-Commit")) as $s | "NEWEST \($s) \(if $s == $h then "head" else "STALE" end) verdict=\($new | v("Verdict")) carried-from=\($new | v("Carried-From"))", "ROOT \(if $root == null then "none" else "\($root | v("Reviewed-Commit")) verdict=\($root | v("Verdict"))" end)" end), ($a[] | select(own($owner) | not) | "IGNORED \(.author.login) \(.authorAssociation) \(.url)")'
}

# The 7.4 checks. Prints NOT-A-MERGE, or each of main-ok, lineage-ok, tree-ok that holds.
# Succeeds only when all three print, then adds a "main=<sha> tree=<sha>" line. $1 is the root: the Reviewed-Commit of the newest owner
# attestation that is not itself a carry-forward.
carry_checks() {
  local old=$1 new main mb t ok=0
  [[ $old =~ ^[0-9a-f]{40}$ ]] || { echo "BAD-ROOT"; return 1; }
  new=$(gh_retry pr view "$pr" --json headRefOid -q .headRefOid)
  git fetch -q origin main "pull/$pr/head"
  main=$(git rev-parse --verify -q "$new^2") || { echo NOT-A-MERGE; return 1; }
  # What was merged is main.
  if git merge-base --is-ancestor "$main" origin/main; then echo main-ok; ok=$((ok + 1)); fi
  # No rewrite since the review.
  if git merge-base --is-ancestor "$old" "$new"; then echo lineage-ok; ok=$((ok + 1)); fi
  # No file changed on both sides since they diverged (so git never merged file contents and no
  # merge driver, .gitattributes or rename-following shaped the result), and the new head's tree is
  # exactly what git produces by merging the reviewed commit with that main commit.
  if mb=$(git merge-base "$old" "$main") \
    && [ -z "$(LC_ALL=C comm -12 <(git diff --no-renames --ignore-submodules=none --name-only "$mb" "$old" | LC_ALL=C sort) <(git diff --no-renames --ignore-submodules=none --name-only "$mb" "$main" | LC_ALL=C sort))" ] \
    && t=$(git -c merge.directoryRenames=false merge-tree --write-tree "$old" "$main") \
    && [ "$t" = "$(git rev-parse "$new^{tree}")" ]; then
    echo tree-ok
    ok=$((ok + 1))
  fi
  # For the carry-forward comment's Basis line.
  [ "$ok" -ne 3 ] || echo "main=$main tree=$t"
  [ "$ok" -eq 3 ]
}

# The #542 format rules, checked only where the status would otherwise pass: the root attestation's
# Findings parse the way scripts/review_metrics.py reads them, and the PR body has a filled Red-first:
# line. Prints the failure description, or nothing when both hold. Returns 3 when a check can't run.
# $1 is the ROOT line's commit. The root's body is picked with the reader's checks (owner login, OWNER
# association, unedited, not a carry-forward), and must name that commit, so the two can't disagree.
format_problem() {
  local root_commit=$1 body out rc
  local metrics
  metrics="$(dirname "$0")/review_metrics.py"
  body=$(gh_retry pr view "$pr" --json url,comments -q 'def own($o): .author.login == $o and .authorAssociation == "OWNER"; (.url | split("/")[3]) as $owner | [.comments[] | select((.body | test("^## Review attestation")) and own($owner) and .includesCreatedEdit == false) | .body | select(test("(?m)^- Carried-From:") | not)] | last // empty') || return 3
  grep -Eq "^- Reviewed-Commit: ${root_commit}[[:space:]]*\$" <<<"$body" || return 3
  out=$(printf '%s\n' "$body" | python3 -I "$metrics" --check-root -) && rc=0 || rc=$?
  case $rc in
    0) ;;
    1) printf '%s\n' "$out" && return 0 ;;
    *) return 3 ;;
  esac
  body=$(gh_retry pr view "$pr" --json body -q .body) || return 3
  out=$(printf '%s\n' "$body" | python3 -I "$metrics" --check-red-first -) && rc=0 || rc=$?
  case $rc in
    0) ;;
    1) printf '%s\n' "$out" ;;
    *) return 3 ;;
  esac
}

# The decision the required status makes: Step 8's attestation conditions, minus CI and merge class.
status_decision() {
  local head out edited newest root verdict carried s state root_commit root_verdict problem missing=""
  # bash clears errexit inside $(...), so a gh failure must return explicitly, not fall through to a verdict.
  head=$(gh_retry pr view "$pr" --json headRefOid -q .headRefOid) || return 3
  [ -n "$head" ] || return 3
  out=$(read_attestations) || return 3

  emit() { printf '%s\t%s\t%s\n' "$1" "$head" "$2"; }

  edited=$(grep -m1 '^EDITED ' <<<"$out" || true)
  if [ -n "$edited" ]; then
    emit failure "An owner attestation was edited after posting; edited ones never count."
    return
  fi
  if grep -qx 'MISSING' <<<"$out"; then
    emit failure "No attestation from the repo owner on this PR."
    return
  fi
  newest=$(grep -m1 '^NEWEST ' <<<"$out" || true)
  [ -n "$newest" ] || { emit failure "Reader printed no NEWEST line."; return; }
  s=$(awk '{print $2}' <<<"$newest")
  state=$(awk '{print $3}' <<<"$newest")
  verdict=$(sed -E 's/^NEWEST [^ ]+ [^ ]+ verdict=(.*) carried-from=[^ ]*$/\1/' <<<"$newest")
  carried=$(sed -E 's/^.* carried-from=([^ ]*)$/\1/' <<<"$newest")

  if [ "$state" != head ]; then
    emit failure "Newest attestation covers ${s:0:7}, the PR head is ${head:0:7}. Post a new one."
    return
  fi

  if [ "$carried" = none ]; then
    case "$verdict" in
      SHIP | SHIP-WITH-FIXES)
        # Not a carry, so the newest attestation is the root.
        problem=$(format_problem "$s") || return 3
        if [ -n "$problem" ]; then
          emit failure "$problem"
        else
          emit success "Owner attestation ($verdict) covers head ${head:0:7}."
        fi
        ;;
      BLOCK) emit failure "Newest attestation's verdict is BLOCK." ;;
      *) emit failure "Newest attestation's verdict isn't SHIP or SHIP-WITH-FIXES, or its Carried-From key is misspelled." ;;
    esac
    return
  fi

  # A carry-forward: trust it only after checking its root and the 7.4 conditions again.
  if [ "$verdict" != "SHIP (carried forward)" ] && [ "$verdict" != SHIP ]; then
    emit failure "Carry-forward's own verdict isn't SHIP (carried forward)."
    return
  fi
  root=$(grep -m1 '^ROOT ' <<<"$out" || true)
  root_commit=$(awk '{print $2}' <<<"$root")
  root_verdict=$(sed -E 's/^ROOT [^ ]+ verdict=(.*)$/\1/' <<<"$root")
  if [ "$root_verdict" != SHIP ]; then
    emit failure "Carry-forward's root attestation isn't verdict SHIP, so it can't be carried."
    return
  fi
  if [ "$carried" != "$root_commit" ]; then
    emit failure "Carry-forward's Carried-From (${carried:0:7}) isn't the root attestation's commit (${root_commit:0:7})."
    return
  fi
  local checks
  checks=$(carry_checks "$root_commit" 2>/dev/null || true)
  for want in main-ok lineage-ok tree-ok; do
    grep -qx "$want" <<<"$checks" || missing="$missing $want"
  done
  if [ -n "$missing" ]; then
    emit failure "Carry-forward fails the Step 7.4 checks; missing:$missing. Needs a fresh review."
    return
  fi
  problem=$(format_problem "$root_commit") || return 3
  if [ -n "$problem" ]; then
    emit failure "$problem"
    return
  fi
  emit success "Carried-forward attestation covers head ${head:0:7}; Step 7.4 checks pass on ${carried:0:7}."
}

# Sets the `attestation` commit status. Fail closed: a reader crash posts `error`, and a POST that
# still fails after the retries exits 1 so the job is red, never green.
set_status() {
  local result state sha description
  if result=$("$0" status "$pr"); then
    IFS=$'\t' read -r state sha description <<<"$result"
  else
    # The head may have moved mid-check; a push's own run decides that case.
    sha=$(gh_retry pr view "$pr" --json headRefOid -q .headRefOid) || return 1
    state=error
    description="The attestation check failed to run; see the workflow run."
  fi
  echo "attestation on ${sha:0:7}: $state: $description"
  gh_retry api --method POST "repos/$GITHUB_REPOSITORY/statuses/$sha" \
    -f state="$state" \
    -f context=attestation \
    -f description="${description:0:140}" \
    -f target_url="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID" >/dev/null
}

case "$cmd" in
  set-status) set_status ;;
  read) read_attestations ;;
  carry)
    [ -n "${3:-}" ] || usage
    carry_checks "$3"
    ;;
  status)
    before=$(gh_retry pr view "$pr" --json headRefOid -q .headRefOid)
    result=$(status_decision)
    after=$(gh_retry pr view "$pr" --json headRefOid -q .headRefOid)
    # A push during the check means the result may describe the old head; the push's own run decides.
    [ "$before" = "$after" ] || { echo "head moved during the check ($before -> $after)" >&2; exit 3; }
    printf '%s\n' "$result"
    ;;
  *) usage ;;
esac
