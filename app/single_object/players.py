from uuid import UUID

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Game, Player


class PlayerObject:
    """Доступ к данным игрока.

    Весь SQL по таблице ``players`` живёт здесь. Возвращает модели и скаляры,
    но не схемы ответа: их собирает слой видов.
    """

    async def create(
        self, session: AsyncSession, token_hash: str, device_id: str | None = None
    ) -> Player:
        """Завести нового игрока. Опыт стартует с нуля по умолчанию колонки."""
        player = Player(token_hash=token_hash, device_id=device_id)
        session.add(player)
        # flush, а не commit: границу транзакции держит вызывающий сервис.
        # После flush заполнены id и xp_total, и их можно отдать во view.
        await session.flush()
        return player

    async def get_by_token_hash(self, session: AsyncSession, token_hash: str) -> Player | None:
        """Найти игрока по хешу токена, либо None.

        Прямой аналог ``get_or_none`` из Tortoise. Через ``session.scalars``,
        а не ``session.scalar``: второй короче на строку, но в асинхронном API
        типизирован как ``Any``, и mypy --strict на нём справедливо ругается.
        ``ScalarResult`` даёт привычный набор — ``one_or_none``, ``first``, ``all``.

        Горячий путь: выполняется на каждом авторизованном запросе, идёт по
        уникальному индексу uq_players_token_hash.
        """
        players = await session.scalars(select(Player).where(Player.token_hash == token_hash))
        return players.one_or_none()

    async def add_xp(self, session: AsyncSession, player_id: UUID, amount: int) -> int:
        """Атомарно изменить опыт на ``amount`` и вернуть новую сумму.

        Прибавление делает сама база выражением ``xp_total + amount``:
        никакого read-modify-write, никаких гонок и никакого SELECT FOR UPDATE.
        Принятое решение проекта, не оптимизация.

        ``amount`` может быть отрицательным — так откатывается опыт при
        удалении партии и при уменьшении её длительности.
        """
        result = await session.execute(
            update(Player)
            .where(Player.id == player_id)
            .values(xp_total=Player.xp_total + amount)
            .returning(Player.xp_total)
        )
        return result.scalar_one()

    async def set_xp(self, session: AsyncSession, player_id: UUID, xp_total: int) -> int:
        """Выставить опыт абсолютным значением.

        В отличие от ``add_xp`` не атомарно по смыслу: одновременные вызовы
        затрут друг друга. Это допустимо, потому что операция ручная и
        единственный её потребитель — PATCH от самого игрока.
        """
        result = await session.execute(
            update(Player)
            .where(Player.id == player_id)
            .values(xp_total=xp_total)
            .returning(Player.xp_total)
        )
        return result.scalar_one()

    async def get_xp_total(self, session: AsyncSession, player_id: UUID) -> int:
        """Текущая сумма опыта.

        Нужен на повторе засчитанной партии: брать xp_total из объекта игрока,
        прочитанного при аутентификации, нельзя — между тем чтением и этим
        моментом соседний запрос мог начислить опыт, и клиент увидел бы
        устаревшее число.

        Здесь намеренно НЕ ``session.get(Player, player_id)``: он сначала
        смотрит в identity map сессии и вернул бы тот самый устаревший объект,
        не сходив в базу, — то есть ровно ту ошибку, ради которой метод и нужен.

        ``scalar_one``, а не ``scalar``: игрок существует заведомо, и исчезнувшая
        строка должна падать громко, а не превращаться в None.
        """
        result = await session.execute(select(Player.xp_total).where(Player.id == player_id))
        return result.scalar_one()

    async def get_by_device_id(self, session: AsyncSession, device_id: str) -> Player | None:
        """Найти игрока по идентификатору устройства, либо None.

        Ключ восстановления после переустановки: токен потерян, а device_id —
        нет, и запись со всем прогрессом находится по нему.
        """
        players = await session.scalars(select(Player).where(Player.device_id == device_id))
        return players.one_or_none()

    async def rotate_token(self, session: AsyncSession, player_id: UUID, token_hash: str) -> None:
        """Заменить хеш токена, не трогая ничего больше.

        Вызывается при повторной регистрации известного устройства: старый
        токен утрачен клиентом, и продолжать хранить его хеш незачем — заодно
        это отзывает доступ, если старый токен где-то остался.
        """
        await session.execute(
            update(Player).where(Player.id == player_id).values(token_hash=token_hash)
        )

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
