"""Tests for config.py -- required-configuration fail-fast behavior and
CLI > environment variable > .env precedence.

Every test changes into a fresh `tmp_path` before resolving settings, so
`load_dotenv()` never picks up a real `.env` file from the developer's
working directory.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from intellisource_ai.config import build_arg_parser, resolve_settings
from intellisource_ai.exceptions import ConfigurationError


def _parse(args_list: list[str]) -> argparse.Namespace:
    return build_arg_parser().parse_args(args_list)


def test_missing_repo_url_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("REPO_URL", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    with pytest.raises(ConfigurationError, match="No target repository configured"):
        resolve_settings(_parse([]))


def test_missing_api_key_raises_configuration_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="ANTHROPIC_API_KEY"):
        resolve_settings(_parse(["--repo-url", "https://github.com/example/repo"]))


def test_cli_flag_takes_precedence_over_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPO_URL", "https://github.com/from-env/repo")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    settings = resolve_settings(_parse(["--repo-url", "https://github.com/from-cli/repo"]))

    assert settings.repo_url == "https://github.com/from-cli/repo"


def test_env_var_used_when_no_cli_flag(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPO_URL", "https://github.com/from-env/repo")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    settings = resolve_settings(_parse([]))

    assert settings.repo_url == "https://github.com/from-env/repo"


def test_defaults_applied_when_not_overridden(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPO_URL", "https://github.com/example/repo")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("REPO_REF", raising=False)
    monkeypatch.delenv("MODEL", raising=False)
    monkeypatch.delenv("BATCH_SIZE", raising=False)

    settings = resolve_settings(_parse([]))

    assert settings.repo_ref == "main"
    assert settings.model == "claude-haiku-4-5"
    assert settings.batch_size == 6
    assert settings.cache_dir.name == "repo"  # derived from the URL's last path segment


def test_no_html_report_flag_disables_report_generation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("REPO_URL", "https://github.com/example/repo")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

    settings = resolve_settings(_parse(["--no-html-report"]))

    assert settings.generate_html_report is False
