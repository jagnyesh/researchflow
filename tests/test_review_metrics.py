"""#520: scripts/review_metrics.py on recorded gh JSON, with no network call.

Fixtures in tests/fixtures/review_metrics/ are real `gh` output from this repo:
- pr518.json: `gh pr view 518 --json headRefOid,url,comments`. A root owner attestation with fixed,
  accepted and routed findings (one line carries two dispositions), then two carry-forwards.
- pr317.json: the same call for #317, an older drifted attestation (`Reviewed commit:` in prose,
  findings with no `finding N:` form). Its Findings block can't be parsed.
- pr518_list.json: the `gh pr list --json` fields of #518 (body, dates, closing issue).

No revert commit exists on main yet, so the revert fixture is the message git's own `git revert`
writes, naming the PR the way a squash-merge subject does.

The fake `gh` and `git` on PATH return only the fields the `--json` flag named, as the real CLI does.
"""

import copy
import csv
import importlib.util
import json
import os
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "review_metrics"

_spec = importlib.util.spec_from_file_location("review_metrics", REPO / "scripts/review_metrics.py")
rm = importlib.util.module_from_spec(_spec)
sys.modules["review_metrics"] = rm
_spec.loader.exec_module(rm)

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
ROOT_SHA = "9edbfd763453969f34f45f2ae5217819ca766082"
PR518_URL = "https://github.com/jagnyesh/researchflow/pull/518"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def root_body(pr="pr518.json"):
    return [c for c in load(pr)["comments"] if c["body"].startswith("## Review attestation")][0][
        "body"
    ]


def issue(n, created, title="x", body="", labels=(), closed=None):
    return {
        "number": n,
        "createdAt": created,
        "closedAt": closed,
        "title": title,
        "body": body,
        "labels": [{"name": name} for name in labels],
    }


def pr(
    n=518, tier="medium", merged="2026-11-15T04:18:49Z", created="2026-11-15T02:05:41Z", closes=456
):
    return {
        "number": n,
        "title": f"pr {n}",
        "body": (
            f"## Testing evidence\n\n- Risk tier: {tier}. Paths: x\n" if tier else "no tier here\n"
        ),
        "createdAt": created,
        "mergedAt": merged,
        "closingIssuesReferences": [{"number": closes}] if closes else [],
    }


def row_for(pr_, body=None, issues=(), reverts=(), reopened=0, now=NOW):
    return rm.build_row(
        pr_,
        attestation=(body, []) if body is not None else (None, ["no attestation"]),
        issues=list(issues),
        reverts=list(reverts),
        reopened=reopened,
        now=now,
    )


def att(*dispositions):
    """An attestation body whose findings carry the given dispositions, one per finding."""
    lines = [f"  - finding {k}: x → {d}" for k, d in enumerate(dispositions, 1)]
    return "\n".join(
        [
            "## Review attestation",
            "- Verdict: SHIP",
            f"- Reviewed-Commit: {ROOT_SHA}",
            "- Reviewer 1: x, 1 pass(es), SHIP",
            "- Findings:",
            *lines,
            "",
        ]
    )


# ------------------------------------------------------------------ attestation parsing


def test_root_with_fixed_accepted_and_routed_findings_is_counted():
    r = row_for(pr(), root_body())

    assert r["findings_total"] == 15
    # finding 14 is the only `accepted`; findings 9, 10, 12 are routed, and 8 is fixed AND routed.
    assert r["findings_accepted"] == 1
    assert r["findings_routed"] == 4
    assert r["findings_fixed"] == 11
    assert r["review_passes"] == 10
    assert r["parse_warnings"] == ""


def test_a_line_with_two_dispositions_counts_in_both_columns():
    body = "## Review attestation\n- Findings:\n  - finding 1: a → fixed (x); rest routed to #9\n"

    f = rm.parse_findings(body)

    assert (f["findings_total"], f["findings_fixed"], f["findings_routed"]) == (1, 1, 1)


def test_process_lines_are_not_findings():
    body = "- Findings:\n  - finding 1: a → fixed\n  - process: shared worktree → settled\n"

    assert rm.parse_findings(body)["findings_total"] == 1


def test_findings_none_is_a_real_zero():
    f = rm.parse_findings("- Findings: none\n- Reviewer 1: x, 1 pass(es), SHIP\n")

    assert f["findings_total"] == 0
    assert f["warnings"] == []


@pytest.mark.parametrize(
    "body",
    [
        "- Findings:\n  - something with no finding form → ok\n",  # drifted nested lines
        "- Findings: a couple of nits, all fixed\n",  # inline prose
        "- Findings:\n",  # empty block
        "- Verdict: SHIP\n",  # no Findings line at all
        "- Findings:\n  - finding 1: a → looks fine\n",  # disposition names no known outcome
        "- Findings:\n  - finding 1: no arrow here\n",
    ],
)
def test_an_unparseable_findings_block_is_empty_with_a_warning_never_zero(body):
    f = rm.parse_findings(body)

    assert f["findings_total"] is None
    assert f["findings_fixed"] is None
    assert f["findings_accepted"] is None
    assert f["findings_routed"] is None
    assert f["warnings"]


def test_the_drifted_recorded_attestation_of_317_does_not_parse():
    f = rm.parse_findings(root_body("pr317.json"))

    assert f["findings_total"] is None
    assert f["warnings"]


def test_no_attestation_gives_empty_counts_and_a_warning():
    r = row_for(pr(), None)

    assert r["findings_total"] == ""
    assert r["review_passes"] == ""
    assert "no attestation" in r["parse_warnings"]


# ------------------------------------------------------------------ the root decision (reuses attestation.sh)


def test_root_is_chosen_from_the_readers_root_line_not_the_carry_forward():
    comments = load("pr518.json")["comments"]
    out = f"NEWEST 6a492a7 head verdict=SHIP (carried forward) carried-from={ROOT_SHA}\nROOT {ROOT_SHA} verdict=SHIP\n"

    body, warnings = rm.pick_root_body(out, comments, PR518_URL)

    assert warnings == []
    assert f"Reviewed-Commit: {ROOT_SHA}" in body
    assert "Carried-From" not in body


def test_a_root_without_a_commit_hash_is_a_warning():
    comments = load("pr317.json")["comments"]

    body, warnings = rm.pick_root_body("ROOT none verdict=none\n", comments, PR518_URL)

    assert body is None
    assert warnings


def test_missing_attestation_and_edited_ones_are_warnings():
    assert rm.pick_root_body("MISSING\n", [], PR518_URL)[1]
    _, w = rm.pick_root_body(
        f"EDITED https://x/1\nROOT {ROOT_SHA} verdict=SHIP\n",
        load("pr518.json")["comments"],
        PR518_URL,
    )
    assert any("edited" in x for x in w)


# ------------------------------------------------------------------ tier


def test_tier_comes_from_the_risk_tier_line_and_defaults_to_unknown():
    assert row_for(pr(tier="high"), root_body())["tier"] == "high"
    assert row_for(pr(tier="Low"), root_body())["tier"] == "low"
    assert row_for(pr(tier=None), root_body())["tier"] == "unknown"


# ------------------------------------------------------------------ follow-ups and escapes


def test_an_issue_named_as_filed_during_review_is_a_follow_up_not_an_escape():
    # Created during review (after the PR opened, before it merged), labelled bug, named `filed`.
    i = issue(600, "2026-11-15T03:00:00Z", title="review finding", labels=["bug"])

    r = row_for(pr(), att("accepted; filed #600"), issues=[i])

    assert r["followups_filed"] == 1
    assert r["escapes"] == 0


def test_a_bug_issue_filed_after_the_merge_within_14_days_is_an_escape():
    i = issue(601, "2026-11-20T00:00:00Z", title="regression", body="from #518", labels=["bug"])

    r = row_for(pr(), root_body(), issues=[i])

    assert r["escapes"] == 1
    assert r["followups_filed"] == 0  # past the 24-hour follow-up window


def test_a_bug_issue_after_14_days_or_without_the_bug_label_is_not_an_escape():
    late = issue(602, "2026-12-01T00:00:00Z", body="#518", labels=["bug"])
    unlabelled = issue(603, "2026-11-16T00:00:00Z", body="#518", labels=["enhancement"])

    r = row_for(pr(), root_body(), issues=[late, unlabelled])

    assert r["escapes"] == 0


def test_an_issue_that_only_cites_the_pr_is_not_a_follow_up():
    # Citation no longer counts (#529): the attestation names no issue, so nothing is filed.
    i = issue(610, "2026-11-15T03:00:00Z", body="#518 and also #456")

    assert row_for(pr(), att("fixed"), issues=[i])["followups_filed"] == 0


def test_a_filed_issue_counts_without_any_window():
    # `filed #n` names a new issue, so the creation time is not consulted.
    i = issue(611, "2026-10-01T00:00:00Z")

    assert row_for(pr(), att("filed #611"), issues=[i])["followups_filed"] == 1


def test_a_filed_issue_missing_from_the_issue_list_still_counts():
    assert row_for(pr(), att("filed #612"), issues=[])["followups_filed"] == 1


def test_the_same_issue_named_twice_in_one_attestation_counts_once():
    i = issue(613, "2026-11-15T03:00:00Z")

    r = row_for(pr(), att("filed #613", "routed to #613"), issues=[i])

    assert r["followups_filed"] == 1


def test_older_attestation_routing_counts_only_issues_created_inside_the_window():
    new = issue(517, "2026-11-15T03:00:00Z")  # created during review
    old = issue(431, "2026-10-15T03:00:00Z")  # created a month before the PR

    r = row_for(pr(), root_body(), issues=[new, old])

    assert r["followups_filed"] == 1


def test_a_routed_issue_not_in_the_issue_list_is_not_counted():
    # An old issue falls outside the fetched search range, so its creation time is unknown.
    assert row_for(pr(), att("routed to #99"), issues=[])["followups_filed"] == 0


def test_an_issue_two_prs_name_counts_once_for_the_earlier_merge():
    i = issue(620, "2026-11-15T03:00:00Z")
    early = pr(1, merged="2026-11-15T04:00:00Z")
    late = pr(2, merged="2026-11-15T05:00:00Z")
    named = {
        1: rm.followup_candidates(early, att("filed #620"), [i]),
        2: rm.followup_candidates(late, att("filed #620"), [i]),
    }

    owned = rm.claim_followups({1: early, 2: late}, named)

    assert (owned[1], owned[2]) == ({620}, set())


def test_a_pr_whose_attestation_cannot_be_parsed_has_an_empty_count_not_zero():
    i = issue(621, "2026-11-15T03:00:00Z", body="#518")

    r = row_for(pr(), "## Review attestation\n- Findings: some prose\n", issues=[i])

    assert r["followups_filed"] == ""
    assert r["parse_warnings"]


def test_the_follow_up_window_for_routed_issues_ends_24_hours_after_the_merge():
    inside = issue(622, "2026-11-16T04:00:00Z")
    outside = issue(623, "2026-11-16T04:30:00Z")

    r = row_for(pr(), att("routed to #622", "routed to #623"), issues=[inside, outside])

    assert r["followups_filed"] == 1


def test_an_attestation_that_files_more_than_one_issue_gets_a_warning():
    r = row_for(pr(), att("filed #630", "filed #631"), issues=[])

    assert "files 2 issues" in r["parse_warnings"]
    assert r["followups_filed"] == 2  # still counted: the warning is the signal


def test_a_filed_issue_that_arrived_ready_for_agent_gets_a_warning():
    i = issue(632, "2026-11-15T03:00:00Z")

    flagged = rm.build_row(
        pr(), (att("filed #632"), []), [i], [], 0, NOW, arrival_labels={632: {"ready-for-agent"}}
    )
    clean = rm.build_row(
        pr(), (att("filed #632"), []), [i], [], 0, NOW, arrival_labels={632: {"needs-triage"}}
    )
    unknown = rm.build_row(pr(), (att("filed #632"), []), [i], [], 0, NOW, arrival_labels={})

    assert "ready-for-agent" in flagged["parse_warnings"]
    assert "ready-for-agent" not in clean["parse_warnings"]
    assert unknown["parse_warnings"] == ""


def test_arrival_labels_are_the_labels_added_within_a_minute_of_creation():
    events = [
        {
            "event": "labeled",
            "label": {"name": "needs-triage"},
            "created_at": "2026-11-15T03:00:20Z",
        },
        {
            "event": "labeled",
            "label": {"name": "ready-for-agent"},
            "created_at": "2026-11-15T09:00:00Z",
        },
        {"event": "closed", "created_at": "2026-11-15T03:00:10Z"},
    ]

    assert rm.arrival_labels(events, "2026-11-15T03:00:00Z") == {"needs-triage"}


def test_filed_and_routed_dispositions_are_parsed_with_their_issue_numbers():
    f = rm.parse_findings(att("filed #5; fixed", "routed to #6", "noted, not filed"))

    assert (f["filed_issues"], f["routed_issues"]) == ([5], [6])
    assert f["findings_total"] == 3
    assert f["findings_routed"] == 2  # filed and routed both go to the tracker


def test_reverts_and_reopened_closing_issue_count_as_escapes():
    r = row_for(pr(), root_body(), reverts=["a1", "b2"], reopened=1)

    assert r["escapes"] == 3


def test_revert_commits_are_matched_by_name_from_git_log_text():
    log = (
        'aaa\x1fRevert "fix: thing (#518)"\x1fThis reverts commit 123.\x1e'
        "bbb\x1ffix: unrelated (#5180)\x1fRevert of nothing #51\x1e"
        'ccc\x1fRevert "other (#519)"\x1fThis reverts commit 456.\x1e'
        "ddd\x1ffeat: mentions (#518) but is not a revert\x1f\x1e"
    )

    assert rm.reverts_naming(log, 518) == ["aaa"]
    assert rm.reverts_naming(log, 519) == ["ccc"]


def test_escape_window_closes_14_days_after_the_merge():
    merged = "2026-11-15T04:18:49Z"

    open_ = row_for(
        pr(merged=merged), root_body(), now=datetime(2026, 11, 29, 4, 18, 48, tzinfo=timezone.utc)
    )
    closed = row_for(
        pr(merged=merged), root_body(), now=datetime(2026, 11, 29, 4, 18, 49, tzinfo=timezone.utc)
    )

    assert open_["escape_window_closed"] == "false"
    assert closed["escape_window_closed"] == "true"


# ------------------------------------------------------------------ summary


def summary_rows(rows, now=NOW):
    return rm.summarize(rows, now=now)


def test_summary_prints_every_tier_even_with_no_prs_and_leaves_open_windows_out_of_escape_rate():
    rows = [
        row_for(pr(1, "low", merged="2026-10-01T00:00:00Z"), root_body(), issues=[]),
        row_for(pr(2, "low", merged="2026-10-02T00:00:00Z"), root_body(), reopened=1),
        row_for(
            pr(3, "low", merged="2026-11-15T00:00:00Z"), root_body(), reopened=1
        ),  # window open
    ]

    s = summary_rows(rows)

    assert [t["tier"] for t in s["tiers"]] == ["low", "medium", "high", "unknown"]
    low = s["tiers"][0]
    assert low["prs"] == 3
    assert low["catch_rate"] == "3/3 (100%)"  # every one has a fixed finding
    assert low["escape_rate"] == "1/2 (50%)"  # the open-window PR is out of the denominator
    assert low["window_open"] == 1
    assert s["tiers"][1]["prs"] == 0
    assert s["tiers"][1]["escape_rate"] == "n/a"
    assert s["tiers"][1]["catch_rate"] == "n/a"


def test_summary_counts_unparsed_attestations_out_of_catch_rate_and_says_so():
    rows = [
        row_for(pr(1, "high"), root_body()),
        row_for(pr(2, "high"), None),
    ]

    high = summary_rows(rows)["tiers"][2]

    assert high["prs"] == 2
    assert high["catch_rate"] == "1/1 (100%)"
    assert high["unparsed"] == 1


# ------------------------------------------------------------------ CSV and CLI

FAKE_GH = r"""#!/usr/bin/env bash
# Fake gh over $FAKE_DIR. Returns only the --json fields asked for, filtered through -q, like gh.
if [ "$1" = api ]; then
  n=$(sed -E 's#.*/issues/([0-9]+)/events.*#\1#' <<<"$2")
  cat "$FAKE_DIR/events$n.json" 2>/dev/null || echo '[]'
  exit 0
fi
trim() { # file fields -> object holding only those fields, failing on an unknown one
  jq -e --arg f "$2" '. as $d | ($f|split(",")) | map(select(in($d)|not)) | length == 0' "$1" >/dev/null \
    || { echo "fake gh: unknown field in $2" >&2; exit 1; }
  jq -c --arg f "$2" '. as $d | reduce ($f|split(",")[]) as $k ({}; .[$k] = $d[$k])' "$1"
}
fields="" query="."
args=("$@")
for ((i = 0; i < ${#args[@]}; i++)); do
  case "${args[i]}" in
    --json) fields=${args[i+1]} ;;
    -q) query=${args[i+1]} ;;
  esac
done
if [ "$1 $2" = "pr view" ] && [ -n "$FAKE_FAIL_READER" ] && [[ "$fields" == *headRefOid* ]]; then
  echo "gh: HTTP 403: API rate limit exceeded" >&2
  exit 1
fi
case "$1 $2" in
  "pr list")
    jq -c --arg f "$fields" '.[] | . as $d | reduce ($f|split(",")[]) as $k ({}; .[$k] = $d[$k])' \
      "$FAKE_DIR/prs.json" | jq -s .
    ;;
  "issue view")
    cat "$FAKE_DIR/issue$3.json" 2>/dev/null || exit 1
    ;;
  "pr view")
    trim "$FAKE_DIR/pr$3.json" "$fields" | jq -r "$query"
    ;;
  "issue list")
    echo "$*" >>"$FAKE_DIR/issue_searches.log"
    jq -c --arg f "$fields" '.[] | . as $d | reduce ($f|split(",")[]) as $k ({}; .[$k] = $d[$k])' \
      "$FAKE_DIR/issues.json" | jq -s .
    ;;
  *) echo "fake gh: unsupported: $*" >&2; exit 64 ;;
esac
"""

FAKE_GIT = r"""#!/usr/bin/env bash
[ "$1" = log ] || { echo "fake git: unsupported: $*" >&2; exit 64; }
cat "$FAKE_DIR/gitlog.txt"
"""


def make_env(tmp_path, prs, issues_, gitlog=""):
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    for name, text in (("gh", FAKE_GH), ("git", FAKE_GIT)):
        f = bindir / name
        f.write_text(text)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    data = tmp_path / "data"
    data.mkdir(exist_ok=True)
    (data / "prs.json").write_text(
        json.dumps([{k: v for k, v in p.items() if k != "_view"} for p in prs])
    )
    for p in prs:
        (data / f"pr{p['number']}.json").write_text(json.dumps(p["_view"]))
    (data / "issues.json").write_text(json.dumps(issues_))
    (data / "gitlog.txt").write_text(gitlog)
    return {
        **os.environ,
        "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
        "FAKE_DIR": str(data),
        "ATTESTATION_RETRY_SLEEP": "0",
    }


def listed(n, tier="medium", merged="2026-11-15T04:18:49Z", view="pr518.json"):
    p = pr(n, tier, merged=merged)
    p["_view"] = load(view)
    return p


def run_cli(tmp_path, env, *args):
    out = tmp_path / "out.csv"
    r = subprocess.run(
        [
            sys.executable,
            "-I",
            str(REPO / "scripts/review_metrics.py"),
            "--out",
            str(out),
            "--now",
            NOW.isoformat(),
            *args,
        ],
        env=env,
        capture_output=True,
        text=True,
    )
    return r, out


def test_cli_writes_one_row_per_merged_pr_and_is_byte_identical_on_rerun(tmp_path):
    prs = [listed(518), listed(317, tier=None, view="pr317.json"), listed(100, tier="high")]
    env = make_env(tmp_path, prs, [])

    r1, out = run_cli(tmp_path, env)
    first = out.read_bytes()
    r2, _ = run_cli(tmp_path, env)

    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
    assert out.read_bytes() == first
    rows = list(csv.DictReader(out.read_text().splitlines()))
    assert [x["pr"] for x in rows] == ["518", "317", "100"]  # merged PRs in == rows out
    assert list(rows[0]) == rm.COLUMNS
    assert (
        rows[1]["findings_total"] == "" and rows[1]["parse_warnings"]
    )  # 317 drifted: empty, not 0
    assert rows[1]["tier"] == "unknown"
    assert rows[0]["findings_total"] == "15"


def test_cli_reads_the_root_through_attestation_sh_and_reports_counts_in(tmp_path):
    env = make_env(tmp_path, [listed(518), listed(317, view="pr317.json")], [])

    r, out = run_cli(tmp_path, env)

    assert "2 merged PRs read, 2 rows written" in r.stdout + r.stderr


def test_cli_counts_issues_and_reverts_it_reads(tmp_path):
    issues_ = [
        issue(517, "2026-11-15T03:00:00Z", body="routed from the review"),
        issue(631, "2026-11-20T00:00:00Z", body="#518", labels=["bug"]),
    ]
    gitlog = 'aaa\x1fRevert "x (#518)"\x1fThis reverts commit 1.\x1e'
    env = make_env(tmp_path, [listed(518)], issues_, gitlog)

    r, out = run_cli(tmp_path, env)

    row = list(csv.DictReader(out.read_text().splitlines()))[0]
    assert row["followups_filed"] == "1"
    assert row["escapes"] == "2"  # one bug issue, one revert


def test_cli_stdout_lists_a_row_per_tier_and_how_many_open_windows_were_left_out(tmp_path):
    env = make_env(tmp_path, [listed(518)], [])

    r, _ = run_cli(tmp_path, env, "--summary")

    for tier in ("low", "medium", "high", "unknown"):
        assert any(line.split()[:1] == [tier] for line in r.stdout.splitlines()), tier
    assert "left out" in r.stdout


def test_issue_flow_counts_opened_and_closed_per_iso_week():
    issues_ = [
        issue(1, "2026-11-02T10:00:00Z", closed="2026-11-03T10:00:00Z"),  # ISO week 45
        issue(2, "2026-11-03T10:00:00Z"),  # week 45, still open
        issue(3, "2026-11-10T10:00:00Z", closed="2026-11-11T10:00:00Z"),  # week 46
    ]

    thursday_of_w46 = datetime(2026, 11, 12, tzinfo=timezone.utc)

    flow = rm.issue_flow(issues_, now=thursday_of_w46, weeks=2)

    assert flow == [
        {"week": "2026-W45", "opened": 2, "closed": 1, "net": 1},
        {"week": "2026-W46", "opened": 1, "closed": 1, "net": 0},
    ]


# ------------------------------------------------------------------ tier from paths (#520 follow-up)


def with_files(p, *paths):
    p = copy.deepcopy(p)
    p["files"] = [{"path": x} for x in paths]
    return p


def tier_row(tier_line, *paths):
    return row_for(with_files(pr(tier=tier_line), *paths), root_body())


@pytest.mark.parametrize(
    "paths,expected",
    [
        (["app/services/sql_validator.py"], "high"),
        (
            ["app/utils/sql_generator.py", "docs/x.md"],
            "high",
        ),  # owner's call: cohort fixes are High
        (["app/services/sql_generator.py"], "medium"),  # no such file: the old, wrong path
        (["app/security/auth.py"], "high"),
        (["tests/fixtures/transpiler_expected_outputs.py"], "high"),  # a golden fixture
        (["tests/eval/fixtures/recorded.json"], "high"),
        (
            [
                "docs/a.md",
                "tests/test_x.py",
                "README.md",
                ".claude/skills/x/SKILL.md",
                "scripts/dials.sh",
            ],
            "low",
        ),
        (["app/web_ui/researcher_portal.py"], "medium"),
        (
            ["scripts/review_metrics.py", "tests/test_review_metrics.py"],
            "medium",
        ),  # a dev script is Medium
        (["docs/a.md", "app/web_ui/x.py"], "medium"),  # not ALL low
        (
            ["app/sql_on_fhir/runner/x.py", "app/services/sql_validator.py"],
            "high",
        ),  # any High path wins
    ],
)
def test_tier_without_a_line_is_derived_from_the_file_list(paths, expected):
    r = tier_row(None, *paths)

    assert r["tier"] == expected
    assert r["tier_source"] == "paths"


def test_an_explicit_tier_line_wins_over_the_path_list():
    r = tier_row("low", "app/services/sql_validator.py")

    assert (r["tier"], r["tier_source"]) == ("low", "line")


def test_a_pr_whose_file_list_cannot_be_read_stays_unknown():
    for p in (pr(tier=None), with_files(pr(tier=None))):  # key missing, and empty list
        r = row_for(p, root_body())
        assert (r["tier"], r["tier_source"]) == ("unknown", "none")


# ------------------------------------------------------------------ noted, not filed


def test_noted_not_filed_has_its_own_column():
    body = (
        "- Reviewer 1 (x): fresh-context subagent, 1 pass(es), SHIP\n"
        "- Findings:\n"
        "  - finding 1: a → fixed\n"
        "  - finding 2: b → noted, not filed\n"
        "  - finding 3: c → accepted\n"
    )

    f = rm.parse_findings(body)

    assert (f["findings_total"], f["findings_fixed"], f["findings_noted"]) == (3, 1, 1)
    assert f["warnings"] == []
    assert "findings_noted" in rm.COLUMNS


def test_findings_none_is_zero_in_every_count_column_including_noted():
    f = rm.parse_findings("- Findings: none\n")

    assert (f["findings_total"], f["findings_noted"]) == (0, 0)


def test_an_unparseable_block_leaves_noted_empty_too():
    assert rm.parse_findings("- Findings: prose\n")["findings_noted"] is None


# ------------------------------------------------------------------ coverage in the summary


def test_summary_says_how_many_findings_parsed_and_how_many_tiers_came_from_paths():
    rows = [
        row_for(with_files(pr(1, tier=None), "docs/a.md"), root_body()),  # low, from paths, parsed
        row_for(with_files(pr(2, tier=None), "docs/a.md"), None),  # low, from paths, not parsed
        row_for(pr(3, "low"), root_body()),  # low, from a line, parsed
    ]

    s = rm.summarize(rows, now=NOW)
    low = s["tiers"][0]

    assert low["findings_parsed"] == "2/3"
    assert low["tier_from_paths"] == 2
    assert s["total"] == {"prs": 3, "findings_parsed": "2/3", "tier_from_paths": 2}
    text = rm.format_summary(rows, [], NOW, 30)
    assert "findings parsed" in text and "2/3" in text and "from paths" in text


# ------------------------------------------------------------------ reviewer findings


def test_the_unfilled_template_placeholder_is_not_a_tier():
    assert rm.parse_tier("- **Risk tier:** <low|medium|high>\n") == "unknown"
    assert rm.parse_tier("- **Risk tier:** medium\n") == "medium"


def test_a_citation_written_as_pr_hash_counts():
    assert rm.cites({"title": "see PR#518", "body": ""}, [518])
    assert not rm.cites({"title": "see #5180 and 1#51", "body": ""}, [518, 51])


def test_a_blank_line_inside_the_findings_block_is_a_warning_not_a_short_count():
    body = "- Findings:\n  - finding 1: a → fixed\n\n  - finding 2: b → fixed\n"

    f = rm.parse_findings(body)

    assert f["findings_total"] is None
    assert any("blank line" in w for w in f["warnings"])


def test_cli_counts_only_reopenings_after_the_merge(tmp_path):
    env = make_env(tmp_path, [listed(518)], [])
    events = [
        {"event": "reopened", "created_at": "2026-11-15T03:00:00Z"},  # before the 04:18 merge
        {"event": "reopened", "created_at": "2026-11-16T00:00:00Z"},  # after it
        {"event": "closed", "created_at": "2026-11-16T01:00:00Z"},
    ]
    (tmp_path / "data" / "events456.json").write_text(json.dumps(events))

    _, out = run_cli(tmp_path, env)

    assert list(csv.DictReader(out.read_text().splitlines()))[0]["escapes"] == "1"


# ------------------------------------------------------------------ follow-up window starts 24 h before the PR


def test_a_routed_issue_filed_2_hours_before_the_pr_opened_is_a_follow_up():
    # PR created 2026-11-15T02:05:41Z; the review runs before the PR opens.
    i = issue(640, "2026-11-15T00:05:00Z")

    assert row_for(pr(), att("routed to #640"), issues=[i])["followups_filed"] == 1


def test_a_routed_issue_created_more_than_24_hours_before_the_pr_opened_is_not_a_follow_up():
    i = issue(641, "2026-11-13T20:00:00Z")

    assert row_for(pr(), att("routed to #641"), issues=[i])["followups_filed"] == 0


def test_the_routed_window_opens_exactly_24_hours_before_the_pr():
    on_edge = issue(642, "2026-11-14T02:05:41Z")
    just_before = issue(643, "2026-11-14T02:05:40Z")

    r = row_for(pr(), att("routed to #642", "routed to #643"), issues=[on_edge, just_before])

    assert r["followups_filed"] == 1


def test_a_bug_issue_filed_1_hour_after_the_merge_is_an_escape_only():
    i = issue(644, "2026-11-15T05:18:49Z", body="regression from #518", labels=["bug"])

    r = row_for(pr(), root_body(), issues=[i])

    assert (r["escapes"], r["followups_filed"]) == (1, 0)


def test_the_routed_window_closes_exactly_24_hours_after_the_merge():
    at_edge = issue(650, "2026-11-16T04:18:49Z")
    one_second_later = issue(651, "2026-11-16T04:18:50Z")

    r = row_for(pr(), att("routed to #650", "routed to #651"), issues=[at_edge, one_second_later])

    assert r["followups_filed"] == 1


def test_cli_searches_issues_from_24_hours_before_the_oldest_pr(tmp_path):
    p = listed(518, merged="2026-10-26T05:00:00Z")
    p["createdAt"] = "2026-10-26T01:00:00Z"
    env = make_env(tmp_path, [p], [])

    run_cli(tmp_path, env)

    # The earliest search date is the day before the oldest PR opened, so a follow-up filed in
    # the 24 hours before it is fetched (the issue flow window starts later, 2026-10-26).
    assert "created:>=2026-10-25" in (tmp_path / "data" / "issue_searches.log").read_text()


# ------------------------------------------------------------------ #529: reader, root comment, clock, windows, caps


def test_a_failing_attestation_reader_fails_the_run_and_shows_its_error(tmp_path):
    env = {**make_env(tmp_path, [listed(518)], []), "FAKE_FAIL_READER": "1"}

    r, out = run_cli(tmp_path, env)

    assert r.returncode != 0
    assert "rate limit" in r.stderr
    assert not out.exists()  # no CSV with a misleading parse warning


def test_a_reader_that_prints_nothing_fails_the_run(monkeypatch):
    monkeypatch.setattr(rm, "run", lambda cmd, check=True: "")

    with pytest.raises(SystemExit) as e:
        rm.read_attestation(518)

    assert "printed nothing" in str(e.value)


def comments_with(**overrides):
    """pr518's root attestation, changed, plus the real comments (the root is replaced)."""
    comments = copy.deepcopy(load("pr518.json")["comments"])
    comments[0].update(overrides)
    return comments


@pytest.mark.parametrize(
    "overrides",
    [
        {"author": {"login": "someone-else"}},
        {"authorAssociation": "CONTRIBUTOR"},
        {"includesCreatedEdit": True},
    ],
)
def test_a_root_comment_the_reader_would_not_trust_is_not_chosen(overrides):
    comments = comments_with(**overrides)
    out = f"ROOT {ROOT_SHA} verdict=SHIP\n"

    body, warnings = rm.pick_root_body(out, comments, PR518_URL)

    assert body is None
    assert "root attestation comment not found" in warnings


def test_the_unedited_owner_root_wins_over_a_later_edited_copy_of_it():
    comments = load("pr518.json")["comments"]
    edited = {
        **copy.deepcopy(comments[0]),
        "includesCreatedEdit": True,
        "body": comments[0]["body"] + "\n",
    }
    out = f"ROOT {ROOT_SHA} verdict=SHIP\n"

    body, _ = rm.pick_root_body(out, [comments[0], edited], PR518_URL)

    assert body == comments[0]["body"]


def test_a_zone_less_now_is_read_as_utc_whatever_the_local_zone(monkeypatch):
    import time

    monkeypatch.setenv("TZ", "America/Chicago")
    time.tzset()
    try:
        assert rm.ts("2026-11-16T12:00:00") == datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        assert rm.ts("2026-11-16T12:00:00Z") == datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)
        assert rm.ts("2026-11-16T12:00:00-06:00") == datetime(
            2026, 11, 16, 18, 0, tzinfo=timezone.utc
        )
    finally:
        monkeypatch.delenv("TZ")
        time.tzset()


def test_a_revert_more_than_14_days_after_the_merge_is_not_an_escape():
    merged = rm.ts("2026-11-15T04:18:49Z")
    log = (
        'aaa\x1fRevert "x (#518)"\x1f\x1f2026-11-29T04:18:49+00:00\x1e'  # on the edge: counts
        'bbb\x1fRevert "x (#518)"\x1f\x1f2026-11-29T04:18:50+00:00\x1e'  # a second late
    )

    assert rm.reverts_naming(log, 518, merged) == ["aaa"]


def test_a_reopening_more_than_14_days_after_the_merge_is_not_an_escape(tmp_path):
    env = make_env(tmp_path, [listed(518)], [])
    events = [
        {"event": "reopened", "created_at": "2026-11-29T04:18:49Z"},  # on the edge
        {"event": "reopened", "created_at": "2026-11-29T04:18:50Z"},
    ]
    (tmp_path / "data" / "events456.json").write_text(json.dumps(events))

    _, out = run_cli(tmp_path, env)

    assert list(csv.DictReader(out.read_text().splitlines()))[0]["escapes"] == "1"


def test_an_event_list_of_exactly_100_warns_on_stderr(tmp_path):
    env = make_env(tmp_path, [listed(518)], [])
    events = [{"event": "labeled", "created_at": "2026-11-15T03:00:00Z"}] * 100
    (tmp_path / "data" / "events456.json").write_text(json.dumps(events))

    r, _ = run_cli(tmp_path, env)

    assert "100 events" in r.stderr


def test_a_file_list_of_exactly_100_warns_on_stderr(tmp_path):
    p = listed(518)
    p["files"] = [{"path": f"docs/f{k}.md"} for k in range(100)]
    env = make_env(tmp_path, [p], [])

    r, _ = run_cli(tmp_path, env)

    assert "100 files" in r.stderr


def test_citations_ignore_fenced_code_blocks():
    text = "see below\n```\nlog line: #518 failed\n```\nend"

    assert not rm.cites({"title": "x", "body": text}, [518])
    assert rm.cites({"title": "x", "body": "```\ncode\n```\nbut also #518"}, [518])


def test_citations_ignore_references_to_other_repositories():
    other = "other-org/other-repo#518 and https://github.com/other-org/other-repo/issues/518"

    assert not rm.cites({"title": other, "body": ""}, [518])
    assert rm.cites(
        {"title": "https://github.com/jagnyesh/researchflow/pull/518", "body": ""}, [518]
    )


def test_check_body_exits_zero_for_a_well_formed_body_and_non_zero_with_warnings(tmp_path):
    good = tmp_path / "good.md"
    good.write_text(att("fixed", "filed #9"))
    bad = tmp_path / "bad.md"
    bad.write_text("## Review attestation\n- Findings:\n  - finding 1: a → looks fine\n")
    two = tmp_path / "two.md"
    two.write_text(att("filed #1", "filed #2"))
    cmd = [sys.executable, "-I", str(REPO / "scripts/review_metrics.py"), "--check-body"]

    ok = subprocess.run([*cmd, str(good)], capture_output=True, text=True)
    no = subprocess.run([*cmd, str(bad)], capture_output=True, text=True)
    many = subprocess.run([*cmd, str(two)], capture_output=True, text=True)

    assert ok.returncode == 0, ok.stderr
    assert no.returncode != 0 and "disposition" in no.stderr
    assert many.returncode != 0 and "files 2 issues" in many.stderr


def test_the_summary_lists_prs_with_more_than_one_filed_issue(tmp_path):
    p = listed(518)
    env = make_env(tmp_path, [p], [])
    # 518's recorded attestation routes to two issues; make the fixture file two instead.
    view = load("pr518.json")
    view["comments"][0]["body"] = (
        view["comments"][0]["body"]
        .replace("routed to #517", "filed #517")
        .replace("routed to #431", "filed #431")
    )
    (tmp_path / "data" / "pr518.json").write_text(json.dumps(view))

    r, _ = run_cli(tmp_path, env, "--summary")

    assert "files more than one issue" in r.stdout
    assert "#518" in r.stdout


# ------------------------------------------------------------------ review of #529: parsing gaps


@pytest.mark.parametrize(
    "disp,filed,routed",
    [
        ("filed #12 and #13", [12, 13], []),
        ("filed #15,#16", [15, 16], []),
        ("routed to #1, #2", [], [1, 2]),
        ("fixed (x); filed #4 and routed to #5, #6", [4], [5, 6]),
    ],
)
def test_a_list_of_issues_after_filed_or_routed_is_read_whole(disp, filed, routed):
    f = rm.parse_findings(att(disp))

    assert (f["filed_issues"], f["routed_issues"]) == (filed, routed)


def test_noted_not_filed_followed_by_an_issue_number_is_not_a_filing():
    f = rm.parse_findings(att("noted, not filed #5"))

    assert f["filed_issues"] == []
    assert (f["findings_noted"], f["findings_routed"]) == (1, 0)


def test_a_comment_that_only_quotes_the_root_hash_mid_line_is_not_the_root():
    comments = load("pr518.json")["comments"]
    quote = {
        **copy.deepcopy(comments[0]),
        "body": f"## Review attestation\nsee - Reviewed-Commit: {ROOT_SHA} x",
    }
    out = f"ROOT {ROOT_SHA} verdict=SHIP\n"

    body, _ = rm.pick_root_body(out, [comments[0], quote], PR518_URL)

    assert body == comments[0]["body"]


def test_arrival_labels_are_read_for_a_filed_issue_older_than_the_issue_search(tmp_path):
    view = load("pr518.json")
    view["comments"][0]["body"] = (
        view["comments"][0]["body"]
        .replace("routed to #517", "filed #99")
        .replace("routed to #431", "noted, not filed")
    )
    p = listed(518)
    env = make_env(tmp_path, [p], [])
    (tmp_path / "data" / "pr518.json").write_text(json.dumps(view))
    (tmp_path / "data" / "issue99.json").write_text(
        json.dumps({"createdAt": "2026-09-01T00:00:00Z"})
    )
    events = [
        {
            "event": "labeled",
            "label": {"name": "ready-for-agent"},
            "created_at": "2026-09-01T00:00:10Z",
        }
    ]
    (tmp_path / "data" / "events99.json").write_text(json.dumps(events))

    _, out = run_cli(tmp_path, env)

    assert "follow-up #99 arrived ready-for-agent" in out.read_text()


@pytest.mark.parametrize(
    "disp", ["filed #1 and then #2", "filed #1 #2", "filed #1 & #2", "routed to #1/#2"]
)
def test_an_issue_list_the_parser_cannot_read_whole_is_a_warning(disp):
    f = rm.parse_findings(att(disp))

    assert any("unread issue" in w for w in f["warnings"])


def test_an_issue_mentioned_before_the_disposition_keyword_is_not_a_warning():
    assert rm.parse_findings(att("fixed (see #12); filed #4"))["warnings"] == []


@pytest.mark.parametrize(
    "disp",
    ["filed #4 (related to #3)", "routed to #517 (part of #400)", "filed #4; see #3"],
)
def test_a_cross_reference_after_a_filed_issue_is_not_an_unread_issue(disp):
    assert rm.parse_findings(att(disp))["warnings"] == []


# ------------------------------------------------- #542: the checks the attestation status runs

CLI = [sys.executable, "-I", str(REPO / "scripts/review_metrics.py")]


def cli(*args, stdin=None):
    return subprocess.run([*CLI, *args], input=stdin, capture_output=True, text=True)


@pytest.mark.parametrize(
    "line",
    [
        None,
        "- Reviewed commit: " + ROOT_SHA,
        "- Reviewed-Commit: 9edbfd7",
        "- Reviewed-Commit: none",
        # The 7.5 reader keeps trailing whitespace and then calls the attestation stale.
        f"- Reviewed-Commit: {ROOT_SHA} ",
    ],
)
def test_check_body_fails_a_missing_or_misspelled_reviewed_commit(tmp_path, line):
    body = att("fixed").replace(f"- Reviewed-Commit: {ROOT_SHA}", line or "")
    f = tmp_path / "a.md"
    f.write_text(body)
    r = cli("--check-body", str(f))
    assert r.returncode == 1
    assert "Reviewed-Commit" in r.stderr


def test_check_root_blocks_only_problems_that_blank_a_metric():
    assert rm.blocking_problems(att("fixed", "filed #1", "filed #2")) == []
    assert rm.blocking_problems(att("fixed", "routed to #1 and then #2")) == []
    assert rm.blocking_problems(att("looks fine")) == [
        "a disposition is not fixed, accepted, filed, routed or noted"
    ]
    assert rm.blocking_problems(att("fixed").replace("1 pass(es)", "one pass")) == [
        "no pass count on a Reviewer line"
    ]
    assert rm.blocking_problems(root_body()) == []
    assert rm.blocking_problems(root_body("pr317.json")) != []


def test_check_root_reads_stdin_and_prints_one_line():
    ok = cli("--check-root", "-", stdin=att("fixed"))
    bad = cli("--check-root", "-", stdin=att("fixed").replace("  - finding 1", "  - Finding 1"))
    assert (ok.returncode, ok.stdout) == (0, "")
    assert bad.returncode == rm.PROBLEM_EXIT
    assert bad.stdout.count("\n") == 1 and "finding N" in bad.stdout


@pytest.mark.parametrize(
    "body,problem",
    [
        ("- Red-first: n/a (docs-only; no test is added or changed)\n", None),
        (
            "Red-first: tests/test_x.py: base 0123 pytest exit 1 (red); here 0123 pytest exit 0\n",
            None,
        ),
        ("- **Red-first:** a manual equivalent was run\n", None),
        ("- red-first: n/a (pure refactor)\n", None),
        ("- **Red-first**: a manual equivalent was run\n", None),
        ("1. Red-first: n/a (docs-only)\n", None),
        ("> - Red-first: n/a (docs-only)\n", None),
        ("- Red-first: n/a (docs-only)\r\n", None),
        ("", "no filled"),
        ("- Red-first note: x: 2 test(s) pass on the base\n", "no filled"),
        ("- Red-first: <per validate-and-ship Step 1>\n", "no filled"),
        ("- Red-first:\n", "no filled"),
        ("- Red-first: n/a\n", "n/a (<reason>)"),
        ("- Red-first: n/a ( )\n", "n/a (<reason>)"),
        ("- Red-first: N/A docs\n", "n/a (<reason>)"),
        ("- Red-first: n/a (docs)\n- Red-first: <per validate-and-ship Step 1>\n", "no filled"),
    ],
)
def test_red_first_problem(body, problem):
    got = rm.red_first_problem(body)
    assert (got is None) if problem is None else (problem in got), got


def test_check_red_first_cli():
    ok = cli("--check-red-first", "-", stdin="- Red-first: n/a (docs-only)\n")
    bad = cli("--check-red-first", "-", stdin="- Commands run: pytest\n")
    assert (ok.returncode, ok.stdout) == (0, "")
    assert bad.returncode == rm.PROBLEM_EXIT
    assert bad.stdout.startswith("PR body has no filled Red-first: line")
