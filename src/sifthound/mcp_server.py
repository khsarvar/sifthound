"""MCP (Model Context Protocol) server exposing Sifthound's search/extract/crawl/map as tools.

Served two ways from the same MCPServer: Streamable HTTP at /mcp on the API server (app.py)
and stdio via `sifthound mcp` (__main__.py). Tools call the shared operations, so every fetch
still goes through Fetcher and its SSRF checks.
"""

from collections.abc import Callable
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import Field

from . import __version__
from .config import Settings
from .models import CrawlRequest, ExtractRequest, ExtractResult, MapRequest, SearchRequest
from .operations import OperationError, run_crawl, run_extract, run_map, run_search
from .search import SearchService

# Per-page content cap for tool output, so one long page can't flood the model's context.
DEFAULT_MAX_CHARS = 4000

INSTRUCTIONS = """Sifthound is a self-hosted web search and extraction service.
Use sifthound_search to find sources for a question, sifthound_extract to read pages whose URLs
you already have, sifthound_map to list a site's URLs, and sifthound_crawl to read many pages of
one site. On large sites, map first and then extract or crawl only the paths you need."""

READ_ONLY = ToolAnnotations(read_only_hint=True, open_world_hint=True)

MaxChars = Annotated[
    int, Field(ge=200, le=50_000, description="Maximum characters of content to return per page.")
]
PathPatterns = Annotated[
    list[str] | None,
    Field(description="Regexes matched against URL paths, e.g. ['/docs/.*']."),
]


def _clip(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + f"\n\n[... truncated at {max_chars} characters]"


def _pages(results: list[ExtractResult], max_chars: int) -> str:
    return "\n\n".join(f"## {r.url}\n\n{_clip(r.raw_content, max_chars)}" for r in results)


def transport_security(settings: Settings) -> TransportSecuritySettings:
    """Host/Origin allowlist for the HTTP transport: localhost (the SDK's default) plus
    MCP_ALLOWED_HOSTS. Anything else is rejected with 421 (DNS-rebinding protection)."""
    hosts = ["127.0.0.1:*", "localhost:*", "[::1]:*", *settings.mcp_allowed_hosts]
    origins = [f"{scheme}://{host}" for host in hosts for scheme in ("http", "https")]
    return TransportSecuritySettings(allowed_hosts=hosts, allowed_origins=origins)


def build_mcp(get_service: Callable[[], SearchService], settings: Settings) -> MCPServer:
    mcp = MCPServer(
        name="sifthound",
        title="Sifthound",
        version=__version__,
        instructions=INSTRUCTIONS,
        website_url="https://github.com/khsarvar/sifthound",
    )

    @mcp.tool(annotations=READ_ONLY)
    async def sifthound_search(
        query: Annotated[str, Field(min_length=1, description="The search query.")],
        max_results: Annotated[int, Field(ge=1, le=20, description="Number of results.")] = 5,
        search_depth: Annotated[
            Literal["basic", "advanced"],
            Field(
                description="'basic' returns search snippets; 'advanced' reads each page and "
                "returns its most relevant passages (slower, better content)."
            ),
        ] = "basic",
        topic: Annotated[
            Literal["general", "news"], Field(description="Use 'news' for current events.")
        ] = "general",
        time_range: Annotated[
            Literal["day", "week", "month", "year"] | None,
            Field(description="Only return results from this recent period."),
        ] = None,
        include_domains: Annotated[
            list[str] | None, Field(description="Only return results from these domains.")
        ] = None,
        exclude_domains: Annotated[
            list[str] | None, Field(description="Never return results from these domains.")
        ] = None,
        max_chars: MaxChars = DEFAULT_MAX_CHARS,
    ) -> str:
        """Search the web and return ranked results with titles, URLs and relevant content.

        Use this to find sources for a question or to discover pages about a topic. If you
        already know the URLs, use sifthound_extract instead."""
        req = SearchRequest(
            query=query,
            max_results=max_results,
            search_depth=search_depth,
            topic=topic,
            time_range=time_range,
            include_domains=include_domains or [],
            exclude_domains=exclude_domains or [],
        )
        try:
            resp = await run_search(get_service(), req)
        except OperationError as e:
            raise ToolError(e.message) from e
        if not resp.results:
            return f'No results for "{query}".'
        lines = [f'# Search results for "{query}"']
        for i, r in enumerate(resp.results, 1):
            date = f" · published {r.published_date}" if r.published_date else ""
            lines.append(
                f"\n## {i}. {r.title}\n{r.url}\nrelevance {r.score:.2f}{date}\n\n"
                f"{_clip(r.content, max_chars)}"
            )
        return "\n".join(lines)

    @mcp.tool(annotations=READ_ONLY)
    async def sifthound_extract(
        urls: Annotated[
            list[str], Field(min_length=1, max_length=20, description="1 to 20 page URLs.")
        ],
        format: Annotated[
            Literal["markdown", "text"], Field(description="Output format of page content.")
        ] = "markdown",
        max_chars: MaxChars = DEFAULT_MAX_CHARS,
    ) -> str:
        """Fetch web pages and return their main content as clean markdown or text.

        Use this when you already have the URLs, for example from sifthound_search results."""
        try:
            resp = await run_extract(get_service(), ExtractRequest(urls=urls, format=format))
        except OperationError as e:
            raise ToolError(e.message) from e
        parts = [_pages(resp.results, max_chars)] if resp.results else []
        if resp.failed_results:
            failed = "\n".join(f"- {f.url}: {f.error}" for f in resp.failed_results)
            parts.append(f"## Failed\n\n{failed}")
        return "\n\n".join(parts)

    @mcp.tool(annotations=READ_ONLY)
    async def sifthound_crawl(
        url: Annotated[str, Field(description="The page to start crawling from.")],
        max_depth: Annotated[
            int, Field(ge=1, le=5, description="How many links deep to follow from the start.")
        ] = 1,
        limit: Annotated[int, Field(ge=1, le=100, description="Maximum pages to return.")] = 10,
        select_paths: PathPatterns = None,
        exclude_paths: PathPatterns = None,
        allow_external: Annotated[
            bool, Field(description="Follow links to other domains.")
        ] = False,
        max_chars: MaxChars = DEFAULT_MAX_CHARS,
    ) -> str:
        """Crawl a website from a starting URL and return the content of the pages found.

        Use this to read many pages of one site. For large sites, call sifthound_map first and
        narrow the crawl with select_paths."""
        req = CrawlRequest(
            url=url,
            max_depth=max_depth,
            limit=limit,
            select_paths=select_paths or [],
            exclude_paths=exclude_paths or [],
            allow_external=allow_external,
        )
        try:
            resp = await run_crawl(get_service(), settings, req)
        except OperationError as e:
            raise ToolError(e.message) from e
        if not resp.results:
            return f"No readable pages found from {resp.base_url}."
        header = f"# Crawled {len(resp.results)} pages from {resp.base_url}"
        return f"{header}\n\n{_pages(resp.results, max_chars)}"

    @mcp.tool(annotations=READ_ONLY)
    async def sifthound_map(
        url: Annotated[str, Field(description="The site or page to map from.")],
        max_depth: Annotated[
            int, Field(ge=1, le=5, description="How many links deep to follow from the start.")
        ] = 1,
        limit: Annotated[int, Field(ge=1, le=200, description="Maximum URLs to return.")] = 50,
        select_paths: PathPatterns = None,
        exclude_paths: PathPatterns = None,
    ) -> str:
        """List the URLs of a website without fetching their content.

        Use this to see how a site is organised before extracting or crawling specific pages."""
        req = MapRequest(
            url=url,
            max_depth=max_depth,
            limit=limit,
            select_paths=select_paths or [],
            exclude_paths=exclude_paths or [],
        )
        try:
            resp = await run_map(get_service(), settings, req)
        except OperationError as e:
            raise ToolError(e.message) from e
        urls = "\n".join(f"- {u}" for u in resp.results)
        return f"# {len(resp.results)} URLs found from {resp.base_url}\n\n{urls}"

    return mcp
