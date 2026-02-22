"""
Unit tests for ZeroWall Demo Target App.
Tests all legitimate endpoint behaviors to ensure:
1. Normal traffic continues working post-mutation
2. The verifier agent can run these to validate candidates
"""
import pytest
from fastapi.testclient import TestClient
from main import app

client = TestClient(app)


# ─── Health + Version ────────────────────────────────────────────────────────

class TestHealthEndpoints:
    def test_health_returns_200(self):
        response = client.get("/health")
        assert response.status_code == 200

    def test_health_has_status_ok(self):
        response = client.get("/health")
        data = response.json()
        assert data["status"] == "ok"

    def test_health_has_version(self):
        response = client.get("/health")
        data = response.json()
        assert "version" in data
        assert data["version"] is not None

    def test_health_has_deploy_hash(self):
        response = client.get("/health")
        data = response.json()
        assert "deploy_hash" in data

    def test_health_has_uptime(self):
        response = client.get("/health")
        data = response.json()
        assert "uptime_seconds" in data
        assert data["uptime_seconds"] >= 0

    def test_version_endpoint(self):
        response = client.get("/version")
        assert response.status_code == 200
        data = response.json()
        assert "app_version" in data
        assert "deploy_hash" in data
        assert data["zerowall_managed"] is True


# ─── Public Info ─────────────────────────────────────────────────────────────

class TestPublicEndpoint:
    def test_public_returns_200(self):
        response = client.get("/public")
        assert response.status_code == 200

    def test_public_has_message(self):
        response = client.get("/public")
        data = response.json()
        assert "message" in data

    def test_public_has_content(self):
        response = client.get("/public")
        data = response.json()
        assert "content" in data


# ─── Items ───────────────────────────────────────────────────────────────────

class TestItemsEndpoint:
    def test_get_item_1(self):
        response = client.get("/items/1")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Gadget Alpha"
        assert data["price"] == pytest.approx(29.99)

    def test_get_item_2(self):
        response = client.get("/items/2")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Widget Beta"

    def test_get_item_3(self):
        response = client.get("/items/3")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Doohickey Gamma"

    def test_get_item_not_found(self):
        response = client.get("/items/999")
        assert response.status_code == 404

    def test_get_item_with_query(self):
        response = client.get("/items/1?q=test")
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "test"


# ─── Data Endpoint (simulated path traversal surface) ────────────────────────

class TestDataEndpoint:
    def test_known_file_returns_content(self):
        response = client.get("/data?file=public.txt")
        assert response.status_code == 200
        data = response.json()
        assert data["file"] == "public.txt"
        assert "content" in data

    def test_known_file_readme(self):
        response = client.get("/data?file=readme.txt")
        assert response.status_code == 200

    def test_unknown_file_returns_response(self):
        """V1 behavior: unknown file returns a response (not error) — simulates info leak."""
        response = client.get("/data?file=unknown.txt")
        assert response.status_code == 200
        data = response.json()
        assert data["file"] == "unknown.txt"

    def test_data_missing_param_returns_422(self):
        response = client.get("/data")
        assert response.status_code == 422


# ─── Run Endpoint (simulated command injection surface) ──────────────────────

class TestRunEndpoint:
    def test_known_cmd_hello(self):
        response = client.post("/run", json={"cmd": "hello"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert "Hello" in data["output"]

    def test_known_cmd_date(self):
        response = client.post("/run", json={"cmd": "date"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_known_cmd_uptime(self):
        response = client.post("/run", json={"cmd": "uptime"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"

    def test_known_cmd_whoami(self):
        response = client.post("/run", json={"cmd": "whoami"})
        assert response.status_code == 200
        data = response.json()
        assert data["output"] == "demouser"

    def test_unknown_cmd_returns_response(self):
        """V1 behavior: unknown cmd returns a descriptive response — simulates injection probe surface."""
        response = client.post("/run", json={"cmd": "rm -rf /"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "unknown"

    def test_run_missing_body_field(self):
        response = client.post("/run", json={})
        assert response.status_code == 200
        data = response.json()
        assert data["cmd"] == ""


# ─── Search Endpoint (simulated SQLi surface) ────────────────────────────────

class TestSearchEndpoint:
    def test_search_returns_results(self):
        response = client.get("/search?q=gadget")
        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert isinstance(data["results"], list)

    def test_search_echoes_query(self):
        """V1 behavior: raw query echoed back — simulates reflection vulnerability."""
        response = client.get("/search?q=test-query")
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "test-query"

    def test_search_missing_param(self):
        response = client.get("/search")
        assert response.status_code == 422

    def test_search_empty_param_rejected(self):
        response = client.get("/search?q=")
        assert response.status_code == 422
