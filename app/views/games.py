from uuid import UUID

from app.models import Game
from app.schemas.games import (
    GameDeletedResponse,
    GameListResponse,
    GameResponse,
    GameResultResponse,
)
from app.xp import LevelInfo


class GameView:
    """Сборка ответов по партии."""

    def make_response_schema(self, game: Game) -> GameResponse:
        """Партия целиком. Канонический случай проекции строки в схему."""
        return GameResponse(
            game_id=game.id,
            client_game_id=game.client_game_id,
            duration_ms=game.duration_ms,
            xp_awarded=game.xp_awarded,
            xp_formula_version=game.xp_formula_version,
            deal_cards=game.deal_cards,
            replay=game.replay,
            created_at=game.created_at,
        )

    def make_list_response_schema(
        self, games: list[Game], total: int, limit: int, offset: int
    ) -> GameListResponse:
        return GameListResponse(
            items=[self.make_response_schema(game=game) for game in games],
            total=total,
            limit=limit,
            offset=offset,
        )

    def make_result_response_schema(
        self,
        game_id: UUID,
        client_game_id: UUID,
        xp_awarded: int,
        xp_total: int,
        level: LevelInfo,
        already_counted: bool,
    ) -> GameResultResponse:
        """Итог засчитанной партии.

        ORM-объект ``Game`` сюда сознательно не передаётся: ``xp_total``
        приходит не из него, а из ``UPDATE ... RETURNING`` по таблице игроков,
        и тащить модель ради двух полей значило бы делать лишний ``SELECT``
        после вставки.
        """
        return GameResultResponse(
            game_id=game_id,
            client_game_id=client_game_id,
            xp_awarded=xp_awarded,
            xp_total=xp_total,
            level=level.level,
            xp_into_level=level.xp_into_level,
            xp_to_next=level.xp_to_next,
            already_counted=already_counted,
        )

    def make_deleted_response_schema(
        self, game_id: UUID, xp_removed: int, xp_total: int, level: LevelInfo
    ) -> GameDeletedResponse:
        return GameDeletedResponse(
            game_id=game_id,
            xp_removed=xp_removed,
            xp_total=xp_total,
            level=level.level,
            xp_into_level=level.xp_into_level,
            xp_to_next=level.xp_to_next,
        )
