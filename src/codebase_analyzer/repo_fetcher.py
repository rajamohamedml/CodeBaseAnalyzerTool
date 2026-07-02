"""Fetches the target repository configured in `Settings` onto local disk.

Shells out to the system `git` binary rather than a Python git library —
a shallow clone is a one-line operation, and avoiding an extra dependency
for something the OS already does well is the simpler choice here.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from codebase_analyzer.exceptions import RepoFetchError

logger = logging.getLogger(__name__)


def fetch_repository(repo_url: str, repo_ref: str, destination: Path, *, refresh: bool = False) -> Path:
    """Shallow-clone `repo_url` at `repo_ref` into `destination`.

    Args:
        repo_url: HTTPS (or SSH) URL of the target git repository. Supplied
            entirely by the caller — this function has no notion of a
            "default" repo.
        repo_ref: Branch, tag, or ref to check out.
        destination: Local directory the repo should live in. Reused across
            runs unless `refresh` is set, so repeated analyses of the same
            repo don't re-download it every time.
        refresh: If True, delete any existing clone at `destination` first.

    Returns:
        The path to the checked-out repository (same as `destination`).

    Raises:
        RepoFetchError: if `git` is not installed, the URL/ref is invalid,
            or the clone otherwise fails. The underlying `git` stderr is
            included in the message for debuggability.
    """
    if refresh and destination.exists():
        logger.info("Removing existing clone at %s (--refresh-repo)", destination)
        shutil.rmtree(destination)

    if destination.exists() and any(destination.iterdir()):
        logger.info("Reusing existing clone at %s", destination)
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    logger.info("Cloning %s (ref=%s) into %s", repo_url, repo_ref, destination)

    try:
        subprocess.run(
            [
                "git",
                "clone",
                "--depth",
                "1",
                "--branch",
                repo_ref,
                repo_url,
                str(destination),
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RepoFetchError(
            "git is not installed or not on PATH. Install git and retry."
        ) from exc
    except subprocess.CalledProcessError as exc:
        # Clean up a partial clone so a retry doesn't see a half-populated,
        # non-empty directory and mistake it for a valid cached clone.
        if destination.exists():
            shutil.rmtree(destination, ignore_errors=True)
        raise RepoFetchError(
            f"Failed to clone {repo_url!r} at ref {repo_ref!r}: {exc.stderr.strip()}"
        ) from exc

    return destination
