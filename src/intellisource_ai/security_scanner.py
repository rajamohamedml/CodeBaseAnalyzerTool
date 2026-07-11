"""Deterministic security/quality signals, computed the same way as
`complexity.py` — regex-based pattern matching over already-parsed source
text, zero LLM cost, and explicitly documented as a heuristic rather than a
certified static-analysis result.

Three checks, each chosen because it's reliably detectable from source text
alone, without needing a full type-resolved AST:

  - Hardcoded credential-like field values (password/secret/token/apikey).
  - SQL built via string concatenation with a SQL keyword literal.
  - An empty (or comment-only) `catch` block silently swallowing exceptions.

Each class's *whole* body (fields and methods, via `ParsedClass.start_line`/
`end_line`) is scanned, not just method bodies one at a time, since a
hardcoded secret is typically a field declaration rather than something
inside a method.
"""

from __future__ import annotations

import re

from intellisource_ai.schemas import ParsedClass, SecurityFinding, SecuritySeverity

_SECRET_FIELD = re.compile(
    r"\bString\s+(\w*(?:password|secret|apikey|api_key|token|credential)\w*)\s*=\s*\"([^\"]*)\"",
    re.IGNORECASE,
)
_SECRET_PLACEHOLDER = re.compile(r"^\s*(|changeme|xxx+|todo|placeholder|\$\{.*\})\s*$", re.IGNORECASE)

_SQL_KEYWORD_LITERAL = re.compile(
    r"\"(?:[^\"\\]|\\.)*\b(?:SELECT|INSERT\s+INTO|UPDATE|DELETE\s+FROM)\b(?:[^\"\\]|\\.)*\"",
    re.IGNORECASE,
)

_CATCH_BLOCK = re.compile(r"catch\s*\([^)]*\)\s*\{([^{}]*)\}", re.DOTALL)
_LINE_COMMENT = re.compile(r"//.*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


def _line_number(class_text: str, offset: int, class_start_line: int) -> int:
    """Map a character offset within `class_text` back to an absolute
    1-indexed line number in the original file.
    """
    return class_start_line + class_text.count("\n", 0, offset)


def _is_effectively_empty(catch_body: str) -> bool:
    """True if a catch block's body is empty once comments are stripped --
    i.e. the exception is silently swallowed. Does not attempt to handle
    comment-like text inside string literals; catch bodies rarely contain
    any, and this is a heuristic, not a lexer.
    """
    stripped = _BLOCK_COMMENT.sub("", catch_body)
    stripped = _LINE_COMMENT.sub("", stripped)
    return stripped.strip() == ""


def scan_class(source_lines: list[str], cls: ParsedClass) -> list[SecurityFinding]:
    """Run all three checks against one class's full source text.

    Args:
        source_lines: The full source file, split into lines (0-indexed),
            matching the 1-indexed `cls.start_line`/`cls.end_line`.
        cls: The class to scan.
    """
    class_text = "\n".join(source_lines[cls.start_line - 1 : cls.end_line])
    findings: list[SecurityFinding] = []

    for match in _SECRET_FIELD.finditer(class_text):
        field_name, literal = match.group(1), match.group(2)
        if _SECRET_PLACEHOLDER.match(literal):
            continue
        findings.append(
            SecurityFinding(
                category="hardcoded_secret",
                severity=SecuritySeverity.HIGH,
                message=f"Hardcoded credential-like value in field '{field_name}'.",
                line=_line_number(class_text, match.start(), cls.start_line),
            )
        )

    for line_offset, line in enumerate(class_text.split("\n")):
        if _SQL_KEYWORD_LITERAL.search(line) and "+" in line:
            findings.append(
                SecurityFinding(
                    category="sql_injection_risk",
                    severity=SecuritySeverity.MEDIUM,
                    message="SQL string appears to be built via concatenation rather than "
                    "a parameterized query.",
                    line=cls.start_line + line_offset,
                )
            )

    for match in _CATCH_BLOCK.finditer(class_text):
        if _is_effectively_empty(match.group(1)):
            findings.append(
                SecurityFinding(
                    category="empty_catch_block",
                    severity=SecuritySeverity.LOW,
                    message="Empty catch block silently swallows the exception.",
                    line=_line_number(class_text, match.start(), cls.start_line),
                )
            )

    return findings
