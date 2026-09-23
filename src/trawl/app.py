import asyncio
import logging
import re
import time
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .answer import AnswerError, AnswerGenerator
from .config import Settings, get_settings
from .crawl import traverse
from .extract import extract
from .fetch import Fetcher, FetchError
from .models import (
    ApiRequest,
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
from .providers import ProviderError, SearxngProvider
from .search import SearchService

log = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)


def create_app(settings: Settings | None = None, service: SearchService | None = None) -> FastAPI:
    """Build the app. Tests inject `service` (with fake provider/fetcher) to stay offline."""
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with httpx.AsyncClient() as client:
            app.state.service = service or SearchService(
                provider=SearxngProvider(client, settings.searxng_url),
                fetcher=Fetcher(client, settings),
                answerer=AnswerGenerator(settings) if settings.answer_enabled else None,
            )
            yield

    app = FastAPI(title="trawl", version="0.1.0", lifespan=lifespan)

    def svc(request: Request) -> SearchService:
        return request.app.state.service

    def authorize(body: ApiRequest, creds: HTTPAuthorizationCredentials | None) -> None:
        if not settings.api_keys:
            return
        key = creds.credentials if creds else body.api_key
        if key not in settings.api_keys:
            raise HTTPException(401, detail={"error": "Unauthorized: missing or invalid API key"})

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.post("/search", response_model=SearchResponse, response_model_exclude_none=False)
    async def search(
        req: SearchRequest,
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
        service: SearchService = Depends(svc),
    ) -> SearchResponse:
        authorize(req, creds)
        start = time.perf_counter()
        if req.include_answer and service.answerer is None:
            raise HTTPException(400, detail={"error": "include_answer is disabled on this server"})
        try:
            results, images = await service.search(req)
        except ProviderError as e:
            raise HTTPException(502, detail={"error": str(e)}) from e

        answer = None
        if req.include_answer:
            depth = req.include_answer if isinstance(req.include_answer, str) else "basic"
            try:
                answer = await service.answerer.generate(req.query, results, depth)
            except AnswerError as e:
                raise HTTPException(502, detail={"error": f"answer generation failed: {e}"}) from e

        return SearchResponse(
            query=req.query,
            answer=answer,
            images=images,
            results=results,
            response_time=round(time.perf_counter() - start, 2),
        )

    @app.post("/extract", response_model=ExtractResponse)
    async def extract_urls(
        req: ExtractRequest,
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
        service: SearchService = Depends(svc),
    ) -> ExtractResponse:
        authorize(req, creds)
        start = time.perf_counter()
        urls = [req.urls] if isinstance(req.urls, str) else req.urls
        if not urls or len(urls) > 20:
            raise HTTPException(400, detail={"error": "provide between 1 and 20 urls"})

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

    @app.post("/crawl", response_model=CrawlResponse)
    async def crawl(
        req: CrawlRequest,
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
        service: SearchService = Depends(svc),
    ) -> CrawlResponse:
        authorize(req, creds)
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
            raise HTTPException(400, detail={"error": f"invalid path/domain regex: {e}"}) from e
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

    @app.post("/map", response_model=MapResponse)
    async def map_site(
        req: MapRequest,
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
        service: SearchService = Depends(svc),
    ) -> MapResponse:
        authorize(req, creds)
        start = time.perf_counter()
        req.limit = min(req.limit, settings.crawl_max_limit)
        try:
            base_url, urls, _ = await traverse(req, service.fetcher, fetch_leaves=False)
        except re.error as e:
            raise HTTPException(400, detail={"error": f"invalid path/domain regex: {e}"}) from e
        return MapResponse(
            base_url=base_url, results=urls, response_time=round(time.perf_counter() - start, 2)
        )

    return app
