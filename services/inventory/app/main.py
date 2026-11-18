# app/main.py
from uuid import uuid4, UUID
from fastapi import FastAPI, Request, Header, HTTPException, status
from fastapi.responses import JSONResponse, PlainTextResponse
from libs.platform_contracts.metrics import metrics
from sqlalchemy import text
from libs.platform_contracts.errors import ApiError, api_error_handler
from libs.platform_contracts.logging import configure_logging
from .config import settings
from .db import async_session_factory
from .events import handle_internal_event
from .routes import router

app = FastAPI(title="KarobarOne INVENTORY Service")
configure_logging(level=getattr(settings, "LOG_LEVEL", "INFO"))

# Register canonical contract exception handler (RULES.md §6)
app.add_exception_handler(ApiError, api_error_handler)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    """Enforces X-Request-Id propagation on every request/response per RULES.md §6."""
    raw_req_id = request.headers.get("X-Request-Id")
    if raw_req_id:
        try:
            req_id = str(UUID(raw_req_id))
        except ValueError:
            req_id = str(uuid4())
    else:
        req_id = str(uuid4())

    request.state.request_id = req_id
    response = await call_next(request)
    response.headers["X-Request-Id"] = req_id
    return response


@app.get("/health/live")
async def health_live():
    """Liveness probe returning 200 OK (RULES.md §1 C2)."""
    return {"status": "alive"}


@app.get("/health/ready")
async def health_ready():
    """Readiness probe verifying DB connectivity (RULES.md §1 C2)."""
    try:
        async with async_session_factory() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready"}
    except Exception as e:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unready", "error": str(e)},
        )


@app.get("/metrics", response_class=PlainTextResponse)
async def get_metrics():
    """Internal Prometheus metrics endpoint (RULES.md §12)."""
    return PlainTextResponse(metrics.render_prometheus_text(), media_type="text/plain; version=0.0.4; charset=utf-8")


@app.post("/internal/events")
async def receive_internal_event(request: Request, x_service_key: str | None = Header(None, alias="X-Service-Key")):
    """Ingress endpoint for cross-service events per SECURITY_LAYER.md."""
    req_id = getattr(request.state, "request_id", str(uuid4()))
    if not x_service_key:
        return JSONResponse(
            status_code=401,
            content={
                "error": {
                    "code": "UNAUTHENTICATED",
                    "message": "Missing X-Service-Key",
                    "details": {},
                    "request_id": req_id,
                }
            },
        )
    caller = settings.get_caller_service(x_service_key)
    if not caller:
        return JSONResponse(
            status_code=403,
            content={
                "error": {
                    "code": "FORBIDDEN_CALLER",
                    "message": "Unregistered caller key",
                    "details": {},
                    "request_id": req_id,
                }
            },
        )

    body = await request.json()
    event_id = body.get("event_id")
    event_type = body.get("event_type")
    payload = body.get("payload", {})

    async with async_session_factory() as session:
        async with session.begin():
            await handle_internal_event(session, event_id, event_type, payload)

    return {"status": "accepted"}


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Formats HTTP exceptions into the standard KarobarOne error envelope (RULES.md §6)."""
    code = getattr(exc, "code", "UNEXPECTED_ERROR")
    req_id = getattr(request.state, "request_id", str(uuid4()))
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": code,
                "message": str(exc.detail),
                "details": {},
                "request_id": req_id,
            }
        },
    )


app.include_router(router, include_in_schema=False)
app.include_router(router, prefix="/api/v1")
