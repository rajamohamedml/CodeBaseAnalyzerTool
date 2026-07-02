"""Deterministic complexity metrics for parsed methods.

Everything here is pure computation over already-parsed source text — no
LLM calls, no network. Kept in its own module so the "free" analysis (this
plus `java_parser.py`) stays clearly separated from the "paid" analysis in
`llm_client.py`.
"""

from __future__ import annotations

import re

from codebase_analyzer.schemas import ComplexityMetrics, ParsedMethod

# 1 (baseline path) + one per branching construct found. This intentionally
# excludes the ternary operator `?:` — a naive `?` count would also match
# Java generic wildcards like `List<?>`, producing more false positives
# than the real ternaries it would catch.
_BRANCH_KEYWORDS = re.compile(r"\bif\b|\bfor\b|\bwhile\b|\bcase\b|\bcatch\b|&&|\|\|")

_DEFAULT_CYCLOMATIC_THRESHOLD = 10
_DEFAULT_LOC_THRESHOLD = 40


def _strip_comments_and_literals(text: str) -> str:
    """Blank out string/char literals and comments so the keyword count
    below doesn't pick up "if"/"for"/etc. that merely appear inside a log
    message or a comment rather than real control flow.

    A small hand-rolled state machine rather than a regex, since correctly
    handling escapes inside strings and nested-looking `/*.../*.../*/`
    sequences is awkward to express as a single regex. Replaces matched
    characters with spaces (preserving newlines) rather than deleting them,
    so line structure — irrelevant here, but useful if this function is
    ever reused for line-aware analysis — stays intact.
    """
    result: list[str] = []
    in_line_comment = False
    in_block_comment = False
    in_string = False
    in_char = False
    i = 0
    while i < len(text):
        two_chars = text[i : i + 2]
        char = text[i]

        if in_line_comment:
            if char == "\n":
                in_line_comment = False
                result.append(char)
            else:
                result.append(" ")
            i += 1
            continue
        if in_block_comment:
            if two_chars == "*/":
                in_block_comment = False
                result.append("  ")
                i += 2
            else:
                result.append(char if char == "\n" else " ")
                i += 1
            continue
        if in_string:
            if char == "\\":
                result.append("  ")
                i += 2
                continue
            if char == '"':
                in_string = False
            result.append(" ")
            i += 1
            continue
        if in_char:
            if char == "\\":
                result.append("  ")
                i += 2
                continue
            if char == "'":
                in_char = False
            result.append(" ")
            i += 1
            continue

        if two_chars == "//":
            in_line_comment = True
            result.append("  ")
            i += 2
            continue
        if two_chars == "/*":
            in_block_comment = True
            result.append("  ")
            i += 2
            continue
        if char == '"':
            in_string = True
            result.append(" ")
            i += 1
            continue
        if char == "'":
            in_char = True
            result.append(" ")
            i += 1
            continue

        result.append(char)
        i += 1

    return "".join(result)


def compute_complexity(
    source_lines: list[str],
    method: ParsedMethod,
    *,
    cyclomatic_threshold: int = _DEFAULT_CYCLOMATIC_THRESHOLD,
    loc_threshold: int = _DEFAULT_LOC_THRESHOLD,
) -> ComplexityMetrics:
    """Compute LOC and an approximate cyclomatic complexity for one method.

    Args:
        source_lines: The full source file, split into lines (0-indexed),
            matching the 1-indexed `method.start_line`/`method.end_line`.
        method: The method whose body should be measured.
        cyclomatic_threshold: Estimate above which `high_complexity` is set.
        loc_threshold: LOC above which `high_complexity` is set regardless
            of the cyclomatic estimate — catches long-but-linear methods
            (e.g. a giant builder chain) that the branch count would miss.

    Returns:
        `ComplexityMetrics` whose `cyclomatic_estimate` is a heuristic, not
        a certified McCabe complexity score — see the field's docstring in
        `schemas.py` and the README's "Assumptions and Limitations".
    """
    body_lines = source_lines[method.start_line - 1 : method.end_line]
    loc = len(body_lines)
    body_text = _strip_comments_and_literals("\n".join(body_lines))
    cyclomatic_estimate = 1 + len(_BRANCH_KEYWORDS.findall(body_text))
    high_complexity = cyclomatic_estimate > cyclomatic_threshold or loc > loc_threshold

    return ComplexityMetrics(
        loc=loc,
        cyclomatic_estimate=cyclomatic_estimate,
        high_complexity=high_complexity,
    )
