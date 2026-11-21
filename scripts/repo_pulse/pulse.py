"""Pure helpers shared by the Repo Pulse exporter (#541). Nothing here touches git, gh or the disk."""

import os
import re

AREAS = ("app", "tests", "docs", "scripts", "ci", "other")


def area(path):
    """Top-level area of a repo path. Root-level *.md files count as docs."""
    if path.startswith("app/"):
        return "app"
    if path.startswith("tests/"):
        return "tests"
    if path.startswith("scripts/"):
        return "scripts"
    if path.startswith(".github/"):
        return "ci"
    if path.startswith("docs/") or ("/" not in path and path.endswith(".md")):
        return "docs"
    return "other"


def ext(path):
    """File extension as loc_now.csv groups it: '(none)' for no dot, the part after a leading dot for dotfiles."""
    b = os.path.basename(path)
    if "." not in b:
        return "(none)"
    return b.rsplit(".", 1)[1]


def split_rename(p):
    """A git --numstat path → (old, new). 'a/{b => c}/d' and 'a => b' are renames; anything else is (None, p)."""
    m = re.match(r"^(.*)\{(.*) => (.*)\}(.*)$", p)
    if m:
        pre, a, b, post = m.groups()
        return re.sub("//", "/", pre + a + post), re.sub("//", "/", pre + b + post)
    if " => " in p:
        a, b = p.split(" => ", 1)
        return a, b
    return None, p


def lane_status(branch, ahead, pr_state, folder_exists=True):
    """(counts, why) for one worktree, by docs/DAILY_DEV_WORKFLOW.md §3: a worktree counts as a lane unless its PR
    is merged or closed, its folder is gone, or it is detached with no commits."""
    if pr_state == "merged":
        return "no", "PR merged"
    if pr_state == "closed":
        return "no", "PR closed"
    if not folder_exists:
        return "no", "folder gone"
    if pr_state == "open":
        return "yes", "open PR"
    if branch.startswith("(detached") and ahead == 0:
        return "no", "detached, no commits"
    if ahead == 0:
        return "yes", "no commits yet"
    return "yes", "commits, no PR yet"


def parse_worktrees(porcelain):
    """`git worktree list --porcelain` → [{path, head, branch}] (branch None when detached), main checkout first."""
    out, cur = [], {}
    for line in porcelain.splitlines() + [""]:
        if line.startswith("worktree "):
            cur = {"path": line[9:], "head": "", "branch": None}
        elif line.startswith("HEAD "):
            cur["head"] = line[5:]
        elif line.startswith("branch refs/heads/"):
            cur["branch"] = line[len("branch refs/heads/") :]
        elif line == "" and cur:
            out.append(cur)
            cur = {}
    return out


def worktree_labels(trees):
    """Branch name, or '(detached at <sha7>)'; detached ones sharing a head also get the folder name, so labels are unique."""
    sha7 = [t["head"][:7] for t in trees]
    labels = []
    for t, s in zip(trees, sha7):
        if t["branch"]:
            labels.append(t["branch"])
        elif (
            sha7.count(s) > 1
            and sum(1 for u in trees if not u["branch"] and u["head"][:7] == s) > 1
        ):
            labels.append(f"(detached at {s}, {os.path.basename(t['path'].rstrip('/'))})")
        else:
            labels.append(f"(detached at {s})")
    return labels
