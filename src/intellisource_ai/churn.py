"""Git-derived change-frequency signal, computed via a single `git log`
pass over the checked-out repository.

Never raises: a shallow clone, a `--local-path` directory with no `.git`,
a missing `git` binary, or any other environment where history isn't
available should degrade to "no churn data" (an empty dict), the same
graceful-degradation policy `pipeline.py` applies to a failed parse or a
failed LLM batch -- not something that aborts the run.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from intellisource_ai.schemas import ChurnMetrics

logger = logging.getLogger(__name__)

_COMMIT_MARKER = "\x02COMMIT\x02"
_LOG_TIMEOUT_SECONDS = 30


def _relative_prefix(repo_root: Path) -> str | None:
    """Find how `repo_root` sits relative to its enclosing git repo's top
    level, so `git log` output (always relative to that top level, not to
    `-C`) can be re-anchored to match `repo_root` -- the same base every
    other module's `file_path` values are relative to.

    Returns `""` when `repo_root` *is* the top level (the common case: a
    fresh clone, or a GitHub Action's `$GITHUB_WORKSPACE`), a subdirectory
    prefix when it's nested inside a larger repo, or `None` if `repo_root`
    isn't inside a git repo at all.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            timeout=_LOG_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None

    top_level = Path(result.stdout.strip())
    try:
        relative = repo_root.resolve().relative_to(top_level.resolve())
    except ValueError:
        return None
    relative_posix = relative.as_posix()
    return "" if relative_posix == "." else relative_posix


def compute_churn(repo_root: Path) -> dict[str, ChurnMetrics]:
    """Return `{file_path: ChurnMetrics}` for every file with at least one
    commit in the available history, keyed by the same forward-slash
    relative path used throughout the rest of the pipeline (relative to
    `repo_root`, not necessarily the git repo's own top level).

    `git log` output is reverse-chronological by default, so the first
    commit encountered touching a given file is that file's most recent
    modification -- no separate sort/max pass is needed.
    """
    prefix = _relative_prefix(repo_root)
    if prefix is None:
        logger.warning("Skipping churn analysis: %s is not inside a git repository", repo_root)
        return {}
    prefix_with_slash = f"{prefix}/" if prefix else ""

    log_command = [
        "git",
        "-C",
        str(repo_root),
        "log",
        f"--pretty=format:{_COMMIT_MARKER}%ad",
        "--date=short",
        "--name-only",
    ]
    try:
        result = subprocess.run(
            log_command,
            capture_output=True,
            text=True,
            timeout=_LOG_TIMEOUT_SECONDS,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        logger.warning("Skipping churn analysis: %s", exc)
        return {}

    if result.returncode != 0:
        logger.warning(
            "Skipping churn analysis: `git log` failed in %s: %s", repo_root, result.stderr.strip()
        )
        return {}

    commit_counts: dict[str, int] = {}
    last_modified: dict[str, str] = {}
    current_date: str | None = None

    for line in result.stdout.splitlines():
        if line.startswith(_COMMIT_MARKER):
            current_date = line[len(_COMMIT_MARKER) :]
            continue
        raw_path = line.strip()
        if not raw_path or current_date is None:
            continue
        if prefix_with_slash and not raw_path.startswith(prefix_with_slash):
            continue  # touched a file outside repo_root's subtree -- not ours to report
        file_path = raw_path[len(prefix_with_slash) :] if prefix_with_slash else raw_path
        commit_counts[file_path] = commit_counts.get(file_path, 0) + 1
        last_modified.setdefault(file_path, current_date)

    return {
        file_path: ChurnMetrics(commit_count=count, last_modified=last_modified.get(file_path))
        for file_path, count in commit_counts.items()
    }
