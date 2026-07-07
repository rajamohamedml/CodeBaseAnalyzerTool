# Agent Instructions for IntelliSource AI

## Purpose

This repository is a Python CLI tool that analyzes an external Java/Spring repository and extracts structured knowledge about its classes, methods, REST endpoints, and complexity. It is repository-agnostic: the target repo is supplied at runtime via `--repo-url` or `REPO_URL`.

## Key workflows

- Analyze a target repository:
  - `python main.py --repo-url https://github.com/<owner>/<repo>`
- Run a smoke test on a small subset:
  - `python main.py --repo-url https://github.com/<owner>/<repo> --max-files 15`
- Refresh clone or LLM cache:
  - `python main.py --repo-url ... --refresh-repo --refresh-cache`
- Skip HTML report generation:
  - `python main.py --repo-url ... --no-html-report`

## Test and quality commands

- `pytest` — unit tests run fully offline; mocks replace real LLM/token calls.
- `ruff check .` — linting.
- `mypy src` — strict static typing checks.

## Project structure and responsibilities

- `main.py` — CLI entrypoint that parses args, resolves settings, configures logging, and runs the pipeline.
- `src/intellisource_ai/config.py` — configuration and env handling.
- `src/intellisource_ai/repo_fetcher.py` — shallow clone of the target repository.
- `src/intellisource_ai/java_parser.py` — parse `.java` files into AST-derived class and method metadata.
- `src/intellisource_ai/complexity.py` — computes LOC and heuristic cyclomatic complexity.
- `src/intellisource_ai/chunker.py` — batches classes into token-safe prompt chunks.
- `src/intellisource_ai/llm_client.py` — orchestrates LangChain/Anthropic calls with structured output.
- `src/intellisource_ai/cache.py` — content-hash cache for LLM results; avoids repeated token cost for unchanged content.
- `src/intellisource_ai/report_generator.py` — renders the final HTML report from the Pydantic model.
- `src/intellisource_ai/schemas.py` — core Pydantic models and the single `ProjectAnalysis` schema.
- `src/intellisource_ai/pipeline.py` — end-to-end orchestration and graceful degradation.

## Important conventions for agents

- Preserve the two-stage design: deterministic static analysis first, then LLM-based semantic description.
- Do not hardcode a target repository URL in the tool.
- `--repo-url` or `REPO_URL` is required; `ANTHROPIC_API_KEY` is required to run LLM calls.
- The pipeline is linear and should degrade gracefully: parse failures or LLM failures should be logged and skipped, not crash the whole run.
- The output model is authoritative: `output/analysis.json`, `output/analysis.schema.json`, and `output/report.html` are generated from the same `ProjectAnalysis` object.
- The test suite expects no real API calls. Use existing mocks from `tests/conftest.py` when working on tests.
- `pyproject.toml` is the source of truth for dependencies and tooling config.
- Avoid exposing secrets or API keys in code or docs.

## Useful doc references

- `README.md` — project overview, architecture, usage, limitations, and setup instructions.
- `CLAUDE.md` — additional guidance for Claude-style agents and command examples.

## When adding or updating code

- Keep the code structure modular and single-responsibility.
- Keep prompt/caching behavior aligned with `cache.py` and `chunker.py`.
- Respect the existing output contract: HTML and JSON must derive from the same schema model.
- If you add a new feature or behavior, update `README.md` or `AGENTS.md` with a concise note instead of duplicating full docs.
