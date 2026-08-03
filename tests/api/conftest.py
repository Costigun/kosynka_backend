import asyncio
from collections.abc import Callable, Iterator
from typing import Any
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.config import get_settings
from app.main import app as fastapi_app

# 5 минут — эталонная партия, ровно 100 опыта при дефолтной кривой.
REFERENCE_DURATION_MS = 300_000


@pytest.fixture(autouse=True)
def clean_database() -> Iterator[None]:
    """Каждый тест начинает с пустых таблиц.

    Движок здесь свой и одноразовый, а не ``app.state.engine``: пул рабочего
    движка привязан к циклу событий, который TestClient крутит в отдельном
    потоке, и обращение к нему снаружи даёт MissingGreenlet.

    Чистится ДО теста, а не после: упавший тест оставляет данные для разбора,
    а следующий всё равно стартует на пустом месте.
    """

    async def truncate() -> None:
        engine = create_async_engine(get_settings().database_url)
        try:
            async with engine.begin() as connection:
                # CASCADE сносит games вслед за players одним запросом.
                await connection.execute(text("TRUNCATE TABLE players, games CASCADE"))
        finally:
            await engine.dispose()

    asyncio.run(truncate())
    yield


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


@pytest.fixture
def registered_player(client: TestClient) -> dict[str, Any]:
    """Свежий игрок."""
    response = client.post("/v1/players")
    assert response.status_code == 201, response.text
    return dict(response.json())


@pytest.fixture
def auth_headers(registered_player: dict[str, Any]) -> dict[str, str]:
    """Заголовок авторизации основного игрока."""
    return {"Authorization": f"Bearer {registered_player['token']}"}


@pytest.fixture
def other_player(client: TestClient) -> dict[str, Any]:
    """Второй игрок — для проверок, что чужое недоступно."""
    response = client.post("/v1/players")
    assert response.status_code == 201, response.text
    return dict(response.json())


@pytest.fixture
def other_auth_headers(other_player: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {other_player['token']}"}


@pytest.fixture
def make_game_payload() -> Callable[..., dict[str, Any]]:
    """Фабрика тела запроса на создание партии."""

    def factory(**overrides: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "client_game_id": str(uuid4()),
            "duration_ms": REFERENCE_DURATION_MS,
        }
        payload.update(overrides)
        return payload

    return factory


@pytest.fixture
def existing_game(
    client: TestClient,
    auth_headers: dict[str, str],
    make_game_payload: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Уже засчитанная партия основного игрока.

    Нужна тестам детального чтения, изменения и удаления: все три работают
    по game_id, который выдаётся только при создании.
    """
    payload = make_game_payload(deal_cards=[1, 2, 3], replay={"moves": 4})
    response = client.post("/v1/games", json=payload, headers=auth_headers)
    assert response.status_code == 200, response.text
    return dict(response.json())


@pytest.fixture
def existing_games(
    client: TestClient,
    auth_headers: dict[str, str],
    make_game_payload: Callable[..., dict[str, Any]],
) -> list[dict[str, Any]]:
    """Три партии основного игрока — для проверок списка и постраничности."""
    created = []
    for duration_ms in (60_000, REFERENCE_DURATION_MS, 600_000):
        response = client.post(
            "/v1/games", json=make_game_payload(duration_ms=duration_ms), headers=auth_headers
        )
        assert response.status_code == 200, response.text
        created.append(dict(response.json()))
    return created


@pytest.fixture
def other_player_game(
    client: TestClient,
    other_auth_headers: dict[str, str],
    make_game_payload: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Партия второго игрока — чтобы проверить, что чужое не читается и не правится."""
    response = client.post("/v1/games", json=make_game_payload(), headers=other_auth_headers)
    assert response.status_code == 200, response.text
    return dict(response.json())
