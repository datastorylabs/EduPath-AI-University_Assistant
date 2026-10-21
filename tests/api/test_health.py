from __future__ import annotations

from sqlalchemy.exc import OperationalError

from backend.app.database import get_db


def test_liveness_does_not_depend_on_database(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_confirms_database_connection(client):
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "database": "ok"}


def test_readiness_returns_safe_503_if_database_fails(client):
    class BrokenSession:
        def execute(self, statement):
            raise OperationalError("SELECT 1", {}, RuntimeError("private connection detail"))

        def close(self):
            pass

    def broken_db():
        yield BrokenSession()

    from backend.app.main import app

    app.dependency_overrides[get_db] = broken_db
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"detail": "Service temporarily unavailable"}
    assert "private connection detail" not in response.text
