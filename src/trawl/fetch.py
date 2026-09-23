"""HTTP fetching of arbitrary user-supplied URLs.

Every URL (and every redirect hop) is checked against private/loopback/link-local ranges
before it is requested, because /extract and /crawl let callers make this server fetch
anything. Note the check resolves DNS separately from httpx, so it does not defend
against DNS rebinding; run behind an egress firewall for hostile multi-tenant setups.
"""

import asyncio
import ipaddress
import socket
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from .config import Settings

MAX_REDIRECTS = 5
TEXT_TYPES = ("text/html", "application/xhtml+xml", "text/plain", "application/xml", "text/xml")


class FetchError(Exception):
    pass


@dataclass
class Page:
    url: str  # final URL after redirects
    html: str
    content_type: str


class Fetcher:
    def __init__(self, client: httpx.AsyncClient, settings: Settings):
        self._client = client
        self._settings = settings
        self._semaphore = asyncio.Semaphore(settings.fetch_concurrency)

    async def fetch(self, url: str) -> Page:
        async with self._semaphore:
            return await self._fetch(url)

    async def _fetch(self, url: str) -> Page:
        for _ in range(MAX_REDIRECTS + 1):
            await self._check_url(url)
            try:
                async with self._client.stream(
                    "GET",
                    url,
                    follow_redirects=False,
                    timeout=self._settings.fetch_timeout,
                    headers={"User-Agent": self._settings.user_agent},
                ) as resp:
                    if resp.is_redirect:
                        location = resp.headers.get("location")
                        if not location:
                            raise FetchError(f"redirect without location ({resp.status_code})")
                        url = urljoin(url, location)
                        continue
                    if resp.status_code >= 400:
                        raise FetchError(f"HTTP {resp.status_code}")
                    content_type = resp.headers.get("content-type", "").split(";")[0].strip()
                    if content_type and not content_type.startswith(TEXT_TYPES):
                        raise FetchError(f"unsupported content type: {content_type}")
                    body = await self._read_limited(resp)
                    return Page(url=str(resp.url), html=body, content_type=content_type)
            except httpx.HTTPError as e:
                raise FetchError(f"{type(e).__name__}: {e}") from e
        raise FetchError("too many redirects")

    async def _read_limited(self, resp: httpx.Response) -> str:
        chunks, size = [], 0
        async for chunk in resp.aiter_bytes():
            size += len(chunk)
            if size > self._settings.fetch_max_bytes:
                raise FetchError("response too large")
            chunks.append(chunk)
        return b"".join(chunks).decode(resp.encoding or "utf-8", errors="replace")

    async def _check_url(self, url: str) -> None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise FetchError("only absolute http(s) URLs are supported")
        if self._settings.allow_private_networks:
            return
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(
                parts.hostname, parts.port, type=socket.SOCK_STREAM
            )
        except socket.gaierror as e:
            raise FetchError(f"DNS resolution failed: {e}") from e
        for info in infos:
            ip = ipaddress.ip_address(info[4][0])
            if not ip.is_global:
                raise FetchError("URL resolves to a non-public address")
