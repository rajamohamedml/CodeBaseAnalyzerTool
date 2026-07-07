# IntelliSource AI

A production grade Python project that analyzes a Java/Spring GitHub repository and extracts
structured knowledge — a project overview, method-level signatures and
descriptions, REST endpoints, and complexity signals — using an LLM
(Claude Haiku 4.5, via LangChain). It is **repo-agnostic**: the target
repository is always supplied by the caller, never hardcoded.

This project can run against any given github repository configured

## About

IntelliSource AI turns an unfamiliar Java/Spring repository into a
navigable, structured summary without requiring the user to read every
file by hand. Point it at any public (or accessible) Git repository URL
and it clones the code, parses every `.java` file into an AST, computes
complexity signals, and asks an LLM to explain — in plain language — what
each class and method is for. The result is a single, versioned
data model (`ProjectAnalysis`) that is rendered both as machine-readable
JSON and as a human-readable HTML report, so a new contributor, a
reviewer, or a technical lead can get oriented in a large codebase in
minutes rather than hours.

It is deliberately **not** a linter, a test generator, or a security
scanner — it answers one question well: *"What does this codebase
contain, and what does each part of it do?"* Everything downstream (the
project overview, the per-class descriptions, the REST API surface, the
complexity hotspots) is derived from that single question.

Two design choices shape everything else in the tool:

- **Static analysis first, LLM second.** Anything derivable
  deterministically from source (class names, method signatures,
  annotations, REST routes, LOC, cyclomatic complexity) is extracted by a
  real Java parser (`javalang`) and a regex-based complexity heuristic —
  for free, with no LLM call. The LLM is reserved for the one thing static
  analysis cannot do: judging what a class or method *means*. This keeps
  runs cheap and repeatable, and means the tool can process large
  repositories without a proportionally large API bill.
- **One model, two outputs.** Every run assembles a single Pydantic model
  (`schemas.ProjectAnalysis`) and renders it into both `analysis.json` and
  `report.html`. Because both come from the same in-memory object, the
  JSON deliverable and the HTML report can never contradict each other.

## What Output You Get

Every run writes three files to `output/`:

### `output/report.html` — human-readable dashboard
A single, self-contained, styled HTML file (no external assets needed) —
the recommended way to review results in a browser. It includes:

- **Project overview** — a generated name, a 1–2 paragraph description of
  the project's purpose, the inferred technology stack, an
  architecture summary (how the codebase is layered/organized), and a
  list of the main domain (business/feature) modules.
- **Stats dashboard** — total files parsed, classes analyzed, methods
  analyzed, REST endpoints discovered, and complexity outliers, at a
  glance.
- **Module-grouped class cards** — every analyzed class, grouped by its
  source directory, showing:
  - its architectural role (`controller` / `service` / `repository` /
    `entity` / `dto` / `mapper` / `assembler` / `config` / `exception` /
    `other`)
  - an LLM-written summary of what the class does
  - every method's signature, a one-sentence description of what it does
    and why, its line count, and its cyclomatic-complexity estimate
    (flagged when it's a high-complexity outlier)
  - any REST endpoints the class exposes (HTTP verb + path), derived
    directly from Spring mapping annotations
- **Notable Findings rollup** — a consolidated list of noteworthy
  design patterns, security-relevant logic, or other characteristics the
  LLM flagged across all classes, surfaced in one place instead of buried
  inside individual class cards.

Pass `--no-html-report` to skip generating this file if only the JSON is
needed.

### `output/analysis.json` — machine-readable deliverable
The same data as the HTML report, in structured JSON, keyed by the
`ProjectAnalysis` schema: `schema_version`, `project` (the overview),
`classes` (the full list of per-class analyses), and `metadata` (see
below). This is the artifact meant for scripts, other tools, or further
automated processing.

### `output/analysis.schema.json` — the formal JSON Schema
Generated straight from the `ProjectAnalysis` Pydantic model, so the JSON
deliverable is machine-*validatable*, not just consistent by convention.

### Run metadata (embedded in `analysis.json`, also printed to console)
Every run reports on itself as a first-class output rather than a hidden
side effect: files parsed, any files that failed to parse (and why),
number of LLM calls made vs. served from cache, total input/output
tokens, and an estimated USD cost. Re-running the same command against an
unchanged repository should serve most or all classes from cache, at
zero additional token cost.

## Approach

The core design decision is to split the work into two stages with very
different cost profiles, and to only pay LLM-token cost for the stage that
genuinely needs it:

1. **Free, deterministic static analysis** (`java_parser.py`,
   `complexity.py`) — a Java grammar parser (`javalang`) extracts every
   class's structure: package, class type, method signatures, parameters,
   annotations, Javadoc, and REST routes (from Spring mapping annotations).
   A regex-based heuristic computes an approximate cyclomatic complexity
   and line count per method. None of this costs a single LLM token.

2. **Targeted, cached LLM calls** (`llm_client.py`, `chunker.py`,
   `cache.py`) — only the *semantic* part (what does this class/method do,
   is anything about it noteworthy) is deferred to Claude LLM. Classes are
   batched together (grouped by directory, capped by both a class count and
   a real token count) so one call covers several small classes at once,
   and every result is cached by content hash so re-running the tool costs
   nothing extra for unchanged files.

The naive alternative — dumping raw source of every file into an LLM and
asking it to describe everything — spends tokens re-deriving syntax a
parser already gives for free. This design spends tokens only on the part
a parser cannot do: judgment about what a class *means*.

Every run produces **two complementary deliverables** from the same
in-memory result, so they can never disagree with each other:

- `output/analysis.json` (+ `output/analysis.schema.json`) — the
  structured JSON deliverable required by the assignment, and its formal
  JSON Schema so it's machine-validatable, not just "consistent by
  convention."
- `output/report.html` — a single, self-contained, styled HTML report for
  human review (module-grouped class cards, a stats dashboard, and a
  "Notable Findings" rollup). Skippable via `--no-html-report` if only the
  JSON is wanted.

### Where the LLM pipeline lives, and how to inspect it

The LLM integration is split across two files with a clear boundary:

- **`llm_client.py`** — the actual model calls. `LLMClient` wraps one
  `ChatAnthropic` instance with two structured-output operations,
  `analyze_batch()` (per-class descriptions for one `ClassBatch`) and
  `generate_overview()` (the single project-wide summary), plus a
  `UsageTracker` that accumulates token/cost totals across every call.
- **`pipeline.py`** — decides *when* the LLM gets called. `_analyze_classes()`
  checks `cache.py` first and only batches the cache misses; `_process_batch()`
  calls `LLMClient.analyze_batch` per batch and contains a failure to that
  batch alone (see Error containment above).

To see what the pipeline actually did on a given run:

1. **Console output** — every run logs cache hits vs. LLM calls made, the
   number of batches, and a final summary line with token counts and
   estimated cost.
2. **`output/analysis.json` → `metadata`** — the same counters
   (`llm_calls_made`, `llm_calls_cached`, `total_input_tokens`,
   `total_output_tokens`, `estimated_cost_usd`) persisted per run, plus
   every class's LLM-written `description`/`notable_aspects`.
3. **The LLM cache file** (under `.cache/<repo>/llm_cache.json` by
   default) — the raw cached `ClassDescription` per content-hash key.
   Delete it, or pass `--refresh-cache`, to force every class back through
   the LLM and watch fresh batch/token logs.

## Methodologies Employed

| Concern | Method |
|---|---|
| Reading the codebase | Shallow `git clone --depth 1` of a caller-supplied repo/ref (`repo_fetcher.py`) |
| Structural extraction | `javalang` AST parsing, walked recursively so nested static classes (this codebase's DTOs) are all captured |
| Documentation extraction | A backward regex search for the nearest preceding `/** ... */` block per class/method, since `javalang` discards comments |
| REST endpoint extraction | Combining a class-level `@RequestMapping` base path with method-level `@GetMapping`/etc., purely from annotation arguments |
| Complexity signal | LOC + a heuristic cyclomatic-complexity estimate (`1 + count of if/for/while/case/catch/&&/\|\|`), with strings/comments stripped first so keywords inside them aren't miscounted |
| Token-limit enforcement | Real token counts via the Anthropic SDK's `count_tokens` endpoint (never a character-count guess, never `tiktoken`), enforced per batch with a hard ceiling |
| LLM orchestration | LangChain's `ChatAnthropic` + `.with_structured_output(PydanticModel)`, so the API/SDK — not prompt wording — guarantees schema-conformant JSON |
| Cost control | Batching (several classes per call) + content-hash caching (`cache.py`) so unchanged files never pay for a second LLM call |
| Output presentation | Both the JSON deliverable and the HTML report are rendered from one Pydantic model (`schemas.ProjectAnalysis`) |

## Best Practices Considered

| # | Practice | Where |
|---|---|---|
| 1 | Separation of concerns — one job per module (fetch, parse, compute, chunk, cache, call the LLM, render, orchestrate) | package layout under `src/intellisource_ai/` |
| 2 | Explicit contracts via typing — full type hints, Pydantic models instead of raw dicts at every module boundary | `schemas.py`, enforced via `mypy --strict` |
| 3 | Fail-fast, explicit configuration — no silent default for the target repo; a missing `--repo-url`/`REPO_URL` or `ANTHROPIC_API_KEY` raises before any network/API call | `config.py` |
| 4 | Custom exception hierarchy instead of bare `except Exception` | `exceptions.py` |
| 5 | Graceful degradation at genuine external-input boundaries (one unparseable file, one failed LLM batch) without crashing the run | `java_parser.py`, `pipeline.py` |
| 6 | Structured logging (stdlib `logging`, never `print`), with `--verbose`/`--quiet` | `logging_config.py` |
| 7 | Idempotent, cost-aware caching — a re-run makes zero additional LLM calls for unchanged files | `cache.py` |
| 8 | Prompt versioning tied to cache invalidation (`PROMPT_VERSION`), so a prompt change doesn't silently mix old and new results | `cache.py` |
| 9 | Secrets hygiene — API key only from environment/`.env`, never logged or hardcoded; `.env` is git-ignored | `config.py`, `.gitignore`, `.env.example` |
| 10 | Fully offline automated tests — the token counter and LLM client are mockable/injectable, so the suite never makes a real network call | `tests/`, `conftest.py` |
| 11 | Static analysis and formatting enforced (`ruff`, `mypy`) | `pyproject.toml` |
| 12 | CI pipeline running lint, type-check, and tests on every push | `.github/workflows/ci.yml` |
| 13 | Single source of truth for dependencies/metadata (`pyproject.toml`, PEP 621) instead of a loose `requirements.txt` | `pyproject.toml` |
| 14 | Documented public API — docstrings on every public class/function, inline comments reserved for genuinely non-obvious logic | throughout `src/intellisource_ai/*.py` |
| 15 | Schema-versioned output (`schema_version` field) for forward compatibility | `schemas.py` |
| 16 | Observability — every run reports files parsed, parse errors, cache hit rate, token usage, and estimated cost as first-class output, not a hidden side effect | `pipeline.py`, the `metadata` block in `analysis.json` |
| 17 | Honest documentation of limitations (below), instead of overclaiming accuracy | this section |
| 18 | Single source of truth for presentation — the HTML report renders the same model as the JSON, so they can't drift apart | `report_generator.py` |
| 19 | Autoescaped templating (Jinja2 `autoescape=True`) — LLM-generated text can never be interpreted as HTML/JS in the report | `report_generator.py` |

Two items the assignment calls out by name got a specific, verifiable answer rather than an approximation:

- **"Maintain efficient code processing without exceeding token limits"** — enforced with the Anthropic SDK's real `count_tokens` endpoint per batch against a hard ceiling (default 4,000 input tokens), not a character-count heuristic. If a single class alone would exceed the ceiling, its methods are split across sub-batches rather than truncated — no content is ever silently dropped.
- **"Structure the output... in a way that is consistent and machine-readable"** — `with_structured_output` guarantees schema-conformant JSON per call, and the pipeline additionally emits `analysis.schema.json` (from `ProjectAnalysis.model_json_schema()`) so the deliverable is machine-*validatable*, not just consistent by convention.

## Assumptions and Limitations

- **One branch/ref per run.** The tool analyzes a single shallow clone of one ref; it does not diff across branches or history.
- **The cyclomatic-complexity estimate is a heuristic**, not a certified McCabe score: `1 + count of if/for/while/case/catch/&&/||` on the method body text (with strings/comments stripped). It is useful for flagging outliers, not for a formal complexity audit.
- **`javalang`'s grammar coverage isn't exhaustive.** Modern syntax such as `record`, sealed classes, or pattern-matching `switch` may fail to parse on some codebases. Affected files are recorded in `parse_errors` and skipped — never silently dropped, but also never analyzed. (The Sakila target repo did not exhibit this issue in testing: Java 17 toolchain, but conventional class-based style throughout.)
- **Class-type classification (`controller`/`service`/`repository`/etc.) is convention-based** — Spring stereotype annotations first, directory-name keywords as a fallback. An unconventionally-organized codebase may be classified as `other` more often.
- **The project overview's tech-stack/dependency information is inferred by the LLM from a truncated excerpt of the README and build file**, not from a structured Gradle/Maven dependency parser. This keeps the one-time overview call simple; it may miss dependencies outside the excerpted portion of a very large build file.
- **Cost estimates use published list pricing** for the configured model at the time this was written and may not reflect promotional or negotiated rates.
- **A class large enough to exceed the per-batch token ceiling on its own bypasses the cache** (its methods are split and analyzed fresh every run) rather than caching a partial result under the whole-class key. This is a rare edge case for typically-sized classes.
- **Javadoc association is a nearest-preceding-comment heuristic**, not based on formal AST comment attachment (which `javalang` doesn't provide) — a Javadoc block separated from its declaration by unusual formatting could occasionally be missed.

## Setup

```powershell
git clone <this-repo>
cd intellisource-ai
pip install -e ".[dev]"
copy .env.example .env
# edit .env: set ANTHROPIC_API_KEY, and REPO_URL if you don't want to pass --repo-url each time
```

## Usage

```powershell
# Analyze the assignment's target repository (repo-url is required -- there is
# no default baked into the tool; this is just an example invocation):
python main.py --repo-url https://github.com/codejsha/spring-rest-sakila

# The identical command works against any other public Java/Spring repo:
python main.py --repo-url https://github.com/<owner>/<repo>

# Cheap smoke test against a handful of files before running the full analysis:
python main.py --repo-url https://github.com/codejsha/spring-rest-sakila --max-files 15

# Full flag reference:
python main.py --help
```

Outputs land under `output/`:

- **Open `output/report.html` in a browser** for the recommended way to review results — a dashboard, module-grouped class cards, and a notable-findings rollup.
- `output/analysis.json` and `output/analysis.schema.json` are the machine-readable deliverable.

A completed run prints a summary: files parsed, parse errors, LLM calls made vs. served from cache, total tokens, and estimated USD cost. Re-running the same command again should show most (or all) classes served from cache.

## Development

```powershell
pytest                 # unit tests -- fully offline, no API calls
ruff check .            # lint
mypy src                # type-check
```

CI (`.github/workflows/ci.yml`) runs all three on every push and pull request. No CI step requires `ANTHROPIC_API_KEY` — the test suite mocks the LLM client and token counter entirely.
