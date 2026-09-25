# trawl

An open-source, self-hostable web search API for AI agents. It exposes the same endpoints and
request/response shapes as [Tavily](https://tavily.com) — `/search`, `/extract`, `/crawl`,
`/map` — so agent code written against Tavily can point at your own server instead.

- **Search** via a [SearXNG](https://github.com/searxng/searxng) metasearch instance (no search API keys needed)
- **Extraction** of clean markdown/text with [trafilatura](https://github.com/adbar/trafilatura)
- **Ranking**: BM25 relevance blended with the upstream engine's order; `advanced` depth fetches each page and returns its most relevant chunks
- **Answers** (`include_answer`) written by Claude from the retrieved results
- **Crawling / site maps** with depth, breadth, limit and regex path/domain filters

## Quick start (Docker)

```bash
cp .env.example .env          # set API_KEYS and (optionally) ANTHROPIC_API_KEY
docker compose up --build
```

```bash
curl -s localhost:8000/search \
  -H "Authorization: Bearer $KEY" -H "Content-Type: application/json" \
  -d '{"query": "latest python release", "search_depth": "advanced", "include_answer": true}'
```

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
