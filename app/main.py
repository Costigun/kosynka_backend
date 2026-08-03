from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import games, meta, players
from app.config import get_settings, get_xp_config
from app.db import create_engine, create_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Движок живёт ровно столько же, сколько приложение.

    ``dispose`` в конце обязателен: без него соединения к managed-базе
    остаются висеть до таймаута на её стороне, а лимит подключений там
    небольшой.
    """
    settings = get_settings()

    # Кривая опыта собирается на старте, а не при первом запросе: невозможные
    # параметры в переменных окружения должны ронять контейнер сразу,
    # а не превращаться в 500 у первого игрока.
    get_xp_config()

    engine = create_engine(settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Kosynka", lifespan=lifespan)

# Пробники живут в корне: они системные, к версии API отношения не имеют.
app.include_router(meta.router)

# Прикладные ручки — под версией. Префикс навешивается здесь, а не в роутерах:
# так все пути видны в одном месте.
app.include_router(players.router, prefix="/v1")
app.include_router(games.router, prefix="/v1")
