"""Renders a `ProjectAnalysis` into a single, self-contained HTML report.

Renders the same model that is serialized to `analysis.json` -- there is no
second, hand-maintained data shape for "the pretty version" -- so the JSON
deliverable and the visual report can never disagree with each other.

Uses Jinja2 with autoescaping enabled. This is mandatory, not optional:
card content includes LLM-generated text, and autoescaping is what
guarantees that text can never be interpreted as HTML/JS if this report is
ever hosted rather than opened locally as a file.
"""

from __future__ import annotations

from pathlib import Path
from typing import TypedDict

from jinja2 import Environment, FileSystemLoader, select_autoescape

from codebase_analyzer.schemas import ClassAnalysis, ProjectAnalysis


class _Finding(TypedDict):
    class_name: str
    file_path: str
    text: str


class _FindingCategory(TypedDict):
    label: str
    icon: str
    # Named `findings`, not `items` -- Jinja's dot-attribute access on a
    # dict tries `getattr` first, so a key literally named "items" would
    # be shadowed by `dict.items` (the bound method) inside the template.
    findings: list[_Finding]

# templates/ lives at the project root, one level above the installed
# package (src/codebase_analyzer/). This resolves correctly for an
# editable install (`pip install -e .`), which is how this tool is
# intended to be run; a packaged wheel distribution would need the
# template shipped as package data instead.
_TEMPLATE_DIR = Path(__file__).resolve().parent.parent.parent / "templates"
_TEMPLATE_NAME = "report.html.jinja2"


def _group_by_module(classes: list[ClassAnalysis]) -> dict[str, list[ClassAnalysis]]:
    """Group classes by feature module for the report's navigation.

    Uses the path segment right after `services/` when present (this
    codebase's convention, and a common one for package-by-feature Spring
    projects); falls back to the file's immediate parent directory name
    for other project layouts.
    """
    modules: dict[str, list[ClassAnalysis]] = {}
    for cls in classes:
        parts = cls.file_path.split("/")
        if "services" in parts:
            idx = parts.index("services")
            module_name = parts[idx + 1] if idx + 1 < len(parts) else "root"
        else:
            module_name = parts[-2] if len(parts) > 1 else "root"
        modules.setdefault(module_name, []).append(cls)
    return dict(sorted(modules.items()))


def _collect_notable_findings(classes: list[ClassAnalysis]) -> list[_FindingCategory]:
    """Roll up every LLM-flagged notable aspect and every statically-flagged
    high-complexity method into categorized, collapsible groups, so a
    reviewer isn't stuck scrolling one flat list of hundreds of items to
    find what's worth a closer look.
    """
    high_complexity: list[_Finding] = []
    notable_aspects: list[_Finding] = []
    for cls in classes:
        for aspect in cls.notable_aspects:
            notable_aspects.append({"class_name": cls.class_name, "file_path": cls.file_path, "text": aspect})
        for method in cls.methods:
            if method.high_complexity:
                high_complexity.append(
                    {
                        "class_name": cls.class_name,
                        "file_path": cls.file_path,
                        "text": (
                            f"High-complexity method {method.signature} "
                            f"(cyclomatic~={method.cyclomatic_estimate}, loc={method.loc})"
                        ),
                    }
                )

    categories: list[_FindingCategory] = [
        {"label": "High-Complexity Methods", "icon": "⚠️", "findings": high_complexity},
        {"label": "Notable Aspects", "icon": "\U0001f4a1", "findings": notable_aspects},
    ]
    return [category for category in categories if category["findings"]]


def render_report(analysis: ProjectAnalysis) -> str:
    """Render `analysis` into a complete, standalone HTML document string."""
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=select_autoescape(["html", "jinja2"]),
    )
    template = env.get_template(_TEMPLATE_NAME)

    total_llm_calls = analysis.metadata.llm_calls_made + analysis.metadata.llm_calls_cached
    cache_hit_rate_pct = (
        round(100 * analysis.metadata.llm_calls_cached / total_llm_calls, 1) if total_llm_calls else 0.0
    )

    return template.render(
        project=analysis.project,
        metadata=analysis.metadata,
        modules=_group_by_module(analysis.classes),
        notable_findings=_collect_notable_findings(analysis.classes),
        total_classes=len(analysis.classes),
        total_methods=sum(len(c.methods) for c in analysis.classes),
        total_endpoints=sum(len(c.rest_endpoints) for c in analysis.classes),
        high_complexity_count=sum(1 for c in analysis.classes for m in c.methods if m.high_complexity),
        cache_hit_rate_pct=cache_hit_rate_pct,
    )


def write_report(analysis: ProjectAnalysis, output_path: Path) -> None:
    """Render `analysis` and write it to `output_path`."""
    html = render_report(analysis)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
