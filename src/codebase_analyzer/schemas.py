"""Pydantic data contracts used across every pipeline stage.

Every shape that crosses a module boundary is a Pydantic model, never a
raw dict — this gives us validation for free and makes the final JSON
deliverable's structure explicit and versioned (`SCHEMA_VERSION`).

The stages, in order, are:
    1. java_parser.py   -> ParseResult (ParsedClass / ParsedMethod)
    2. complexity.py    -> ComplexityMetrics (merged onto each ParsedMethod)
    3. llm_client.py    -> ClassBatchAnalysis / ProjectOverview (LLM structured output)
    4. pipeline.py       -> ProjectAnalysis (the final, assembled deliverable)
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


class ClassType(StrEnum):
    """Convention-based classification of a class's architectural role,
    inferred from its package path and Spring annotations in java_parser.py.
    This is a heuristic, not an authoritative language-level concept — an
    unconventionally-organized codebase may be misclassified as OTHER.
    """

    CONTROLLER = "controller"
    SERVICE = "service"
    REPOSITORY = "repository"
    ENTITY = "entity"
    DTO = "dto"
    MAPPER = "mapper"
    ASSEMBLER = "assembler"
    CONFIG = "config"
    EXCEPTION = "exception"
    OTHER = "other"


# ---------------------------------------------------------------------------
# Stage 1 — structural data extracted by java_parser.py (zero LLM cost)
# ---------------------------------------------------------------------------


class AnnotationInfo(BaseModel):
    """A single Java annotation as it appeared on a class or method, e.g.
    `@GetMapping("/actors/{id}")` -> name="GetMapping", arguments=["/actors/{id}"].
    """

    name: str
    arguments: list[str] = Field(default_factory=list)


class RestEndpoint(BaseModel):
    """An HTTP route derived from a Spring mapping annotation. Only
    populated for controller methods — extracted from annotations directly,
    without any LLM involvement.
    """

    http_method: str
    path: str


class ParsedMethod(BaseModel):
    """Structural facts about one method/constructor, extracted purely by
    parsing the AST. `start_line`/`end_line` are 1-indexed and are what
    complexity.py uses to slice the method body out of the source file.
    """

    name: str
    signature: str
    return_type: str
    parameters: list[str] = Field(default_factory=list)
    modifiers: list[str] = Field(default_factory=list)
    annotations: list[AnnotationInfo] = Field(default_factory=list)
    javadoc: str | None = None
    start_line: int
    end_line: int


class ParsedClass(BaseModel):
    """Structural facts about one class/interface/enum. One `.java` file can
    yield multiple `ParsedClass` entries — this codebase's DTOs nest several
    static classes inside a single outer file.

    `rest_endpoints` is populated purely from Spring mapping annotations
    (class-level `@RequestMapping` base path combined with method-level
    `@GetMapping`/etc.) — no LLM involvement, since this is derivable
    deterministically from the AST.
    """

    file_path: str
    package: str
    class_name: str
    class_type: ClassType
    javadoc: str | None = None
    annotations: list[AnnotationInfo] = Field(default_factory=list)
    methods: list[ParsedMethod] = Field(default_factory=list)
    rest_endpoints: list[RestEndpoint] = Field(default_factory=list)


class ParseResult(BaseModel):
    """Everything `java_parser.py` extracted from one source tree, plus a
    record of any files it could not parse (never silently dropped).

    `files_discovered` is tracked separately from `len(classes)` because a
    file that parses successfully but declares zero types (e.g. package-info
    files) would otherwise be invisible in file-count reporting.
    """

    classes: list[ParsedClass] = Field(default_factory=list)
    parse_errors: list[str] = Field(default_factory=list)
    files_discovered: int = 0


# ---------------------------------------------------------------------------
# Stage 2 — complexity.py output (also zero LLM cost)
# ---------------------------------------------------------------------------


class ComplexityMetrics(BaseModel):
    """Deterministic complexity signal for one method.

    `cyclomatic_estimate` is a regex-based heuristic (1 + count of
    branching keywords/operators in the method body) — an approximation
    useful for flagging outliers, not a certified McCabe complexity score.
    See README "Assumptions and Limitations".
    """

    loc: int
    cyclomatic_estimate: int
    high_complexity: bool


# ---------------------------------------------------------------------------
# Stage 3 — LLM structured-output contracts (llm_client.py)
# ---------------------------------------------------------------------------
# Field `description=` text below is sent to the model as part of the tool
# schema via LangChain's `with_structured_output`, so it doubles as prompt
# guidance, not just documentation for humans reading this file.


class MethodDescription(BaseModel):
    """One method's LLM-written description, matched back to its signature."""

    signature: str = Field(description="Must exactly match one of the provided method signatures.")
    description: str = Field(description="One sentence explaining what the method does and why.")


class ClassDescription(BaseModel):
    """The LLM's semantic analysis of one class, matched back by class_name."""

    class_name: str = Field(description="Must exactly match one of the provided class names.")
    description: str = Field(description="A one-to-two sentence summary of the class's purpose.")
    methods: list[MethodDescription] = Field(default_factory=list)
    notable_aspects: list[str] = Field(
        default_factory=list,
        description="Design patterns, security-relevant logic, or other noteworthy "
        "characteristics of this class. Return an empty list if nothing stands out — "
        "do not invent findings.",
    )


class ClassBatchAnalysis(BaseModel):
    """Structured-output contract for one batched LLM call covering several classes."""

    classes: list[ClassDescription]


class ProjectOverview(BaseModel):
    """Structured-output contract for the single, project-wide overview LLM call."""

    name: str
    description: str = Field(
        description="1-2 paragraph summary of the project's purpose and functionality."
    )
    tech_stack: list[str] = Field(
        default_factory=list, description="Frameworks/libraries the project depends on."
    )
    architecture_summary: str = Field(
        description="How the codebase is organized (layers, modules, patterns)."
    )
    main_modules: list[str] = Field(
        default_factory=list, description="The project's main feature areas/modules."
    )


# ---------------------------------------------------------------------------
# Stage 4 — final assembled deliverable (pipeline.py)
# ---------------------------------------------------------------------------


class MethodAnalysis(BaseModel):
    """One method in the final report: structure + complexity + LLM description."""

    signature: str
    description: str
    loc: int
    cyclomatic_estimate: int
    high_complexity: bool


class ClassAnalysis(BaseModel):
    """One class in the final report."""

    file_path: str
    package: str
    class_name: str
    class_type: ClassType
    description: str
    rest_endpoints: list[RestEndpoint] = Field(default_factory=list)
    methods: list[MethodAnalysis] = Field(default_factory=list)
    notable_aspects: list[str] = Field(default_factory=list)


class RunMetadata(BaseModel):
    """Observability data about the run itself — cost, cache effectiveness,
    and any files that could not be parsed. Treating cost and correctness
    as first-class, inspectable outputs rather than hidden side effects.
    """

    generated_at: str
    model_used: str
    total_files_parsed: int
    parse_errors: list[str] = Field(default_factory=list)
    llm_calls_made: int
    llm_calls_cached: int
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float


class ProjectAnalysis(BaseModel):
    """The complete, schema-versioned deliverable written to `analysis.json`
    and rendered into `report.html` by `report_generator.py`. Both files are
    derived from one instance of this model, so they can never disagree.
    """

    schema_version: str = SCHEMA_VERSION
    project: ProjectOverview
    classes: list[ClassAnalysis] = Field(default_factory=list)
    metadata: RunMetadata

    @staticmethod
    def now_iso() -> str:
        """UTC timestamp helper used when constructing `RunMetadata.generated_at`."""
        return datetime.now(UTC).isoformat()
