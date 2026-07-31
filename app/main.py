from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import meta
from app.config import get_settings
from app.db import create_engine, create_session_factory


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Движок живёт ровно столько же, сколько приложение.

    ``dispose`` в конце обязателен: без него соединения к managed-базе
    остаются висеть до таймаута на её стороне, а лимит подключений там
    небольшой.
    """
    settings = get_settings()
    engine = create_engine(settings)
    app.state.engine = engine
    app.state.session_factory = create_session_factory(engine)
    try:
        yield
    finally:
        await engine.dispose()


app = FastAPI(title="Kosynka", lifespan=lifespan)
app.include_router(meta.router)
