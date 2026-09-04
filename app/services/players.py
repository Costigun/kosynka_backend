from sqlalchemy.ext.asyncio import AsyncSession

from app import xp
from app.models import Player
from app.schemas.players import (
    PlayerDeletedResponse,
    PlayerRegisteredResponse,
    PlayerStateResponse,
    PlayerUpdateRequest,
)
from app.security import generate_token, hash_token
from app.single_object import player_object
from app.views import player_view
from app.views.players import PlayerView
from app.xp import XpConfig


class PlayerService:
    """Оркестрация по игроку.

    Сервис ходит за данными в слой объектов и отдаёт результат в слой видов.
    SQL здесь не пишется, схемы ответа руками не собираются.
    """

    view: PlayerView = player_view

    async def register(
        self, session: AsyncSession, config: XpConfig, device_id: str | None = None
    ) -> PlayerRegisteredResponse:
        """Зарегистрировать устройство.

        С ``device_id`` регистрация идемпотентна: известное устройство получает
        свою же запись со всем прогрессом и свежий токен. Это единственный
        способ пережить переустановку приложения — токен теряется вместе
        с данными, а в базе от него только хеш.

        Без ``device_id`` каждый вызов создаёт нового игрока: ключа
        идемпотентности нет, повторить прежний ответ нечем.
        """
        token = generate_token()
        token_hash = hash_token(token)

        if device_id is None:
            # Ключа идемпотентности нет — повторить прежний ответ нечем,
            # каждый вызов заводит нового игрока.
            player = await player_object.create(session=session, token_hash=token_hash)
            restored = False
        else:
            # Чтение идёт только ради флага: сама вставка ниже атомарна и
            # в этом ответе не нуждается. raise_exception=False — для
            # регистрации «устройства ещё нет» нормальный путь, а не ошибка.
            #
            # ЦЕНА такого разделения: два одновременных запроса с одним
            # device_id могут оба прочитать «нет» и оба ответить restored=false,
            # хотя игрок один. Флаг соврёт, данные — нет: прогресс в ответе
            # прочитан из той самой строки. Держать флаг честным можно было бы
            # только выяснением, вставили мы или обновили, — платить за это
            # усложнением ради поля, которое в этот момент всегда про нулевой
            # прогресс, незачем.
            existing = await player_object.get_by_device_id(
                session=session, device_id=device_id, raise_exception=False
            )
            player = await player_object.upsert_by_device_id(
                session=session, token_hash=token_hash, device_id=device_id
            )
            restored = existing is not None

        await session.commit()

        return self.view.make_registered_response_schema(
            player=player,
            level=xp.level_for_xp(player.xp_total, config),
            token=token,
            restored=restored,
        )

    async def detail(self, player: Player, config: XpConfig) -> PlayerStateResponse:
        """Текущее состояние игрока.

        В базу не ходит: игрок уже прочитан при аутентификации, а уровень
        считается из его опыта чистой функцией.
        """
        return self.view.make_response_schema(
            player=player, level=xp.level_for_xp(player.xp_total, config)
        )

    async def update(
        self,
        session: AsyncSession,
        player: Player,
        data: PlayerUpdateRequest,
        config: XpConfig,
    ) -> PlayerStateResponse:
        """Изменить игрока.

        Изменяемое поле ровно одно — ``xp_total``. Это единственное место
        во всём API, где клиент пишет значение, которое иначе выводит сервер.
        """
        player = await player_object.set_xp(
            session=session, player_id=player.id, xp_total=data.xp_total
        )
        await session.commit()

        return self.view.make_response_schema(
            player=player, level=xp.level_for_xp(player.xp_total, config)
        )

    async def delete(self, session: AsyncSession, player: Player) -> PlayerDeletedResponse:
        """Удалить игрока вместе со всеми его партиями.

        Восстановления нет: ни email, ни пароля, ни привязки к аккаунту —
        удалённого игрока не вернуть даже по device_id, потому что строки
        больше не существует.
        """
        # Считаем до удаления: после каскада строк уже нет.
        games_deleted = await player_object.count_games(session=session, player_id=player.id)

        await player_object.delete(session=session, player_id=player.id)
        await session.commit()

        return self.view.make_deleted_response_schema(player=player, games_deleted=games_deleted)
