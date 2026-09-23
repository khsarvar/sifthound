import httpx
import pytest

from trawl.config import Settings
from trawl.extract import extract
from trawl.fetch import Fetcher, FetchError, Page


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
