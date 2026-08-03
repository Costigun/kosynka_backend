from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, JsonValue

# Верхняя граница длительности — не игровое ограничение, а защита от
# переполнения BIGINT: без неё стозначное число доехало бы до драйвера и дало
# 500 вместо честного 422. Правдоподобного потолка нет намеренно: пожилой игрок
# вполне может раскладывать партию час, и отказ стоил бы ему опыта навсегда.
MAX_DURATION_MS = 2**63 - 1


class GameCreateRequest(BaseModel):
    """Партия, завершившаяся победой.

    Лишние поля намеренно игнорируются, а не запрещаются: приложение на
    устройстве нельзя обновить по требованию, и поле от более новой версии
    клиента не должно стоить игроку опыта.
    """

    # Ключ идемпотентности, генерируется клиентом.
    client_game_id: UUID
    duration_ms: int = Field(ge=1, le=MAX_DURATION_MS)

    # Задел на итерацию 2. Принимаются и складываются в базу БЕЗ ПРОВЕРКИ —
    # JsonValue означает «любой валидный JSON», ноль предположений о форме.
    deal_cards: JsonValue = None
    replay: JsonValue = None


class GameUpdateRequest(BaseModel):
    """Изменение партии.

    Все поля необязательны, и отличать «не прислали» от «прислали null» надо
    обязательно: у deal_cards значение null осмысленно само по себе. Поэтому
    сервис читает не поля объекта, а ``model_dump(exclude_unset=True)``.

    Смена duration_ms влечёт пересчёт опыта: партия помнит, сколько за неё
    начислено, и разница переносится на суммарный опыт игрока.
    """

    duration_ms: int | None = Field(default=None, ge=1, le=MAX_DURATION_MS)
    deal_cards: JsonValue = None
    replay: JsonValue = None


class GameResponse(BaseModel):
    """Партия целиком."""

    game_id: UUID
    client_game_id: UUID
    duration_ms: int
    xp_awarded: int
    xp_formula_version: int
    deal_cards: JsonValue
    replay: JsonValue
    created_at: datetime


class GameListResponse(BaseModel):
    """Страница списка партий.

    Общее число возвращается отдельным запросом COUNT: без него клиент не
    может показать, сколько всего партий, и вынужден листать вслепую.
    """

    items: list[GameResponse]
    total: int
    limit: int
    offset: int


class GameResultResponse(BaseModel):
    """Итог засчитанной партии."""

    # Идентификатор строки: без него клиент не может потом обратиться
    # к партии — ни прочитать, ни изменить, ни удалить.
    game_id: UUID
    # Эхо запроса: у клиента офлайн-очередь, и ответ надо сопоставить с тем,
    # что было отправлено.
    client_game_id: UUID
    xp_awarded: int
    xp_total: int
    level: int
    xp_into_level: int
    xp_to_next: int
    # True, если партия с таким client_game_id уже была засчитана раньше
    # и опыт повторно не начислялся.
    already_counted: bool


class GameDeletedResponse(BaseModel):
    """Подтверждение удаления партии.

    Возвращает состояние игрока после отката опыта: удаление партии обязано
    забрать начисленное за неё, иначе в сумме останется опыт за партию,
    которой больше нет.
    """

    game_id: UUID
    xp_removed: int
    xp_total: int
    level: int
    xp_into_level: int
    xp_to_next: int
