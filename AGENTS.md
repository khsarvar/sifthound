# Repository Guidelines

## Project Structure & Module Organization

The FastAPI service lives in `src/trawl/`. `app.py` defines the API, `models.py` holds Tavily-compatible request and response shapes, and `search.py` coordinates providers, fetching, ranking, extraction, and answers. `crawl.py` handles traversal. Tests are in `tests/test_*.py`, with shared fake providers and HTTP fixtures in `tests/conftest.py`. Docker assets live in `Dockerfile`, `docker-compose.yml`, and `docker/searxng/`.

## Build, Test, and Development Commands

- `python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"` installs the package and development tools (Python 3.11+).
- `.venv/bin/pytest` runs the offline suite; add a test path or `::test_name` to target one case.
- `.venv/bin/ruff check . && .venv/bin/ruff format --check .` runs the same lint and format checks as CI. Use `.venv/bin/ruff format .` to apply formatting.
- `.venv/bin/trawl --port 8000` starts the local API; OpenAPI docs are at `/docs`.
- `docker compose up --build` starts the API and SearXNG together. Local search requires SearXNG with JSON output enabled.

## Coding Style & Naming Conventions

Use four-space indentation, Python type annotations, and Ruff's 100-character line limit. Ruff enforces `E`, `F`, `I`, `UP`, and `B` rules; keep imports sorted. Use `snake_case` for modules, functions, and variables, and `PascalCase` for classes. Preserve Tavily-compatible field names and response shapes; add optional fields when extending behavior. API errors use `HTTPException` with a `{"error": ...}` detail object.

## Testing Guidelines

Use pytest and pytest-asyncio (`asyncio_mode = "auto"`). Name test files `test_<area>.py` and cases `test_<behavior>`. Keep tests network-free: use `FakeProvider`, `httpx.MockTransport`, and fixture pages in `tests/conftest.py`. Add coverage for changed endpoint behavior, including errors and security boundaries. CI runs pytest on Python 3.11, 3.12, and 3.13; no numeric coverage threshold is configured.

## Commit & Pull Request Guidelines

Recent commits use short, imperative subjects such as “Add CI workflow” and “Return 502 instead of 500”; follow that style. In pull requests, describe the behavior changed, note relevant API compatibility or security effects, link an issue when applicable, and report pytest and Ruff results. Include example requests and responses for API changes; screenshots are useful only for visible UI or documentation changes.

## Security & Configuration

Use `.env.example` to configure local settings; never commit `.env` or credentials. Route all fetches of caller-supplied URLs through `Fetcher`, which validates schemes and public addresses at each redirect. Do not bypass it or enable automatic redirects for those URLs. Keep `ALLOW_PRIVATE_NETWORKS=false` except in trusted local setups.
