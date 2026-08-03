from typing import Any, Literal, overload
from uuid import UUID

from pydantic import JsonValue
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import raise_game_not_found
from app.models import Game

POPULATE = {"populate_existing": True}


class GameObject:
    """Доступ к данным партии.

    Каждый метод, кроме вставки, принимает ``player_id`` и фильтрует по нему.
    Это не перестраховка: без такого фильтра любой игрок читал бы и правил
    чужие партии, зная только идентификатор. Поэтому «чужая» и «несуществующая»
    здесь неразличимы — обе дают 404, и это намеренно.
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
    ) -> Game | None:
        """Вставить партию, если такой ещё не было.

        Возвращает новую партию либо None, если у игрока уже есть партия
        с этим ``client_game_id``.

        Здесь напрашивался бы ``get_or_create`` в духе Django, но именно он и
        был бы неверен: между «посмотреть» и «вставить» пролезает параллельный
        дубликат, и опыт удваивается. ON CONFLICT DO NOTHING отдаёт разрешение
        конфликта самой базе — это и есть корректная версия get_or_create.
        """
        result = await session.execute(
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
        game_id = result.scalar_one_or_none()
        if game_id is None:
            return None
        # Возвращаем через детальный геттер: запись и чтение не должны
        # расходиться в том, как выглядит партия.
        return await self.get_by_id(session=session, player_id=player_id, game_id=game_id)

    @overload
    async def get_by_id(
        self,
        session: AsyncSession,
        player_id: UUID,
        game_id: UUID,
        raise_exception: Literal[True] = True,
    ) -> Game: ...

    @overload
    async def get_by_id(
        self,
        session: AsyncSession,
        player_id: UUID,
        game_id: UUID,
        raise_exception: Literal[False],
    ) -> Game | None: ...

    async def get_by_id(
        self,
        session: AsyncSession,
        player_id: UUID,
        game_id: UUID,
        raise_exception: bool = True,
    ) -> Game | None:
        """Партия игрока по идентификатору."""
        games = await session.scalars(
            select(Game)
            .where(Game.id == game_id, Game.player_id == player_id)
            .execution_options(**POPULATE)
        )
        game = games.one_or_none()
        if raise_exception and game is None:
            raise_game_not_found()
        return game

    @overload
    async def get_by_client_game_id(
        self,
        session: AsyncSession,
        player_id: UUID,
        client_game_id: UUID,
        raise_exception: Literal[True] = True,
    ) -> Game: ...

    @overload
    async def get_by_client_game_id(
        self,
        session: AsyncSession,
        player_id: UUID,
        client_game_id: UUID,
        raise_exception: Literal[False],
    ) -> Game | None: ...

    async def get_by_client_game_id(
        self,
        session: AsyncSession,
        player_id: UUID,
        client_game_id: UUID,
        raise_exception: bool = True,
    ) -> Game | None:
        """Партия игрока по ключу идемпотентности.

        Нужна на повторе: пересчитывать опыт формулой нельзя — параметры
        кривой могли поменяться между первой попыткой и ретраем, и клиент
        получил бы другое число за ту же партию. Берём записанное.
        """
        games = await session.scalars(
            select(Game)
            .where(Game.player_id == player_id, Game.client_game_id == client_game_id)
            .execution_options(**POPULATE)
        )
        game = games.one_or_none()
        if raise_exception and game is None:
            raise_game_not_found()
        return game

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

    async def update(
        self,
        session: AsyncSession,
        player_id: UUID,
        game_id: UUID,
        values: dict[str, Any],
    ) -> Game:
        """Изменить поля партии и вернуть её обновлённой.

        ``values`` приходит уже отфильтрованным сервисом: сюда попадают только
        те поля, которые клиент прислал явно. Пустой словарь означал бы
        ``UPDATE`` без ``SET`` — синтаксическую ошибку, поэтому такой случай
        сервис отсекает до вызова.

        Параметра ``raise_exception`` здесь нет: изменять несуществующую партию
        всегда ошибка, выбирать нечего.
        """
        result = await session.execute(
            update(Game)
            .where(Game.id == game_id, Game.player_id == player_id)
            .values(**values)
            .returning(Game.id)
        )
        if result.scalar_one_or_none() is None:
            raise_game_not_found()
        # Результат отдаёт детальный геттер, а не RETURNING.
        return await self.get_by_id(session=session, player_id=player_id, game_id=game_id)

    async def delete(self, session: AsyncSession, player_id: UUID, game_id: UUID) -> Game:
        """Удалить партию и вернуть удалённую строку.

        Объект нужен вызывающему коду, чтобы откатить начисленный за партию
        опыт: иначе в сумме остался бы опыт за партию, которой больше нет.
        """
        result = await session.execute(
            delete(Game).where(Game.id == game_id, Game.player_id == player_id).returning(Game)
        )
        game = result.scalar_one_or_none()
        if game is None:
            raise_game_not_found()
        return game
