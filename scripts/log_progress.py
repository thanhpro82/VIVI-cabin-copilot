#!/usr/bin/env python3
"""
post-commit hook — auto-append a progress line to frontend/PROGRESS.md
whenever a commit touches files under frontend/.

Only meant for the frontend/ workstream (see frontend/CLAUDE.md mục 11).
Never blocks a commit: any failure here is swallowed silently, same
philosophy as scripts/log_hook.py.

Design note (no amend, no lock file): earlier versions used
`git commit --amend` to fold the log line into the commit that triggered
it, guarded by a lock file to stop the resulting recursive post-commit
call. That is fragile — if the script dies between creating the lock and
running the amend, the lock is left behind and silently swallows the
*next* real commit's log line.

Instead, the log line is committed as its own tiny follow-up commit
(pathspec-limited to frontend/PROGRESS.md, so any other dirty files in
the working tree are left untouched). Recursion is stopped by
construction, not by external state: the guard below skips any commit
whose diff is *exactly* frontend/PROGRESS.md — which is true of the
follow-up commit itself — so the chain always terminates after one hop,
even if the script crashes mid-way (worst case: nothing gets committed,
never a loop).
"""
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

VN_TZ = timezone(timedelta(hours=7))
PROGRESS_REL_PATH = "frontend/PROGRESS.md"


def git(*args) -> str:
    # Decode as UTF-8 explicitly: on Windows, subprocess text-mode falls back
    # to the system code page (cp1252), which mangles Vietnamese commit
    # messages into mojibake. Same fix as scripts/log_hook.py's stdin read.
    try:
        raw = subprocess.check_output(["git", *args], stderr=subprocess.DEVNULL)
        return raw.decode("utf-8", errors="replace").strip()
    except Exception:
        return ""


def main():
    repo_root = Path(git("rev-parse", "--show-toplevel") or ".")

    changed = git(
        "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
    ).splitlines()
    if not changed:
        sys.exit(0)

    # Base case: this commit IS the auto-log follow-up commit from a
    # previous invocation — do nothing, so the chain stops here.
    if changed == [PROGRESS_REL_PATH]:
        sys.exit(0)

    if not any(f.startswith("frontend/") for f in changed):
        sys.exit(0)

    subject = git("log", "-1", "--pretty=%s")
    if not subject:
        sys.exit(0)

    progress_file = repo_root / PROGRESS_REL_PATH
    if not progress_file.exists():
        sys.exit(0)  # scaffold hasn't created it yet — nothing to append to

    ts = datetime.now(VN_TZ).strftime("%Y-%m-%d %H:%M")
    n_files = len(changed)
    line = f"- {ts} · {subject} · {n_files} file(s)\n"

    with open(progress_file, "a", encoding="utf-8") as f:
        f.write(line)

    # Pathspec-limited add + commit: only frontend/PROGRESS.md is staged and
    # committed, regardless of whatever else is dirty in the working tree.
    subprocess.run(
        ["git", "add", "--", PROGRESS_REL_PATH],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    subprocess.run(
        [
            "git", "commit", "--no-verify",
            "-m", "chore(fe): cập nhật PROGRESS.md [auto]",
            "--", PROGRESS_REL_PATH,
        ],
        cwd=repo_root,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        # Never block a commit because of this hook.
        sys.exit(0)
