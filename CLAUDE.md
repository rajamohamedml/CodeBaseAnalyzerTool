# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Setup

```powershell
pip install -e ".[dev]"
copy .env.example .env
# Fill in ANTHROPIC_API_KEY; set REPO_URL to avoid passing --repo-url each time
```

## Commands

```powershell
# Run analysis (--repo-url is always required, no default is baked in)
python main.py --repo-url https://github.com/<owner>/<repo>

# Cheap smoke test (analyze a small subset of files)
python main.py --repo-url https://github.com/<owner>/<repo> --max-files 15

# Force re-clone the repo or bypass the LLM cache
python main.py --repo-url ... --refresh-repo --refresh-cache

# Full flag reference
python main.py --help
```

```powershell
pytest              # unit tests — fully offline, no API calls
ruff check .        # lint
mypy src            # type-check (strict mode)
```

To run a single test file: `pytest tests/test_cache.py -v`

## Architecture

The pipeline is a strict linear sequence with no backwards edges. Each stage has a single file:

```
repo_fetcher.py  → shallow git clone of target repo
java_parser.py   → AST parse of all .java files → ParsedClass / ParsedMethod
complexity.py    → heuristic LOC + cyclomatic per method → ComplexityMetrics
chunker.py       → group classes into token-bounded batches → ClassBatch
llm_client.py    → LangChain ChatAnthropic calls with structured output
cache.py         → content-hash cache for LLM results across runs
pipeline.py      → orchestrates all stages, owns graceful-degradation policy
report_generator.py → renders ProjectAnalysis → HTML (Jinja2 autoescape)
```

All cross-module contracts are Pydantic models in `schemas.py` — never raw dicts. The four stages in order produce: `ParseResult` → `ComplexityMetrics` (keyed by `ComplexityIndex`) → `ClassDescription` (via LLM) → `ProjectAnalysis` (the final deliverable).

**Two-stage cost split**: static analysis (java_parser, complexity) runs free; the LLM is called only for semantic descriptions (what does this class *mean*). Raw source is never sent to the LLM — only condensed signature/annotation/complexity text produced by `chunker.render_class_for_prompt`.

**Batching**: Classes are grouped by source directory first, then capped by `--batch-size` (default 6) and a real token ceiling (default 4,000 input tokens). Token counts come from the Anthropic SDK's `count_tokens` endpoint — never a character-count heuristic or tiktoken.

**Caching**: `cache.py` keys on `SHA-256(PROMPT_VERSION + rendered_class_text)`. A class whose source is unchanged costs zero tokens on re-runs. Bump `PROMPT_VERSION` in `cache.py` when the extraction prompt changes meaningfully.

**Output**: `pipeline.py` writes `output/analysis.json`, `output/analysis.schema.json`, and `output/report.html` — all derived from the single `ProjectAnalysis` Pydantic model, so JSON and HTML can never disagree.

**Error containment**: `pipeline.py` is the sole owner of the degradation policy. A failed parse, failed LLM batch, or failed overview call is logged and skipped; the run continues. Classes with no LLM description get an explicit `"Description unavailable."` placeholder rather than being silently dropped.

## Key Design Constraints

- `config.py` enforces fail-fast before any network call: `--repo-url`/`REPO_URL` and `ANTHROPIC_API_KEY` must be present or a `ConfigurationError` is raised.
- `mypy --strict` is enforced project-wide; the only exception is `javalang.*` (no stubs available).
- The test suite (`tests/`) never makes real API calls — `LLMClient` and the token counter are injected/mocked via `conftest.py`. CI runs with no `ANTHROPIC_API_KEY`.
- `ClassType` classification is a heuristic: Spring stereotype annotations first, package directory keywords as fallback. Unconventional layouts classify as `OTHER`.
- A class too large for a single batch is split across sub-batches by `chunker._split_oversized_class`; that class is not cached (a partial result would be stored under the whole-class key).
