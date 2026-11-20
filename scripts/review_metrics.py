#!/usr/bin/env python3
"""Review metrics: catch, escape and follow-up counts per merged PR, and per risk tier (#520).

Reads merged PRs through `gh` and writes logs/review_metrics.csv (ignored by git).

  review_metrics.py [--limit 30] [--out logs/review_metrics.csv] [--summary] [--now ISO8601]

Grain: one row per merged PR. Primary key: `pr`. Row order is the order `gh pr list` returns.
Rerun rule: the file is overwritten from scratch, so a rerun on the same input is byte-identical.
`--now` pins the clock that decides `escape_window_closed`; it defaults to the current UTC time, and
a value with no zone is UTC. Timestamps are UTC. Merged PRs in equals rows out (30 read, 30 written
on a rerun of the same input); the script prints both counts.

Columns:
  tier, tier_source    the `Risk tier:` line of the PR body (source `line`; an explicit line always
                       wins), else derived from the PR's file list with the rules of
                       docs/DAILY_DEV_WORKFLOW.md section 1 (source `paths`: any High path gives
                       high, only docs, tests and harness paths gives low, else medium). `unknown`
                       with source `none` only when the file list is empty or missing. The
                       whole body is searched for the line, not just its Testing evidence section.
  findings_*           (fixed, accepted, routed, and noted for `noted, not filed`) counted from the root
                       attestation: the one `scripts/attestation.sh read` reports as ROOT (the owner's
                       newest unedited attestation that is not a carry-forward). The reader is the
                       authority on which comment counts; its ROOT line names only a commit, so the
                       comment is found with the reader's own checks (owner login, OWNER association,
                       unedited). A line can carry two dispositions ("fixed (...); routed to #517"),
                       so fixed + accepted + routed can exceed findings_total. `findings_routed`
                       counts `filed #<n>` and `routed to #<n>` alike.
  review_passes        the sum of the `<k> pass(es)` values on the Reviewer lines.
  followups_filed      the issues the root attestation names as filed, counted once each. A Findings
                       disposition `filed #<n>` names a new issue and counts as is. `routed to #<n>`
                       is the older spelling for both a new issue and a comment on an old one, so it
                       counts only when the issue was created from 24 hours before the PR opened to 24
                       hours after it merged (the Step 2 review runs before the PR exists). An issue
                       two attestations name counts for the earlier merge. An issue that qualifies as
                       an escape is never also a follow-up. Citations no longer count (owner,
                       2026-11-18): a sibling or planning issue that cites the PR is not a follow-up.
                       Empty, never 0, when the attestation can't be parsed.
  escapes              revert commits on origin/main naming the PR, plus reopenings of the closed
                       issue after the merge, both within 14 days of it, plus `bug` issues created after the merge and within
                       14 days that cite the PR or its closed issue. A follow-up is not an escape: an
                       issue that qualifies as an escape is never also counted as a follow-up.
  escape_window_closed true once 14 days have passed since the merge.
  parse_warnings       empty, or why a value is empty. An unparseable value is empty, never 0: a 0
                       means the reviewer found nothing. Also set when an attestation files more than
                       one issue, or a follow-up arrived labelled `ready-for-agent` (the label it was
                       created with, from the first minute of the issue's events; unreadable means
                       no warning). The summary lists both.

  review_metrics.py --check-body <file>   parse a drafted attestation body; exit 1 on any warning,
                                          or when its `- Reviewed-Commit:` line is missing or not 40 hex.
  review_metrics.py --check-root <file|->       the required `attestation` status's Findings rule (#542):
                                          exit 10, with one line on stdout, only on a problem that leaves a
                                          metric column empty. Soft warnings (two filed issues, an unread
                                          issue reference) pass here; --check-body still reports them.
  review_metrics.py --check-red-first <file|->  the status's Red-first rule (#542): the PR body needs a
                                          filled `Red-first:` line, and `n/a` needs `n/a (<reason>)`.
                                          Exit 10 and one line on a problem, as --check-root.

Limits: `git log origin/main` runs without a fetch, so reverts newer than the local ref are missed.
`gh pr list --state merged` orders by creation time, so "the last 30 merged" can differ at the edge.
`gh pr list --json files` and the issue events call return at most 100 each; a list of exactly 100
prints a warning on stderr, and a High path or a late reopening past the cap can be missed.
If `scripts/attestation.sh read` fails or prints nothing, the run fails with its error.
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
    d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    # A zone-less value is UTC, as --help says; astimezone() would read it as local time.
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)


# ---------------------------------------------------------------- parsing


def issue_refs(disp, keyword):
    """Issue numbers after `keyword` in a disposition: `#1`, `#1, #2`, `#1 and #2`, `#1,#2`."""
    return [
        int(n)
        for m in re.finditer(rf"{keyword} ((?:#\d+(?:\s*(?:,|and)\s*)?)+)", disp)
        for n in re.findall(r"#(\d+)", m.group(1))
    ]


def unread_ref(disp):
    """True when a `#n` follows an issue list directly, as in `filed #1 and then #2`, and was not read."""
    return any(
        re.match(r"[\s,&/]*(?:(?:and|then|also)\s+)*#\d", disp[m.end() :])
        for m in re.finditer(
            r"(?:(?<!not )\bfiled|\brouted to) (?:#\d+(?:\s*(?:,|and)\s*)?)+", disp
        )
    )


def parse_findings(body):
    """Counts from one attestation body. Counts are None, with warnings, when the block can't be read."""
    out = {
        "findings_total": None,
        "findings_fixed": None,
        "findings_accepted": None,
        "findings_routed": None,
        "findings_noted": None,
        "review_passes": None,
        "filed_issues": [],
        "routed_issues": [],
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
    filed_issues, routed_issues = [], []
    problems, problems_soft = [], []
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
        filed_here = issue_refs(disp, r"(?<!not )\bfiled")
        routed_here = issue_refs(disp, r"\brouted to")
        is_routed = bool(filed_here or routed_here)  # both spellings go to the issue tracker
        is_noted = disp.startswith("noted, not filed")
        if not (is_fixed or is_accepted or is_routed or is_noted):
            problems.append("a disposition is not fixed, accepted, filed, routed or noted")
            continue
        if unread_ref(disp):
            problems_soft.append(
                "a disposition names an unread issue (use `#a, #b` or `#a and #b`)"
            )
        total += 1
        filed_issues += [n for n in filed_here if n not in filed_issues]
        routed_issues += [n for n in routed_here if n not in routed_issues]
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
        filed_issues=filed_issues,
        routed_issues=routed_issues,
    )
    out["warnings"].extend(dict.fromkeys(problems_soft))
    if len(filed_issues) > 1:
        out["warnings"].append(f"attestation files {len(filed_issues)} issues (the rule allows 1)")
    return out


# Authority: docs/DAILY_DEV_WORKFLOW.md §1 (the risk classifier), plus the owner's call of
# 2026-11-14 that cohort fixes in app/utils/sql_generator.py are High. Re-read §1 when it changes.
# §1 also lists "IRB-scope logic" as High; no path in the repo implements it, so no rule matches it.
# Paths §1 does not name (.github/**, config/**) fall to medium.
HIGH_PATHS = re.compile(
    r"^(app/services/(sql_validator|sql_synthesis|feasibility_service)\.py"
    r"|app/utils/sql_generator\.py"
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


def read_attestation(n):
    """The reader's lines for PR `n`. The reader always prints something, so a failure or empty output stops the run."""
    out = run(["bash", str(ATTESTATION_SH), "read", str(n)])
    if not out.strip():
        sys.exit(f"attestation.sh read {n}: the reader printed nothing")
    return out


def pick_root_body(reader_output, comments, pr_url):
    """(body, warnings). The reader's ROOT line names the root attestation's commit; find that comment.

    scripts/attestation.sh read is the authority on which comment counts, and its ROOT line carries
    only a commit. So the comment is found with the reader's own three checks: the repo owner's
    login (the PR URL's owner), authorAssociation OWNER, and never edited.
    """
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
    owner = pr_url.split("/")[3]
    for c in reversed(comments):
        b = c["body"]
        if (
            (c.get("author") or {}).get("login") == owner
            and c.get("authorAssociation") == "OWNER"
            and c.get("includesCreatedEdit") is False
            and b.startswith("## Review attestation")
            and re.search(rf"(?m)^- Reviewed-Commit: {sha}", b)
            and not re.search(r"(?m)^- Carried-From:", b)
        ):
            return b, warnings
    return None, warnings + ["root attestation comment not found"]


REPO_URL = r"github\.com/jagnyesh/researchflow"
FENCE = re.compile(r"```.*?```", re.S)


def cites(issue, numbers):
    """Used for escapes only. Fenced code blocks and other repositories' references don't count."""
    text = FENCE.sub("", f"{issue.get('title') or ''}\n{issue.get('body') or ''}")
    return any(
        re.search(rf"(?:(?<![\w#/&])|(?<=PR))#{n}(?!\d)|{REPO_URL}/(?:pull|issues)/{n}(?!\d)", text)
        for n in numbers
    )


def reverts_naming(git_log, pr, merged=None):
    """Hashes of revert commits in `git log --format=%H%x1f%s%x1f%b%x1f%cI%x1e` text that name the PR.

    With `merged`, a revert dated more than ESCAPE_DAYS after it is not an escape. A record with no
    date field is kept.
    """
    found = []
    for rec in git_log.split("\x1e"):
        parts = rec.strip("\n").split("\x1f")
        if len(parts) < 3 or not parts[1].startswith("Revert"):
            continue
        if re.search(rf"(?<![\w#/])#{pr}(?!\d)", parts[1] + "\n" + parts[2]):
            if merged is not None and len(parts) > 3 and parts[3].strip():
                if ts(parts[3].strip()) > merged + timedelta(days=ESCAPE_DAYS):
                    continue
            found.append(parts[0].strip())
    return found


# ---------------------------------------------------------------- rows


ARRIVAL_SECONDS = 60
_UNSET = object()


def arrival_labels(events, created_at):
    """Labels added within a minute of the issue's creation, from `gh api .../issues/<n>/events`."""
    t0 = ts(created_at)
    return {
        e["label"]["name"]
        for e in events
        if e.get("event") == "labeled"
        and timedelta(0) <= ts(e["created_at"]) - t0 <= timedelta(seconds=ARRIVAL_SECONDS)
    }


def followup_candidates(pr, body, issues):
    """Issue numbers the PR's root attestation names as filed, or None when it can't be parsed.

    `filed #n` counts as is. `routed to #n` is the older spelling for both a new issue and a comment
    on an old one, so it counts only when the issue was created from 24 hours before the PR opened to
    24 hours after it merged.
    """
    if body is None:
        return None
    f = parse_findings(body)
    if f["findings_total"] is None:
        return None
    lo = ts(pr["createdAt"]) - timedelta(hours=FOLLOWUP_HOURS)
    hi = ts(pr["mergedAt"]) + timedelta(hours=FOLLOWUP_HOURS)
    made = {i["number"]: ts(i["createdAt"]) for i in issues}
    named = set(f["filed_issues"])
    named |= {n for n in f["routed_issues"] if n in made and lo <= made[n] <= hi}
    return named


def claim_followups(prs, candidates):
    """{pr number: issues it owns}. An issue two attestations name goes to the earlier merge.

    `prs` is {number: gh pr dict}; `candidates` is {number: set or None}. A None stays None.
    """
    taken, owned = set(), {}
    for n in sorted(prs, key=lambda k: (ts(prs[k]["mergedAt"]), k)):
        if candidates[n] is None:
            owned[n] = None
            continue
        owned[n] = candidates[n] - taken
        taken |= owned[n]
    return owned


def build_row(pr, attestation, issues, reverts, reopened, now, owned=_UNSET, arrival_labels=None):
    """One CSV row (strings). `attestation` is (root body or None, warnings).

    `owned` is the PR's issues after claim_followups; left out, the PR owns all it names.
    `arrival_labels` is {issue: labels it arrived with}; an issue missing from it isn't checked.
    """
    body, warnings = attestation
    warnings = list(warnings)
    f = None
    if body is not None:
        f = parse_findings(body)
        warnings += f["warnings"]
    merged = ts(pr["mergedAt"])
    closing = [r["number"] for r in pr.get("closingIssuesReferences") or []]
    numbers = [pr["number"], *closing]

    escaped_issues = {
        i["number"]
        for i in issues
        if any(lab["name"] == "bug" for lab in i.get("labels") or [])
        and merged < ts(i["createdAt"]) <= merged + timedelta(days=ESCAPE_DAYS)
        and cites(i, numbers)
    }
    if owned is _UNSET:
        owned = followup_candidates(pr, body, issues)
    follow = None if owned is None else owned - escaped_issues
    for n in sorted(follow or ()):
        if "ready-for-agent" in (arrival_labels or {}).get(n, ()):
            warnings.append(f"follow-up #{n} arrived ready-for-agent")
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
        "followups_filed": "" if follow is None else len(follow),
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
        counted = [r for r in rs if r["followups_filed"] != ""]
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
                    f"{sum(r['followups_filed'] for r in counted) / len(counted):.2f}"
                    if counted
                    else "n/a"
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
        f"catch rate, findings/PR and follow-ups/PR: {unparsed} PR(s) whose attestation could not be "
        "parsed left out"
    )
    many = [f"#{r['pr']}" for r in rows if "attestation files " in r["parse_warnings"]]
    ready = [f"#{r['pr']}" for r in rows if "arrived ready-for-agent" in r["parse_warnings"]]
    lines.append(f"PRs whose attestation files more than one issue: {', '.join(many) or 'none'}")
    lines.append(f"PRs with a follow-up that arrived ready-for-agent: {', '.join(ready) or 'none'}")
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


def issue_events(n):
    events = gh_json("api", f"repos/{{owner}}/{{repo}}/issues/{n}/events?per_page=100")
    if len(events) >= 100:
        print(
            f"warning: issue #{n} has 100 events; later ones are not read, so a reopening may be missed",
            file=sys.stderr,
        )
    return events


def created_at(n):
    """An issue's creation time, or None when it can't be read (then no label check is made)."""
    r = subprocess.run(
        ["gh", "issue", "view", str(n), "--json", "createdAt"], capture_output=True, text=True
    )  # nosec B603 B607 - fixed argument list, no shell
    try:
        return json.loads(r.stdout)["createdAt"] if r.returncode == 0 else None
    except (ValueError, KeyError):
        return None


def blocking_problems(body):
    """The parse problems that leave a metric column empty. The `attestation` status fails on these."""
    f = parse_findings(body)
    problems = [] if f["review_passes"] is not None else ["no pass count on a Reviewer line"]
    if f["findings_total"] is None:
        problems += [w for w in f["warnings"] if w not in problems]
    return problems


# A list item, a numbered item or a quote may carry it, and the label may be bold with the colon
# inside or outside the bold: `- **Red-first:** x` and `- **Red-first**: x` both count.
RED_FIRST_LINE = re.compile(
    r"(?mi)^[ \t]*(?:>[ \t]*)*(?:(?:[-*+]|\d+[.)])[ \t]+)?\**red-first\**:\**(?P<v>.*)$"
)
# --check-root and --check-red-first exit with this code, and print one line, when they find a
# problem. A Python crash exits 1 with nothing on stdout, so 1 can never mean "problem found":
# scripts/attestation.sh reads any other non-zero exit as "the check didn't run" and posts error.
PROBLEM_EXIT = 10


def red_first_problem(body):
    """None when every `Red-first:` line in a PR body is filled and there is at least one, else why not."""
    values = [m.group("v").strip() for m in RED_FIRST_LINE.finditer(body or "")]
    if not values or any(not v or re.fullmatch(r"<[^>]*>", v) for v in values):
        return "PR body has no filled Red-first: line (validate-and-ship Step 1)."
    for v in values:
        if re.match(r"n/a\b", v, re.I) and not re.match(r"n/a\s*\(\s*[^\s)]", v, re.I):
            return "PR body's Red-first: n/a has no reason; write n/a (<reason>) (validate-and-ship Step 1)."
    return None


def read_text(path):
    return sys.stdin.read() if path == "-" else Path(path).read_text()


def check_body(path):
    text = read_text(path)
    f = parse_findings(text)
    warnings = list(f["warnings"])
    if not re.search(r"(?m)^- Reviewed-Commit: [0-9a-f]{40}\r?$", text):
        warnings.append("no `- Reviewed-Commit: <40-hex sha>` line (spelled exactly)")
    for w in warnings:
        print(f"attestation format: {w}", file=sys.stderr)
    if warnings:
        sys.exit(1)
    print("attestation format ok")


def check_root(path):
    problems = blocking_problems(read_text(path))
    if problems:
        print(f"Root attestation's Findings don't parse: {'; '.join(problems)}.")
        sys.exit(PROBLEM_EXIT)


def check_red_first(path):
    problem = red_first_problem(read_text(path))
    if problem:
        print(problem)
        sys.exit(PROBLEM_EXIT)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--limit", type=int, default=30)
    ap.add_argument(
        "--out", default=os.environ.get("REVIEW_METRICS_OUT", "logs/review_metrics.csv")
    )
    ap.add_argument(
        "--summary", action="store_true", help="print the per-tier and issue-flow summary"
    )
    ap.add_argument("--now", help="ISO 8601 clock override; a value with no zone is UTC")
    ap.add_argument(
        "--check-body",
        metavar="FILE",
        help="parse a drafted attestation body; exit non-zero on any format warning",
    )
    ap.add_argument("--check-root", metavar="FILE", help="the attestation status's Findings rule")
    ap.add_argument(
        "--check-red-first", metavar="FILE", help="the attestation status's Red-first rule"
    )
    a = ap.parse_args(argv)
    if a.check_body:
        return check_body(a.check_body)
    if a.check_root:
        return check_root(a.check_root)
    if a.check_red_first:
        return check_red_first(a.check_red_first)
    now = ts(a.now) if a.now else datetime.now(timezone.utc)

    prs = gh_json(
        "pr", "list", "--state", "merged", "--limit", str(a.limit),
        "--json", "number,title,body,createdAt,mergedAt,closingIssuesReferences,files",
    )  # fmt: skip
    if not prs:
        sys.exit("no merged PRs returned")
    for p in prs:
        if len(p.get("files") or []) == 100:
            print(
                f"warning: PR #{p['number']} lists exactly 100 files; the list may be cut, so a High path may be missed",
                file=sys.stderr,
            )

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
                   "--format=%H%x1f%s%x1f%b%x1f%cI%x1e"])  # fmt: skip

    attested, reopened = {}, {}
    for p in prs:
        reader = read_attestation(p["number"])
        view = gh_json("pr", "view", str(p["number"]), "--json", "url,comments")
        attested[p["number"]] = pick_root_body(reader, view["comments"], view["url"])
        merged = ts(p["mergedAt"])
        reopened[p["number"]] = 0
        for n in [r["number"] for r in p.get("closingIssuesReferences") or []]:
            reopened[p["number"]] += sum(
                1
                for e in issue_events(n)
                if e.get("event") == "reopened"
                and merged < ts(e["created_at"]) <= merged + timedelta(days=ESCAPE_DAYS)
            )

    by_number = {p["number"]: p for p in prs}
    owned = claim_followups(
        by_number,
        {n: followup_candidates(by_number[n], attested[n][0], issues) for n in by_number},
    )
    created = {i["number"]: i["createdAt"] for i in issues}
    labels = {}
    for n in sorted({n for o in owned.values() for n in o or ()}):
        # A filed issue can predate the issue search, so its creation time is read on its own.
        made = created.get(n) or created_at(n)
        if made:
            labels[n] = arrival_labels(issue_events(n), made)

    rows = [
        build_row(
            p,
            attestation=attested[p["number"]],
            issues=issues,
            reverts=reverts_naming(git_log, p["number"], ts(p["mergedAt"])),
            reopened=reopened[p["number"]],
            now=now,
            owned=owned[p["number"]],
            arrival_labels=labels,
        )
        for p in prs
    ]

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
