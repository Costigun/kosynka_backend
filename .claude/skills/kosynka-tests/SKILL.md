---
name: kosynka-tests
description: >-
  Как писать и запускать тесты в kosynka-backend: разделение tests/unit и
  tests/api, поднятие Postgres для API-тестов, полный инвентарь фикстур
  conftest (registered_player, auth_headers, make_game_payload, existing_game,
  other_player и другие), стиль тестов (классы TestXxx, латинские имена,
  arrange/act/assert), обязательный набор проверок для новой ручки, опорные
  числа кривой опыта и ловушки TestClient/lifespan/TRUNCATE. Используй, когда
  пишешь или правишь тесты, когда тесты падают с MissingGreenlet,
  AttributeError на app.state или ошибкой подключения к базе, и когда нужно
  прогнать проверки перед коммитом.
---

# Тесты в kosynka-backend

Репозиторий: `/Users/maksim/kosynka_project/kosynka_backend`.
Poetry локально — **`poetry2`**.

Сейчас 131 тест: `tests/unit` — 63 (xp 52, config 6, security 5),
`tests/api` — 68 (games 39, players 25, meta 4).

---

## Запуск

```bash
# юнит-тесты: секунды, база не нужна
poetry2 run pytest tests/unit -q

# API-тесты: нужен живой Postgres
docker compose up -d db
poetry2 run pytest tests/api -q

# всё вместе
poetry2 run pytest tests -q

# один класс / один тест
poetry2 run pytest tests/api/test_games.py::TestGameCreate -q
poetry2 run pytest tests/api/test_games.py::TestGameCreate::test_win_awards_xp -q
```

DSN берётся из `KOSYNKA_DATABASE_URL`; локально он лежит в `.env`, который
читает `pydantic-settings`. Настоящее окружение всегда важнее файла.

**Первый запуск на пустой базе:** сначала `poetry2 run alembic upgrade head`,
иначе `TRUNCATE` в фикстуре упрётся в отсутствующие таблицы.

В CI Postgres поднимается сервисом (`postgres:18`), и API-тесты идут **после**
шага `alembic upgrade head && alembic check`.

---

## Что где лежит

| Каталог | Правило |
|---|---|
| `tests/unit/` | без базы и сети. Импортировать `app.db`, `app.main`, ходить в сеть — нельзя |
| `tests/api/` | против настоящего Postgres, через `TestClient`, только по HTTP |

Промежуточного слоя нет намеренно: сервисы и слой доступа проверяются теми же
API-тестами. Отдельные тесты на `single_object` с моками не заводить — они
проверяли бы моки.

---

## Фикстуры `tests/api/conftest.py`

| Фикстура | Что даёт |
|---|---|
| `clean_database` | **autouse**, `TRUNCATE players, games CASCADE` перед каждым тестом |
| `client` | `TestClient` в контекстном менеджере |
| `registered_player` | тело ответа `POST /v1/players` (там `player_id` и `token`) |
| `auth_headers` | `{"Authorization": "Bearer …"}` основного игрока |
| `other_player` / `other_auth_headers` | второй игрок — проверять, что чужое недоступно |
| `make_game_payload` | фабрика тела `POST /v1/games`, принимает `**overrides` |
| `existing_game` | уже засчитанная партия основного игрока (с `deal_cards` и `replay`) |
| `existing_games` | три партии длительностью 60 000 / 300 000 / 600 000 мс |
| `other_player_game` | партия второго игрока |

Константа `REFERENCE_DURATION_MS = 300_000` — эталонная пятиминутная партия,
ровно **100 опыта** при дефолтной кривой.

Новую фикстуру заводи, только если она нужна больше чем одному тесту;
одноразовую подготовку пиши прямо в тесте.

### Почему фикстуры устроены именно так

- **`clean_database` создаёт свой одноразовый движок**, а не берёт
  `app.state.engine`. Пул рабочего движка привязан к циклу событий, который
  `TestClient` крутит в отдельном потоке; обращение к нему снаружи даёт
  `MissingGreenlet`.
- **Чистится ДО теста, а не после.** Упавший тест оставляет данные для разбора,
  а следующий всё равно стартует на пустом месте.
- **`TestClient` обязательно как контекстный менеджер.** Без `with` не
  выполняется `lifespan`, не появляются `app.state.engine` и
  `app.state.session_factory`, и любая ручка падает с `AttributeError` вместо
  осмысленной ошибки.

---

## Стиль

```python
class TestGameCreate:
    """POST /v1/games — засчитать победу."""

    def test_retry_does_not_award_xp_twice(
        self, client: TestClient, auth_headers: dict[str, str], make_game_payload: MakePayload
    ) -> None:
        """Идемпотентность по (player_id, client_game_id): мобильная сеть
        ретраит запросы, и второй такой же не должен стоить удвоенного опыта."""
        payload = make_game_payload()

        first = client.post("/v1/games", json=payload, headers=auth_headers).json()
        second = client.post("/v1/games", json=payload, headers=auth_headers).json()

        assert first["already_counted"] is False
        assert second["already_counted"] is True
        assert second["xp_total"] == first["xp_total"] == 100
```

- Тесты сгруппированы в классы по ручке: `TestGameCreate`, `TestGameList`,
  `TestGameRead`, `TestGameUpdate`, `TestGameDelete`. Новая ручка — новый класс.
- **Имена — латиницей**, содержательно: `test_coefficient_clamped_on_both_sides`.
  Русские имена тестов в репозитории были и вычищены, не возвращай их.
- Docstring нужен там, где неочевидно **почему** так должно быть; на
  самоописательный тест — не нужен.
- Три блока с пустыми строками: подготовка, действие, проверки.
- Тесты синхронные. `pytest-asyncio` в проекте нет и не нужен — `TestClient`
  сам крутит цикл событий.
- Аннотации типов обязательны (`-> None`, `dict[str, str]`): `ruff` и `mypy`
  идут по `app tests`. Локальный алиас `MakePayload = Callable[..., dict[str, Any]]`
  объявляется в начале файла.
- В ответе проверяем конкретные числа, а не «что-то пришло». Числа берутся из
  опорных точек ниже.

---

## Обязательный набор для новой ручки

1. успех — код и **все** значимые поля тела;
2. `401` без заголовка `Authorization` и `401` с несуществующим токеном;
3. `404` на чужом объекте (через `other_player_game`), если ручка ходит по `id`;
4. идемпотентность, если ручка что-то создаёт: второй одинаковый запрос не
   меняет состояние и возвращает тот же объект;
5. `422` на негодном теле, если у полей есть ограничения;
6. побочный эффект, если он есть: удаление партии забирает опыт, смена
   `duration_ms` его пересчитывает.

---

## Опорные числа

Кривая при дефолтных параметрах — на них завязаны и unit-, и API-тесты:

```
пороги уровней: 0, 200, 450, 763, 1154, 1642, 2252, 3015, 3969, 5161
300_000 мс (5 минут)  → 100 опыта     ← REFERENCE_DURATION_MS
две эталонных партии  → 200 опыта, уровень 2, xp_to_next 250
```

`tests/unit/test_xp.py` — параметризованная таблица «минуты → опыт».
**Правишь `app/xp.py` — дополняй таблицу, а не переписывай её.** Там уже есть
опорная точка на восьми минутах ровно про то, что `round()` банковское:
`round(62.5) == 62`, а нужно 63, поэтому в `xp.py` округление сделано явно
через `+0.5`. Обратно не «упрощать».

---

## Ловушки

- `MissingGreenlet` в тесте — почти всегда обращение к движку приложения
  снаружи его цикла событий либо чтение серверного умолчания после `flush()`
  без перечитывания объекта.
- `AttributeError: state.session_factory` — `TestClient` создан без `with`.
- Тесты падают все разом на подключении — не поднят `db`
  (`docker compose up -d db`) или не накачены миграции.
- Тест «прошёл, но не то проверил»: `client.post(...)` без `headers=auth_headers`
  даст 401, а `assert response.json()` на 401 всё равно что-то вернёт. Проверяй
  `status_code` первым.
- `assert response.status_code == 200, response.text` в фикстурах — не
  украшение: без `response.text` падение фикстуры не говорит ничего.

---

## Перед коммитом

```bash
poetry2 run ruff check app tests && poetry2 run ruff format --check app tests
poetry2 run mypy app
poetry2 run pytest tests -q
poetry2 run alembic check
poetry2 check --lock
```

Тесты — обязательный шаг перед любым коммитом, даже если о них не просили.
Красное — не коммитим, а разбираемся.
