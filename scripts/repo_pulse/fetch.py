"""Fetch everything the Repo Pulse export needs into <raw>/*.json (REPO_PULSE_REPO=owner/name).

usage: fetch.py <raw>
"""

import json, os, sys

sys.path.insert(0, os.path.dirname(__file__))
from gh import R, api, paged, pmap

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)


def save(name, obj):
    json.dump(obj, open(os.path.join(OUT, name), "w"))


pulls = paged(f"{R}/pulls?state=all")
save("pulls.json", pulls)
print("pulls", len(pulls))
issues = paged(f"{R}/issues?state=all")
save("issues.json", issues)
print("issues+prs", len(issues))
events = paged(f"{R}/issues/events")
save("issue_events.json", events)
print("events", len(events))
runs = paged(f"{R}/actions/runs?branch=main", key="workflow_runs", max_pages=10)
save("runs.json", runs)
print("runs", len(runs))

want = [p for p in pulls if p["merged_at"] or p["state"] == "open"]


def detail(p):
    n, sha = p["number"], p["head"]["sha"]
    return {
        "number": n,
        "pull": api(f"{R}/pulls/{n}"),
        "commits": paged(f"{R}/pulls/{n}/commits"),
        "files": paged(f"{R}/pulls/{n}/files", max_pages=30),
        "comments": paged(f"{R}/issues/{n}/comments"),
        "check_runs": paged(f"{R}/commits/{sha}/check-runs?filter=latest", key="check_runs"),
        "statuses": api(f"{R}/commits/{sha}/status?per_page=100"),
    }


details = pmap(detail, want)
save("pr_details.json", details)
print("details", len(details))

# failed jobs of each workflow's latest run among the last 100 on main (ci_main.csv's failing_job)
latest = {}
for r in sorted(runs, key=lambda r: r["created_at"], reverse=True)[:100]:
    latest.setdefault(r["name"], r)
failing = {}
for r in latest.values():
    if r["conclusion"] == "failure":
        jobs = api(f"{R}/actions/runs/{r['id']}/jobs?per_page=100")["jobs"]
        failing[str(r["id"])] = "; ".join(j["name"] for j in jobs if j["conclusion"] == "failure")
save("failing_jobs.json", failing)
