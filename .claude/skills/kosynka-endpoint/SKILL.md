---
name: kosynka-endpoint
description: >-
  Пошаговый рецепт вертикального среза в kosynka-backend: как добавить или
  изменить ручку, поле в ответе, параметр запроса. Порядок файлов снизу вверх
  (schemas → single_object → views → services → api → tests), готовые шаблоны
  каждого слоя в стиле репозитория, регистрация в __init__ и main.py,
  обязательный набор тестов и гейт перед коммитом. Используй, когда просят
  «добавь ручку», «новый эндпоинт», «добавь поле в ответ», «сделай метод
  PATCH/DELETE для …», а также когда правишь существующий срез и нужно понять,
  какие ещё файлы обязаны измениться вместе с ним.
---

# Вертикальный срез в kosynka-backend

Репозиторий: `/Users/maksim/kosynka_project/kosynka_backend`.
Домен (модели, опыт, идемпотентность, семантика существующих ручек) — в скилле
[kosynka-players-games]. Здесь только **процедура**: что и в каком порядке писать.

Локально Poetry — **`poetry2`** (2.4.1). Голый `poetry` в системе старый (1.3.2)
и этот `pyproject.toml` не разберёт.

---

## Порядок файлов

Строго снизу вверх — каждый следующий слой опирается на готовый предыдущий.
Обратный порядок заставляет переписывать сигнатуры по два раза.

| # | Файл | Что там появляется |
|---|---|---|
| 1 | `app/models.py` | только если меняется схема БД → **миграция в том же коммите**, см. [kosynka-migrations] |
| 2 | `app/schemas/<сущность>.py` | `XxxRequest` и `XxxResponse` |
| 3 | `app/schemas/__init__.py` | реэкспорт новых схем в `__all__` |
| 4 | `app/single_object/<сущность>.py` | SQL-метод |
| 5 | `app/views/<сущность>.py` | `make_xxx_response_schema` |
| 6 | `app/services/<сущность>.py` | оркестрация + `commit()` |
| 7 | `app/api/<сущность>.py` | роут |
| 8 | `tests/api/test_<сущность>.py` | тесты: успех, 401, чужой объект, идемпотентность |

Новая **сущность** (не новая ручка у существующей) добавляет ещё три строки:
экземпляр в `app/single_object/__init__.py`, `app/views/__init__.py`,
`app/services/__init__.py`, плюс `app.include_router(..., prefix="/v1")`
в `app/main.py`. Префикс навешивается в `main.py`, не в роутере.

---

## Шаблоны слоёв

### Схемы — `app/schemas/`

```python
class GameUpdateRequest(BaseModel):
    """Изменение партии."""

    duration_ms: int | None = Field(default=None, ge=1, le=MAX_DURATION_MS)
    deal_cards: JsonValue = None


class GameResponse(BaseModel):
    """Партия целиком."""

    game_id: UUID
    duration_ms: int
    created_at: datetime
```

- **Поля перечисляются руками, `from_attributes` не включать.** У `Player` есть
  `token_hash` и `device_id` — автомаппинг по совпадению имён и есть тот
  механизм, которым секрет уезжает в ответ.
- Лишние поля в теле **игнорируются**, а не запрещаются (`extra` не трогать):
  приложение на устройстве нельзя обновить по требованию.
- Частичное обновление: все поля `| None = None`, а сервис читает
  `model_dump(exclude_unset=True)` — «не прислали» и «прислали null» это разные
  вещи, и для `deal_cards` вторая осмысленна.
- Целочисленные поля, которые уедут в BIGINT, ограничивай сверху
  (`le=MAX_DURATION_MS`), иначе стозначное число доедет до драйвера и даст 500
  вместо честного 422.

### Доступ — `app/single_object/`

Весь SQL живёт тут и только тут. Импортировать `services` и `views` нельзя.

```python
    @overload
    async def get_by_id(
        self, session: AsyncSession, player_id: UUID, game_id: UUID,
        raise_exception: Literal[True] = True,
    ) -> Game: ...

    @overload
    async def get_by_id(
        self, session: AsyncSession, player_id: UUID, game_id: UUID,
        raise_exception: Literal[False],
    ) -> Game | None: ...

    async def get_by_id(
        self, session: AsyncSession, player_id: UUID, game_id: UUID,
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
```

Обязательные приёмы:

1. **`raise_exception` у любого геттера одного объекта**, дефолт `True`. Две
   перегрузки по `Literal[True]`/`Literal[False]` — без них `mypy --strict`
   требует проверок на `None` там, где их быть не должно.
2. **Фильтр по `player_id` в каждом методе.** Без него игрок читает и правит
   чужое, зная только id. «Чужая» и «несуществующая» неразличимы — обе 404.
3. **Запись возвращает объект детальным геттером**, а не результатом
   `RETURNING`. После `flush()` серверных умолчаний (`created_at`) в объекте
   нет, и обращение к ним в async даёт `MissingGreenlet`.
4. **`session.scalars(...).one_or_none()`**, не `session.scalar(...)`: второй
   в асинхронном API типизирован как `Any`.
5. **`execution_options(populate_existing=True)`** при перечитывании, иначе
   identity map отдаст устаревший объект. `session.get(Model, pk)` для свежего
   чтения не использовать — он вообще не сходит в базу.
6. Возвращаем модели, а не схемы. Скаляры — только у счётчиков (`count_*`).
7. Вставка с идемпотентностью — `pg_insert(...).on_conflict_do_nothing(...)`,
   а не `get_or_create`: между «посмотреть» и «вставить» пролезает дубликат.

### Виды — `app/views/`

```python
    def make_response_schema(self, game: Game) -> GameResponse:
        return GameResponse(
            game_id=game.id,
            duration_ms=game.duration_ms,
            created_at=game.created_at,
        )
```

Принимают **доменные объекты** (`Game`, `Player`, `LevelInfo`), а не россыпь
полей. Ходить в базу видам нечем и незачем.

### Сервис — `app/services/`

```python
    async def delete(
        self, session: AsyncSession, player: Player, game_id: UUID, config: XpConfig
    ) -> GameDeletedResponse:
        """Удалить партию и забрать начисленный за неё опыт."""
        game = await game_object.delete(session=session, player_id=player.id, game_id=game_id)
        player = await player_object.add_xp(
            session=session, player_id=player.id, amount=-game.xp_awarded
        )
        await session.commit()

        return self.view.make_deleted_response_schema(
            game=game, player=player, level=xp.level_for_xp(player.xp_total, config)
        )
```

- **Граница транзакции — здесь.** `commit()` вызывает сервис, не слой доступа
  и не роут. Все изменения одного запроса — в одной транзакции.
- Чистые функции (`app/xp.py`) вызываются отсюда, конфиг приходит аргументом.
- `view` объявлен атрибутом класса: `view: GameView = game_view`.

### Роут — `app/api/`

```python
@router.delete("/games/{game_id}", response_model=GameDeletedResponse)
async def delete_game(
    game_id: UUID,
    player: Player = Depends(current_player),
    session: AsyncSession = Depends(get_session),
    config: XpConfig = Depends(get_xp_config),
) -> GameDeletedResponse:
    """Удалить партию и забрать начисленный за неё опыт."""
    return await game_service.delete(session=session, player=player, game_id=game_id, config=config)
```

- **Ровно одна строка вызова сервиса. Логики ноль**, включая проверки на `None`
  и сборку `dict`.
- **`response_model` в декораторе И аннотация возврата.** Первое задаёт
  контракт и фильтрует ответ, второе требует `mypy --strict`. Класс в
  `response_model` — ровно тот, что возвращает соответствующий
  `make_*_response_schema`.
- Аутентификация — `Depends(current_player)`. Публичная ручка — без него.
- Ограничения на query-параметры прямо в сигнатуре:
  `limit: int = Query(default=20, ge=1, le=100)`. Верхняя граница обязательна,
  иначе один запрос вытянет всю историю в память.
- `Depends(...)` в дефолтах — идиома FastAPI, `B008` для неё отключён в
  `pyproject.toml`. Не переписывай сигнатуры ради линтера.
- Ошибки — фабрики из `app/exceptions.py` (`raise_*() -> NoReturn`), а не
  `raise HTTPException` по месту. Нужна новая — заводи фабрику там же.

---

## Коды ответов: что уже решено

| Ситуация | Ответ |
|---|---|
| нет заголовка `Authorization` **или** токен неизвестен | 401, один и тот же текст |
| объект чужой **или** его нет | 404 (403 сообщал бы, что объект существует) |
| повторный вызов идемпотентной ручки | тот же код, что и первый (для `POST /v1/games` — 200) |
| создание игрока | 201 |

Путь `/me`, а не `/{player_id}`: администратора нет, игрок трогает только себя.

---

## Тесты

Новая ручка — новые тесты в `tests/api/`. Минимум:

- успех,
- 401 без токена,
- 404 на чужой объект (если ручка работает по `id`),
- идемпотентность, если ручка что-то создаёт.

Подробности — в скилле [kosynka-tests].

---

## Гейт перед коммитом

```bash
poetry2 run ruff check app tests && poetry2 run ruff format --check app tests
poetry2 run mypy app
poetry2 run pytest tests          # 131 тест; для tests/api нужен живой Postgres
poetry2 run alembic check
poetry2 check --lock
```

Красное — не коммитим.

---

## Чего не делать

Не добавлять слои, зависимости, кеши и абстракции «на вырост» — проект
сознательно минимальный. Не расширять API за пределы итерации 1 (лидерборд,
рейтинги, ники, статистика, достижения, draw-3, вход через Google,
синхронизация между устройствами) без явной просьбы.

Все идентификаторы — латиницей, включая имена тестов. Комментарии и
docstring-и — по-русски.
