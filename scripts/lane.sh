#!/bin/bash
# lane.sh — parallel-lane harness for the throughput workflow.
#
# Automates docs/DAILY_DEV_WORKFLOW.md §5.7 (worktree add + env copy + dep sync)
# and §5.6 (tmux window per lane), with the §7 WIP=2 guardrail enforced.
#
# A "lane" is a git worktree on its own per-issue branch, running an agent in
# its own tmux window. One branch per issue, one PR per issue (§4.2).
#
#   scripts/lane.sh open  <issue> [--type feat|fix] [--slug <slug>] [--no-deps] [--force]
#   scripts/lane.sh close <issue> [--force] [--delete-branch]
#   scripts/lane.sh list
#
# Examples:
#   scripts/lane.sh open 82 --type fix --slug dob-column
#   scripts/lane.sh close 82 --delete-branch

set -euo pipefail

TMUX_SESSION="researchflow"
WIP_LIMIT=2

die()  { echo "lane: $*" >&2; exit 1; }
info() { echo "  $*"; }

repo_root()    { git rev-parse --show-toplevel 2>/dev/null || die "not inside a git repo"; }
repo_name()    { basename "$(repo_root)"; }
default_branch() {
  # symbolic-ref prints nothing on failure (unlike rev-parse, which prints the
  # literal 'origin/HEAD' to stdout and would leak a bad ref under pipefail).
  local b
  if b="$(git symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null)" && [ -n "$b" ]; then
    echo "${b#origin/}"
  elif git show-ref --verify -q refs/heads/main; then
    echo main
  else
    echo master
  fi
}

# Directory a lane's worktree lives in: sibling of the repo, <repo>-<issue>.
lane_dir() {
  local issue="$1"
  echo "$(dirname "$(repo_root)")/$(repo_name)-${issue}"
}

# Count active lane worktrees: only sibling dirs matching <repo>-<issue>, so an
# unrelated worktree (e.g. a .claude/worktrees/ one) doesn't inflate the WIP.
# substr over the whole line (not $2) tolerates spaces in the path; awk exits 0
# on no-match so `set -e` doesn't kill a bare assignment.
active_lane_count() {
  local prefix; prefix="$(dirname "$(repo_root)")/$(repo_name)-"
  git worktree list --porcelain \
    | awk -v p="$prefix" '
        index($0, "worktree ") == 1 {
          path = substr($0, 10)
          if (index(path, p) == 1 && substr(path, length(p) + 1) ~ /^[0-9]+$/) c++
        }
        END { print c + 0 }'
}

tmux_has_session() { tmux has-session -t "$TMUX_SESSION" 2>/dev/null; }

cmd_open() {
  local issue="" type="feat" slug="" do_deps=1 force=0
  [ $# -gt 0 ] || die "open needs an issue number"
  issue="$1"; shift
  [[ "$issue" =~ ^[0-9]+$ ]] || die "issue must be numeric, got '$issue'"
  while [ $# -gt 0 ]; do
    case "$1" in
      --type)  type="${2:-}"; shift 2 ;;
      --slug)  slug="${2:-}"; shift 2 ;;
      --no-deps) do_deps=0; shift ;;
      --force) force=1; shift ;;
      *) die "unknown flag for open: $1" ;;
    esac
  done
  case "$type" in feat|fix) ;; *) die "--type must be feat or fix" ;; esac

  local count; count="$(active_lane_count)"
  if [ "$count" -ge "$WIP_LIMIT" ] && [ "$force" -eq 0 ]; then
    die "WIP limit reached ($count/$WIP_LIMIT active lanes). Close a lane first, or --force (see §7: never scale past validation)."
  fi

  local branch dir base main env_src
  branch="${type}/${issue}${slug:+-$slug}"
  dir="$(lane_dir "$issue")"
  base="$(default_branch)"
  main="$(repo_root)"
  [ -e "$dir" ] && die "worktree dir already exists: $dir"

  echo "Opening lane #$issue → $dir (branch $branch off $base)"
  git -C "$main" fetch origin "$base" --quiet 2>/dev/null || true
  # Prefer origin/<base> so the lane starts from latest main, not local drift.
  # `if` (not `&&`) so a missing origin ref doesn't trip `set -e`.
  local start="$base"
  if git -C "$main" show-ref --verify -q "refs/remotes/origin/$base"; then
    start="origin/$base"
  fi
  git -C "$main" worktree add "$dir" -b "$branch" "$start"

  env_src="$main/.env"
  if [ -f "$env_src" ]; then cp "$env_src" "$dir/.env"; info "copied .env"; else info "no .env to copy (skipped)"; fi

  if [ "$do_deps" -eq 1 ]; then
    if command -v uv >/dev/null 2>&1; then
      info "creating venv + syncing deps (isolated to the lane's own .venv)…"
      # Isolate to the worktree's venv. A shell profile may export VIRTUAL_ENV
      # or CONDA_PREFIX (an already-activated env); a bare `uv pip sync` honors
      # those over ./.venv and would DESTRUCTIVELY rewrite that shared env.
      # `--python "$py"` is LOAD-BEARING: it is authoritative over both
      # VIRTUAL_ENV and CONDA_PREFIX — do NOT drop it (that reopens the hijack
      # for conda users). `unset VIRTUAL_ENV` is belt-and-suspenders and also
      # silences uv's env-mismatch warning.
      # requirements.lock is the exact runtime env (synced); requirements-dev.txt
      # (pytest, fakeredis, …) is layered on top with `install` so a lane can run
      # tests out of the box. `sync` first pins runtime versions; `install` is
      # additive and won't remove them. `-c requirements.lock` constrains the dev
      # layer to those pins, so a dev floor above a lock pin hard-errors (→ die)
      # instead of silently drifting the runtime env. The `[ ! -f ] ||` guard
      # keeps a repo without a dev file from failing the chain into `die`.
      local py="$dir/.venv/bin/python"
      ( cd "$dir" && unset VIRTUAL_ENV && uv venv --quiet \
          && uv pip sync --python "$py" config/requirements.lock \
          && { [ ! -f config/requirements-dev.txt ] \
                 || uv pip install --quiet --python "$py" \
                      -c config/requirements.lock -r config/requirements-dev.txt ; } ) \
        || die "dep sync failed in $dir"
      info "deps synced into $dir/.venv (runtime + dev/test)"
    else
      info "uv not found — skipping dep sync; in $dir run: uv venv && uv pip sync --python .venv/bin/python config/requirements.lock && uv pip install --python .venv/bin/python -c config/requirements.lock -r config/requirements-dev.txt"
    fi
  else
    info "--no-deps: skipped venv + dep sync"
  fi

  local win="lane:$issue"
  if [ -n "${TMUX:-}" ]; then
    tmux new-window -n "$win" -c "$dir"; info "tmux window '$win' opened in current session"
  elif tmux_has_session; then
    tmux new-window -t "$TMUX_SESSION" -n "$win" -c "$dir"; info "tmux window '$win' opened in session '$TMUX_SESSION'"
  else
    info "no tmux session; start one:  tmux new -s $TMUX_SESSION  (then re-run to get a lane window)"
  fi

  echo
  echo "Lane #$issue ready. Next:"
  echo "  cd $dir"
  echo "  # launch Claude Code, hand off the plan, then: /tdd → /validate-and-ship"
}

cmd_close() {
  local issue="" force=0 del_branch=0
  [ $# -gt 0 ] || die "close needs an issue number"
  issue="$1"; shift
  [[ "$issue" =~ ^[0-9]+$ ]] || die "issue must be numeric, got '$issue'"
  while [ $# -gt 0 ]; do
    case "$1" in
      --force) force=1; shift ;;
      --delete-branch) del_branch=1; shift ;;
      *) die "unknown flag for close: $1" ;;
    esac
  done

  local dir main; dir="$(lane_dir "$issue")"; main="$(repo_root)"
  local branch=""
  branch="$(git -C "$dir" rev-parse --abbrev-ref HEAD 2>/dev/null || true)"

  echo "Closing lane #$issue ($dir)"
  if [ -d "$dir" ]; then
    if [ "$force" -eq 1 ]; then git -C "$main" worktree remove --force "$dir"
    else git -C "$main" worktree remove "$dir" || die "worktree has changes; commit/push or re-run with --force"; fi
    info "worktree removed"
  else
    info "no worktree dir; pruning stale registration"
  fi
  git -C "$main" worktree prune

  if tmux_has_session; then
    tmux kill-window -t "$TMUX_SESSION:lane:$issue" 2>/dev/null && info "tmux window closed" || true
  fi

  if [ "$del_branch" -eq 1 ] && [ -n "$branch" ]; then
    # -d refuses an unmerged branch (data-loss guard); --force escalates to -D.
    local delflag="-d"; [ "$force" -eq 1 ] && delflag="-D"
    if git -C "$main" branch "$delflag" "$branch" 2>/dev/null; then
      info "deleted branch $branch"
    else
      info "branch $branch kept (unmerged — pass --force to force-delete, or: git branch -D $branch)"
    fi
  fi
}

cmd_list() {
  echo "Worktrees (lanes):"
  git worktree list
  echo
  echo "WIP: $(active_lane_count)/$WIP_LIMIT active lane(s)"
  if tmux_has_session; then
    echo
    echo "tmux windows in '$TMUX_SESSION':"
    tmux list-windows -t "$TMUX_SESSION" -F "  #{window_index}: #{window_name}"
  fi
}

usage() {
  # Print the leading comment block (after the shebang), stopping at the first
  # non-comment line so code never leaks into --help.
  awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "$0"
}

main() {
  local cmd="${1:-}"; shift || true
  case "$cmd" in
    open)  cmd_open  "$@" ;;
    close) cmd_close "$@" ;;
    list|status) cmd_list ;;
    ""|-h|--help|help) usage ;;
    *) die "unknown command '$cmd' (open|close|list)" ;;
  esac
}

main "$@"
