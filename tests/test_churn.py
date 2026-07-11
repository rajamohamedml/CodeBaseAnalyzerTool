"""Tests for churn.py -- exercises real `git log` against a throwaway repo
created in tmp_path (local-only git operations, no network, no fixtures
shared with the rest of the suite)."""

from __future__ import annotations

import subprocess
from pathlib import Path

from intellisource_ai.churn import compute_churn

_GIT_ENV_ARGS = [
    "-c",
    "user.name=Test",
    "-c",
    "user.email=test@example.com",
    "-c",
    "commit.gpgsign=false",
]


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *_GIT_ENV_ARGS, *args], check=True, capture_output=True)


def _init_repo_with_history(repo: Path) -> None:
    repo.mkdir()
    _git(repo, "init")
    (repo / "A.java").write_text("class A {}", encoding="utf-8")
    _git(repo, "add", "A.java")
    _git(repo, "commit", "-m", "add A")

    (repo / "B.java").write_text("class B {}", encoding="utf-8")
    _git(repo, "add", "B.java")
    _git(repo, "commit", "-m", "add B")

    (repo / "A.java").write_text("class A { void x() {} }", encoding="utf-8")
    _git(repo, "add", "A.java")
    _git(repo, "commit", "-m", "touch A again")


def test_computes_commit_counts_per_file(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    _init_repo_with_history(repo)

    churn = compute_churn(repo)

    assert churn["A.java"].commit_count == 2
    assert churn["B.java"].commit_count == 1
    assert churn["A.java"].last_modified is not None


def test_non_git_directory_returns_empty(tmp_path: Path) -> None:
    plain_dir = tmp_path / "not-a-repo"
    plain_dir.mkdir()

    assert compute_churn(plain_dir) == {}
