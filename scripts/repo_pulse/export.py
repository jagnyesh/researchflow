"""Build the Repo Pulse CSVs (#541) from a full clone and the REST data fetch.py saved.

usage: export.py <clone> <raw> <out>
Needs REPO_PULSE_REPO (owner/name) in the environment, raw/exported_at, and raw/local.json from local.py.
The clone must have origin/main and refs/remotes/pr/* (run.py fetches both).
"""

import csv, json, os, re, subprocess, sys  # nosec B404 - fixed git/gh argument lists, no shell
from collections import defaultdict, Counter
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from pulse import area, ext, lane_status, split_rename

REPO, RAW, OUT = sys.argv[1:4]
os.makedirs(OUT, exist_ok=True)
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"  # git's empty tree, not a secret  # pragma: allowlist secret


def git(*a):
    return subprocess.run(  # nosec B603 B607 - fixed git/gh argument lists, no shell
        ["git", "-C", REPO, *a], capture_output=True, text=True, check=True
    ).stdout


def load(n):
    return json.load(open(os.path.join(RAW, n)))


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def z(d):
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if d else ""


def monday(d):
    return (d - timedelta(days=d.weekday())).isoformat()


def write(name, header, rows):
    with open(os.path.join(OUT, name), "w", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(header)
        w.writerows(rows)
    print(f"{name}: {len(rows)} rows")


EXPORT = ts(open(os.path.join(RAW, "exported_at")).read().strip())
HEAD = git("rev-parse", "origin/main").strip()

# ---------------------------------------------------------------- commits, churn, hot files
TYPES = {"feat", "fix", "docs", "ci", "chore", "test", "workflow", "refactor"}


log = git(
    "log", "--first-parent", "origin/main", "-M", "--numstat", "--format=%x00%H%x1f%P%x1f%aI%x1f%s"
)
commits, churn = [], []
file_stats = defaultdict(lambda: [0, 0, 0, ""])  # commits, added, deleted, last date
# Oldest first, so a rename meets the old path's history already in file_stats.
for block in reversed(log.split("\x00")[1:]):
    head, *lines = block.strip("\n").split("\n")
    sha, parents, date, subj = head.split("\x1f")
    parent = parents.split()[0] if parents else None
    d = datetime.fromisoformat(date).astimezone(timezone.utc).date()
    m = re.match(r"^(\w+)(\([^)]*\))?!?:", subj)
    typ = m.group(1).lower() if m and m.group(1).lower() in TYPES else "other"
    prm = re.findall(r"\(#(\d+)\)", subj)
    pr = prm[-1] if prm else ""
    nf = na = nd = 0
    per = defaultdict(lambda: [0, 0, 0, 0])
    for l in lines:
        if not l.strip():
            continue
        a, dl, p = l.split("\t")
        if a == "-":
            continue
        a, dl = int(a), int(dl)
        old, new = split_rename(p)
        nf += 1
        na += a
        nd += dl
        ar = area(new)
        per[ar][0] += 1
        per[ar][1] += a
        per[ar][2] += dl
        if old and area(old) != ar:
            n_old = git("show", f"{parent}:{old}").count("\n") if parent else 0
            per[ar][3] += n_old
            per[area(old)][3] -= n_old
        fs = file_stats[new]
        if old and old in file_stats:  # follow renames forward
            o = file_stats.pop(old)
            fs[0] += o[0]
            fs[1] += o[1]
            fs[2] += o[2]
            fs[3] = fs[3] or o[3]
        fs[0] += 1
        fs[1] += a
        fs[2] += dl
        fs[3] = max(fs[3], d.isoformat())
    commits.append([sha[:7], d.isoformat(), monday(d), typ, pr, subj, nf, na, nd])
    for ar in sorted(per):
        f, a, dl, mv = per[ar]
        churn.append([sha[:7], d.isoformat(), monday(d), ar, f, a, dl, mv])
# churn: oldest commit first, areas alphabetical within a commit
order = {c[0]: i for i, c in enumerate(commits)}
churn.sort(key=lambda r: (order[r[0]], r[3]))
write(
    "commits.csv",
    ["sha", "date", "week", "type", "pr", "subject", "files", "added", "deleted"],
    commits,
)
write("churn.csv", ["sha", "date", "week", "area", "files", "added", "deleted", "moved"], churn)

in_head = set(git("ls-tree", "-r", "--name-only", "origin/main").splitlines())
hot = sorted(
    ((p, s) for p, s in file_stats.items() if p in in_head), key=lambda x: (-x[1][0], -x[1][1])
)[:20]
write(
    "hot_files.csv",
    ["path", "area", "commits", "added", "deleted", "last_changed"],
    [[p, area(p), s[0], s[1], s[2], s[3]] for p, s in hot],
)

loc = defaultdict(lambda: [0, 0])
for l in git("diff", "--numstat", EMPTY_TREE, "origin/main").splitlines():
    a, _, p = l.split("\t")
    if a == "-":
        continue
    k = (area(p), ext(p))
    loc[k][0] += 1
    loc[k][1] += int(a)
write(
    "loc_now.csv",
    ["area", "ext", "files", "lines"],
    [[a, e, f, n] for (a, e), (f, n) in sorted(loc.items())],
)

# ---------------------------------------------------------------- CI
runs = load("runs.json")
for r in runs:  # gh run list names dynamic (Pages) workflows by their path
    if r["event"] == "dynamic" and "pages-build-deployment" in r["path"]:
        r["name"] = r["path"].rsplit("/", 1)[-1]
runs.sort(key=lambda r: r["created_at"], reverse=True)
write(
    "ci_runs.csv",
    ["run", "workflow", "event", "attempt", "created_at", "status", "conclusion", "sha"],
    [
        [
            r["id"],
            r["name"],
            r["event"],
            r["run_attempt"],
            r["created_at"],
            r["status"],
            r["conclusion"] or "",
            r["head_sha"][:7],
        ]
        for r in reversed(runs)
    ],
)

last100 = runs[:100]
by_wf = defaultdict(list)
for r in last100:
    by_wf[r["name"]].append(r)
failing_jobs = (
    json.load(open(os.path.join(RAW, "failing_jobs.json")))
    if os.path.exists(os.path.join(RAW, "failing_jobs.json"))
    else {}
)
ci_main = []
for wf, rs in sorted(by_wf.items(), key=lambda kv: -len(kv[1])):
    latest = rs[0]
    succ = [r for r in rs if r["conclusion"] == "success"]
    ci_main.append(
        [
            wf,
            len(rs),
            sum(r["conclusion"] == "failure" for r in rs),
            latest["conclusion"] or "",
            latest["created_at"][:10],
            rs[-1]["created_at"][:10],
            succ[0]["created_at"][:10] if succ else "",
            failing_jobs.get(str(latest["id"]), "") if latest["conclusion"] == "failure" else "",
        ]
    )
write(
    "ci_main.csv",
    [
        "workflow",
        "runs",
        "failures",
        "last_conclusion",
        "last_run",
        "first_run_in_window",
        "last_success",
        "failing_job",
    ],
    ci_main,
)

# ---------------------------------------------------------------- issues
issues = [i for i in load("issues.json") if "pull_request" not in i]
open_issues = [i for i in issues if i["state"] == "open"]
cnt = Counter()
for i in open_issues:
    labels = {l["name"] for l in i["labels"]}
    kind = "bug" if "bug" in labels else "enhancement" if "enhancement" in labels else "unlabelled"
    stage = next(
        (s for s in ("needs-triage", "ready-for-agent", "ready-for-human") if s in labels),
        "no stage",
    )
    cnt[(kind, stage)] += 1
write(
    "issues_open.csv", ["kind", "stage", "issues"], [[k, s, n] for (k, s), n in sorted(cnt.items())]
)

esc = []
for c in commits:
    if c[5].startswith("Revert"):
        full = git("log", "-1", "--format=%cI", c[0]).strip()
        esc.append(["revert", c[0], z(ts(full)), c[5]])
issue_by_n = {i["number"]: i for i in issues}
reopen = {}
for e in load("issue_events.json"):
    if (
        e["event"] == "reopened"
        and e["issue"]["number"] in issue_by_n
        and "pull_request" not in e["issue"]
    ):
        n = e["issue"]["number"]
        reopen[n] = max(reopen.get(n, ""), e["created_at"])
for n, at in sorted(reopen.items(), key=lambda kv: kv[1]):
    esc.append(["reopened issue", f"#{n}", at, issue_by_n[n]["title"]])
esc.sort(key=lambda r: r[2])
write("escapes.csv", ["kind", "ref", "at", "title"], esc)

# ---------------------------------------------------------------- PRs
pulls = load("pulls.json")
details = {d["number"]: d for d in load("pr_details.json")}
ATT = re.compile(r"^## Review attestation")
SHIPV = re.compile(r"(?m)^-?\s*Verdict:\s*\**SHIP")


def field(body, k):
    if k == "Reviewed-Commit":
        m = re.search(r"(?mi)^-?\s*Reviewed[- ]Commit:\s*`?([0-9a-f]{7,40})", body)
    else:
        m = re.search(r"(?m)^-?\s*Verdict:\s*\**([A-Z][A-Z-]*)", body)
    return m.group(1).strip() if m else None


def owner_atts(d, p):
    owner = p["html_url"].split("/")[3]  # the PR URL's owner, as attestation.sh read takes it
    return sorted(
        [
            c
            for c in d["comments"]
            if c["user"]["login"] == owner
            and c["author_association"] == "OWNER"
            and ATT.search(c["body"] or "")
        ],
        key=lambda c: c["created_at"],
    )


def edited(c):
    return c["updated_at"] != c["created_at"]


def rollup(d):
    """GraphQL-style rollup: latest check run per name, plus latest status per context."""
    items = []
    for r in d["check_runs"]:
        items.append(
            {
                "kind": "run",
                "name": r["name"],
                "workflow": (r.get("app") or {}).get("slug", ""),
                "conclusion": (r["conclusion"] or "").upper(),
                "completed": r["completed_at"],
                "status": r["status"],
                "started": r["started_at"],
            }
        )
    for s in (d["statuses"] or {}).get("statuses", []):
        items.append(
            {
                "kind": "status",
                "name": s["context"],
                "state": s["state"].upper(),
                "started": s["updated_at"],
            }
        )
    return items


merged = sorted([p for p in pulls if p["merged_at"]], key=lambda p: p["merged_at"])
open_prs = sorted([p for p in pulls if p["state"] == "open"], key=lambda p: -p["number"])

ml = []
for p in merged:
    d = details[p["number"]]
    created, merged_at = p["created_at"], p["merged_at"]
    items = rollup(d)
    greens = [
        i["completed"]
        for i in items
        if i["kind"] == "run"
        and i["conclusion"] == "SUCCESS"
        and i["completed"]
        and created <= i["completed"] <= merged_at
    ]
    green = max(greens) if greens else None
    pending, failed = set(), set()
    for i in items:
        if i["kind"] == "status":
            if i["state"] in ("PENDING", "EXPECTED") or i["started"] > merged_at:
                pending.add(i["name"])
            if i["state"] in ("FAILURE", "ERROR") and i["started"] <= merged_at:
                failed.add(i["name"])
        else:
            c = i["completed"] or ""
            if i["name"] != "CodeQL" and (c == "" or c > merged_at):
                pending.add(i["name"])
            if (
                i["conclusion"]
                in ("FAILURE", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE")
                and c
                and c <= merged_at
            ):
                failed.add(i["name"])
    og = round((ts(green) - ts(created)).total_seconds() / 60) if green else ""
    gm = round((ts(merged_at) - ts(green)).total_seconds() / 60) if green else ""
    evidence = 1 if re.search(r"(?im)^\W*Testing evidence", p["body"] or "") else 0
    unedited = [c for c in owner_atts(d, p) if not edited(c)]
    if unedited:
        newest = unedited[-1]
        att = "current" if field(newest["body"], "Reviewed-Commit") == p["head"]["sha"] else "stale"
        verdict = field(newest["body"], "Verdict") or ""
    else:
        att, verdict = "none", ""
    verified = int(
        evidence == 1
        and att == "current"
        and verdict in ("SHIP", "SHIP-WITH-FIXES")
        and bool(green)
        and not pending
        and not failed
    )
    # §3's up-to-date rule, measured: commits main had when this PR merged that its head lacked.
    # PR heads come from refs/remotes/pr/<n>; a missing object leaves the cell blank.
    behind = ""
    mc = p.get("merge_commit_sha")
    if mc:
        try:
            base = git("rev-parse", f"{mc}^1").strip()
            behind = int(git("rev-list", "--count", f"{p['head']['sha']}..{base}").strip())
        except subprocess.CalledProcessError:
            behind = ""
    ml.append(
        [
            p["number"],
            p["title"],
            created,
            green or "",
            merged_at,
            merged_at[:10],
            og,
            gm,
            len(pending),
            len(failed),
            evidence,
            att,
            verdict,
            verified,
            behind,
        ]
    )
write(
    "merge_latency.csv",
    [
        "pr",
        "title",
        "created_at",
        "green_at",
        "merged_at",
        "merge_day",
        "open_to_green_min",
        "green_to_merge_min",
        "pending_checks",
        "failed_checks",
        "evidence",
        "attestation",
        "verdict",
        "verified",
        "base_behind",
    ],
    ml,
)

sys.path.insert(0, os.path.join(REPO, "scripts"))
from review_metrics import parse_tier, tier_from_paths  # noqa: E402

SERIAL = re.compile(r"^config/")  # §3: two lanes that both touch config/** run in series


def pr_tier(p):
    t = parse_tier(p["body"])
    return (
        t
        if t != "unknown"
        else tier_from_paths([f["filename"] for f in details[p["number"]]["files"]])
    )


open_files = {p["number"]: {f["filename"] for f in details[p["number"]]["files"]} for p in open_prs}


def shares_with(n):
    mine = open_files[n]
    out = []
    for m, theirs in open_files.items():
        if m != n and (
            mine & theirs
            or (any(SERIAL.match(x) for x in mine) and any(SERIAL.match(x) for x in theirs))
        ):
            out.append(f"#{m}")
    return " ".join(out)


po = []
for p in open_prs:
    d = details[p["number"]]
    pull = d["pull"]
    items = rollup(d)
    ok = sum(
        1
        for i in items
        if (i.get("conclusion") or i.get("state")) in ("SUCCESS", "SKIPPED", "NEUTRAL")
    )
    bad = sum(
        1
        for i in items
        if (i.get("conclusion") or i.get("state"))
        in ("FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE")
    )
    mg = {True: "MERGEABLE", False: "CONFLICTING"}.get(pull["mergeable"], "UNKNOWN")
    po.append(
        [
            p["number"],
            p["title"],
            p["created_at"][:10],
            p["head"]["ref"],
            pull["changed_files"],
            pull["additions"],
            pull["deletions"],
            ok,
            bad,
            len(items),
            mg,
            pr_tier(p),
            shares_with(p["number"]),
        ]
    )
write(
    "prs_open.csv",
    [
        "pr",
        "title",
        "opened",
        "branch",
        "files",
        "added",
        "deleted",
        "checks_passed",
        "checks_failed",
        "checks_total",
        "mergeable",
        "tier",
        "shares_with",
    ],
    po,
)

# lanes
merge_msgs = {}
for block in git("log", "--first-parent", "origin/main", "--format=%x00%s%n%b").split("\x00")[1:]:
    prm = re.findall(r"\(#(\d+)\)", block.split("\n", 1)[0])
    if prm:
        merge_msgs[int(prm[-1])] = block
lane_prs = merged + sorted(open_prs, key=lambda p: p["number"])
spans, files_of = {}, {}
for p in lane_prs:
    d = details[p["number"]]
    dates = [c["commit"]["author"]["date"] for c in d["commits"]]
    start = min(dates) if dates else p["created_at"]
    spans[p["number"]] = (ts(start), ts(p["merged_at"]) if p["merged_at"] else EXPORT)
    files_of[p["number"]] = {f["filename"] for f in d["files"]} | {
        f.get("previous_filename") for f in d["files"] if f.get("previous_filename")
    }
lanes = []
for p in lane_prs:
    n = p["number"]
    d = details[n]
    atts = owner_atts(d, p)
    ship = [c for c in atts if SHIPV.search(c["body"])]
    first_ship = ship[0]["created_at"] if ship else ""
    end = p["merged_at"] or ""
    wait = (
        round(((ts(end) if end else EXPORT) - ts(first_ship)).total_seconds() / 60)
        if first_ship
        else ""
    )
    upd = sum(1 for c in d["commits"] if len(c["parents"]) > 1)
    carried = sum(1 for c in atts if re.search(r"(?m)^- Carried-From:", c["body"]))
    if p["merged_at"]:
        self_m = (
            1
            if re.search(r"(?m)^Merged-By: pipeline \(standing-rule", merge_msgs.get(n, ""))
            else 0
        )
    else:
        self_m = ""
    s0, e0 = spans[n]
    share = sum(
        1
        for m in lane_prs
        if m["number"] != n
        and spans[m["number"]][0] < e0
        and s0 < spans[m["number"]][1]
        and files_of[n] & files_of[m["number"]]
    )
    fork = (
        1
        if p["head"]["repo"] is None
        or p["head"]["repo"]["full_name"] != p["base"]["repo"]["full_name"]
        else 0
    )
    lanes.append(
        [
            n,
            p["title"],
            "merged" if p["merged_at"] else "open",
            fork,
            z(s0),
            p["created_at"],
            first_ship,
            end,
            wait,
            upd,
            len(atts),
            carried,
            self_m,
            share,
        ]
    )
write(
    "lanes.csv",
    [
        "pr",
        "title",
        "state",
        "fork",
        "started_at",
        "opened_at",
        "first_ship_at",
        "ended_at",
        "wait_min",
        "updates_from_main",
        "attestations",
        "carried",
        "self_merged",
        "shares_file_with",
    ],
    lanes,
)

# ---------------------------------------------------------------- worktrees and status
local = json.load(open(os.path.join(RAW, "local.json")))
by_sha = {p["head"]["sha"]: p for p in pulls}
ln = []
for wt in local["worktrees"]:
    branch, sha, ahead = wt["label"], wt["head"], wt["ahead"]
    if branch.startswith("(detached"):
        cands = [by_sha[sha]] if sha in by_sha else []
    else:
        cands = [
            p
            for p in pulls
            if p["head"]["ref"] == branch
            and p["head"]["repo"]
            and p["head"]["repo"]["full_name"] == p["base"]["repo"]["full_name"]
        ]
        cands = [c for c in cands if c["state"] == "open"] + cands
    pr = cands[0] if cands else None
    state = (
        "none"
        if not pr
        else "open" if pr["state"] == "open" else "merged" if pr["merged_at"] else "closed"
    )
    counts, why = lane_status(branch, ahead, state, wt.get("exists", True))
    ln.append([branch, ahead, pr["number"] if pr else "", state, counts, why])
ln.sort(key=lambda r: (r[4] != "yes", r[0]))
write("lanes_now.csv", ["branch", "commits_ahead", "pr", "pr_state", "counts", "why"], ln)

head_committed = z(ts(git("log", "-1", "--format=%cI", "origin/main").strip()))[:16] + "Z"
status = [
    ("branch", "main"),
    ("behind_origin", local["behind"]),
    ("ahead_of_origin", local["ahead"]),
    ("untracked_files", local["untracked"]),
    ("head_sha", HEAD[:7]),
    ("head_committed", head_committed),
    ("open_prs", len(open_prs)),
    ("open_issues", len(open_issues)),
    ("merged_prs", len(merged)),
    ("exported_at", EXPORT.strftime("%Y-%m-%dT%H:%MZ")),
    ("lanes_open", sum(r[4] == "yes" for r in ln)),
]
write("status.csv", ["metric", "value"], status)
