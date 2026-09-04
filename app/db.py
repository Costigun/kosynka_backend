from collections.abc import AsyncIterator

from fastapi import Request
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """Движок создаётся один раз при старте приложения, не на уровне модуля.

    Иначе импорт ``app.db`` требовал бы настроенного окружения, и юнит-тесты
    с линтерами тянули бы за собой базу.
    """
    return create_async_engine(
        settings.database_url,
        pool_size=settings.db_pool_size,
        # Без «сверх-лимитных» соединений: иначе реальное число подключений
        # к базе становится непредсказуемым и не поддаётся расчёту
        # «pool_size × число контейнеров».
        max_overflow=0,
        # База — соседний контейнер, и он переживает перезапуски: деплой
        # поднимает её заново, restart: unless-stopped — после падения.
        # Соединения в пуле при этом остаются мёртвыми, и без pre_ping первый
        # же запрос после такого перезапуска падал бы на одном из них.
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """Зависимость FastAPI: сессия на время обработки запроса."""
    session_factory: async_sessionmaker[AsyncSession] = request.app.state.session_factory
    async with session_factory() as session:
        yield session
