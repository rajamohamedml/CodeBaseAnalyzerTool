"""Tests for dependency_graph.py -- purely offline, over in-memory
ParsedClass records (no parsing, no network)."""

from __future__ import annotations

from intellisource_ai.dependency_graph import build_dependency_graph, depends_on_by_class
from intellisource_ai.schemas import ClassType, ParsedClass


def _cls(class_name: str, imports: list[str]) -> ParsedClass:
    return ParsedClass(
        file_path=f"{class_name}.java",
        package="com.example",
        class_name=class_name,
        class_type=ClassType.OTHER,
        imports=imports,
        start_line=1,
        end_line=1,
    )


def test_builds_edge_for_internal_import() -> None:
    classes = [
        _cls("ActorController", ["com.example.domain.ActorService", "java.util.List"]),
        _cls("ActorService", ["com.example.repository.ActorRepository"]),
        _cls("ActorRepository", []),
    ]

    edges = build_dependency_graph(classes)

    pairs = {(e.from_class, e.to_class) for e in edges}
    assert ("ActorController", "ActorService") in pairs
    assert ("ActorService", "ActorRepository") in pairs
    # java.util.List is external -- never an edge target.
    assert not any(to == "List" for _, to in pairs)


def test_no_self_edge() -> None:
    classes = [_cls("Self", ["com.example.Self"])]

    edges = build_dependency_graph(classes)

    assert edges == []


def test_depends_on_by_class_groups_and_sorts() -> None:
    classes = [
        _cls("A", ["com.example.C", "com.example.B"]),
        _cls("B", []),
        _cls("C", []),
    ]

    edges = build_dependency_graph(classes)
    grouped = depends_on_by_class(edges)

    assert grouped["A"] == ["B", "C"]
