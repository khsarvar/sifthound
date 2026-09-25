import httpcore
import httpx
import pytest

from trawl.config import Settings
from trawl.extract import extract
from trawl.fetch import Fetcher, FetchError, Page, PublicOnlyBackend, public_only_transport


def fetcher(handler) -> Fetcher:
    settings = Settings(_env_file=None)
    return Fetcher(httpx.AsyncClient(transport=httpx.MockTransport(handler)), settings)


@pytest.mark.parametrize(
    "url", ["http://127.0.0.1/", "http://10.0.0.5/admin", "http://[::1]/", "file:///etc/passwd"]
)
async def test_blocks_private_and_non_http(url):
    with pytest.raises(FetchError):
        await fetcher(lambda r: httpx.Response(200))._fetch(url)


async def test_blocks_redirect_to_private_address():
    def handler(request):
        return httpx.Response(302, headers={"location": "http://169.254.169.254/latest"})

    with pytest.raises(FetchError, match="non-public"):
        await fetcher(handler).fetch("http://93.184.216.34/")


async def test_rejects_binary_content():
    def handler(request):
        return httpx.Response(200, content=b"%PDF", headers={"content-type": "application/pdf"})

    with pytest.raises(FetchError, match="content type"):
        await fetcher(handler).fetch("http://93.184.216.34/doc.pdf")


def test_extract_resolves_links_and_images():
    html = """<html><head><title>T</title><base href="https://site.com/dir/"></head><body>
      <article><p>Enough body text here to be kept by the extractor as main content of
      this page, repeated so it clears the minimum length threshold comfortably.</p>
      <a href="page#frag">x</a><a href="javascript:void(0)">y</a><img src="img.png"></article>
      </body></html>"""
    doc = extract(Page(url="https://site.com/dir/index", html=html, content_type="text/html"))
    assert "main content" in doc.content
    assert doc.links == ["https://site.com/dir/page"]
    assert doc.images == ["https://site.com/dir/img.png"]


class RecordingBackend(httpcore.AsyncMockBackend):
    """Mock network: records the address connected to and the TLS server_hostname."""

    def __init__(self):
        super().__init__([b"HTTP/1.1 200 OK\r\nContent-Type: text/html\r\n", b"\r\n"])
        self.connected: list[str] = []
        self.tls_hostnames: list[str] = []

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        self.connected.append(host)
        stream = await super().connect_tcp(host, port)
        tls_hostnames = self.tls_hostnames

        async def start_tls(ssl_context, server_hostname=None, timeout=None):
            tls_hostnames.append(server_hostname)
            return stream

        stream.start_tls = start_tls
        return stream


def guarded(answers: list[list[str]]) -> tuple[httpx.AsyncClient, RecordingBackend]:
    """Client over public_only_transport whose resolver returns `answers` in turn."""
    inner = RecordingBackend()

    async def resolve(host, port):
        return answers.pop(0)

    transport = public_only_transport(PublicOnlyBackend(inner, resolve=resolve))
    return httpx.AsyncClient(transport=transport), inner


async def test_connects_to_the_checked_address_with_original_hostname_for_tls():
    client, inner = guarded([["93.184.216.34"]])
    async with client:
        resp = await client.get("https://example.com/")
    assert resp.status_code == 200
    assert inner.connected == ["93.184.216.34"]
    assert inner.tls_hostnames == ["example.com"]


@pytest.mark.parametrize(
    "addresses",
    [["10.0.0.1"], ["93.184.216.34", "127.0.0.1"], ["::ffff:169.254.169.254"], []],
)
async def test_refuses_non_public_addresses_at_connect_time(addresses):
    client, inner = guarded([addresses])
    async with client:
        with pytest.raises(httpx.ConnectError):
            await client.get("http://rebind.test/")
    assert inner.connected == []


async def test_dns_rebinding_after_precheck_is_blocked():
    # Fetcher's pre-check sees a public IP literal; the connect-time lookup (simulating a
    # rebinding DNS answer) returns a private one, and the connection must be refused.
    client, inner = guarded([["10.0.0.1"]])
    fetcher = Fetcher(client, Settings(_env_file=None))
    with pytest.raises(FetchError, match="non-public"):
        await fetcher.fetch("http://93.184.216.34/")
    assert inner.connected == []
