from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app


@pytest.fixture
def client() -> Iterator[TestClient]:
    """TestClient обязательно как контекстный менеджер.

    Без ``with`` не выполняется lifespan, а значит не появляются
    ``app.state.engine`` и ``app.state.session_factory`` — и любая ручка,
    которой нужна база, падает с AttributeError вместо осмысленной ошибки.

    Требует поднятого Postgres и KOSYNKA_DATABASE_URL в окружении:
    ``docker compose up -d db``.
    """
    with TestClient(fastapi_app) as client:
        yield client
