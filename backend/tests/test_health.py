from fastapi.testclient import TestClient

from app.main import app


def test_health_reports_db_postgis_and_config():
    body = TestClient(app).get("/health").json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert body["postgis"].startswith("3.")
    assert body["config_version"]
