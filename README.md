# trawl — open-source, self-hosted Tavily alternative

[![CI](https://github.com/khsarvar/trawl/actions/workflows/ci.yml/badge.svg)](https://github.com/khsarvar/trawl/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)

**trawl is an open-source, self-hosted web search API for AI agents and LLM apps, and a drop-in
replacement for the [Tavily](https://tavily.com) API.** It serves the same `/search`,
`/extract`, `/crawl` and `/map` endpoints with the same request and response shapes, so code
written for Tavily (including the official Python SDK and the LangChain integration) works
against your own server by changing only the base URL. It needs no search API key.

- **Search** through a [SearXNG](https://github.com/searxng/searxng) metasearch instance, with no search API keys
- **Extraction** of clean markdown or text from web pages with [trafilatura](https://github.com/adbar/trafilatura)
- **Ranking**: BM25 relevance blended with the upstream engine's order; `advanced` depth fetches each page and returns its most relevant chunks
- **Answers** (`include_answer`) written by Claude from the retrieved results
- **Crawling and site maps** with depth, breadth, limit and regex path/domain filters
- **SSRF protection**: private and internal addresses are blocked, including via redirects and DNS rebinding
- **MIT licensed**

## Use it as a drop-in Tavily replacement

Point the official Tavily clients at your trawl server with `api_base_url`. The key can be any
string when auth is disabled, or one of your `API_KEYS`.

```python
from tavily import TavilyClient

client = TavilyClient(api_key="your-trawl-key", api_base_url="http://localhost:8000")
results = client.search("latest python release", search_depth="advanced", max_results=5)
pages = client.extract(urls=["https://en.wikipedia.org/wiki/Okapi_BM25"])
```

LangChain, through [`langchain-tavily`](https://github.com/tavily-ai/langchain-tavily):

```python
from langchain_tavily import TavilySearch

search = TavilySearch(
    max_results=5, tavily_api_key="your-trawl-key", api_base_url="http://localhost:8000"
)
search.invoke({"query": "what is BM25 ranking"})
```

Tested with `tavily-python` 0.8.4 (search, extract, crawl, map; sync and async) and
`langchain-tavily` 0.2.18 (search, extract).

## Quick start (Docker)

```bash
cp .env.example .env          # set API_KEYS and (optionally) ANTHROPIC_API_KEY
docker compose up --build
```

This starts trawl on port 8000 alongside a SearXNG instance. Try a search:

```bash
curl -s localhost:8000/search \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"query": "latest python release", "search_depth": "advanced", "include_answer": true}'
```

OpenAPI docs are served at http://localhost:8000/docs.

## trawl vs Tavily, Firecrawl and crw

| | trawl | [Tavily](https://tavily.com) | [Firecrawl](https://github.com/firecrawl/firecrawl) | [crw](https://github.com/fastcrw/crw) |
|---|---|---|---|---|
| License | MIT | Proprietary (hosted service) | AGPL-3.0 | AGPL-3.0 |
| Self-hosted | Yes | No | Yes | Yes (also a managed API) |
| Tavily-compatible API | Yes | — | No (own API) | No (own API) |
| Search source | SearXNG metasearch | Proprietary | — | — |
| JavaScript rendering | No (static HTML) | — | Yes | — |
| MCP server | Not yet | Yes | Yes | Yes |
| Language | Python | — | TypeScript | Rust |

**When to pick something else:** if you'd rather not run infrastructure, or you want Tavily's
neural reranking, use hosted Tavily. If you need JavaScript-rendered pages or a scraping
platform with more features, look at Firecrawl or crw. trawl is for teams that want the
Tavily API on their own servers under a permissive license.

## FAQ

### What is trawl?
trawl is an open-source web search and extraction API for AI agents. It reproduces the Tavily
API (`/search`, `/extract`, `/crawl`, `/map`) on infrastructure you run yourself, using SearXNG
for search results, trafilatura for content extraction and BM25 for relevance ranking.

### Is trawl a drop-in replacement for Tavily?
For the four core endpoints, yes. The request and response fields match Tavily's, and the
official `tavily-python` SDK and `langchain-tavily` work by setting `api_base_url`. The
differences: relevance scores come from BM25 rather than a neural reranker, `instructions`
(crawl/map) and `include_image_descriptions` (search) are accepted but ignored, and Tavily's
`/research` endpoint isn't implemented.

### Do I need a search API key?
No. Search results come from SearXNG, which queries public search engines. The only optional
key is `ANTHROPIC_API_KEY`, used when a request sets `include_answer`.

### Does it work with LangChain?
Yes, through the official `langchain-tavily` package. Pass `api_base_url` pointing at your
trawl server, as in the example above.

### Is it safe to expose trawl on a public server?
Set `API_KEYS` so only your clients can call it. `/extract` and `/crawl` fetch caller-supplied
URLs, so trawl refuses private, loopback and link-local addresses, checked on every redirect and
at connect time against the exact address used, which also stops DNS rebinding.

### Can I run it without Docker?
Yes. Install it with pip (see Local development) and point `SEARXNG_URL` at any SearXNG
instance with the JSON output format enabled. `/extract`, `/crawl` and `/map` work without
SearXNG.

## Local development

```bash
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
docker compose up searxng -d    # uncomment its `ports:` in docker-compose.yml first
.venv/bin/trawl                 # http://127.0.0.1:8000, docs at /docs
.venv/bin/pytest                # offline test suite
.venv/bin/ruff check . && .venv/bin/ruff format .
```

## API

All endpoints take JSON `POST` bodies and a `Authorization: Bearer <key>` header (a legacy
`api_key` body field is also accepted). If `API_KEYS` is empty, auth is disabled.

| Endpoint   | Purpose | Key parameters |
|------------|---------|----------------|
| `/search`  | Web search | `query`, `search_depth` (`basic`/`advanced`), `topic` (`general`/`news`), `time_range`, `max_results`, `chunks_per_source`, `include_answer`, `include_raw_content`, `include_images`, `include_domains`, `exclude_domains` |
| `/extract` | Clean content from up to 20 URLs | `urls`, `extract_depth`, `format` (`markdown`/`text`), `include_images` |
| `/crawl`   | Crawl a site and return page content | `url`, `max_depth`, `max_breadth`, `limit`, `select_paths`, `exclude_paths`, `select_domains`, `exclude_domains`, `allow_external`, `format` |
| `/map`     | List a site's URLs without content | same traversal parameters as `/crawl` |

Differences from hosted Tavily: `instructions` (crawl/map) and `include_image_descriptions` are
accepted but ignored; relevance scores come from BM25, not a neural reranker.

## Configuration

Environment variables (see `.env.example`): `API_KEYS`, `SEARXNG_URL`, `ANSWER_ENABLED`,
`ANSWER_MODEL`, `ANSWER_EFFORT`, `FETCH_TIMEOUT`, `FETCH_CONCURRENCY`, `FETCH_MAX_BYTES`,
`ALLOW_PRIVATE_NETWORKS`, `CRAWL_MAX_LIMIT`.

**Security:** `/extract` and `/crawl` make the server fetch caller-supplied URLs. Requests to
private, loopback and link-local addresses are blocked (including via redirects) unless
`ALLOW_PRIVATE_NETWORKS=true`. The check runs at connect time against the exact address being
connected to, so DNS rebinding can't get around it. Fetches of user URLs ignore
`HTTP(S)_PROXY`, since a proxy would hide the destination address. As defense in depth for
hostile multi-tenant deployments, also restrict egress at the network level.

## License

MIT
