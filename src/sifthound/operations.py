"""Endpoint logic shared by the REST API (app.py) and the MCP tools (mcp_server.py).

Each operation takes a request model and returns the Tavily-shaped response model. Failures
the caller should see are raised as OperationError(status, message); REST maps them to
HTTPException and MCP to tool errors.
"""

import asyncio
import re
import time

from .answer import AnswerError
from .config import Settings
from .crawl import traverse
from .extract import extract
from .fetch import FetchError
from .models import (
    CrawlRequest,
    CrawlResponse,
    ExtractRequest,
    ExtractResponse,
    ExtractResult,
    FailedResult,
    MapRequest,
    MapResponse,
    SearchRequest,
    SearchResponse,
)
from .providers import ProviderError
from .search import SearchService


class OperationError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


async def run_search(service: SearchService, req: SearchRequest) -> SearchResponse:
    start = time.perf_counter()
    if req.include_answer and service.answerer is None:
        raise OperationError(400, "include_answer is disabled on this server")
    try:
        results, images = await service.search(req)
    except ProviderError as e:
        raise OperationError(502, str(e)) from e

    answer = None
    if req.include_answer:
        depth = req.include_answer if isinstance(req.include_answer, str) else "basic"
        try:
            answer = await service.answerer.generate(req.query, results, depth)
        except AnswerError as e:
            raise OperationError(502, f"answer generation failed: {e}") from e

    return SearchResponse(
        query=req.query,
        answer=answer,
        images=images,
        results=results,
        response_time=round(time.perf_counter() - start, 2),
    )


async def run_extract(service: SearchService, req: ExtractRequest) -> ExtractResponse:
    start = time.perf_counter()
    urls = [req.urls] if isinstance(req.urls, str) else req.urls
    if not urls or len(urls) > 20:
        raise OperationError(400, "provide between 1 and 20 urls")

    async def one(url: str) -> ExtractResult | FailedResult:
        try:
            page = await service.fetcher.fetch(url)
        except FetchError as e:
            return FailedResult(url=url, error=str(e))
        doc = await asyncio.to_thread(
            extract, page, fmt=req.format, advanced=req.extract_depth == "advanced"
        )
        if not doc.content:
            return FailedResult(url=url, error="no extractable content")
        return ExtractResult(
            url=url, raw_content=doc.content, images=doc.images if req.include_images else []
        )

    outcomes = await asyncio.gather(*(one(u) for u in urls))
    return ExtractResponse(
        results=[o for o in outcomes if isinstance(o, ExtractResult)],
        failed_results=[o for o in outcomes if isinstance(o, FailedResult)],
        response_time=round(time.perf_counter() - start, 2),
    )


async def run_crawl(service: SearchService, settings: Settings, req: CrawlRequest) -> CrawlResponse:
    start = time.perf_counter()
    req.limit = min(req.limit, settings.crawl_max_limit)
    try:
        base_url, _, docs = await traverse(
            req,
            service.fetcher,
            fetch_leaves=True,
            fmt=req.format,
            advanced=req.extract_depth == "advanced",
        )
    except re.error as e:
        raise OperationError(400, f"invalid path/domain regex: {e}") from e
    return CrawlResponse(
        base_url=base_url,
        results=[
            ExtractResult(
                url=d.url, raw_content=d.content, images=d.images if req.include_images else []
            )
            for d in docs
            if d.content
        ],
        response_time=round(time.perf_counter() - start, 2),
    )


async def run_map(service: SearchService, settings: Settings, req: MapRequest) -> MapResponse:
    start = time.perf_counter()
    req.limit = min(req.limit, settings.crawl_max_limit)
    try:
        base_url, urls, _ = await traverse(req, service.fetcher, fetch_leaves=False)
    except re.error as e:
        raise OperationError(400, f"invalid path/domain regex: {e}") from e
    return MapResponse(
        base_url=base_url, results=urls, response_time=round(time.perf_counter() - start, 2)
    )
