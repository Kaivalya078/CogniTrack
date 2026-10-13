from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import engine, get_session
from app.main import app


@pytest.fixture
def session() -> Iterator[Session]:
    """A session whose work, commits included, is rolled back after the test."""
    with engine.connect() as connection:
        transaction = connection.begin()
        # Commits inside the test only release a savepoint; the outer transaction never commits.
        with Session(bind=connection, join_transaction_mode="create_savepoint") as session:
            yield session
        transaction.rollback()


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app.dependency_overrides[get_session] = lambda: session
    yield TestClient(app, base_url="http://localhost")
    app.dependency_overrides.clear()
