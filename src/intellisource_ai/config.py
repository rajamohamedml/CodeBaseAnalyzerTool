"""Application configuration.

Settings are resolved with a strict precedence: CLI flag > environment
variable > `.env` file entry. There is deliberately no in-code default for
`repo_url` or the API key beyond the git convention of "main" for the ref
default — the target repository is always a decision the caller makes,
never one baked into this tool. See `resolve_settings` for the fail-fast
behavior when a required value is missing.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from intellisource_ai.exceptions import ConfigurationError

# These are the only "defaults" in this module. Note that none of them name
# a specific target repository — REPO is always supplied by the caller.
DEFAULT_MODEL = "claude-haiku-4-5"
DEFAULT_REPO_REF = "main"  # a git convention default, not repo-specific
DEFAULT_BATCH_SIZE = 6
DEFAULT_OUTPUT_PATH = Path("output/analysis.json")
DEFAULT_TOKEN_CEILING_PER_BATCH = 4000


@dataclass(frozen=True)
class Settings:
    """Fully-resolved, immutable configuration for one pipeline run."""

    repo_url: str
    repo_ref: str
    anthropic_api_key: str
    model: str
    batch_size: int
    token_ceiling_per_batch: int
    output_path: Path
    include_tests: bool
    max_files: int | None
    refresh_cache: bool
    refresh_repo: bool
    generate_html_report: bool
    cache_dir: Path

    @property
    def llm_cache_path(self) -> Path:
        """Where per-file LLM results are cached across runs."""
        return self.cache_dir / "llm_cache.json"

    @property
    def repo_clone_path(self) -> Path:
        """Where the target repository is (or will be) shallow-cloned."""
        return self.cache_dir / "repo"

    @property
    def schema_output_path(self) -> Path:
        """Sibling JSON Schema file, e.g. output/analysis.schema.json."""
        return self.output_path.with_suffix(".schema.json")

    @property
    def report_output_path(self) -> Path:
        """Sibling HTML report, e.g. output/report.html."""
        return self.output_path.with_name("report.html")


def _first_non_empty(*values: str | None) -> str | None:
    """Return the first value that is neither None nor blank/whitespace-only."""
    for value in values:
        if value is not None and value.strip():
            return value.strip()
    return None


def _derive_repo_name(repo_url: str) -> str:
    """Derive a filesystem-safe cache key from a repo URL, e.g.
    'https://github.com/codejsha/spring-rest-sakila' -> 'spring-rest-sakila'.
    This lets multiple target repos be cached side by side without collisions.
    """
    return repo_url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".git") or "repo"


def build_arg_parser() -> argparse.ArgumentParser:
    """Define the CLI surface. Kept separate from `resolve_settings` so
    `main.py` can call `--help` cheaply without needing the environment
    fully configured.
    """
    parser = argparse.ArgumentParser(
        prog="intellisource-ai",
        description=(
            "Analyze a Java/Spring GitHub repository and extract structured "
            "knowledge (project overview, method signatures, complexity) "
            "using an LLM, via LangChain."
        ),
    )
    parser.add_argument(
        "--repo-url",
        default=None,
        help="Target GitHub repository URL. Required unless REPO_URL is set "
        "via environment variable or .env. No default is built into this tool.",
    )
    parser.add_argument(
        "--ref",
        dest="ref",
        default=None,
        help=f"Git branch/tag/commit to analyze (default: {DEFAULT_REPO_REF!r}).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help=f"Path for the JSON deliverable (default: {DEFAULT_OUTPUT_PATH}). "
        "The JSON Schema and HTML report are written alongside it.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help=f"Anthropic model ID for description extraction (default: {DEFAULT_MODEL!r}).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=None,
        help=f"Max classes per LLM batch call (default: {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--include-tests",
        action="store_true",
        help="Also analyze src/test/java sources (excluded by default to save cost).",
    )
    parser.add_argument(
        "--max-files",
        type=int,
        default=None,
        help="Cap the number of Java files analyzed, for cheap smoke-testing.",
    )
    parser.add_argument(
        "--refresh-cache",
        action="store_true",
        help="Ignore the on-disk LLM response cache and re-call the LLM for every file.",
    )
    parser.add_argument(
        "--refresh-repo",
        action="store_true",
        help="Re-clone the target repository even if it is already cached locally.",
    )
    parser.add_argument(
        "--no-html-report",
        action="store_true",
        help="Skip generating output/report.html; only write the JSON deliverable.",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument("--verbose", action="store_true", help="Enable DEBUG-level logging.")
    verbosity.add_argument("--quiet", action="store_true", help="Only log warnings and errors.")
    return parser


def resolve_settings(args: argparse.Namespace) -> Settings:
    """Resolve final `Settings` from CLI args, environment variables, and `.env`.

    Precedence per field is CLI flag > environment variable (including
    values loaded from `.env` by `load_dotenv()`, called once here) > the
    small set of non-repo-specific defaults declared at module level.

    Raises:
        ConfigurationError: if `repo_url` or `ANTHROPIC_API_KEY` cannot be
            resolved from any source. Both checks happen here, before the
            caller has cloned a repo or opened any network connection.
    """
    # `load_dotenv()` with no path defaults to *upward-searching parent
    # directories* from the caller's location, not just the current
    # working directory -- on a machine with an unrelated .env sitting in
    # an ancestor folder, that silently loads a stranger's secret into
    # this process. Scope loading strictly to a .env in the current
    # working directory instead; a missing file here is a silent no-op.
    load_dotenv(dotenv_path=Path.cwd() / ".env")

    repo_url = _first_non_empty(args.repo_url, os.environ.get("REPO_URL"))
    if repo_url is None:
        raise ConfigurationError(
            "No target repository configured. Pass --repo-url or set REPO_URL "
            "(environment variable or .env). This tool never assumes a default "
            "repository -- see .env.example for the expected format."
        )

    api_key = _first_non_empty(os.environ.get("ANTHROPIC_API_KEY"))
    if api_key is None:
        raise ConfigurationError(
            "ANTHROPIC_API_KEY is not set. Copy .env.example to .env and fill "
            "it in, or export it directly in your shell."
        )

    repo_ref = _first_non_empty(args.ref, os.environ.get("REPO_REF")) or DEFAULT_REPO_REF
    model = _first_non_empty(args.model, os.environ.get("MODEL")) or DEFAULT_MODEL
    batch_size = args.batch_size or int(os.environ.get("BATCH_SIZE", DEFAULT_BATCH_SIZE))
    output_path = Path(args.output) if args.output else DEFAULT_OUTPUT_PATH

    return Settings(
        repo_url=repo_url,
        repo_ref=repo_ref,
        anthropic_api_key=api_key,
        model=model,
        batch_size=batch_size,
        token_ceiling_per_batch=DEFAULT_TOKEN_CEILING_PER_BATCH,
        output_path=output_path,
        include_tests=args.include_tests,
        max_files=args.max_files,
        refresh_cache=args.refresh_cache,
        refresh_repo=args.refresh_repo,
        generate_html_report=not args.no_html_report,
        cache_dir=Path(".cache") / _derive_repo_name(repo_url),
    )
