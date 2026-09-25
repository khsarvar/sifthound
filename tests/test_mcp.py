import httpx
import pytest
from conftest import PAGES, FakeProvider, mock_transport
from fastapi.testclient import TestClient
from mcp.client import Client

from sifthound.app import create_app
from sifthound.config import Settings
from sifthound.fetch import Fetcher
from sifthound.mcp_server import build_mcp
from sifthound.search import SearchService

TOOLS = {"sifthound_search", "sifthound_extract", "sifthound_crawl", "sifthound_map"}


def settings(**overrides) -> Settings:
    return Settings(allow_private_networks=True, _env_file=None, **overrides)


def service(hits, s: Settings) -> SearchService:
    return SearchService(
        FakeProvider(hits), Fetcher(httpx.AsyncClient(transport=mock_transport()), s), None
    )


@pytest.fixture
def mcp_client(hits):
    s = settings()
    svc = service(hits, s)
    return Client(build_mcp(lambda: svc, s))


async def call(client: Client, tool: str, args: dict) -> tuple[str, bool]:
    result = await client.call_tool(tool, args)
    return result.content[0].text, result.is_error


async def test_lists_read_only_tools(mcp_client):
    async with mcp_client as client:
        tools = (await client.list_tools()).tools
    assert {t.name for t in tools} == TOOLS
    for tool in tools:
        assert tool.annotations.read_only_hint and tool.annotations.open_world_hint
        assert tool.description


async def test_search_formats_results(mcp_client):
    async with mcp_client as client:
        text, is_error = await call(client, "sifthound_search", {"query": "install example"})
    assert not is_error
    assert text.startswith('# Search results for "install example"')
    assert "https://docs.example.com/install" in text and "relevance" in text


async def test_extract_reports_pages_and_failures(mcp_client):
    async with mcp_client as client:
        text, is_error = await call(
            client,
            "sifthound_extract",
            {"urls": ["https://docs.example.com/install", "https://docs.example.com/missing"]},
        )
    assert not is_error
    assert "## https://docs.example.com/install" in text and "pip install example" in text
    assert "## Failed" in text and "https://docs.example.com/missing: HTTP 404" in text


async def test_extract_truncates_long_pages(mcp_client):
    async with mcp_client as client:
        text, _ = await call(
            client,
            "sifthound_extract",
            {"urls": ["https://docs.example.com/install"], "max_chars": 200},
        )
    assert "[... truncated at 200 characters]" in text


async def test_crawl_and_map(mcp_client):
    async with mcp_client as client:
        crawled, _ = await call(client, "sifthound_crawl", {"url": "https://docs.example.com/"})
        mapped, _ = await call(client, "sifthound_map", {"url": "https://docs.example.com/"})
    assert crawled.startswith("# Crawled") and "## https://docs.example.com/install" in crawled
    assert "- https://docs.example.com/usage" in mapped
    assert "other.org" not in mapped  # external links stay out unless allow_external


@pytest.mark.parametrize(
    ("tool", "args", "message"),
    [
        ("sifthound_map", {"url": "https://docs.example.com/", "select_paths": ["("]}, "regex"),
        ("sifthound_extract", {"urls": []}, "urls"),
    ],
)
async def test_bad_input_is_a_tool_error(mcp_client, tool, args, message):
    async with mcp_client as client:
        text, is_error = await call(client, tool, args)
    assert is_error and message in text


# --- Streamable HTTP endpoint on the API server ----------------------------------------------

INITIALIZE = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "test", "version": "0"},
    },
}
MCP_HEADERS = {"Accept": "application/json, text/event-stream"}


def http_client(hits, **overrides) -> TestClient:
    s = settings(**overrides)
    return TestClient(create_app(s, service(hits, s)), base_url="http://localhost:8000")


def test_http_endpoint_initializes(hits):
    with http_client(hits) as client:
        resp = client.post("/mcp", json=INITIALIZE, headers=MCP_HEADERS)
    assert resp.status_code == 200
    assert '"name":"sifthound"' in resp.text


@pytest.mark.parametrize(
    ("headers", "query", "status"),
    [
        ({}, "", 401),
        ({"Authorization": "Bearer wrong"}, "", 401),
        ({"Authorization": "Bearer k1"}, "", 200),
        ({}, "?api_key=k1", 200),
    ],
)
def test_http_endpoint_requires_api_key(hits, headers, query, status):
    with http_client(hits, api_keys=["k1"]) as client:
        resp = client.post(f"/mcp{query}", json=INITIALIZE, headers=MCP_HEADERS | headers)
    assert resp.status_code == status
    if status == 401:
        assert resp.json() == {"detail": {"error": "Unauthorized: missing or invalid API key"}}


def test_http_endpoint_host_allowlist(hits):
    headers = MCP_HEADERS | {"Host": "search.example.com"}
    with http_client(hits) as client:
        assert client.post("/mcp", json=INITIALIZE, headers=headers).status_code == 421
    with http_client(hits, mcp_allowed_hosts=["search.example.com"]) as client:
        assert client.post("/mcp", json=INITIALIZE, headers=headers).status_code == 200


def test_rest_endpoints_unaffected(hits):
    with http_client(hits) as client:
        assert client.post("/extract", json={"urls": list(PAGES)[:1]}).status_code == 200
