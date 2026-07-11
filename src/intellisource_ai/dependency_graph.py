"""Internal class-to-class dependency graph, derived from import statements.

Purely deterministic — no LLM involvement. An edge `A -> B` means A's file
imports B, and B is one of the classes this run actually parsed; imports of
the JDK, third-party libraries, or Spring itself are not internal classes
and never appear as an edge endpoint.
"""

from __future__ import annotations

from collections import defaultdict

from intellisource_ai.schemas import DependencyEdge, ParsedClass


def build_dependency_graph(classes: list[ParsedClass]) -> list[DependencyEdge]:
    """Build the directed "depends on" edge list for `classes`.

    Args:
        classes: Every class parsed this run, used both as the edge
            sources and as the universe of valid edge targets.
    """
    internal_names = {cls.class_name for cls in classes}
    seen: set[tuple[str, str]] = set()
    edges: list[DependencyEdge] = []

    for cls in classes:
        imported_simple_names = {path.rsplit(".", 1)[-1] for path in cls.imports}
        for target in sorted(imported_simple_names & internal_names):
            if target == cls.class_name:
                continue
            pair = (cls.class_name, target)
            if pair in seen:
                continue
            seen.add(pair)
            edges.append(DependencyEdge(from_class=cls.class_name, to_class=target))

    return edges


def depends_on_by_class(edges: list[DependencyEdge]) -> dict[str, list[str]]:
    """Group `edges` into `{class_name: [classes it depends on]}`, sorted
    for stable output. Used by `pipeline.py` to attach per-class
    `depends_on` lists onto each `ClassAnalysis`.
    """
    grouped: dict[str, list[str]] = defaultdict(list)
    for edge in edges:
        grouped[edge.from_class].append(edge.to_class)
    return {from_class: sorted(targets) for from_class, targets in grouped.items()}
