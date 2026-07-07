"""Custom exception hierarchy for intellisource_ai.

Each failure mode the pipeline can encounter is a distinct, named exception
type rather than a bare `Exception`. This lets callers (and `pipeline.py`'s
error-containment logic) catch precisely the failure they know how to
recover from, instead of swallowing everything with a blanket `except`.
"""

from __future__ import annotations


class IntelliSourceAIError(Exception):
    """Base class for all errors raised by this package."""


class ConfigurationError(IntelliSourceAIError):
    """Raised when required configuration (e.g. repo_url, API key) is missing
    or invalid. Always raised before any network or LLM call is attempted.
    """


class RepoFetchError(IntelliSourceAIError):
    """Raised when cloning or updating the target repository fails."""


class JavaParseError(IntelliSourceAIError):
    """Raised when a single `.java` file cannot be parsed.

    This is deliberately scoped to one file — `pipeline.py` catches this
    per-file and records it in `parse_errors` rather than aborting the run,
    since Java grammar coverage in `javalang` isn't guaranteed for every
    repo the tool might be pointed at.
    """


class LLMExtractionError(IntelliSourceAIError):
    """Raised when an LLM call for a class batch or the project overview
    fails after the SDK's own retries are exhausted. Caught per-batch in
    `pipeline.py` so one failed batch doesn't sink the entire run.
    """
