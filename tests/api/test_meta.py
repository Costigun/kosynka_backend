from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import create_async_engine

from app.db import create_session_factory
from app.main import app as fastapi_app

# Порт 1 не слушает никто — подключение отваливается сразу, тест не ждёт таймаут.
DEAD_DSN = "postgresql+asyncpg://nobody:nobody@127.0.0.1:1/nothing"


@pytest.fixture
def база_недоступна() -> Iterator[None]:
    """Подменяет фабрику сессий на смотрящую в никуда."""
    original = fastapi_app.state.session_factory
    fastapi_app.state.session_factory = create_session_factory(create_async_engine(DEAD_DSN))
    try:
        yield
    finally:
        fastapi_app.state.session_factory = original


def test_healthz_отвечает(client: TestClient) -> None:
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_подтверждает_что_база_отвечает(client: TestClient) -> None:
    response = client.get("/readyz")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readyz_отдаёт_503_когда_база_недоступна(client: TestClient, база_недоступна: None) -> None:
    """Готовность должна падать честно: 503 уводит контейнер из балансировки,
    но не перезапускает его."""
    response = client.get("/readyz")

    assert response.status_code == 503


def test_healthz_не_зависит_от_базы(client: TestClient, база_недоступна: None) -> None:
    """Ключевое свойство /healthz, ради которого он отделён от /readyz.

    Если бы liveness ходил в базу, моргнувший Postgres перезапускал бы все
    контейнеры разом — то есть превращал бы недоступность базы в аварию.
    """
    response = client.get("/healthz")

    assert response.status_code == 200
