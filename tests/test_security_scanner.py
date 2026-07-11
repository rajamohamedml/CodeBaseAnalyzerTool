"""Tests for security_scanner.py -- purely offline, regex-based checks
over an in-memory source snippet (no parsing, no network)."""

from __future__ import annotations

from intellisource_ai.schemas import ClassType, ParsedClass, SecuritySeverity
from intellisource_ai.security_scanner import scan_class


def _class_with_body(body: str) -> tuple[list[str], ParsedClass]:
    source_lines = body.splitlines()
    cls = ParsedClass(
        file_path="Bad.java",
        package="com.example",
        class_name="Bad",
        class_type=ClassType.OTHER,
        start_line=1,
        end_line=len(source_lines),
    )
    return source_lines, cls


def test_detects_hardcoded_secret() -> None:
    source_lines, cls = _class_with_body(
        'public class Bad {\n    private String apiKey = "sk-12345abcdef";\n}\n'
    )

    findings = scan_class(source_lines, cls)

    assert any(f.category == "hardcoded_secret" for f in findings)
    hit = next(f for f in findings if f.category == "hardcoded_secret")
    assert hit.severity == SecuritySeverity.HIGH
    assert hit.line == 2


def test_ignores_placeholder_secret_value() -> None:
    source_lines, cls = _class_with_body(
        'public class Bad {\n    private String apiToken = "${API_TOKEN}";\n}\n'
    )

    findings = scan_class(source_lines, cls)

    assert not any(f.category == "hardcoded_secret" for f in findings)


def test_detects_sql_string_concatenation() -> None:
    source_lines, cls = _class_with_body(
        "public class Bad {\n"
        '    void run(String id) { String sql = "SELECT * FROM users WHERE id = " + id; }\n'
        "}\n"
    )

    findings = scan_class(source_lines, cls)

    assert any(f.category == "sql_injection_risk" for f in findings)


def test_detects_empty_catch_block() -> None:
    source_lines, cls = _class_with_body(
        "public class Bad {\n"
        "    void run() {\n"
        "        try {\n"
        "            doSomething();\n"
        "        } catch (Exception e) {\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    findings = scan_class(source_lines, cls)

    assert any(f.category == "empty_catch_block" for f in findings)


def test_clean_class_has_no_findings() -> None:
    source_lines, cls = _class_with_body(
        "public class Bad {\n"
        "    void run() {\n"
        "        try {\n"
        "            doSomething();\n"
        "        } catch (Exception e) {\n"
        "            log.warn(\"failed\", e);\n"
        "        }\n"
        "    }\n"
        "}\n"
    )

    assert scan_class(source_lines, cls) == []
