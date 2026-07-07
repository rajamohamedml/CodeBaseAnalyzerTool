"""Centralized logging setup.

The rest of the package uses the stdlib `logging` module exclusively —
never `print()` — so log level, format, and destination are controlled in
exactly one place and can be tuned per-run via `--verbose`/`--quiet`.
"""

from __future__ import annotations

import logging

_LOG_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
_DATE_FORMAT = "%H:%M:%S"


def configure_logging(*, verbose: bool = False, quiet: bool = False) -> None:
    """Configure the root logger once, at process startup.

    Args:
        verbose: If True, set level to DEBUG (shows per-file/per-batch detail).
        quiet: If True, set level to WARNING (suppresses routine progress logs).
            Ignored if `verbose` is also True.

    Raises:
        Nothing — this only configures logging handlers.
    """
    if verbose:
        level = logging.DEBUG
    elif quiet:
        level = logging.WARNING
    else:
        level = logging.INFO

    logging.basicConfig(level=level, format=_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Third-party HTTP libraries are chatty at INFO/DEBUG; keep our own
    # package's logs as the signal and quiet the noise unless --verbose.
    if not verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
        logging.getLogger("anthropic").setLevel(logging.WARNING)
