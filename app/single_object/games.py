from typing import Any
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Game


class GameObject:
    """Доступ к данным партии.

    Каждый метод, кроме вставки, принимает ``player_id`` и фильтрует по нему.
    Это не перестраховка: без такого фильтра любой игрок читал бы и правил
    чужие партии, зная только идентификатор.
    """

    async def insert_if_absent(
        self,
        session: AsyncSession,
        player_id: UUID,
        client_game_id: UUID,
        duration_ms: int,
        xp_awarded: int,
        xp_formula_version: int,
        deal_cards: JsonValue,
        replay: JsonValue,
    ) -> UUID | None:
        """Вставить партию, если такой ещё не было.

        Возвращает id новой строки либо None, если партия с этим
        ``client_game_id`` у игрока уже есть.

        Здесь напрашивался бы ``get_or_create`` в духе Django, но именно он и
        был бы неверен: между «посмотреть» и «вставить» пролезает параллельный
        дубликат, и опыт удваивается. ON CONFLICT DO NOTHING отдаёт разрешение
        конфликта самой базе — это и есть корректная версия get_or_create.
        """
        return await session.scalar(
            pg_insert(Game)
            .values(
                player_id=player_id,
                client_game_id=client_game_id,
                duration_ms=duration_ms,
                xp_awarded=xp_awarded,
                xp_formula_version=xp_formula_version,
                deal_cards=deal_cards,
                replay=replay,
            )
            .on_conflict_do_nothing(index_elements=["player_id", "client_game_id"])
            .returning(Game.id)
        )

    async def get_by_id(self, session: AsyncSession, player_id: UUID, game_id: UUID) -> Game | None:
        """Партия игрока по идентификатору, либо None."""
        games = await session.scalars(
            select(Game).where(Game.id == game_id, Game.player_id == player_id)
        )
        return games.one_or_none()

    async def list_by_player(
        self, session: AsyncSession, player_id: UUID, limit: int, offset: int
    ) -> list[Game]:
        """Партии игрока, новые сверху.

        Сортировка по created_at с добором по id: без второго ключа порядок
        строк с одинаковым временем не определён, и одна и та же партия могла
        бы попасть на две соседние страницы или не попасть ни на одну.
        """
        games = await session.scalars(
            select(Game)
            .where(Game.player_id == player_id)
            .order_by(Game.created_at.desc(), Game.id.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(games.all())

    async def count_by_player(self, session: AsyncSession, player_id: UUID) -> int:
        """Сколько всего партий у игрока."""
        result = await session.execute(
            select(func.count()).select_from(Game).where(Game.player_id == player_id)
        )
        return result.scalar_one()

    async def get_id_and_awarded_xp(
        self, session: AsyncSession, player_id: UUID, client_game_id: UUID
    ) -> tuple[UUID, int]:
        """Идентификатор и начисленный опыт уже засчитанной партии.

        Нужен на повторе: пересчитывать формулой нельзя — параметры кривой
        могли поменяться между первой попыткой и ретраем, и клиент получил бы
        другое число за ту же партию.
        """
        result = await session.execute(
            select(Game.id, Game.xp_awarded).where(
                Game.player_id == player_id,
                Game.client_game_id == client_game_id,
            )
        )
        row = result.one()
        return row.id, row.xp_awarded

    async def update(
        self,
        session: AsyncSession,
        player_id: UUID,
        game_id: UUID,
        values: dict[str, Any],
    ) -> Game | None:
        """Изменить поля партии и вернуть её обновлённой.

        ``values`` приходит уже отфильтрованным сервисом: сюда попадают только
        те поля, которые клиент прислал явно. Пустой словарь означал бы
        ``UPDATE`` без ``SET`` — синтаксическую ошибку, поэтому такой случай
        сервис отсекает до вызова.
        """
        result = await session.execute(
            update(Game)
            .where(Game.id == game_id, Game.player_id == player_id)
            .values(**values)
            .returning(Game)
        )
        return result.scalar_one_or_none()

    async def delete(self, session: AsyncSession, player_id: UUID, game_id: UUID) -> int | None:
        """Удалить партию и вернуть, сколько опыта за неё было начислено.

        Возвращает None, если партии нет или она чужая. Значение нужно, чтобы
        сервис откатил этот опыт у игрока: иначе в сумме остался бы опыт за
        партию, которой больше нет.
        """
        result = await session.execute(
            delete(Game)
            .where(Game.id == game_id, Game.player_id == player_id)
            .returning(Game.xp_awarded)
        )
        return result.scalar_one_or_none()
