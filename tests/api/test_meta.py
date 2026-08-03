from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import create_session_factory
from app.main import app as fastapi_app

# Порт 1 не слушает никто — подключение отваливается сразу, тест не ждёт таймаут.
DEAD_DSN = "postgresql+asyncpg://nobody:nobody@127.0.0.1:1/nothing"


@pytest.fixture
def database_unavailable() -> Iterator[None]:
    """Подменяет фабрику сессий на смотрящую в никуда."""
    original = fastapi_app.state.session_factory
    fastapi_app.state.session_factory = create_session_factory(create_async_engine(DEAD_DSN))
    try:
        yield
    finally:
        fastapi_app.state.session_factory = original


class TestHealthz:
    """GET /healthz — живость процесса."""

    def test_responds_ok(self, client: TestClient) -> None:
        response = client.get("/healthz")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_does_not_depend_on_database(
        self, client: TestClient, database_unavailable: None
    ) -> None:
        """Ключевое свойство, ради которого пробник отделён от /readyz.

        Если бы liveness ходил в базу, моргнувший Postgres перезапускал бы все
        контейнеры разом — то есть превращал бы недоступность базы в аварию.
        """
        assert client.get("/healthz").status_code == 200


class TestReadyz:
    """GET /readyz — готовность обслуживать запросы."""

    def test_confirms_database_responds(self, client: TestClient) -> None:
        response = client.get("/readyz")

        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    def test_returns_503_when_database_unavailable(
        self, client: TestClient, database_unavailable: None
    ) -> None:
        """Готовность должна падать честно: 503 уводит контейнер из
        балансировки, но не перезапускает его."""
        assert client.get("/readyz").status_code == 503
