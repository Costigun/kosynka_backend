from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app import xp
from app.models import Player
from app.schemas.games import (
    GameCreateRequest,
    GameDeletedResponse,
    GameListResponse,
    GameResponse,
    GameResultResponse,
    GameUpdateRequest,
)
from app.single_object import game_object, player_object
from app.views import game_view
from app.views.games import GameView
from app.xp import XpConfig


class GameService:
    """Оркестрация по партии."""

    view: GameView = game_view

    async def create(
        self,
        session: AsyncSession,
        player: Player,
        data: GameCreateRequest,
        config: XpConfig,
    ) -> GameResultResponse:
        """Засчитать победу и начислить опыт.

        Порядок шагов переставлять нельзя. Сначала вставка партии: уникальный
        индекс отсекает повтор ДО того, как будет тронут опыт. Если начислить
        первым, а вставка потом упрётся в конфликт, опыт окажется удвоен и
        откатывать его придётся руками.

        Обе операции идут в одной транзакции: падение между ними откатывает всё.
        """
        game = await game_object.insert_if_absent(
            session=session,
            player_id=player.id,
            client_game_id=data.client_game_id,
            duration_ms=data.duration_ms,
            xp_awarded=xp.xp_for_win(duration_ms=data.duration_ms, config=config),
            xp_formula_version=xp.XP_FORMULA_VERSION,
            deal_cards=data.deal_cards,
            replay=data.replay,
        )

        if game is None:
            # Повтор: опыт не начисляем, отдаём то, что уже записано.
            already_counted = True
            game = await game_object.get_by_client_game_id(
                session=session, player_id=player.id, client_game_id=data.client_game_id
            )
            player = await player_object.get_by_id(session=session, player_id=player.id)
        else:
            already_counted = False
            player = await player_object.add_xp(
                session=session, player_id=player.id, amount=game.xp_awarded
            )

        await session.commit()

        return self.view.make_result_response_schema(
            game=game,
            player=player,
            level=xp.level_for_xp(player.xp_total, config),
            already_counted=already_counted,
        )

    async def detail(self, session: AsyncSession, player: Player, game_id: UUID) -> GameResponse:
        """Одна партия игрока."""
        game = await game_object.get_by_id(session=session, player_id=player.id, game_id=game_id)
        return self.view.make_response_schema(game=game)

    async def list(
        self, session: AsyncSession, player: Player, limit: int, offset: int
    ) -> GameListResponse:
        """Партии игрока, новые сверху."""
        games = await game_object.list_by_player(
            session=session, player_id=player.id, limit=limit, offset=offset
        )
        total = await game_object.count_by_player(session=session, player_id=player.id)

        return self.view.make_list_response_schema(
            games=games, total=total, limit=limit, offset=offset
        )

    async def update(
        self,
        session: AsyncSession,
        player: Player,
        game_id: UUID,
        data: GameUpdateRequest,
        config: XpConfig,
    ) -> GameResponse:
        """Изменить партию.

        Читаются только явно присланные поля: ``exclude_unset`` отличает
        «не прислали» от «прислали null», а для deal_cards и replay значение
        null осмысленно само по себе.

        Смена длительности влечёт пересчёт опыта. Разница переносится на
        суммарный опыт игрока атомарным сложением — иначе в сумме остался бы
        опыт за длительность, которой больше нет.
        """
        values: dict[str, Any] = data.model_dump(exclude_unset=True)
        if not values:
            # UPDATE без SET — синтаксическая ошибка. Пустой запрос считаем
            # запросом на чтение.
            return await self.detail(session=session, player=player, game_id=game_id)

        current = await game_object.get_by_id(session=session, player_id=player.id, game_id=game_id)

        xp_delta = 0
        if "duration_ms" in values and values["duration_ms"] != current.duration_ms:
            recomputed = xp.xp_for_win(duration_ms=values["duration_ms"], config=config)
            xp_delta = recomputed - current.xp_awarded
            values["xp_awarded"] = recomputed
            # Версия формулы обновляется вместе с опытом: партия обязана помнить,
            # по каким правилам посчитано то, что в ней лежит сейчас.
            values["xp_formula_version"] = xp.XP_FORMULA_VERSION

        game = await game_object.update(
            session=session, player_id=player.id, game_id=game_id, values=values
        )
        if xp_delta:
            await player_object.add_xp(session=session, player_id=player.id, amount=xp_delta)

        await session.commit()

        return self.view.make_response_schema(game=game)

    async def delete(
        self, session: AsyncSession, player: Player, game_id: UUID, config: XpConfig
    ) -> GameDeletedResponse:
        """Удалить партию и забрать начисленный за неё опыт.

        Откат опыта обязателен: иначе в сумме остался бы опыт за партию,
        которой больше нет, и уровень перестал бы соответствовать истории.
        """
        game = await game_object.delete(session=session, player_id=player.id, game_id=game_id)
        player = await player_object.add_xp(
            session=session, player_id=player.id, amount=-game.xp_awarded
        )
        await session.commit()

        return self.view.make_deleted_response_schema(
            game=game, player=player, level=xp.level_for_xp(player.xp_total, config)
        )
