from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

from backend.app.database import create_database_engine, get_db
from backend.app.main import app
from backend.app.models import Base
from backend.app.services.rate_limit import reset_memory_limiter_for_tests


@pytest.fixture()
def client() -> TestClient:
    engine = create_database_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)

    def override_get_db():
        with test_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    app.state.testing_session_factory = test_session
    app.state.testing_engine = engine
    reset_memory_limiter_for_tests()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
    del app.state.testing_session_factory
    del app.state.testing_engine
    reset_memory_limiter_for_tests()
    engine.dispose()
