# tests/test_gateway.py
"""
Gateway Reverse Proxy Tests (SERVICES.md §9, ROADMAP Phase 11).
Tests:
- Health check endpoints (/health/live, /health/ready)
- Prefix routing to all 8 microservices
- Monolith fallback for unextracted routes
- X-Request-Id generation and propagation
- Instant rollback rehearsal (flipping route line back to monolith)
- Upstream error handling (503 UPSTREAM_UNAVAILABLE)
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
import httpx

from app.main import app, load_route_table, resolve_upstream_base_url
from app.config import settings


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_gateway_health_live(client):
    resp = client.get("/health/live")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "gateway"


def test_gateway_health_ready(client):
    resp = client.get("/health/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["routes_count"] >= 8


@pytest.mark.asyncio
async def test_gateway_routes_to_extracted_microservice(client):
    """Verifies that an incoming request to /api/v1/items routes to catalog service."""
    mock_resp = httpx.Response(
        status_code=200,
        content=b'{"items": []}',
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "http://catalog-api:8000/api/v1/items"),
    )

    with patch("app.main.http_client.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        resp = client.get("/api/v1/items", headers={"x-request-id": "req-12345"})

        assert resp.status_code == 200
        assert resp.headers["x-served-by"] == "catalog"
        assert resp.headers["x-request-id"] == "req-12345"
        assert resp.json() == {"items": []}

        mock_req.assert_called_once()
        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["method"] == "GET"
        assert "/api/v1/items" in call_kwargs["url"]


@pytest.mark.asyncio
async def test_gateway_generates_and_propagates_request_id(client):
    """If client omits X-Request-Id, gateway generates UUID and forwards it upstream."""
    mock_resp = httpx.Response(
        status_code=200,
        content=b'{"authenticated": true}',
        headers={"content-type": "application/json"},
        request=httpx.Request("POST", "http://iam-api:8000/api/v1/auth/login"),
    )

    with patch("app.main.http_client.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        resp = client.post("/api/v1/auth/login", json={"email": "user@test.com"})

        assert resp.status_code == 200
        assert "x-request-id" in resp.headers
        generated_id = resp.headers["x-request-id"]
        assert len(generated_id) > 10

        call_kwargs = mock_req.call_args[1]
        assert call_kwargs["headers"]["x-request-id"] == generated_id


@pytest.mark.asyncio
async def test_gateway_monolith_fallback_for_unextracted_paths(client):
    """Unextracted monolith paths fall back to UPSTREAM_MONOLITH_URL."""
    mock_resp = httpx.Response(
        status_code=200,
        content=b'{"legacy_feature": true}',
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "http://monolith:8000/api/v1/legacy/reports"),
    )

    with patch("app.main.http_client.request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = mock_resp

        resp = client.get("/api/v1/legacy/reports")

        assert resp.status_code == 200
        assert resp.headers["x-served-by"] == "monolith"


@pytest.mark.asyncio
async def test_gateway_instant_rollback_rehearsal(client):
    """
    Rollback rehearsal (DEPLOY.md §4.4, Phase 11 Exit Gate):
    Flipping a route target from 'inventory' to 'monolith' immediately routes
    traffic back to the monolith without downtime.
    """
    mock_resp_monolith = httpx.Response(
        status_code=200,
        content=b'{"source": "monolith_fallback"}',
        headers={"content-type": "application/json"},
        request=httpx.Request("GET", "http://monolith:8000/api/v1/inventory/availability"),
    )

    from app import main as gateway_main

    original_routes = list(gateway_main.route_table)
    try:
        updated_routes = [
            {"prefix": r["prefix"], "target": "monolith" if r.get("target") == "inventory" else r["target"]}
            for r in original_routes
        ]
        gateway_main.route_table = updated_routes

        with patch("app.main.http_client.request", new_callable=AsyncMock) as mock_req:
            mock_req.return_value = mock_resp_monolith

            resp = client.get("/api/v1/inventory/availability")

            assert resp.status_code == 200
            assert resp.headers["x-served-by"] == "monolith"
            assert resp.json()["source"] == "monolith_fallback"
    finally:
        gateway_main.route_table = original_routes


@pytest.mark.asyncio
async def test_gateway_upstream_unavailable_returns_503(client):
    """When an upstream microservice is down, gateway returns controlled 503 envelope."""
    with patch("app.main.http_client.request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = httpx.ConnectError("Connection refused")

        resp = client.get("/api/v1/tenants/current")

        assert resp.status_code == 503
        data = resp.json()
        assert data["error"]["code"] == "UPSTREAM_UNAVAILABLE"
        assert "tenant" in data["error"]["message"]

