# app/main.py
"""
KarobarOne API Gateway — Reverse proxy routing /api/v1/* by path prefix.
Source: SERVICES.md §9, DEPLOY.md §4.4, RULES.md §1 C2.
"""
import os
import re
from contextlib import asynccontextmanager
from uuid import uuid4
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, Response as FastAPIResponse, PlainTextResponse
from fastapi.middleware.cors import CORSMiddleware
import httpx
import structlog
import yaml

from libs.platform_contracts.metrics import metrics
from .config import settings

logger = structlog.get_logger("gateway")

# Persistent HTTP client and route table in memory
http_client: httpx.AsyncClient | None = None
route_table: list[dict[str, str]] = []
default_target: str = "monolith"


def load_route_table(path: str) -> tuple[list[dict], str]:
    """Loads prefix and pattern routes from YAML file."""
    if not os.path.exists(path):
        logger.warning("routes_file_not_found_using_defaults", path=path)
        return [], "monolith"
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    routes = data.get("routes", [])
    for r in routes:
        if "pattern" in r:
            r["_regex"] = re.compile(r["pattern"])
    # Sort regex pattern routes first, then prefixes by length descending
    routes.sort(key=lambda r: (1 if "pattern" in r else 0, len(r.get("prefix", r.get("pattern", "")))), reverse=True)
    def_target = data.get("default_target", "monolith")
    return routes, def_target


def resolve_upstream_base_url(target_name: str) -> str:
    """Maps target name to configured upstream environment base URL."""
    target_upper = target_name.upper().strip()
    attr_name = f"UPSTREAM_{target_upper}_URL"
    url = getattr(settings, attr_name, None)
    if not url:
        return settings.UPSTREAM_MONOLITH_URL
    return url.rstrip("/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    global http_client, route_table, default_target
    route_table, default_target = load_route_table(settings.ROUTES_FILE_PATH)
    logger.info("gateway_routes_loaded", routes_count=len(route_table), default_target=default_target)
    http_client = httpx.AsyncClient(timeout=settings.GATEWAY_CLIENT_TIMEOUT_SEC)
    yield
    if http_client:
        await http_client.aclose()


app = FastAPI(
    title="KarobarOne Gateway",
    version="1.0.0",
    docs_url=None if settings.ENVIRONMENT == "prod" else "/docs",
    redoc_url=None,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health/live")
async def health_live():
    return {"status": "ok", "service": "gateway"}


@app.get("/health/ready")
async def health_ready():
    return {"status": "ok", "service": "gateway", "routes_count": len(route_table)}


@app.get("/metrics", response_class=PlainTextResponse)
async def get_metrics():
    """Internal Prometheus metrics endpoint (RULES.md §12)."""
    return PlainTextResponse(metrics.render_prometheus_text(), media_type="text/plain; version=0.0.4; charset=utf-8")


# Hop-by-hop headers to strip when proxying
HOP_BY_HOP_HEADERS = {
    "host",
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
}


@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"])
async def proxy_request(request: Request, path: str):
    """Reverse proxies all incoming requests according to prefix routes table."""
    full_path = f"/{path}"
    request_id = request.headers.get("x-request-id") or str(uuid4())

    # 1. Match route pattern or prefix
    matched_target = default_target
    for r in route_table:
        if "_regex" in r:
            if r["_regex"].search(full_path):
                matched_target = r.get("target", default_target)
                break
        elif full_path.startswith(r.get("prefix", "")):
            matched_target = r.get("target", default_target)
            break

    upstream_base = resolve_upstream_base_url(matched_target)
    target_url = f"{upstream_base}{full_path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    # 2. Prepare headers (filter hop-by-hop headers, ensure X-Request-Id)
    upstream_headers = {
        k: v for k, v in request.headers.items()
        if k.lower() not in HOP_BY_HOP_HEADERS
    }
    upstream_headers["x-request-id"] = request_id

    # 3. Read body
    body = await request.body()

    client = http_client or httpx.AsyncClient(timeout=settings.GATEWAY_CLIENT_TIMEOUT_SEC)

    try:
        upstream_resp = await client.request(
            method=request.method,
            url=target_url,
            headers=upstream_headers,
            content=body,
        )

        resp_headers = {
            k: v for k, v in upstream_resp.headers.items()
            if k.lower() not in HOP_BY_HOP_HEADERS
        }
        resp_headers["x-request-id"] = request_id
        resp_headers["x-served-by"] = matched_target

        metrics.inc_counter("http_requests_total", status_class=f"{upstream_resp.status_code // 100}xx", target=matched_target)
        return FastAPIResponse(
            content=upstream_resp.content,
            status_code=upstream_resp.status_code,
            headers=resp_headers,
        )
    except httpx.ConnectError as e:
        logger.error("upstream_connect_error", target=matched_target, url=target_url, error=str(e))
        return JSONResponse(
            status_code=503,
            content={
                "error": {
                    "code": "UPSTREAM_UNAVAILABLE",
                    "message": f"Upstream service '{matched_target}' is unreachable",
                    "details": {"target_url": target_url},
                }
            },
            headers={"x-request-id": request_id, "x-served-by": matched_target},
        )
    except httpx.TimeoutException as e:
        logger.error("upstream_timeout", target=matched_target, url=target_url, error=str(e))
        return JSONResponse(
            status_code=504,
            content={
                "error": {
                    "code": "GATEWAY_TIMEOUT",
                    "message": f"Upstream service '{matched_target}' timed out",
                    "details": {"target_url": target_url},
                }
            },
            headers={"x-request-id": request_id, "x-served-by": matched_target},
        )
    except Exception as e:
        logger.error("proxy_unexpected_error", target=matched_target, url=target_url, error=str(e))
        return JSONResponse(
            status_code=502,
            content={
                "error": {
                    "code": "BAD_GATEWAY",
                    "message": f"Gateway error proxying to '{matched_target}': {str(e)}",
                }
            },
            headers={"x-request-id": request_id, "x-served-by": matched_target},
        )
