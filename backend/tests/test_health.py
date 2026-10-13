from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_db_ok():
    # Hits the real Postgres from DATABASE_URL: checking the DB is the point of this endpoint.
    response = TestClient(app, base_url="http://localhost").get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "db": "ok"}
