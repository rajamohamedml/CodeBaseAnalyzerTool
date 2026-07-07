"""Tests for complexity.py -- pure computation, no I/O, no LLM."""

from __future__ import annotations

from intellisource_ai.complexity import compute_complexity
from intellisource_ai.schemas import ParsedMethod


def _method(start_line: int, end_line: int) -> ParsedMethod:
    return ParsedMethod(
        name="example",
        signature="void example()",
        return_type="void",
        parameters=[],
        modifiers=["public"],
        annotations=[],
        javadoc=None,
        start_line=start_line,
        end_line=end_line,
    )


def test_simple_method_has_baseline_complexity_of_one() -> None:
    source_lines = [
        "public void example() {",
        "    doSomething();",
        "}",
    ]
    metrics = compute_complexity(source_lines, _method(1, 3))

    assert metrics.loc == 3
    assert metrics.cyclomatic_estimate == 1
    assert metrics.high_complexity is False


def test_branches_increase_the_estimate() -> None:
    source_lines = [
        "public void example() {",  # line 1
        "    if (a) {",  # line 2 -- if #1
        "        doA();",  # line 3
        "    } else if (b) {",  # line 4 -- if #2
        "        doB();",  # line 5
        "    }",  # line 6
        "    for (int i = 0; i < 10; i++) {",  # line 7 -- for #1
        "        if (a && b) {",  # line 8 -- if #3, && #1
        "            doC();",  # line 9
        "        }",  # line 10
        "    }",  # line 11
        "}",  # line 12
    ]
    metrics = compute_complexity(source_lines, _method(1, 12))

    # 1 baseline + 3*'if' + 1*'for' + 1*'&&' = 6
    assert metrics.cyclomatic_estimate == 6
    assert metrics.high_complexity is False


def test_high_complexity_flag_set_above_cyclomatic_threshold() -> None:
    branchy_lines = ["public void example() {"]
    branchy_lines += [f"    if (x == {i}) {{ doWork({i}); }}" for i in range(15)]
    branchy_lines.append("}")

    metrics = compute_complexity(branchy_lines, _method(1, len(branchy_lines)))

    assert metrics.cyclomatic_estimate > 10
    assert metrics.high_complexity is True


def test_high_complexity_flag_set_above_loc_threshold_even_if_linear() -> None:
    long_linear_lines = ["public void example() {"]
    long_linear_lines += [f"    doStep{i}();" for i in range(60)]
    long_linear_lines.append("}")

    metrics = compute_complexity(long_linear_lines, _method(1, len(long_linear_lines)))

    assert metrics.cyclomatic_estimate == 1
    assert metrics.high_complexity is True


def test_keywords_inside_strings_and_comments_are_not_counted() -> None:
    source_lines = [
        "public void example() {",
        '    log.info("if this looks like a branch, it is not: for/while/case");',
        "    // if this is a comment mentioning for and while, ignore it",
        "    doWork();",
        "}",
    ]
    metrics = compute_complexity(source_lines, _method(1, 5))

    assert metrics.cyclomatic_estimate == 1
