from app.models import Game, Player
from app.schemas.games import (
    GameDeletedResponse,
    GameListResponse,
    GameResponse,
    GameResultResponse,
)
from app.xp import LevelInfo


class GameView:
    """Сборка ответов по партии.

    Все методы принимают доменные объекты — ``Game`` и, где ответ включает
    состояние игрока, ``Player``.
    """

    def make_response_schema(self, game: Game) -> GameResponse:
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
        self, game: Game, player: Player, level: LevelInfo, already_counted: bool
    ) -> GameResultResponse:
        """Итог засчитанной партии: сама партия плюс состояние игрока после неё."""
        return GameResultResponse(
            game_id=game.id,
            client_game_id=game.client_game_id,
            xp_awarded=game.xp_awarded,
            xp_total=player.xp_total,
            level=level.level,
            xp_into_level=level.xp_into_level,
            xp_to_next=level.xp_to_next,
            already_counted=already_counted,
        )

    def make_deleted_response_schema(
        self, game: Game, player: Player, level: LevelInfo
    ) -> GameDeletedResponse:
        """Подтверждение удаления: что удалили и каким стал игрок."""
        return GameDeletedResponse(
            game_id=game.id,
            xp_removed=game.xp_awarded,
            xp_total=player.xp_total,
            level=level.level,
            xp_into_level=level.xp_into_level,
            xp_to_next=level.xp_to_next,
        )
