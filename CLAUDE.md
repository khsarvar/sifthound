# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

Sifthound is an open-source, self-hostable alternative to the Tavily API: a FastAPI service exposing
`/search`, `/extract`, `/crawl`, `/map` with **Tavily-compatible request/response shapes**
(`src/sifthound/models.py`). Compatibility is the product requirement — don't rename fields or
change response shapes; add new behavior as optional fields instead. Errors are returned as
`HTTPException(status, detail={"error": ...})`; keep that shape consistent across endpoints.

## Commands

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"   # setup
.venv/bin/pytest                                   # all tests (offline, <1s)
.venv/bin/pytest tests/test_api.py::test_extract   # single test
.venv/bin/ruff check . && .venv/bin/ruff format .  # lint + format (line length 100)
.venv/bin/sifthound --port 8000                    # run server; OpenAPI docs at /docs, MCP at /mcp
.venv/bin/sifthound mcp                            # MCP over stdio
docker compose up --build                          # API + SearXNG
```

`/search` needs a SearXNG instance with the JSON format enabled (`docker/searxng/settings.yml`);
`/extract`, `/crawl`, `/map` work without it. Config is env vars / `.env` via `config.Settings`
(see `.env.example`).

## Architecture

Request flow for `/search` (`search.py` → `SearchService`):
1. `providers.py` — a `SearchProvider` returns raw `Hit`s (title/url/snippet). `SearxngProvider` is
   the only backend; new backends (Brave, Bing, …) just implement the protocol. Providers do no
   ranking or fetching.
2. Domain filtering happens post-hoc (plus `site:` operators in the query), so the provider is
   over-fetched (`max_results * 2`).
3. `search_depth="advanced"` or `include_raw_content` → pages are fetched (`fetch.py`) and
   extracted (`extract.py`, trafilatura, run in a thread). Advanced replaces the snippet with the
   top BM25 chunks of the page (`rank.best_chunks`); a failed fetch falls back to the snippet.
4. `rank.combine_scores` blends normalized BM25 with the provider's rank position → `score` in [0,1].
5. `include_answer` → `answer.py` calls Claude (`claude-opus-5` by default, adaptive thinking,
   server-side refusal fallback via `fallbacks="default"`). Failures surface as HTTP 502, never a
   silent `null` answer.

`/crawl` and `/map` share `crawl.traverse` (BFS over `Document.links`). `/map` passes
`fetch_leaves=False` so pages at `max_depth` are listed but not fetched. User-supplied path/domain
filters are regexes; `re.error` becomes a 400.

Endpoint logic lives in `operations.py` (`run_search`/`run_extract`/`run_crawl`/`run_map`), shared
by the REST handlers in `app.py` and the MCP tools in `mcp_server.py`. Operations raise
`OperationError(status, message)`; REST maps it to `HTTPException(status, {"error": ...})`, MCP to a
`ToolError`. Put new endpoint behavior in the operation, not the handler, so both surfaces get it.

MCP (`mcp_server.build_mcp`, SDK v2 `MCPServer`) is served two ways: Streamable HTTP mounted at
`/mcp` in `create_app`, behind `RequireApiKey` (same `API_KEYS`, Bearer or `?api_key=`) and a
Host allowlist (`MCP_ALLOWED_HOSTS` + localhost, else 421); and stdio via `sifthound mcp`
(`__main__.py`). Mounted, the MCP app's own lifespan never runs, so `create_app`'s lifespan must
enter `mcp.session_manager.run()`. In stdio mode stdout is the protocol: log to stderr only.

`app.service_context(settings)` builds the production `SearchService` with two `httpx.AsyncClient`s:
a shared one (SearXNG) and a guarded one for `Fetcher` (see Security invariant); the API lifespan
and stdio mode both use it. Tests inject a `SearchService` built from `FakeProvider` + a `Fetcher`
over `httpx.MockTransport` (`tests/conftest.py`) — keep tests network-free; add fixture pages to
`PAGES`. MCP tests use the SDK's in-process `Client(mcp)`; HTTP `/mcp` tests need a `localhost`
base URL (`TestClient`'s default `testserver` host gets 421).

## Security invariant

All outbound fetches of user-supplied URLs must go through `Fetcher`, which rejects non-http(s)
schemes and non-public IPs on every redirect hop (redirects are followed manually for this reason).
In the app, `Fetcher` runs on its own client over `public_only_transport()`, whose
`PublicOnlyBackend` resolves each host, refuses non-public addresses, and connects to the checked
IP — this is what defeats DNS rebinding, so don't give `Fetcher` the shared client (SearXNG is
usually on a private network). Don't call `httpx` with `follow_redirects=True` on user URLs or
bypass `Fetcher`. Tests set `allow_private_networks=True` only because the mock hosts don't
resolve; `tests/test_fetch.py` covers the connect-time guard with a fake resolver.

## Not implemented (accepted for compatibility, ignored)

`instructions` on `/crawl`/`/map`, `include_image_descriptions` on `/search`.
