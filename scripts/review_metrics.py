#!/usr/bin/env python3
"""Review metrics: catch, escape and follow-up counts per merged PR, and per risk tier (#520).

Reads merged PRs through `gh` and writes logs/review_metrics.csv (ignored by git).

  review_metrics.py [--limit 30] [--out logs/review_metrics.csv] [--summary] [--now ISO8601]

Grain: one row per merged PR. Primary key: `pr`. Row order is the order `gh pr list` returns.
Rerun rule: the file is overwritten from scratch, so a rerun on the same input is byte-identical.
`--now` pins the clock that decides `escape_window_closed`; it defaults to the current UTC time.
Timestamps are UTC. Merged PRs in equals rows out; the script prints both counts.

Columns:
  tier, tier_source    the `Risk tier:` line of the PR body (source `line`; an explicit line always
                       wins), else derived from the PR's file list with the rules of
                       docs/DAILY_DEV_WORKFLOW.md section 1 (source `paths`: any High path gives
                       high, only docs, tests and harness paths gives low, else medium). `unknown`
                       with source `none` only when the file list is empty or missing. The
                       whole body is searched for the line, not just its Testing evidence section.
  findings_*           (fixed, accepted, routed, and noted for `noted, not filed`) counted from the root attestation: the one `scripts/attestation.sh read`
                       reports as ROOT (the owner's newest unedited attestation that is not a
                       carry-forward). This script never decides which comment counts. A line can
                       carry two dispositions ("fixed (...); routed to #517"), so fixed + accepted +
                       routed can exceed findings_total.
  review_passes        the sum of the `<k> pass(es)` values on the Reviewer lines.
  followups_filed      issues created from 24 hours before the PR's creation to 24 hours after its
                       merge that cite the PR or an issue it closes, deduplicated by number, and
                       that are not counted as an escape. The window opens before the PR because the
                       Step 2 review runs before the PR exists, so about half of the follow-ups are
                       filed before it (2026-11-01 onward: 49 inside the PR's own window, 56 earlier,
                       39 of those in the 6 hours before). Git records no lane start (the first
                       commit also lands after the review), so 24 hours is a fixed lookback. It can admit a sibling
                       or planning issue that cites the closing issue the day before the PR opens;
                       the script can't tell those from review follow-ups.
  escapes              revert commits on origin/main naming the PR, plus reopenings of the closed
                       issue after the merge, plus `bug` issues created after the merge and within
                       14 days that cite the PR or its closed issue. A follow-up is not an escape: an
                       issue that qualifies as an escape is never also counted as a follow-up.
  escape_window_closed true once 14 days have passed since the merge.
  parse_warnings       empty, or why a value is empty. An unparseable value is empty, never 0: a 0
                       means the reviewer found nothing.

Limits: `git log origin/main` runs without a fetch, so reverts newer than the local ref are missed.
`gh pr list --state merged` orders by creation time, so "the last 30 merged" can differ at the edge.
`gh pr list --json files` returns at most 100 files per PR, so a very large PR could miss a High path.
A PR whose attestation lacks a 40-hex `- Reviewed-Commit:` line has no usable root, because
the reader's ROOT line carries that hash. It gets empty counts and a warning. A comment from a
non-owner can't win the root slot unless it repeats the owner's commit hash and format.
"""

import argparse
import csv
import json
import os
import re
import subprocess  # nosec B404 - fixed gh, git and bash argument lists; no shell, no untrusted input
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ATTESTATION_SH = HERE / "attestation.sh"
TIERS = ["low", "medium", "high", "unknown"]
ESCAPE_DAYS = 14
FOLLOWUP_HOURS = 24
COLUMNS = [
    "pr",
    "merged_at",
    "tier",
    "tier_source",
    "findings_total",
    "findings_fixed",
    "findings_accepted",
    "findings_routed",
    "findings_noted",
    "review_passes",
    "followups_filed",
    "escapes",
    "escape_window_closed",
    "parse_warnings",
]
FINDING_LINE = re.compile(r"^ {2,}- finding \d+:\s*(?P<rest>.*)$")
ANY_NESTED = re.compile(r"^ {2,}- (?P<rest>.*)$")


def ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


# ---------------------------------------------------------------- parsing


def parse_findings(body):
    """Counts from one attestation body. Counts are None, with warnings, when the block can't be read."""
    out = {
        "findings_total": None,
        "findings_fixed": None,
        "findings_accepted": None,
        "findings_routed": None,
        "findings_noted": None,
        "review_passes": None,
        "warnings": [],
    }
    passes = [
        int(m.group(1))
        for line in body.splitlines()
        if line.startswith("- Reviewer")
        for m in re.finditer(r"(\d+) pass(?:\(es\)|es)?\b", line)
    ]
    if passes:
        out["review_passes"] = sum(passes)
    else:
        out["warnings"].append("no pass count on a Reviewer line")

    lines = body.splitlines()
    head = next((i for i, ln in enumerate(lines) if re.match(r"^- Findings:", ln)), None)
    if head is None:
        out["warnings"].append("no Findings line")
        return out
    inline = lines[head].split(":", 1)[1].strip()
    if inline:
        if re.fullmatch(r"none\.?", inline, re.I):
            out.update(
                findings_total=0,
                findings_fixed=0,
                findings_accepted=0,
                findings_routed=0,
                findings_noted=0,
            )
        else:
            out["warnings"].append("Findings line has inline text, not a nested list")
        return out

    total = fixed = accepted = routed = noted = 0
    problems = []
    for k, ln in enumerate(lines[head + 1 :], start=head + 1):
        if not ln.strip():
            if any(ANY_NESTED.match(x) for x in lines[k + 1 : k + 2]):
                problems.append("blank line inside the Findings block")
            continue
        if not ln.startswith(" "):
            break
        nested = ANY_NESTED.match(ln)
        if not nested:
            continue
        if nested.group("rest").startswith("process:"):
            continue
        m = FINDING_LINE.match(ln)
        if not m:
            problems.append(f"nested line is not `finding N:` ({nested.group('rest')[:40]!r})")
            continue
        rest = m.group("rest")
        arrow = max(rest.rfind("→"), rest.rfind("->"))
        if arrow < 0:
            problems.append("a finding has no → disposition")
            continue
        disp = rest[arrow:].lstrip("→->").strip().lower()
        is_fixed = disp.startswith("fixed")
        is_accepted = disp.startswith("accepted")
        is_routed = re.search(r"routed to #\d+", disp) is not None
        is_noted = disp.startswith("noted, not filed")
        if not (is_fixed or is_accepted or is_routed or is_noted):
            problems.append("a disposition is not fixed, accepted, routed or noted")
            continue
        total += 1
        fixed += is_fixed
        accepted += is_accepted
        routed += is_routed
        noted += is_noted
    if problems or total == 0:
        out["warnings"].extend(problems or ["empty Findings block"])
        return out
    out.update(
        findings_total=total,
        findings_fixed=fixed,
        findings_accepted=accepted,
        findings_routed=routed,
        findings_noted=noted,
    )
    return out


# Authority: docs/DAILY_DEV_WORKFLOW.md §1 (the risk classifier), plus the owner's call of
# 2026-11-14 that cohort fixes in app/services/sql_generator.py are High. Re-read §1 when it changes.
# §1 also lists "IRB-scope logic" as High; no path in the repo implements it, so no rule matches it.
# Paths §1 does not name (.github/**, config/**) fall to medium.
HIGH_PATHS = re.compile(
    r"^(app/services/(sql_validator|sql_synthesis|sql_generator|feasibility_service)\.py"
    r"|app/agents/(phenotype_agent|extraction_agent)\.py"
    r"|app/security/"
    r"|app/.*encrypt"
    r"|tests/fixtures/transpiler_expected_outputs\.py"
    r"|tests/eval/(cases\.py|fixtures/))"
)
LOW_PATHS = re.compile(
    r"^(docs/|tests/|\.claude/|scripts/(lane|dials)\.sh$|CLAUDE\.md$|[^/]+\.md$)"
)


def tier_from_paths(paths):
    """high if any path is High; low if every path is docs, tests or harness; else medium."""
    if not paths:
        return "unknown"
    if any(HIGH_PATHS.match(x) for x in paths):
        return "high"
    return "low" if all(LOW_PATHS.match(x) for x in paths) else "medium"


def parse_tier(body):
    # A filled word only: the unfilled template's `<low|medium|high>` must not read as `low`.
    # The whole body is searched, not just the Testing evidence section.
    m = re.search(r"(?mi)^\W*risk tier:\**[ \t]*(low|medium|high)\b(?!\s*[|/])", body or "")
    return m.group(1).lower() if m else "unknown"


def pick_root_body(reader_output, comments):
    """(body, warnings). The reader's ROOT line names the root attestation's commit; find that comment."""
    warnings = []
    lines = reader_output.splitlines()
    if any(ln.startswith("EDITED ") for ln in lines):
        warnings.append("edited owner attestation ignored")
    if "MISSING" in lines:
        return None, warnings + ["no owner attestation"]
    root = next((ln for ln in lines if ln.startswith("ROOT ")), None)
    sha = root.split()[1] if root else ""
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        return None, warnings + ["root attestation has no Reviewed-Commit hash"]
    for c in reversed(comments):
        b = c["body"]
        if (
            b.startswith("## Review attestation")
            and f"- Reviewed-Commit: {sha}" in b
            and "- Carried-From:" not in b
        ):
            return b, warnings
    return None, warnings + ["root attestation comment not found"]


def cites(issue, numbers):
    text = f"{issue.get('title') or ''}\n{issue.get('body') or ''}"
    return any(
        re.search(rf"(?<![\d#/&])#{n}(?!\d)|/(?:pull|issues)/{n}(?!\d)", text) for n in numbers
    )


def reverts_naming(git_log, pr):
    """Hashes of revert commits in `git log --format=%H%x1f%s%x1f%b%x1e` text that name the PR."""
    found = []
    for rec in git_log.split("\x1e"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) < 3 or not parts[1].startswith("Revert"):
            continue
        if re.search(rf"(?<![\w#/])#{pr}(?!\d)", parts[1] + "\n" + parts[2]):
            found.append(parts[0].strip())
    return found


# ---------------------------------------------------------------- rows


def build_row(pr, attestation, issues, reverts, reopened, now):
    """One CSV row (strings). `attestation` is (root body or None, warnings)."""
    body, warnings = attestation
    warnings = list(warnings)
    f = None
    if body is not None:
        f = parse_findings(body)
        warnings += f["warnings"]
    created, merged = ts(pr["createdAt"]), ts(pr["mergedAt"])
    closing = [r["number"] for r in pr.get("closingIssuesReferences") or []]
    numbers = [pr["number"], *closing]

    escaped_issues = {
        i["number"]
        for i in issues
        if any(lab["name"] == "bug" for lab in i.get("labels") or [])
        and merged < ts(i["createdAt"]) <= merged + timedelta(days=ESCAPE_DAYS)
        and cites(i, numbers)
    }
    follow = {
        i["number"]
        for i in issues
        if created - timedelta(hours=FOLLOWUP_HOURS)
        <= ts(i["createdAt"])
        <= merged + timedelta(hours=FOLLOWUP_HOURS)
        and cites(i, numbers)
        and i["number"] not in escaped_issues
    }
    escapes = len(reverts) + reopened + len(escaped_issues)

    tier = parse_tier(pr.get("body"))
    tier_source = "line"
    if tier == "unknown":
        tier = tier_from_paths([x["path"] for x in pr.get("files") or []])
        tier_source = "none" if tier == "unknown" else "paths"

    def n(key):
        return "" if f is None or f[key] is None else f[key]

    return {
        "pr": pr["number"],
        "merged_at": pr["mergedAt"],
        "tier": tier,
        "tier_source": tier_source,
        "findings_total": n("findings_total"),
        "findings_fixed": n("findings_fixed"),
        "findings_accepted": n("findings_accepted"),
        "findings_routed": n("findings_routed"),
        "findings_noted": n("findings_noted"),
        "review_passes": n("review_passes"),
        "followups_filed": len(follow),
        "escapes": escapes,
        "escape_window_closed": "true" if now >= merged + timedelta(days=ESCAPE_DAYS) else "false",
        "parse_warnings": "; ".join(warnings),
    }


def _pct(k, n):
    return f"{k}/{n} ({round(100 * k / n)}%)" if n else "n/a"


def summarize(rows, now):
    tiers = []
    for t in TIERS:
        rs = [r for r in rows if r["tier"] == t]
        parsed = [r for r in rs if r["findings_total"] != ""]
        closed = [r for r in rs if r["escape_window_closed"] == "true"]
        tiers.append(
            {
                "tier": t,
                "prs": len(rs),
                "catch_rate": _pct(sum(1 for r in parsed if r["findings_fixed"] >= 1), len(parsed)),
                "findings_per_pr": (
                    f"{sum(r['findings_total'] for r in parsed) / len(parsed):.1f}"
                    if parsed
                    else "n/a"
                ),
                "followups_per_pr": (
                    f"{sum(r['followups_filed'] for r in rs) / len(rs):.2f}" if rs else "n/a"
                ),
                "escape_rate": _pct(sum(1 for r in closed if r["escapes"] >= 1), len(closed)),
                "window_open": len(rs) - len(closed),
                "unparsed": len(rs) - len(parsed),
                "findings_parsed": f"{len(parsed)}/{len(rs)}",
                "tier_from_paths": sum(1 for r in rs if r["tier_source"] == "paths"),
            }
        )
    total = {
        "prs": len(rows),
        "findings_parsed": f"{sum(1 for r in rows if r['findings_total'] != '')}/{len(rows)}",
        "tier_from_paths": sum(1 for r in rows if r["tier_source"] == "paths"),
    }
    return {"tiers": tiers, "total": total}


def issue_flow(issues, now, weeks=4):
    """Opened and closed per ISO week for the last `weeks` weeks, ending with the week of `now`."""
    monday = (now - timedelta(days=now.weekday())).date()
    out = []
    for back in range(weeks - 1, -1, -1):
        d = monday - timedelta(weeks=back)
        y, w, _ = d.isocalendar()
        label = f"{y}-W{w:02d}"
        opened = sum(1 for i in issues if _week(i["createdAt"]) == label)
        closed = sum(1 for i in issues if i.get("closedAt") and _week(i["closedAt"]) == label)
        out.append({"week": label, "opened": opened, "closed": closed, "net": opened - closed})
    return out


def _week(s):
    y, w, _ = ts(s).isocalendar()
    return f"{y}-W{w:02d}"


def format_summary(rows, flow, now, limit):
    s = summarize(rows, now)
    lines = [
        f"== review metrics, last {len(rows)} merged PRs (limit {limit}) ==",
        f"{'tier':<8}{'PRs':>4}  {'catch rate':<14}{'findings/PR':>12}{'follow-ups/PR':>15}  {'escape rate':<14}"
        "findings parsed  tier from paths",
    ]
    for t in s["tiers"]:
        lines.append(
            f"{t['tier']:<8}{t['prs']:>4}  {t['catch_rate']:<14}{t['findings_per_pr']:>12}"
            f"{t['followups_per_pr']:>15}  {t['escape_rate']:<14}{t['findings_parsed']:>15}  {t['tier_from_paths']:>9}"
        )
    tot = s["total"]
    lines.append(
        f"{'total':<8}{tot['prs']:>4}  findings parsed {tot['findings_parsed']}, "
        f"tier from paths {tot['tier_from_paths']} of {tot['prs']}"
    )
    open_n = sum(t["window_open"] for t in s["tiers"])
    unparsed = sum(t["unparsed"] for t in s["tiers"])
    lines.append(
        f"escape rate: {open_n} PR(s) with a 14-day window still open left out of the denominators"
    )
    lines.append(
        f"catch rate and findings/PR: {unparsed} PR(s) whose attestation could not be parsed left out"
    )
    lines.append("")
    lines.append("== issue flow, ISO weeks ==")
    lines.append(f"{'week':<10}{'opened':>7}{'closed':>7}{'net':>5}")
    for w in flow:
        lines.append(f"{w['week']:<10}{w['opened']:>7}{w['closed']:>7}{w['net']:>+5}")
    return "\n".join(lines)


# ---------------------------------------------------------------- I/O


def run(cmd, check=True):
    r = subprocess.run(
        cmd, capture_output=True, text=True
    )  # nosec B603 - fixed argument lists, no shell
    if check and r.returncode != 0:
        sys.exit(f"{' '.join(cmd[:4])}...: {r.stderr.strip()[:300]}")
    return r.stdout


def gh_json(*args):
    return json.loads(run(["gh", *args]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument(
        "--out", default=os.environ.get("REVIEW_METRICS_OUT", "logs/review_metrics.csv")
    )
    ap.add_argument(
        "--summary", action="store_true", help="print the per-tier and issue-flow summary"
    )
    ap.add_argument("--now", help="ISO 8601 UTC clock override")
    a = ap.parse_args(argv)
    now = ts(a.now) if a.now else datetime.now(timezone.utc)

    prs = gh_json(
        "pr", "list", "--state", "merged", "--limit", str(a.limit),
        "--json", "number,title,body,createdAt,mergedAt,closingIssuesReferences,files",
    )  # fmt: skip
    if not prs:
        sys.exit("no merged PRs returned")

    since = (
        (min(ts(p["createdAt"]) for p in prs) - timedelta(hours=FOLLOWUP_HOURS)).date().isoformat()
    )
    flow_start = ((now - timedelta(days=now.weekday())) - timedelta(weeks=3)).date().isoformat()
    fields = "number,createdAt,closedAt,title,body,labels"
    issue_limit = 1000
    issues = {}
    for search in (f"created:>={min(since, flow_start)}", f"closed:>={flow_start}"):
        batch = gh_json(
            "issue",
            "list",
            "--state",
            "all",
            "--limit",
            str(issue_limit),
            "--search",
            search,
            "--json",
            fields,
        )
        if len(batch) >= issue_limit:
            print(
                f"warning: issue search hit the {issue_limit} limit; counts may be low",
                file=sys.stderr,
            )
        issues.update({i["number"]: i for i in batch})
    issues = list(issues.values())

    git_log = run(["git", "log", "origin/main", f"--since={min(ts(p['mergedAt']) for p in prs).isoformat()}",
                   "--format=%H%x1f%s%x1f%b%x1e"])  # fmt: skip

    rows = []
    for p in prs:
        reader = run(["bash", str(ATTESTATION_SH), "read", str(p["number"])], check=False)
        comments = gh_json("pr", "view", str(p["number"]), "--json", "comments")["comments"]
        reopened = 0
        for n in [r["number"] for r in p.get("closingIssuesReferences") or []]:
            events = gh_json("api", f"repos/{{owner}}/{{repo}}/issues/{n}/events?per_page=100")
            reopened += sum(
                1
                for e in events
                if e.get("event") == "reopened" and ts(e["created_at"]) > ts(p["mergedAt"])
            )
        rows.append(
            build_row(
                p,
                attestation=pick_root_body(reader, comments),
                issues=issues,
                reverts=reverts_naming(git_log, p["number"]),
                reopened=reopened,
                now=now,
            )
        )

    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    print(f"{len(prs)} merged PRs read, {len(rows)} rows written to {out}")
    if a.summary:
        print(format_summary(rows, issue_flow(issues, now), now, a.limit))


if __name__ == "__main__":
    main()
