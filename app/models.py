import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    MetaData,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import Uuid

# Именованные ограничения. Без конвенции PostgreSQL придумывает имена сам,
# и обратная миграция превращается в угадывание: op.drop_constraint() нужно
# точное имя. CLAUDE.md фиксирует, что downgrade пишется руками, — значит
# имена должны быть предсказуемыми. Вводить это бесплатно можно только пока
# миграций ноль, то есть прямо сейчас.
NAMING_CONVENTION = {
    "pk": "pk_%(table_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
}


class Base(DeclarativeBase):
    """Базовый класс моделей."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


# Потолок опыта. Живёт рядом с колонкой, а не в схеме запроса, потому что это
# свойство хранилища, а не игры: xp_total лежит в INTEGER, и 2147483647 — предел
# самого типа. На него опираются двое: pydantic-схема PATCH-а (чтобы стозначное
# число стало 422, а не 500) и SQL-отсечка в add_xp (чтобы начисление на потолке
# не переполнило колонку). Раз предел один, то и константа обязана быть одна:
# разъехавшись, эти двое дадут ровно ту дыру, ради которой отсечка и заводилась.
MAX_XP_TOTAL = 2**31 - 1


class Player(Base):
    """Игрок.

    Соответствует одному устройству: регистрации без email и пароля, только
    токен. Колонки ``level`` здесь нет намеренно — уровень выводится из
    ``xp_total`` формулой, чтобы перебалансировка кривой не требовала
    миграции игроков.
    """

    __tablename__ = "players"

    # UUID, а не bigserial: последовательный идентификатор выдавал бы наружу
    # число игроков и порядок регистрации. Дефолт Python-side — тогда атрибут
    # заполнен сразу после session.add(), без RETURNING.
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # Идентичность устройства, отделённая от учётных данных.
    #
    # Токен не истекает, но теряется: переустановка приложения или очистка
    # данных — и прогресс не восстановить, потому что в базе только хеш.
    # device_id переживает переустановку (на Android — Settings.Secure.ANDROID_ID)
    # и позволяет вернуть игроку его же запись, выдав свежий токен.
    #
    # nullable намеренно: старые записи его не имеют, а клиент может не прислать.
    # UNIQUE — потому что это ключ идемпотентности регистрации.
    #
    # ЦЕНА, которую надо знать: кто предъявит чужой device_id, получит на него
    # токен, то есть заберёт аккаунт. Закрыть это можно только настоящим входом
    # через Google, а он вынесен за пределы итерации 1. Лидерборда нет, так что
    # угнавший чужой уровень в пасьянсе обманет только себя.
    device_id: Mapped[str | None] = mapped_column(String(128), nullable=True, unique=True)

    # sha256(token) в hex — 64 символа. Сам токен не хранится: он показывается
    # ровно один раз при регистрации. UNIQUE здесь не формальность, а рабочий
    # индекс: по нему идёт поиск на каждом авторизованном запросе.
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    # Два дефолта нужны оба: Python-side заполняет атрибут в объекте,
    # server-side гарантирует, что xp_total + n никогда не встретит NULL.
    xp_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")

    # timezone=True и явный nullable=False: расхождение по этим двум признакам
    # у timestamp-колонок уже ловилось alembic check в этом репозитории.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Game(Base):
    """Сыгранная партия.

    Ручка принимает только победы, поэтому колонки ``won`` нет: хранение
    проигрышей — это статистика, а она в итерацию 1 не входит.
    """

    __tablename__ = "games"
    __table_args__ = (
        # Идемпотентность. Мобильная сеть ретраит запросы, и опыт не должен
        # удваиваться: этот индекс — сам шлюз, а не вспомогательная проверка.
        UniqueConstraint("player_id", "client_game_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)

    # CASCADE, а не RESTRICT: удаление игрока по обращению не должно упираться
    # в его партии. Отдельного индекса по player_id нет — он ведущая колонка
    # составного UNIQUE, и тот же B-tree обслуживает выборку партий игрока.
    player_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("players.id", ondelete="CASCADE"), nullable=False
    )

    # Ключ идемпотентности, генерируется клиентом локально.
    client_game_id: Mapped[uuid.UUID] = mapped_column(Uuid, nullable=False)

    # BIGINT, а не INTEGER: INTEGER упёрся бы в 24.8 суток.
    duration_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)

    # Сколько начислено именно за эту партию. Нужен, чтобы повтор запроса вернул
    # то же число: параметры кривой могли поменяться между попытками, и пересчёт
    # дал бы другой результат.
    xp_awarded: Mapped[int] = mapped_column(Integer, nullable=False)

    # Принятое решение: каждая партия помнит версию формулы — иначе пересчитать
    # опыт задним числом невозможно.
    xp_formula_version: Mapped[int] = mapped_column(Integer, nullable=False)

    # Задел на итерацию 2. Принимаются и складываются БЕЗ проверки — не удалять
    # и не начинать валидировать по своей инициативе.
    # none_as_null обязателен: иначе SQLAlchemy пишет Python None как JSON-литерал
    # null, и колонка никогда не бывает SQL NULL.
    deal_cards: Mapped[Any] = mapped_column(JSONB(none_as_null=True), nullable=True)
    replay: Mapped[Any] = mapped_column(JSONB(none_as_null=True), nullable=True)

    # Момент приёма сервером, а не момент игры: клиент мог играть офлайн
    # и прислать партию через сутки.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
