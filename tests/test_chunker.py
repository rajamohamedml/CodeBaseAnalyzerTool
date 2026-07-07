"""Tests for chunker.py -- batch-size and token-ceiling limits, and the
oversized-class-splitting fallback. Uses `fake_anthropic_client` (see
conftest.py) instead of a real Anthropic client, so no network call is made.

Token ceilings in the ceiling-specific tests are derived from the fake
tokenizer's own measurement of the fixtures, rather than hardcoded numbers
-- this keeps the tests correct even if the prompt-rendering format in
`chunker.render_class_for_prompt` changes length later.
"""

from __future__ import annotations

from intellisource_ai.chunker import build_batches, render_class_for_prompt
from intellisource_ai.schemas import ClassType, ParsedClass, ParsedMethod

from .conftest import FakeAnthropicClient

_MODEL = "claude-haiku-4-5"


def _make_class(name: str, method_count: int) -> ParsedClass:
    methods = [
        ParsedMethod(
            name=f"method{i}",
            signature=f"void method{i}()",
            return_type="void",
            parameters=[],
            modifiers=["public"],
            annotations=[],
            javadoc=None,
            start_line=i + 1,
            end_line=i + 2,
        )
        for i in range(method_count)
    ]
    return ParsedClass(
        file_path=f"src/main/java/pkg/{name}.java",
        package="pkg",
        class_name=name,
        class_type=ClassType.SERVICE,
        javadoc=None,
        annotations=[],
        methods=methods,
        rest_endpoints=[],
    )


def _tokens_for(client: FakeAnthropicClient, cls: ParsedClass) -> int:
    return client.messages.count_tokens(
        model=_MODEL, messages=[{"role": "user", "content": render_class_for_prompt(cls, {})}]
    ).input_tokens


def test_batch_size_cap_is_respected(fake_anthropic_client: FakeAnthropicClient) -> None:
    classes = [_make_class(f"Class{i}", method_count=1) for i in range(10)]

    batches = build_batches(
        classes,
        complexity_index={},
        anthropic_client=fake_anthropic_client,
        model=_MODEL,
        batch_size=3,
        token_ceiling=1_000_000,  # effectively unlimited: batch_size alone is the limiting factor
    )

    assert sum(len(b.classes) for b in batches) == 10
    assert all(len(b.classes) <= 3 for b in batches)


def test_token_ceiling_forces_separate_batches(fake_anthropic_client: FakeAnthropicClient) -> None:
    classes = [_make_class(f"Class{i}", method_count=2) for i in range(4)]
    single_class_tokens = _tokens_for(fake_anthropic_client, classes[0])

    # Comfortably fits exactly one class but never two -- forces every
    # class into its own batch without tripping the oversized-single-class
    # split path (each class alone is well under this ceiling).
    token_ceiling = int(single_class_tokens * 1.5)

    batches = build_batches(
        classes,
        complexity_index={},
        anthropic_client=fake_anthropic_client,
        model=_MODEL,
        batch_size=100,
        token_ceiling=token_ceiling,
    )

    assert sum(len(b.classes) for b in batches) == 4
    assert len(batches) == 4
    assert all(len(b.classes) == 1 for b in batches)


def test_oversized_single_class_is_split_not_truncated(fake_anthropic_client: FakeAnthropicClient) -> None:
    huge_class = _make_class("HugeClass", method_count=40)
    small_variant_tokens = _tokens_for(fake_anthropic_client, _make_class("HugeClass", method_count=2))
    huge_tokens = _tokens_for(fake_anthropic_client, huge_class)

    # Comfortably between a small slice of the class and the whole thing --
    # guarantees the whole-class render trips the oversized path.
    token_ceiling = (huge_tokens + small_variant_tokens) // 2

    batches = build_batches(
        [huge_class],
        complexity_index={},
        anthropic_client=fake_anthropic_client,
        model=_MODEL,
        batch_size=100,
        token_ceiling=token_ceiling,
    )

    assert len(batches) > 1
    all_method_names = {
        method.name for batch in batches for cls in batch.classes for method in cls.methods
    }
    assert all_method_names == {f"method{i}" for i in range(40)}
