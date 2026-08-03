from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_xp_config
from app.db import get_session
from app.models import Player
from app.schemas.players import (
    PlayerDeletedResponse,
    PlayerRegisteredResponse,
    PlayerRegisterRequest,
    PlayerStateResponse,
    PlayerUpdateRequest,
)
from app.security import current_player
from app.services import player_service
from app.xp import XpConfig

# Путь /me, а не /{player_id}: администратора в проекте нет, игрок может
# трогать только себя, и идентификатор в пути был бы декорацией — сервер всё
# равно взял бы его из токена.
router = APIRouter(tags=["players"])


@router.post(
    "/players",
    response_model=PlayerRegisteredResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register_player(
    payload: PlayerRegisterRequest | None = None,
    session: AsyncSession = Depends(get_session),
    config: XpConfig = Depends(get_xp_config),
) -> PlayerRegisteredResponse:
    """Регистрация устройства. Ни email, ни пароля — только опциональный device_id."""
    return await player_service.register(
        session=session, config=config, device_id=payload.device_id if payload else None
    )


@router.get("/players/me", response_model=PlayerStateResponse)
async def read_current_player(
    player: Player = Depends(current_player),
    config: XpConfig = Depends(get_xp_config),
) -> PlayerStateResponse:
    """Текущий уровень и опыт предъявителя токена."""
    return await player_service.state(player=player, config=config)


@router.patch("/players/me", response_model=PlayerStateResponse)
async def update_current_player(
    payload: PlayerUpdateRequest,
    player: Player = Depends(current_player),
    session: AsyncSession = Depends(get_session),
    config: XpConfig = Depends(get_xp_config),
) -> PlayerStateResponse:
    """Изменить игрока. Изменяемое поле ровно одно — xp_total."""
    return await player_service.update(session=session, player=player, data=payload, config=config)


@router.delete("/players/me", response_model=PlayerDeletedResponse)
async def delete_current_player(
    player: Player = Depends(current_player),
    session: AsyncSession = Depends(get_session),
) -> PlayerDeletedResponse:
    """Удалить игрока и все его партии. Восстановления нет."""
    return await player_service.delete(session=session, player=player)
