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

    body, warnings = rm.pick_root_body(out, comments)

    assert warnings == []
    assert f"Reviewed-Commit: {ROOT_SHA}" in body
    assert "Carried-From" not in body


def test_a_root_without_a_commit_hash_is_a_warning():
    comments = load("pr317.json")["comments"]

    body, warnings = rm.pick_root_body("ROOT none verdict=none\n", comments)

    assert body is None
    assert warnings


def test_missing_attestation_and_edited_ones_are_warnings():
    assert rm.pick_root_body("MISSING\n", [])[1]
    _, w = rm.pick_root_body(
        f"EDITED https://x/1\nROOT {ROOT_SHA} verdict=SHIP\n", load("pr518.json")["comments"]
    )
    assert any("edited" in x for x in w)


# ------------------------------------------------------------------ tier


def test_tier_comes_from_the_risk_tier_line_and_defaults_to_unknown():
    assert row_for(pr(tier="high"), root_body())["tier"] == "high"
    assert row_for(pr(tier="Low"), root_body())["tier"] == "low"
    assert row_for(pr(tier=None), root_body())["tier"] == "unknown"


# ------------------------------------------------------------------ follow-ups and escapes


def test_issue_filed_before_the_merge_is_a_follow_up_not_an_escape():
    # Created during review (after the PR opened, before it merged), cites the PR, labelled bug.
    i = issue(600, "2026-11-15T03:00:00Z", title="review of #518", labels=["bug"])

    r = row_for(pr(), root_body(), issues=[i])

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


def test_an_issue_that_existed_before_the_pr_opened_is_not_a_follow_up():
    i = issue(517, "2026-11-14T00:00:00Z", body="routed from #518")

    assert row_for(pr(), root_body(), issues=[i])["followups_filed"] == 0


def test_follow_ups_may_cite_the_closed_issue_and_dedupe_by_number():
    both = issue(610, "2026-11-15T03:00:00Z", body="#518 and also #456")
    via_issue = issue(611, "2026-11-15T20:00:00Z", body="found while closing #456")
    unrelated = issue(612, "2026-11-15T20:00:00Z", body="about #4561 and #5180")

    r = row_for(pr(), root_body(), issues=[both, via_issue, unrelated, copy.deepcopy(both)])

    assert r["followups_filed"] == 2


def test_the_follow_up_window_ends_24_hours_after_the_merge():
    inside = issue(620, "2026-11-16T04:00:00Z", body="#518")
    outside = issue(621, "2026-11-16T04:30:00Z", body="#518")

    assert row_for(pr(), root_body(), issues=[inside, outside])["followups_filed"] == 1


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
case "$1 $2" in
  "pr list")
    jq -c --arg f "$fields" '.[] | . as $d | reduce ($f|split(",")[]) as $k ({}; .[$k] = $d[$k])' \
      "$FAKE_DIR/prs.json" | jq -s .
    ;;
  "pr view")
    trim "$FAKE_DIR/pr$3.json" "$fields" | jq -r "$query"
    ;;
  "issue list")
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
        issue(630, "2026-11-15T03:00:00Z", body="#518"),
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
            ["app/services/sql_generator.py", "docs/x.md"],
            "high",
        ),  # owner's call: cohort fixes are High
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
