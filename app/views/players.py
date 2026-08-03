from uuid import UUID

from app.models import Player
from app.schemas.players import (
    PlayerDeletedResponse,
    PlayerRegisteredResponse,
    PlayerStateResponse,
)
from app.xp import LevelInfo


class PlayerView:
    """Сборка ответов по игроку.

    Слой видов и только он превращает доменные объекты в схемы ответа.
    Поля перечисляются руками, а не через ``from_attributes``: у ``Player``
    есть колонки ``token_hash`` и ``device_id``, и автомаппинг по совпадению
    имён — ровно тот механизм, которым секрет однажды уезжает в ответ. Забыть
    поле здесь заметно сразу, вынести лишнее — невозможно.
    """

    def make_registered_response_schema(
        self, player: Player, token: str, level: LevelInfo, restored: bool
    ) -> PlayerRegisteredResponse:
        # token приходит отдельным аргументом, а не из модели, и это намеренно:
        # в базе его нет и быть не может, он живёт только в памяти обработчика.
        return PlayerRegisteredResponse(
            player_id=player.id,
            token=token,
            xp_total=player.xp_total,
            level=level.level,
            restored=restored,
        )

    def make_state_response_schema(self, player: Player, level: LevelInfo) -> PlayerStateResponse:
        return PlayerStateResponse(
            player_id=player.id,
            xp_total=player.xp_total,
            level=level.level,
            xp_into_level=level.xp_into_level,
            xp_to_next=level.xp_to_next,
        )

    def make_updated_response_schema(
        self, player_id: UUID, xp_total: int, level: LevelInfo
    ) -> PlayerStateResponse:
        """Состояние после изменения.

        Модель сюда не передаётся: ``xp_total`` приходит из ``UPDATE ...
        RETURNING``, и объект игрока в сессии уже устарел.
        """
        return PlayerStateResponse(
            player_id=player_id,
            xp_total=xp_total,
            level=level.level,
            xp_into_level=level.xp_into_level,
            xp_to_next=level.xp_to_next,
        )

    def make_deleted_response_schema(
        self, player_id: UUID, games_deleted: int
    ) -> PlayerDeletedResponse:
        return PlayerDeletedResponse(player_id=player_id, games_deleted=games_deleted)
