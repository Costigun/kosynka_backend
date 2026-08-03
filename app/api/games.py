from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_xp_config
from app.db import get_session
from app.models import Player
from app.schemas.games import (
    GameCreateRequest,
    GameDeletedResponse,
    GameListResponse,
    GameResponse,
    GameResultResponse,
    GameUpdateRequest,
)
from app.security import current_player
from app.services import game_service
from app.xp import XpConfig

router = APIRouter(tags=["games"])


@router.post("/games")
async def submit_game(
    payload: GameCreateRequest,
    player: Player = Depends(current_player),
    session: AsyncSession = Depends(get_session),
    config: XpConfig = Depends(get_xp_config),
) -> GameResultResponse:
    """Партия завершена победой: засчитать и начислить опыт.

    Код 200, а не 201, и на повторе тоже: повтор — это не создание, и
    переключение между 200 и 201 заставляло бы клиента ветвиться. Факт
    создания несёт поле ``already_counted``.
    """
    return await game_service.submit(session=session, player=player, data=payload, config=config)


@router.get("/games")
async def list_games(
    player: Player = Depends(current_player),
    session: AsyncSession = Depends(get_session),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> GameListResponse:
    """Партии игрока, новые сверху.

    Верхняя граница limit не вкусовщина: без неё один запрос вытянул бы всю
    историю игрока в память.
    """
    return await game_service.list(session=session, player=player, limit=limit, offset=offset)


@router.get("/games/{game_id}")
async def read_game(
    game_id: UUID,
    player: Player = Depends(current_player),
    session: AsyncSession = Depends(get_session),
) -> GameResponse:
    """Одна партия. 404, если её нет или она чужая."""
    return await game_service.detail(session=session, player=player, game_id=game_id)


@router.patch("/games/{game_id}")
async def update_game(
    game_id: UUID,
    payload: GameUpdateRequest,
    player: Player = Depends(current_player),
    session: AsyncSession = Depends(get_session),
    config: XpConfig = Depends(get_xp_config),
) -> GameResponse:
    """Изменить партию. Смена длительности пересчитывает опыт."""
    return await game_service.update(
        session=session, player=player, game_id=game_id, data=payload, config=config
    )


@router.delete("/games/{game_id}")
async def delete_game(
    game_id: UUID,
    player: Player = Depends(current_player),
    session: AsyncSession = Depends(get_session),
    config: XpConfig = Depends(get_xp_config),
) -> GameDeletedResponse:
    """Удалить партию и забрать начисленный за неё опыт."""
    return await game_service.delete(session=session, player=player, game_id=game_id, config=config)
