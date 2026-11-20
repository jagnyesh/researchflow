"""Thin REST helper over `gh api` with manual paging: --paginate follows Link headers to repositories/<id>/... URLs,
which some proxies refuse, and GraphQL is not used at all, so this runs wherever `gh api` reaches the REST API.
"""

import json, os, subprocess, time  # nosec B404 - fixed git/gh argument lists, no shell
from concurrent.futures import ThreadPoolExecutor

R = "repos/" + os.environ["REPO_PULSE_REPO"]
ENV = {k: v for k, v in os.environ.items() if k != "GH_TOKEN"}


def api(path, tries=4):
    for t in range(tries):
        p = subprocess.run(
            ["gh", "api", path], capture_output=True, text=True, env=ENV
        )  # nosec B603 B607 - fixed git/gh argument lists, no shell
        if p.returncode == 0:
            return json.loads(p.stdout) if p.stdout.strip() else None
        if "HTTP 404" in p.stderr:
            return None
        time.sleep(2 * (t + 1))
    raise RuntimeError(f"{path}: {p.stderr.strip()[:300]}")


def paged(path, key=None, max_pages=100):
    out, sep = [], "&" if "?" in path else "?"
    for page in range(1, max_pages + 1):
        d = api(f"{path}{sep}per_page=100&page={page}")
        items = d.get(key, []) if key else d
        out += items
        if len(items) < 100:
            break
    return out


def pmap(fn, items, workers=12):
    with ThreadPoolExecutor(workers) as ex:
        return list(ex.map(fn, items))
