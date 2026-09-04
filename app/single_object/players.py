from typing import Literal, overload
from uuid import UUID

from sqlalchemy import BigInteger, cast, delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import raise_player_not_found, raise_unauthorized
from app.models import MAX_XP_TOTAL, Game, Player

# Чтение обновляет объект значениями из базы, а не отдаёт его из кеша сессии.
# Без этого identity map вернул бы прежний объект с устаревшим xp_total —
# тот самый, что прочитан при аутентификации.
POPULATE = {"populate_existing": True}


class PlayerObject:
    """Доступ к данным игрока.

    Весь SQL по таблице ``players`` живёт здесь. Методы получения и изменения
    работают с объектом ``Player`` и его же возвращают: собирать состояние
    из скаляров вызывающему коду не приходится.
    """

    async def create(
        self, session: AsyncSession, token_hash: str, device_id: str | None = None
    ) -> Player:
        """Завести нового игрока. Опыт стартует с нуля по умолчанию колонки."""
        player = Player(token_hash=token_hash, device_id=device_id)
        session.add(player)
        # flush, а не commit: границу транзакции держит вызывающий сервис.
        await session.flush()
        # Возвращаем через детальный геттер: после flush серверные умолчания
        # (created_at) в объекте ещё не заполнены, и обращение к ним в async
        # дало бы MissingGreenlet. Заодно запись и чтение не расходятся.
        return await self.get_by_id(session=session, player_id=player.id)

    @overload
    async def get_by_id(
        self, session: AsyncSession, player_id: UUID, raise_exception: Literal[True] = True
    ) -> Player: ...

    @overload
    async def get_by_id(
        self, session: AsyncSession, player_id: UUID, raise_exception: Literal[False]
    ) -> Player | None: ...

    async def get_by_id(
        self, session: AsyncSession, player_id: UUID, raise_exception: bool = True
    ) -> Player | None:
        """Игрок по идентификатору, прочитанный заново из базы.

        Именно заново: между аутентификацией и этим моментом соседний запрос
        мог начислить опыт, и объект в сессии успел устареть.
        """
        players = await session.scalars(
            select(Player).where(Player.id == player_id).execution_options(**POPULATE)
        )
        player = players.one_or_none()
        if raise_exception and player is None:
            raise_player_not_found()
        return player

    @overload
    async def get_by_token_hash(
        self, session: AsyncSession, token_hash: str, raise_exception: Literal[True] = True
    ) -> Player: ...

    @overload
    async def get_by_token_hash(
        self, session: AsyncSession, token_hash: str, raise_exception: Literal[False]
    ) -> Player | None: ...

    async def get_by_token_hash(
        self, session: AsyncSession, token_hash: str, raise_exception: bool = True
    ) -> Player | None:
        """Игрок по хешу токена.

        Не найден — это 401, а не 404: предъявленный токен неизвестен,
        и сообщать, существует ли такой, незачем.

        Горячий путь: выполняется на каждом авторизованном запросе, идёт по
        уникальному индексу uq_players_token_hash.
        """
        players = await session.scalars(select(Player).where(Player.token_hash == token_hash))
        player = players.one_or_none()
        if raise_exception and player is None:
            raise_unauthorized()
        return player

    @overload
    async def get_by_device_id(
        self, session: AsyncSession, device_id: str, raise_exception: Literal[True] = True
    ) -> Player: ...

    @overload
    async def get_by_device_id(
        self, session: AsyncSession, device_id: str, raise_exception: Literal[False]
    ) -> Player | None: ...

    async def get_by_device_id(
        self, session: AsyncSession, device_id: str, raise_exception: bool = True
    ) -> Player | None:
        """Игрок по идентификатору устройства.

        Ключ восстановления после переустановки: токен потерян, а device_id —
        нет, и запись со всем прогрессом находится по нему.

        Регистрация зовёт этот метод с ``raise_exception=False``: для неё
        «устройства ещё нет» — нормальный путь, а не ошибка.
        """
        players = await session.scalars(select(Player).where(Player.device_id == device_id))
        player = players.one_or_none()
        if raise_exception and player is None:
            raise_player_not_found()
        return player

    async def add_xp(self, session: AsyncSession, player_id: UUID, amount: int) -> Player:
        """Атомарно изменить опыт на ``amount`` и вернуть обновлённого игрока.

        Прибавление делает сама база выражением ``xp_total + amount``:
        никакого read-modify-write, никаких гонок и никакого SELECT FOR UPDATE.
        Принятое решение проекта, не оптимизация.

        ``amount`` может быть отрицательным — так откатывается опыт при
        удалении партии и при уменьшении её длительности.

        Сумма зажата с обеих сторон, и обе отсечки не косметика — каждая
        закрывает свой способ загнать игрока в вечный 500:

        * снизу: игрок мог выставить себе меньший опыт через PATCH, а потом
          удалить партию. Отрицательный xp_total роняет ValueError в
          level_for_xp, то есть ломает каждую ручку, считающую уровень;
        * сверху: PATCH принимает ровно MAX_XP_TOTAL, и следующая же победа
          добавляла бы к потолку колонки — asyncpg отвечает на это
          NumericValueOutOfRangeError, и приём партий залипает намертво.

        CAST в BIGINT обязателен и снять его нельзя: LEAST отсекает результат,
        но сложение ``integer + integer`` переполняется РАНЬШЕ, чем до отсечки
        доходит дело, — база считает выражение, а не читает его слева направо.
        В BIGINT та же сумма помещается с запасом, а обратно в INTEGER её
        приводит уже присваивание, которому LEAST гарантировал влезающее число.

        Обе отсечки живут внутри того же атомарного выражения: ни чтения,
        ни блокировки, ни второго запроса.
        """
        await session.execute(
            update(Player)
            .where(Player.id == player_id)
            .values(
                xp_total=func.least(
                    MAX_XP_TOTAL,
                    func.greatest(0, Player.xp_total + cast(amount, BigInteger)),
                )
            )
        )
        # Результат отдаёт детальный геттер, а не RETURNING: так изменение
        # возвращает ровно тот же объект, что вернуло бы чтение.
        return await self.get_by_id(session=session, player_id=player_id)

    async def set_xp(self, session: AsyncSession, player_id: UUID, xp_total: int) -> Player:
        """Выставить опыт абсолютным значением и вернуть обновлённого игрока.

        В отличие от ``add_xp`` не атомарно по смыслу: одновременные вызовы
        затрут друг друга. Это допустимо, потому что операция ручная и
        единственный её потребитель — PATCH от самого игрока.
        """
        await session.execute(
            update(Player).where(Player.id == player_id).values(xp_total=xp_total)
        )
        # Результат отдаёт детальный геттер, а не RETURNING: так изменение
        # возвращает ровно тот же объект, что вернуло бы чтение.
        return await self.get_by_id(session=session, player_id=player_id)

    async def rotate_token(self, session: AsyncSession, player_id: UUID, token_hash: str) -> Player:
        """Заменить хеш токена и вернуть обновлённого игрока.

        Вызывается при повторной регистрации известного устройства: старый
        токен утрачен клиентом, и продолжать хранить его хеш незачем — заодно
        это отзывает доступ, если прежний токен где-то остался.
        """
        await session.execute(
            update(Player).where(Player.id == player_id).values(token_hash=token_hash)
        )
        # Результат отдаёт детальный геттер, а не RETURNING: так изменение
        # возвращает ровно тот же объект, что вернуло бы чтение.
        return await self.get_by_id(session=session, player_id=player_id)

    async def count_games(self, session: AsyncSession, player_id: UUID) -> int:
        """Сколько партий у игрока.

        Считается до удаления: после каскада строк уже нет, а сказать клиенту,
        сколько данных исчезло, надо.
        """
        result = await session.execute(
            select(func.count()).select_from(Game).where(Game.player_id == player_id)
        )
        return result.scalar_one()

    async def delete(self, session: AsyncSession, player_id: UUID) -> None:
        """Удалить игрока. Партии уходят каскадом по внешнему ключу."""
        await session.execute(delete(Player).where(Player.id == player_id))
