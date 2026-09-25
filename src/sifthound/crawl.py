"""Breadth-first site traversal shared by /map (URLs only) and /crawl (URLs + content)."""

import asyncio
import re
from urllib.parse import urlsplit

from .extract import Document, extract
from .fetch import Fetcher, FetchError
from .models import MapRequest
from .search import domain_matches


def normalize_start_url(url: str) -> str:
    url = url if "://" in url else f"https://{url}"
    parts = urlsplit(url)
    return parts._replace(path=parts.path or "/").geturl()


class _UrlFilter:
    def __init__(self, req: MapRequest, root_host: str):
        self.req = req
        self.root_host = root_host
        self.select_paths = [re.compile(p) for p in req.select_paths]
        self.exclude_paths = [re.compile(p) for p in req.exclude_paths]
        self.select_domains = [re.compile(p) for p in req.select_domains]
        self.exclude_domains = [re.compile(p) for p in req.exclude_domains]

    def allows(self, url: str) -> bool:
        parts = urlsplit(url)
        host = parts.hostname or ""
        if not self.req.allow_external and not (
            host == self.root_host or domain_matches(url, [self.root_host])
        ):
            return False
        if self.select_domains and not any(p.search(host) for p in self.select_domains):
            return False
        if any(p.search(host) for p in self.exclude_domains):
            return False
        path = parts.path or "/"
        if self.select_paths and not any(p.search(path) for p in self.select_paths):
            return False
        return not any(p.search(path) for p in self.exclude_paths)


async def traverse(
    req: MapRequest,
    fetcher: Fetcher,
    *,
    fetch_leaves: bool,
    fmt: str = "markdown",
    advanced: bool = False,
) -> tuple[str, list[str], list[Document]]:
    """Breadth-first crawl from req.url up to max_depth link hops, following at most
    max_breadth new links per page. Filters apply to discovered links; the start URL is
    always fetched.

    Returns (base_url, discovered_urls, documents). With fetch_leaves=False (/map) pages at
    max_depth are listed but never fetched, since only their URLs are needed."""
    base_url = normalize_start_url(req.url)
    url_filter = _UrlFilter(req, (urlsplit(base_url).hostname or "").removeprefix("www."))
    discovered = [base_url]
    seen = {base_url}
    frontier = [base_url]
    docs: list[Document] = []

    for depth in range(req.max_depth + 1):
        if not frontier:
            break
        if fetch_leaves and len(docs) >= req.limit:
            break
        if not fetch_leaves and (depth == req.max_depth or len(discovered) >= req.limit):
            break
        batch = frontier[: req.limit - len(docs)]
        fetched = await asyncio.gather(*(_fetch_doc(fetcher, u, fmt, advanced) for u in batch))
        next_frontier: list[str] = []
        for doc in fetched:
            if doc is None:
                continue
            docs.append(doc)
            seen.add(doc.url)  # final URL after redirects
            if depth == req.max_depth:
                continue
            new_links = [u for u in doc.links if u not in seen and url_filter.allows(u)]
            for link in new_links[: req.max_breadth]:
                seen.add(link)
                discovered.append(link)
                next_frontier.append(link)
        frontier = next_frontier
    return base_url, discovered[: req.limit], docs[: req.limit]


async def _fetch_doc(fetcher: Fetcher, url: str, fmt: str, advanced: bool) -> Document | None:
    try:
        page = await fetcher.fetch(url)
    except FetchError:
        return None
    return await asyncio.to_thread(extract, page, fmt=fmt, advanced=advanced)
