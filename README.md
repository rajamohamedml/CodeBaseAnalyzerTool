# Codebase Analyzer

Is a project that analyzes a Java/Spring GitHub repository and extracts
structured knowledge — a project overview, method-level signatures and
descriptions, REST endpoints, and complexity signals — using an LLM
(Claude Haiku 4.5, via LangChain). It is **repo-agnostic**: the target
repository is always supplied by the caller, never hardcoded.

This project was built to satisfy a "Codebase Analysis using LLM" coding
assignment, demonstrated against any given repository (configurable).

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
   is anything about it noteworthy) is deferred to Claude. Classes are
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
| 1 | Separation of concerns — one job per module (fetch, parse, compute, chunk, cache, call the LLM, render, orchestrate) | package layout under `src/codebase_analyzer/` |
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
| 14 | Documented public API — docstrings on every public class/function, inline comments reserved for genuinely non-obvious logic | throughout `src/codebase_analyzer/*.py` |
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
cd CodebaseAnalyzer
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
