"""review_metrics.csv and issue_flow.csv, using scripts/review_metrics.py's own functions.

The repo's script reads gh's GraphQL fields, which this session can't reach, so this feeds the same
functions REST data reshaped to those fields. Two stand-ins differ from the script:
  - closingIssuesReferences: taken from closing keywords in the PR body (Closes/Fixes/Resolves #n).
  - the attestation reader: attestation.sh read's ROOT rule, applied here to the REST comments
    (owner login, OWNER association, unedited, body starting "## Review attestation", newest one
    that is not a carry-forward).
usage: review.py <clone> <raw> <out>   (REPO_PULSE_REPO=owner/name in the environment)
"""

import csv, json, os, re, subprocess, sys  # nosec B404 - fixed git/gh argument lists, no shell
from collections import defaultdict
from datetime import datetime, timedelta, timezone

REPO, RAW, OUT = sys.argv[1:4]
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import review_metrics as rm  # noqa: E402

load = lambda n: json.load(open(os.path.join(RAW, n)))
NOW = datetime.fromisoformat(
    open(os.path.join(RAW, "exported_at")).read().strip().replace("Z", "+00:00")
)

pulls = load("pulls.json")
details = {d["number"]: d for d in load("pr_details.json")}
events = load("issue_events.json")


def gh_comment(c):
    return {
        "author": {"login": c["user"]["login"]},
        "authorAssociation": c["author_association"],
        "includesCreatedEdit": c["updated_at"] != c["created_at"],
        "body": c["body"] or "",
    }


def reader_output(comments, owner):
    """attestation.sh read, minus the NEWEST/IGNORED lines pick_root_body doesn't use."""
    att = [c for c in comments if c["body"].startswith("## Review attestation")]
    own = [c for c in att if c["author"]["login"] == owner and c["authorAssociation"] == "OWNER"]
    lines = ["EDITED x" for c in own if c["includesCreatedEdit"]]
    clean = [c["body"] for c in own if not c["includesCreatedEdit"]]
    if not clean:
        return "\n".join(lines + ["MISSING"])
    roots = [b for b in clean if not re.search(r"(?m)^- Carried-From:", b)]
    if roots:
        m = re.search(r"(?m)^- Reviewed-Commit: ([^\r\n]*)", roots[-1])
        lines.append(f"ROOT {m.group(1).strip() if m else 'none'}")
    else:
        lines.append("ROOT none")
    return "\n".join(lines)


CLOSES = re.compile(r"(?i)\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(\d+)")

issues = [
    {
        "number": i["number"],
        "createdAt": i["created_at"],
        "closedAt": i["closed_at"],
        "title": i["title"],
        "body": i["body"],
        "labels": [{"name": l["name"]} for l in i["labels"]],
    }
    for i in load("issues.json")
    if "pull_request" not in i
]
reopen_events = defaultdict(list)
label_events = defaultdict(list)
for e in events:
    n = e["issue"]["number"]
    if e["event"] == "reopened":
        reopen_events[n].append(e)
    if e["event"] == "labeled":
        label_events[n].append(
            {
                "event": "labeled",
                "label": {"name": e["label"]["name"]},
                "created_at": e["created_at"],
            }
        )

merged = sorted([p for p in pulls if p["merged_at"]], key=lambda p: p["merged_at"])
prs, attested, reopened = {}, {}, {}
for p in merged:
    n = p["number"]
    d = details[n]
    body = p["body"] or ""
    pr = {
        "number": n,
        "title": p["title"],
        "body": body,
        "createdAt": p["created_at"],
        "mergedAt": p["merged_at"],
        "closingIssuesReferences": [
            {"number": int(k)} for k in dict.fromkeys(CLOSES.findall(body))
        ],
        "files": [{"path": f["filename"]} for f in d["files"]],
    }
    prs[n] = pr
    comments = [gh_comment(c) for c in d["comments"]]
    owner = p["html_url"].split("/")[3]  # the PR URL's owner, as attestation.sh read takes it
    attested[n] = rm.pick_root_body(reader_output(comments, owner), comments, p["html_url"])
    m = rm.ts(p["merged_at"])
    reopened[n] = sum(
        1
        for k in (r["number"] for r in pr["closingIssuesReferences"])
        for e in reopen_events[k]
        if m < rm.ts(e["created_at"]) <= m + timedelta(days=rm.ESCAPE_DAYS)
    )

git_log = subprocess.run(  # nosec B603 B607 - fixed git/gh argument lists, no shell
    ["git", "-C", REPO, "log", "origin/main", "--format=%H%x1f%s%x1f%b%x1f%cI%x1e"],
    capture_output=True,
    text=True,
    check=True,
).stdout
owned = rm.claim_followups(
    prs, {n: rm.followup_candidates(prs[n], attested[n][0], issues) for n in prs}
)
created = {i["number"]: i["createdAt"] for i in issues}
labels = {
    n: rm.arrival_labels(label_events[n], created[n])
    for n in {k for o in owned.values() for k in o or ()}
    if n in created
}
rows = [
    rm.build_row(
        prs[n],
        attestation=attested[n],
        issues=issues,
        reverts=rm.reverts_naming(git_log, n, rm.ts(prs[n]["mergedAt"])),
        reopened=reopened[n],
        now=NOW,
        owned=owned[n],
        arrival_labels=labels,
    )
    for n in prs
]
with open(os.path.join(OUT, "review_metrics.csv"), "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=rm.COLUMNS, lineterminator="\n")
    w.writeheader()
    w.writerows(rows)
print("review_metrics.csv:", len(rows), "rows")

# issue flow: every ISO week from the first issue to the export's week
first = min(rm.ts(i["createdAt"]) for i in issues)
weeks, d = [], (first - timedelta(days=first.weekday())).date()
end = (NOW - timedelta(days=NOW.weekday())).date()
while d <= end:
    weeks.append(d)
    d += timedelta(weeks=1)
flow = []
for monday in weeks:
    y, wk, _ = monday.isocalendar()
    label = f"{y}-W{wk:02d}"
    o = sum(1 for i in issues if rm._week(i["createdAt"]) == label)
    c = sum(1 for i in issues if i["closedAt"] and rm._week(i["closedAt"]) == label)
    flow.append([label, monday.isoformat(), o, c, o - c])
with open(os.path.join(OUT, "issue_flow.csv"), "w", newline="") as fh:
    w = csv.writer(fh, lineterminator="\n")
    w.writerow(["week", "monday", "opened", "closed", "net"])
    w.writerows(flow)
print("issue_flow.csv:", len(flow), "rows")
