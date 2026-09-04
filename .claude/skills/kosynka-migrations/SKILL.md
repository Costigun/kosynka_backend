---
name: kosynka-migrations
description: >-
  Работа с Alembic в kosynka-backend: как завести миграцию под изменение
  модели, требование обратной совместимости из-за порядка выкатки (upgrade head
  идёт до перезапуска приложения), NAMING_CONVENTION и ручной downgrade,
  проверка alembic check в CI, ловушки timestamptz/JSONB/server_default и
  откат релиза, который образ возвращает, а миграции — нет. Используй при любом
  изменении app/models.py, при добавлении или удалении колонок, индексов и
  ограничений, при падении alembic check, при разборе «схема не совпадает с
  моделями» и при написании downgrade.
---

# Миграции в kosynka-backend

Репозиторий: `/Users/maksim/kosynka_project/kosynka_backend`.
Poetry локально — **`poetry2`**. Схема БД и обоснование каждой колонки — в
скилле [kosynka-players-games].

---

## Главное правило

**Меняешь `app/models.py` — миграция в том же коммите.** `alembic check` в CI
валит пайплайн при расхождении, и это уже ловило реальный баг: нехватку
`timezone=True` и явного `nullable=False` у timestamp-колонок.

---

## Команды

```bash
docker compose up -d db                    # база должна быть поднята

poetry2 run alembic upgrade head           # накатить
poetry2 run alembic check                  # модели совпадают с миграциями?
poetry2 run alembic revision --autogenerate -m "player device_id"
poetry2 run alembic downgrade -1           # откатить одну (локально)
poetry2 run alembic history --verbose
poetry2 run alembic current
```

`alembic/env.py` берёт DSN из `KOSYNKA_DATABASE_URL` (через `get_settings()`),
а не из `alembic.ini`; знаки `%` экранируются, иначе пароль с процентом
развалит `configparser`. `target_metadata = Base.metadata` — именно на это
смотрит `alembic check`.

---

## Порядок действий

1. Правишь `app/models.py`.
2. `alembic upgrade head` — база в состоянии «до».
3. `alembic revision --autogenerate -m "…"`.
4. **Читаешь сгенерированный файл целиком и правишь.** Autogenerate — черновик:
   он не видит переименований (видит `DROP` + `ADD`, то есть потерю данных),
   путается в серверных умолчаниях и не расставляет комментарии.
5. Пишешь `downgrade()` руками — Alembic сам его не придумает правильно.
6. Дописываешь docstring: **зачем** изменение и почему оно обратно совместимо.
7. `alembic upgrade head && alembic check` — должно быть тихо.
8. `git add alembic/versions/<новый файл>` сразу после создания.

---

## Обратная совместимость — требование, а не пожелание

Порядок в `deploy/release.sh` фиксирован: `alembic upgrade head` идёт **до**
`docker compose up -d`. В этот момент **новая схема работает со старым кодом**.

Отсюда правила:

- Новая колонка добавляется **nullable**. Обязательной — следующим релизом,
  когда весь код уже умеет её писать.
- Удаление колонки — в два релиза: сначала код перестаёт её читать, потом
  колонка уходит.
- Переименование = добавить новую + перелить + удалить старую, тремя релизами,
  а не `ALTER … RENAME` одним.
- Долгие блокирующие `ALTER` на боевой базе не делаем — приложение в этот
  момент живо.

Если миграция упала, `release.sh` завершается **до** `up -d`, и старая версия
продолжает работать. Это не полусломанный деплой, а задуманное поведение.

---

## Имена ограничений

`NAMING_CONVENTION` в `app/models.py` задаёт предсказуемые имена:

```
pk_%(table_name)s
uq_%(table_name)s_%(column_0_N_name)s
fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s
ix_%(table_name)s_%(column_0_N_name)s
ck_%(table_name)s_%(constraint_name)s
```

Без неё PostgreSQL придумывает имена сам, а `op.drop_constraint()` в
`downgrade()` требует точного имени — обратная миграция превращается в
угадывание. В миграциях имя оборачивай в `op.f(...)`:

```python
op.create_unique_constraint(op.f("uq_players_device_id"), "players", ["device_id"])
...
op.drop_constraint(op.f("uq_players_device_id"), "players", type_="unique")
```

В `downgrade()` **порядок обратный**: ограничение снимается до колонки, на
которой стоит.

---

## Образец миграции

```python
"""player device_id

Идентичность устройства, отделённая от токена: позволяет вернуть игроку его
запись после переустановки приложения.

Миграция обратно совместима — колонка nullable, старый код продолжает работать
с новой схемой.

Revision ID: 6be62dd928db
Revises: a2eee5721208
"""

def upgrade() -> None:
    op.add_column("players", sa.Column("device_id", sa.String(length=128), nullable=True))
    # UNIQUE, потому что device_id — ключ идемпотентности регистрации.
    # В PostgreSQL несколько NULL уникальности не нарушают.
    op.create_unique_constraint(op.f("uq_players_device_id"), "players", ["device_id"])


def downgrade() -> None:
    op.drop_constraint(op.f("uq_players_device_id"), "players", type_="unique")
    op.drop_column("players", "device_id")
```

---

## Ловушки

- **Timestamp-колонки.** В модели обязательно `DateTime(timezone=True)`,
  явный `nullable=False` и `server_default=func.now()`. Расхождение по любому
  из трёх признаков ловится `alembic check` — уже ловилось.
- **Два дефолта у счётчиков.** `default=0` заполняет атрибут в Python,
  `server_default="0"` защищает `xp_total + n` от NULL. Нужны оба.
- **JSONB — только `JSONB(none_as_null=True)`.** Без флага Python `None`
  пишется JSON-литералом `null`, и колонка никогда не бывает SQL NULL.
- **Autogenerate не видит переименований.** Оставишь как есть — релиз молча
  сотрёт данные.
- **`alembic check` требует поднятой базы.** «Не могу подключиться» это не
  расхождение схемы.
- **Откат релиза миграции не откатывает.** `IMAGE_TAG=<старый sha> docker
  compose up -d` возвращает образ, но схема остаётся новой. Обратная миграция
  пишется и запускается руками — ещё одна причина держать `downgrade()` рабочим.
- **Разовый запуск миграций тоже берёт соединение.** `KOSYNKA_DB_POOL_SIZE`
  не должен упираться в `max_connections` (у `postgres:18` по умолчанию 100).
- Индекс не заводить «на всякий случай»: у `games` нет отдельного индекса по
  `player_id`, потому что это ведущая колонка составного UNIQUE и тот же B-tree
  обслуживает выборку партий игрока.

---

## Проверки перед коммитом

```bash
poetry2 run alembic upgrade head
poetry2 run alembic check
poetry2 run pytest tests -q
poetry2 run ruff check app tests && poetry2 run mypy app
poetry2 check --lock
```
