"""Tests for scripts/attestation.sh (`read`, `carry`, `status`).

The script is the reader behind the required `attestation` status check, so a wrong
`success` lets a PR merge on a stale or blocked review and a wrong `failure` blocks
every merge. The real script runs against a fake `gh` (first on PATH) that serves
JSON fixtures and, like the real one, returns only the fields named in `--json`,
filtered through `-q`. `carry` and `status` run real git in a temporary repository.
No network call is made.

Fixtures in tests/fixtures/attestation/ are `gh pr view <n> --json headRefOid,url,comments`
output recorded from this repo (2026-11-14), trimmed to the fields the script reads
(`author`, `authorAssociation`, `body`, `includesCreatedEdit`, `url`):

- pr484.json: the PR that added the script. A real owner SHIP (Reviewed-Commit
  bba4918...) and a real owner carry-forward (Reviewed-Commit 77c4864..., which is
  also the head).
- pr475.json: a throwaway PR from the same work. Two owner SHIPs and an owner
  carry-forward that was edited after posting (`includesCreatedEdit: true`).
- pr480.json: a throwaway PR with no attestation, only an unrelated comment.

No real BLOCK, SHIP-WITH-FIXES or non-owner attestation exists on this repo, so those
cases take a real comment and change one field in the test (verdict, author,
association, head). The structure is the recorded one; only the changed value is ours.
"""

import copy
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "scripts" / "attestation.sh"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "attestation"

PR484_SHIP_COMMIT = "bba4918f0ddc59cd7688d36139bb814b53b072e0"
PR484_HEAD = "77c4864733b327581754f0c18a2547f717fddf2c"

FAKE_GH = r"""#!/usr/bin/env bash
# Fake `gh pr view <n> --json <fields> [-q <jq>]` over $FAKE_GH_FIXTURE.
[ -z "${FAKE_GH_FAIL:-}" ] || { echo "gh: simulated failure" >&2; exit 1; }
# Scripted HTTP outcomes: one code per call, consumed from $FAKE_GH_<KIND>_CODES (a file, one code per
# line; an empty or missing file means 200). Non-200 prints what gh prints and fails.
scripted() {
  local f=$1 code
  [ -s "$f" ] || return 0
  code=$(head -n1 "$f"); tail -n +2 "$f" >"$f.next"; mv "$f.next" "$f"
  [ "$code" = 200 ] && return 0
  echo "gh: Simulated (HTTP $code)" >&2
  exit 1
}
if [ "$1" = api ]; then
  scripted "${FAKE_GH_API_CODES:-/nonexistent}"
  echo "$*" >>"$FAKE_GH_API_LOG"
  exit 0
fi
[ "$1 $2" = "pr view" ] || { echo "fake gh: unsupported: $*" >&2; exit 64; }
scripted "${FAKE_GH_VIEW_CODES:-/nonexistent}"
[ "$1 $2" = "pr view" ] || { echo "fake gh: unsupported: $*" >&2; exit 64; }
shift 3
fields="" query="."
while [ $# -gt 0 ]; do
  case "$1" in
    --json) fields=$2; shift 2 ;;
    -q) query=$2; shift 2 ;;
    *) echo "fake gh: unsupported arg $1" >&2; exit 64 ;;
  esac
done
jq -e --arg f "$fields" '. as $d | ($f | split(",")) | map(select(in($d) | not)) | length == 0' \
  "$FAKE_GH_FIXTURE" >/dev/null || { echo "fake gh: unknown field in $fields" >&2; exit 1; }
jq -c --arg f "$fields" '. as $d | reduce ($f | split(",")[]) as $k ({}; .[$k] = $d[$k])' "$FAKE_GH_FIXTURE" \
  | jq -r "$query"
"""


def load(name):
    return json.loads((FIXTURES / name).read_text())


def comment(pr, i):
    return copy.deepcopy(pr["comments"][i])


def with_verdict(c, verdict):
    lines = [
        f"- Verdict: {verdict}" if ln.startswith("- Verdict:") else ln
        for ln in c["body"].split("\n")
    ]
    c["body"] = "\n".join(lines)
    return c


@pytest.fixture
def fake_gh(tmp_path):
    bindir = tmp_path / "bin"
    bindir.mkdir()
    gh = bindir / "gh"
    gh.write_text(FAKE_GH)
    gh.chmod(gh.stat().st_mode | stat.S_IEXEC)

    class Fake:
        env = {
            **os.environ,
            "PATH": f"{bindir}{os.pathsep}{os.environ['PATH']}",
            "FAKE_GH_FIXTURE": str(tmp_path / "pr.json"),
            "FAKE_GH_API_LOG": str(tmp_path / "api.log"),
            "FAKE_GH_API_CODES": str(tmp_path / "api.codes"),
            "FAKE_GH_VIEW_CODES": str(tmp_path / "view.codes"),
            "ATTESTATION_RETRY_SLEEP": "0",
            "GITHUB_REPOSITORY": "o/r",
            "GITHUB_SERVER_URL": "https://github.example",
            "GITHUB_RUN_ID": "7",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        }
        cwd = tmp_path

        @classmethod
        def serve(cls, pr):
            Path(cls.env["FAKE_GH_FIXTURE"]).write_text(json.dumps(pr))

        @classmethod
        def run(cls, *args, cwd=None):
            return subprocess.run(
                ["bash", str(SCRIPT), *args],
                env=cls.env,
                cwd=cwd or cls.cwd,
                capture_output=True,
                text=True,
                timeout=60,
            )

    return Fake


def status(fake_gh, pr, head=None, cwd=None):
    pr = copy.deepcopy(pr)
    if head is not None:
        pr["headRefOid"] = head
    fake_gh.serve(pr)
    r = fake_gh.run("status", "1", cwd=cwd)
    return r


def parse(r):
    assert r.returncode == 0, r.stderr
    state, head, desc = r.stdout.rstrip("\n").split("\t")
    assert desc.strip(), "description must not be empty"
    return state, head, desc


# ---------------------------------------------------------------- fake gh sanity


def test_fake_gh_returns_only_requested_fields(fake_gh):
    fake_gh.serve(load("pr484.json"))
    r = subprocess.run(
        ["gh", "pr", "view", "1", "--json", "headRefOid"],
        env=fake_gh.env,
        capture_output=True,
        text=True,
    )
    assert json.loads(r.stdout) == {"headRefOid": PR484_HEAD}


# ---------------------------------------------------------------- status (no git)


def test_status_no_attestation_fails(fake_gh):
    state, _, desc = parse(status(fake_gh, load("pr480.json")))
    assert state == "failure"
    assert "No attestation" in desc


def test_status_ship_on_head_succeeds(fake_gh):
    pr = load("pr484.json")
    pr["comments"] = [comment(pr, 0)]
    pr["headRefOid"] = PR484_SHIP_COMMIT  # the head when the SHIP was posted
    state, head, _ = parse(status(fake_gh, pr))
    assert (state, head) == ("success", PR484_SHIP_COMMIT)


def test_status_ship_with_fixes_succeeds(fake_gh):
    pr = load("pr484.json")
    pr["comments"] = [with_verdict(comment(pr, 0), "SHIP-WITH-FIXES")]
    pr["headRefOid"] = PR484_SHIP_COMMIT
    assert parse(status(fake_gh, pr))[0] == "success"


def test_status_block_fails(fake_gh):
    pr = load("pr484.json")
    pr["comments"] = [with_verdict(comment(pr, 0), "BLOCK")]
    pr["headRefOid"] = PR484_SHIP_COMMIT
    state, _, desc = parse(status(fake_gh, pr))
    assert state == "failure"
    assert "BLOCK" in desc


def test_status_unknown_verdict_fails(fake_gh):
    pr = load("pr484.json")
    pr["comments"] = [with_verdict(comment(pr, 0), "MAYBE")]
    pr["headRefOid"] = PR484_SHIP_COMMIT
    assert parse(status(fake_gh, pr))[0] == "failure"


def test_status_stale_attestation_fails(fake_gh):
    pr = load("pr484.json")
    pr["comments"] = [comment(pr, 0)]
    pr["headRefOid"] = PR484_HEAD  # pushed after the review of bba4918
    state, _, desc = parse(status(fake_gh, pr))
    assert state == "failure"
    assert "bba4918" in desc


def test_status_edited_owner_attestation_fails(fake_gh):
    pr = load("pr475.json")
    assert pr["comments"][2]["includesCreatedEdit"] is True
    state, _, desc = parse(status(fake_gh, pr))
    assert state == "failure"
    assert "edited" in desc


@pytest.mark.parametrize(
    "login,assoc",
    [("jagnyesh", "CONTRIBUTOR"), ("someone-else", "NONE"), ("someone-else", "OWNER")],
)
def test_status_non_owner_attestation_fails(fake_gh, login, assoc):
    pr = load("pr484.json")
    c = comment(pr, 0)
    c["author"]["login"] = login
    c["authorAssociation"] = assoc
    pr["comments"] = [c]
    pr["headRefOid"] = PR484_SHIP_COMMIT
    state, _, desc = parse(status(fake_gh, pr))
    assert state == "failure"
    assert "No attestation" in desc


def test_read_reports_ignored_non_owner_lines(fake_gh):
    pr = load("pr484.json")
    c = comment(pr, 0)
    c["authorAssociation"] = "NONE"
    pr["comments"] = [c]
    fake_gh.serve(pr)
    r = fake_gh.run("read", "1")
    assert r.returncode == 0, r.stderr
    lines = r.stdout.splitlines()
    assert "MISSING" in lines
    assert any(ln.startswith("IGNORED jagnyesh NONE ") for ln in lines)


def test_read_prints_newest_and_root(fake_gh):
    fake_gh.serve(load("pr484.json"))
    r = fake_gh.run("read", "1")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines() == [
        f"NEWEST {PR484_HEAD} head verdict=SHIP (carried forward) carried-from={PR484_SHIP_COMMIT}",
        f"ROOT {PR484_SHIP_COMMIT} verdict=SHIP",
    ]


def test_read_prints_edited_line(fake_gh):
    fake_gh.serve(load("pr475.json"))
    r = fake_gh.run("read", "1")
    edited = [ln for ln in r.stdout.splitlines() if ln.startswith("EDITED ")]
    assert edited == ["EDITED " + load("pr475.json")["comments"][2]["url"]]


def test_status_empty_head_exits_3(fake_gh):
    r = status(fake_gh, load("pr484.json"), head="")
    assert r.returncode == 3


def test_status_gh_failure_exits_nonzero(fake_gh):
    fake_gh.serve(load("pr484.json"))
    fake_gh.env["FAKE_GH_FAIL"] = "1"
    try:
        r = fake_gh.run("status", "1")
    finally:
        del fake_gh.env["FAKE_GH_FAIL"]
    assert r.returncode == 1
    assert r.stdout == ""


def test_bad_pr_number_prints_usage(fake_gh):
    r = fake_gh.run("read", "abc")
    assert r.returncode == 2


# --------------------------------------------------------------- set-status + retry


def script_codes(fake_gh, kind, codes):
    Path(fake_gh.env[f"FAKE_GH_{kind}_CODES"]).write_text("".join(f"{c}\n" for c in codes))


def posted(fake_gh):
    log = Path(fake_gh.env["FAKE_GH_API_LOG"])
    return log.read_text().splitlines() if log.exists() else []


def ship_on_head():
    pr = load("pr484.json")
    pr["comments"] = [comment(pr, 0)]
    pr["headRefOid"] = PR484_SHIP_COMMIT
    return pr


def set_status(fake_gh, pr, view=(), api=()):
    fake_gh.serve(pr)
    script_codes(fake_gh, "VIEW", view)
    script_codes(fake_gh, "API", api)
    return fake_gh.run("set-status", "1")


def test_set_status_posts_success_for_a_ship_on_head(fake_gh):
    r = set_status(fake_gh, ship_on_head())
    assert r.returncode == 0, r.stderr
    (call,) = posted(fake_gh)
    assert f"statuses/{PR484_SHIP_COMMIT}" in call and "state=success" in call


def test_set_status_502_then_200_on_post_ends_in_success(fake_gh):
    r = set_status(fake_gh, ship_on_head(), api=[502, 200])
    assert r.returncode == 0, r.stderr
    calls = posted(fake_gh)
    assert len(calls) == 1 and "state=success" in calls[0]


def test_set_status_persistent_502_on_post_fails_the_job(fake_gh):
    r = set_status(fake_gh, ship_on_head(), api=[502, 502, 502, 200])
    assert r.returncode != 0
    assert posted(fake_gh) == []


def test_set_status_502_then_200_on_reader_view_ends_in_success(fake_gh):
    r = set_status(fake_gh, ship_on_head(), view=[503, 200])
    assert r.returncode == 0, r.stderr
    assert "state=success" in posted(fake_gh)[0]


def test_set_status_persistent_502_on_reader_never_posts_success(fake_gh):
    r = set_status(fake_gh, ship_on_head(), view=[502] * 9)
    assert r.returncode != 0
    assert not any("state=success" in c for c in posted(fake_gh))


def test_set_status_4xx_on_post_is_not_retried(fake_gh):
    r = set_status(fake_gh, ship_on_head(), api=[422, 200])
    assert r.returncode != 0
    assert posted(fake_gh) == []


def test_set_status_4xx_on_view_is_not_retried_and_never_succeeds(fake_gh):
    r = set_status(fake_gh, ship_on_head(), view=[404, 200, 200, 200, 200, 200])
    assert not any("state=success" in c for c in posted(fake_gh))
    # The 404 was not retried: the reader gave up, and only the fallback head lookup consumed a 200.
    assert Path(fake_gh.env["FAKE_GH_VIEW_CODES"]).read_text().count("200") == 4
    assert "state=error" in posted(fake_gh)[0], r.stderr


def test_set_status_reader_failure_posts_error_not_success(fake_gh):
    # A non-HTTP crash in the reader (e.g. jq) must post `error`, never success.
    pr = ship_on_head()
    pr["comments"] = "not-a-list"
    r = set_status(fake_gh, pr)
    (call,) = posted(fake_gh)
    assert "state=error" in call, (r.stdout, r.stderr)


def test_set_status_failure_verdict_still_posts_failure(fake_gh):
    r = set_status(fake_gh, load("pr480.json"))
    assert r.returncode == 0, r.stderr
    assert "state=failure" in posted(fake_gh)[0]


# ------------------------------------------------------------ real git (carry)


def git(cwd, *args):
    r = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
        env={
            **os.environ,
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_SYSTEM": os.devnull,
            "GIT_AUTHOR_NAME": "t",
            "GIT_AUTHOR_EMAIL": "t@example.invalid",
            "GIT_COMMITTER_NAME": "t",
            "GIT_COMMITTER_EMAIL": "t@example.invalid",
        },
    )
    return r.stdout.strip()


def commit_file(cwd, name, content, msg):
    (Path(cwd) / name).write_text(content)
    git(cwd, "add", name)
    git(cwd, "commit", "-q", "-m", msg)
    return git(cwd, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    """origin (bare) + clone. main has shared.txt (10 lines) and a.txt."""
    origin = tmp_path / "origin.git"
    work = tmp_path / "work"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    git(tmp_path, "clone", "-q", str(origin), str(work))
    git(work, "checkout", "-q", "-b", "main")
    commit_file(work, "shared.txt", "".join(f"{i}\n" for i in range(10)), "base")
    git(work, "push", "-q", "origin", "main")

    class R:
        pass

    r = R()
    r.origin, r.work = origin, work
    return r


def publish(repo, pr_ref_sha, main_sha):
    git(repo.work, "push", "-q", "origin", f"{main_sha}:refs/heads/main", "--force")
    git(repo.work, "push", "-q", "origin", f"{pr_ref_sha}:refs/pull/1/head", "--force")


def carry_setup(repo, both_sides=False):
    """Branch commit `old`, main advances to `m`, branch merges main -> `new`."""
    base = git(repo.work, "rev-parse", "HEAD")
    git(repo.work, "checkout", "-q", "-b", "pr", base)
    shared = "".join(f"{i}\n" for i in range(10)).replace("1\n", "one-pr\n", 1)
    old = commit_file(
        repo.work,
        "shared.txt" if both_sides else "pr.txt",
        shared if both_sides else "pr\n",
        "pr work",
    )
    git(repo.work, "checkout", "-q", "main")
    if both_sides:
        main_shared = "".join(f"{i}\n" for i in range(10)).replace("8\n", "eight-main\n", 1)
        m = commit_file(repo.work, "shared.txt", main_shared, "main moves, same file")
    else:
        m = commit_file(repo.work, "main.txt", "main\n", "main moves")
    git(repo.work, "checkout", "-q", "pr")
    git(repo.work, "merge", "-q", "--no-ff", "-m", "merge main", "main")
    new = git(repo.work, "rev-parse", "HEAD")
    publish(repo, new, m)
    return old, m, new


def run_carry(fake_gh, repo, old, new):
    pr = load("pr484.json")
    pr["headRefOid"] = new
    fake_gh.serve(pr)
    return fake_gh.run("carry", "1", old, cwd=repo.work)


def test_carry_clean_merge_prints_all_ok(fake_gh, repo):
    old, m, new = carry_setup(repo)
    r = run_carry(fake_gh, repo, old, new)
    assert r.returncode == 0, r.stdout + r.stderr
    lines = r.stdout.splitlines()
    assert lines[:3] == ["main-ok", "lineage-ok", "tree-ok"]
    assert lines[3] == f"main={m} tree={git(repo.work, 'rev-parse', new + '^{tree}')}"


def test_carry_file_changed_on_both_sides_fails_tree_ok(fake_gh, repo):
    old, m, new = carry_setup(repo, both_sides=True)
    r = run_carry(fake_gh, repo, old, new)
    assert r.returncode == 1
    assert r.stdout.splitlines() == ["main-ok", "lineage-ok"]


def test_carry_rewritten_branch_fails_lineage_ok(fake_gh, repo):
    old, m, new = carry_setup(repo)
    # Rewrite the reviewed commit: same tree, new commit object, then merge main again.
    base = git(repo.work, "merge-base", old, m)
    git(repo.work, "checkout", "-q", "-B", "pr2", base)
    commit_file(repo.work, "pr.txt", "pr\n", "pr work, rewritten")
    git(repo.work, "merge", "-q", "--no-ff", "-m", "merge main", "main")
    new2 = git(repo.work, "rev-parse", "HEAD")
    publish(repo, new2, m)
    r = run_carry(fake_gh, repo, old, new2)
    assert r.returncode == 1
    assert "lineage-ok" not in r.stdout.splitlines()
    assert "main-ok" in r.stdout.splitlines()


def test_carry_merge_with_extra_edit_fails_tree_ok(fake_gh, repo):
    old, m, new = carry_setup(repo)
    # The merge commit carries a change the review never saw.
    (Path(repo.work) / "smuggled.txt").write_text("x\n")
    git(repo.work, "add", "smuggled.txt")
    git(repo.work, "commit", "-q", "--amend", "--no-edit")
    evil = git(repo.work, "rev-parse", "HEAD")
    publish(repo, evil, m)
    r = run_carry(fake_gh, repo, old, evil)
    assert r.returncode == 1
    assert r.stdout.splitlines() == ["main-ok", "lineage-ok"]


def test_carry_head_not_a_merge_prints_not_a_merge(fake_gh, repo):
    old, m, new = carry_setup(repo)
    git(repo.work, "checkout", "-q", old)
    plain = commit_file(repo.work, "more.txt", "x\n", "plain push")
    publish(repo, plain, m)
    r = run_carry(fake_gh, repo, old, plain)
    assert r.returncode == 1
    assert r.stdout.splitlines() == ["NOT-A-MERGE"]


def test_carry_merge_of_non_main_parent_fails_main_ok(fake_gh, repo):
    old, m, new = carry_setup(repo)
    # Head merges a side branch that is not on origin/main.
    git(repo.work, "checkout", "-q", "-b", "side", old)
    side = commit_file(repo.work, "side.txt", "s\n", "side")
    git(repo.work, "checkout", "-q", "-B", "pr3", old)
    git(repo.work, "merge", "-q", "--no-ff", "-m", "merge side", side)
    new3 = git(repo.work, "rev-parse", "HEAD")
    publish(repo, new3, m)
    r = run_carry(fake_gh, repo, old, new3)
    assert r.returncode == 1
    assert "main-ok" not in r.stdout.splitlines()


def test_carry_bad_root_is_rejected(fake_gh, repo):
    old, m, new = carry_setup(repo)
    r = run_carry(fake_gh, repo, "not-a-sha", new)
    assert r.returncode == 1
    assert r.stdout.splitlines() == ["BAD-ROOT"]


# ------------------------------------------------- status carry-forward (real git)


def remap(pr, mapping):
    return json.loads(
        json.dumps(pr).replace(PR484_SHIP_COMMIT, mapping[0]).replace(PR484_HEAD, mapping[1])
    )


def carried_pr(old, new, drop_root=False, carry_verdict=None):
    """pr484 with its two real SHAs swapped for the temp repo's commits."""
    pr = remap(load("pr484.json"), (old, new))
    if drop_root:
        pr["comments"] = pr["comments"][1:]
    if carry_verdict:
        with_verdict(pr["comments"][-1], carry_verdict)
    return pr


def test_status_carry_forward_with_passing_checks_succeeds(fake_gh, repo):
    old, m, new = carry_setup(repo)
    state, head, desc = parse(status(fake_gh, carried_pr(old, new), cwd=repo.work))
    assert (state, head) == ("success", new)
    assert "Carried-forward" in desc


def test_status_carry_forward_failing_checks_fails(fake_gh, repo):
    old, m, new = carry_setup(repo, both_sides=True)
    state, _, desc = parse(status(fake_gh, carried_pr(old, new), cwd=repo.work))
    assert state == "failure"
    assert "tree-ok" in desc


def test_status_carry_forward_without_ship_root_fails(fake_gh, repo):
    old, m, new = carry_setup(repo)
    state, _, desc = parse(status(fake_gh, carried_pr(old, new, drop_root=True), cwd=repo.work))
    assert state == "failure"
    assert "root" in desc


def test_status_carry_forward_with_block_root_fails(fake_gh, repo):
    old, m, new = carry_setup(repo)
    pr = carried_pr(old, new)
    with_verdict(pr["comments"][0], "BLOCK")
    state, _, desc = parse(status(fake_gh, pr, cwd=repo.work))
    assert state == "failure"
    assert "root" in desc


def test_status_carry_forward_own_verdict_block_fails(fake_gh, repo):
    old, m, new = carry_setup(repo)
    pr = carried_pr(old, new, carry_verdict="BLOCK")
    state, _, desc = parse(status(fake_gh, pr, cwd=repo.work))
    assert state == "failure"
    assert "verdict" in desc


def test_status_carried_from_not_the_root_fails(fake_gh, repo):
    old, m, new = carry_setup(repo)
    pr = carried_pr(old, new)
    other = "0" * 40
    pr["comments"][1]["body"] = pr["comments"][1]["body"].replace(
        f"Carried-From: {old}", f"Carried-From: {other}"
    )
    state, _, desc = parse(status(fake_gh, pr, cwd=repo.work))
    assert state == "failure"
    assert "Carried-From" in desc


def test_status_head_moving_during_check_exits_3(fake_gh, tmp_path):
    # A gh that answers with a different head on each call.
    counter = tmp_path / "n"
    counter.write_text("0")
    real = Path(fake_gh.env["PATH"].split(os.pathsep)[0]) / "gh"
    real.write_text(
        FAKE_GH.replace(
            "jq -c --arg f",
            'n=$(cat "$FAKE_GH_COUNTER"); echo $((n+1)) > "$FAKE_GH_COUNTER"; '
            'if [ "$n" -ge 1 ]; then '
            'jq -c --arg f "$fields" \'. as $d | reduce ($f | split(",")[]) as $k ({}; .[$k] = $d[$k]) '
            '| if has("headRefOid") then .headRefOid = "ffffffffffffffffffffffffffffffffffffffff" else . end\' '
            '"$FAKE_GH_FIXTURE" | jq -r "$query"; exit 0; fi; jq -c --arg f',
            1,
        )
    )
    fake_gh.env["FAKE_GH_COUNTER"] = str(counter)
    pr = load("pr484.json")
    pr["comments"] = [comment(pr, 0)]
    pr["headRefOid"] = PR484_SHIP_COMMIT
    fake_gh.serve(pr)
    r = fake_gh.run("status", "1")
    assert r.returncode == 3
    assert r.stdout == ""
    assert "head moved" in r.stderr
    shutil.rmtree(real.parent, ignore_errors=True)


def test_status_carry_forward_uses_newest_non_carry_root(fake_gh, repo):
    old, m, new = carry_setup(repo)
    pr = carried_pr(old, new)
    older_block = with_verdict(copy.deepcopy(pr["comments"][0]), "BLOCK")
    pr["comments"].insert(0, older_block)
    state, _, _ = parse(status(fake_gh, pr, cwd=repo.work))
    assert state == "success"


def test_status_carry_forward_with_ship_with_fixes_root_fails(fake_gh, repo):
    old, m, new = carry_setup(repo)
    pr = carried_pr(old, new)
    with_verdict(pr["comments"][0], "SHIP-WITH-FIXES")
    state, _, desc = parse(status(fake_gh, pr, cwd=repo.work))
    assert state == "failure"
    assert "root" in desc


def test_status_quoted_heading_mid_comment_is_not_an_attestation(fake_gh):
    pr = load("pr480.json")
    head = load("pr484.json")["headRefOid"]
    owner = load("pr484.json")["comments"][0]
    quoted = copy.deepcopy(owner)
    quoted["body"] = "Pasting the last one for reference:\n" + owner["body"].replace(
        PR484_SHIP_COMMIT, head
    )
    pr["comments"].append(quoted)
    state, _, desc = parse(status(fake_gh, pr, head=head))
    assert state == "failure"
    assert "No attestation" in desc


def test_carry_without_root_prints_usage(fake_gh):
    fake_gh.serve(load("pr484.json"))
    r = fake_gh.run("carry", "1")
    assert r.returncode == 2
