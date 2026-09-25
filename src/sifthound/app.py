import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import parse_qs

import httpx
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import ASGIApp, Receive, Scope, Send

from . import __version__
from .answer import AnswerGenerator
from .config import Settings, get_settings
from .fetch import Fetcher, public_only_transport
from .mcp_server import build_mcp, transport_security
from .models import (
    ApiRequest,
    CrawlRequest,
    CrawlResponse,
    ExtractRequest,
    ExtractResponse,
    MapRequest,
    MapResponse,
    SearchRequest,
    SearchResponse,
)
from .operations import OperationError, run_crawl, run_extract, run_map, run_search
from .providers import SearxngProvider
from .search import SearchService

log = logging.getLogger(__name__)
bearer = HTTPBearer(auto_error=False)
UNAUTHORIZED = "Unauthorized: missing or invalid API key"


@asynccontextmanager
async def service_context(settings: Settings) -> AsyncIterator[SearchService]:
    """The production SearchService, with its HTTP clients open for the context's lifetime.
    Used by the API server's lifespan and by `sifthound mcp` (stdio)."""
    # User-supplied URLs get their own client whose transport refuses non-public
    # addresses at connect time; SearXNG is often on a private network, so it can't share.
    fetch_transport = None if settings.allow_private_networks else public_only_transport()
    async with (
        httpx.AsyncClient() as client,
        httpx.AsyncClient(transport=fetch_transport) as fetch_client,
    ):
        yield SearchService(
            provider=SearxngProvider(client, settings.searxng_url),
            fetcher=Fetcher(fetch_client, settings),
            answerer=AnswerGenerator(settings) if settings.answer_enabled else None,
        )


class RequireApiKey:
    """ASGI wrapper enforcing API_KEYS on the MCP endpoint, like `authorize` does for REST.
    Accepts `Authorization: Bearer <key>` or, for clients that can't set headers, `?api_key=`."""

    def __init__(self, app: ASGIApp, api_keys: list[str]):
        self.app = app
        self.api_keys = api_keys

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self.api_keys and self._key(scope) not in self.api_keys:
            response = JSONResponse({"detail": {"error": UNAUTHORIZED}}, status_code=401)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _key(scope: Scope) -> str | None:
        auth = dict(scope["headers"]).get(b"authorization", b"").decode("latin-1")
        if auth[:7].lower() == "bearer ":
            return auth[7:].strip()
        return parse_qs(scope.get("query_string", b"").decode()).get("api_key", [None])[0]


def create_app(settings: Settings | None = None, service: SearchService | None = None) -> FastAPI:
    """Build the app. Tests inject `service` (with fake provider/fetcher) to stay offline."""
    settings = settings or get_settings()

    mcp = build_mcp(lambda: app.state.service, settings)
    mcp_http = mcp.streamable_http_app(transport_security=transport_security(settings))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # Mounted, the MCP app's own lifespan never runs, so its session manager starts here.
        async with mcp.session_manager.run():
            if service is not None:
                app.state.service = service
                yield
            else:
                async with service_context(settings) as app.state.service:
                    yield

    app = FastAPI(title="sifthound", version=__version__, lifespan=lifespan)
    app.router.routes.append(Route("/mcp", RequireApiKey(mcp_http, settings.api_keys)))

    def svc(request: Request) -> SearchService:
        return request.app.state.service

    def authorize(body: ApiRequest, creds: HTTPAuthorizationCredentials | None) -> None:
        if not settings.api_keys:
            return
        key = creds.credentials if creds else body.api_key
        if key not in settings.api_keys:
            raise HTTPException(401, detail={"error": UNAUTHORIZED})

    def failed(e: OperationError) -> HTTPException:
        return HTTPException(e.status, detail={"error": e.message})

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
        try:
            return await run_search(service, req)
        except OperationError as e:
            raise failed(e) from e

    @app.post("/extract", response_model=ExtractResponse)
    async def extract_urls(
        req: ExtractRequest,
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
        service: SearchService = Depends(svc),
    ) -> ExtractResponse:
        authorize(req, creds)
        try:
            return await run_extract(service, req)
        except OperationError as e:
            raise failed(e) from e

    @app.post("/crawl", response_model=CrawlResponse)
    async def crawl(
        req: CrawlRequest,
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
        service: SearchService = Depends(svc),
    ) -> CrawlResponse:
        authorize(req, creds)
        try:
            return await run_crawl(service, settings, req)
        except OperationError as e:
            raise failed(e) from e

    @app.post("/map", response_model=MapResponse)
    async def map_site(
        req: MapRequest,
        creds: HTTPAuthorizationCredentials | None = Depends(bearer),
        service: SearchService = Depends(svc),
    ) -> MapResponse:
        authorize(req, creds)
        try:
            return await run_map(service, settings, req)
        except OperationError as e:
            raise failed(e) from e

    return app
