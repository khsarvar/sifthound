"""Web search backends. A provider only returns raw hits (title/url/snippet); ranking,
content extraction and answers happen in search.py so every backend gets them for free."""

from dataclasses import dataclass
from typing import Protocol

import httpx


class ProviderError(Exception):
    pass


@dataclass
class Hit:
    title: str
    url: str
    snippet: str
    published_date: str | None = None


class SearchProvider(Protocol):
    async def search(
        self, query: str, *, topic: str, time_range: str | None, max_results: int
    ) -> list[Hit]: ...

    async def images(self, query: str, *, max_results: int) -> list[str]: ...


_TIME_RANGES = {"d": "day", "w": "week", "m": "month", "y": "year"}


class SearxngProvider:
    """Queries a SearXNG instance's JSON API (requires `json` in search.formats)."""

    def __init__(self, client: httpx.AsyncClient, base_url: str):
        self._client = client
        self._base_url = base_url.rstrip("/")

    async def search(
        self, query: str, *, topic: str, time_range: str | None, max_results: int
    ) -> list[Hit]:
        params = {"q": query, "categories": "news" if topic == "news" else "general"}
        if time_range:
            params["time_range"] = _TIME_RANGES.get(time_range, time_range)
        hits: list[Hit] = []
        seen: set[str] = set()
        # SearXNG pages hold ~10 results; fetch more pages until we have enough.
        for page in range(1, 4):
            results = await self._query({**params, "pageno": page})
            if not results:
                break
            for r in results:
                url = r.get("url")
                if not url or url in seen:
                    continue
                seen.add(url)
                hits.append(
                    Hit(
                        title=r.get("title") or "",
                        url=url,
                        snippet=r.get("content") or "",
                        published_date=r.get("publishedDate"),
                    )
                )
            if len(hits) >= max_results:
                break
        return hits

    async def images(self, query: str, *, max_results: int) -> list[str]:
        results = await self._query({"q": query, "categories": "images"})
        urls = [r["img_src"] for r in results if r.get("img_src")]
        return list(dict.fromkeys(urls))[:max_results]

    async def _query(self, params: dict) -> list[dict]:
        try:
            resp = await self._client.get(
                f"{self._base_url}/search", params={**params, "format": "json"}, timeout=20
            )
            resp.raise_for_status()
            return resp.json().get("results", [])
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderError(f"SearXNG request failed: {e}") from e
