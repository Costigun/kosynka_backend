---
name: kosynka-deploy
description: >-
  Доставка и эксплуатация kosynka-backend: как устроен путь «пуш в main →
  GitHub Actions → образ в GHCR → ssh → docker compose», что лежит на сервере
  в /opt/kosynka, шаги release.sh и почему их порядок неизменен, откат на
  прошлый образ, диагностика упавшего деплоя и живого сервера, где живут
  секреты и переменные окружения, ловушки томов caddy_data и pgdata, GHCR и
  паролей базы. Используй при правке .github/workflows/ci.yml, deploy/,
  Dockerfile или compose-файлов, при разборе красного деплоя, при добавлении
  переменной окружения и когда нужно посмотреть, что крутится на сервере.
---

# Доставка и эксплуатация kosynka-backend

Репозиторий: `/Users/maksim/kosynka_project/kosynka_backend`.

Разовая настройка сервера расписана в **`docs/deploy.md`** (15 КБ), устройство
TLS и запасной путь с сертификатом на голый IP — в **`docs/tls.md`** (18 КБ).
Здесь — рабочая схема и то, что нужно под рукой; за пошаговыми инструкциями
иди в эти два файла.

---

## Схема

```
пуш в main → GitHub Actions
             ├─ quality: ruff, mypy, unit, alembic upgrade+check, api-тесты
             └─ deploy (needs: quality)
                ├─ build & push ghcr.io/costigun/kosynka-backend:<sha>
                ├─ rsync deploy/ → /opt/kosynka/  (--exclude='.env*')
                └─ ssh → IMAGE_TAG=<sha> bash /opt/kosynka/release.sh
```

Решения, которые не переоткрываются:

- **Один сервер и `docker compose`, без Kubernetes.** k8s здесь был написан и
  выброшен: на одной ноде он не даёт ни планирования, ни HA, только вдвое
  больше эксплуатации. Не предлагать возврат, пока нет второй ноды.
- **Деплой ровно на пуш в `main`.** Одна ветка, одно окружение, stage нет.
- **Тесты и деплой в одном workflow**, `deploy` стоит за `needs: quality` —
  раскатиться в обход красных тестов нельзя.
- **Тег образа — sha коммита, не `latest`.** Видно, что крутится, и возможен
  откат одной строкой.
- **Логика деплоя в `deploy/release.sh`, не в yaml.** Её видно целиком и можно
  прогнать руками.
- **Простой на секунды при выкатке допустим:** игра работает офлайн, сеть
  опциональна.
- `concurrency: deploy-production`, `cancel-in-progress: false` — два деплоя
  подрались бы за compose, но прерванный на середине оставляет мусор.

---

## Что на сервере

```
/opt/kosynka/
  docker-compose.yml   # caddy + app + db (postgres:18)   ← rsync из deploy/
  Caddyfile            # реверс-прокси и TLS               ← rsync из deploy/
  release.sh           # сам деплой                        ← rsync из deploy/
  .env                 # IMAGE_TAG=<sha>, пишет release.sh
  .env.app             # настройки приложения, KOSYNKA_*   ← руками, один раз
  .env.db              # пароль postgres                   ← руками, один раз
  .env.site            # домен и почта для ACME            ← руками, один раз
```

Наружу смотрит только Caddy, он же терминирует TLS. Порт 5432 закрыт: до базы
достаёт только приложение по compose-сети.

`deploy/cloud-init.yaml` отдаётся **хостеру при создании ВМ**, на работающий
сервер не едет (исключён в rsync).

**Секреты в git не попадают вообще.** `rsync` идёт с `--exclude='.env*'`,
чтобы выкатка их не затирала.

---

## Шаги `release.sh` — порядок неизменен

```bash
echo "IMAGE_TAG=${IMAGE_TAG}" > .env
docker compose pull
docker compose up -d --wait db                              # 1) база и healthcheck
docker compose run --rm --no-deps app alembic upgrade head  # 2) миграции
docker compose up -d --remove-orphans                       # 3) новый код
# ждать healthy до 60 с, иначе показать логи и выйти с ошибкой
docker image prune -f
```

- **База поднимается отдельным шагом:** на первом деплое не запущено ничего, а
  `run --no-deps` сам её не поднял бы. `--wait` держит паузу до зелёного
  healthcheck, иначе миграции упрутся в неготовый Postgres.
- **Миграции до перезапуска приложения** → новая схема работает со старым
  кодом → миграции обязаны быть обратно совместимыми. Подробности и правила —
  в скилле [kosynka-migrations].
- **Упавшая миграция завершает скрипт до `up -d`**, старая версия продолжает
  работать. Это задумано.
- **Деплой успешен только когда healthcheck позеленел**, иначе в лог падают
  последние 50 строк приложения и джоба краснеет.

---

## Откат

```bash
ssh deploy@SERVER
cd /opt/kosynka
IMAGE_TAG=<старый sha> docker compose up -d
```

**Миграции это не откатывает.** Обратная миграция пишется и запускается руками.

---

## Диагностика

```bash
ssh deploy@SERVER 'cd /opt/kosynka && docker compose ps'
ssh deploy@SERVER 'cd /opt/kosynka && docker compose logs -f --tail=100 app'
ssh deploy@SERVER 'cd /opt/kosynka && cat .env'          # какой sha крутится
ssh deploy@SERVER 'cd /opt/kosynka && docker compose logs --tail=50 caddy'

curl -s https://ДОМЕН/healthz     # {"status":"ok"} — базу не трогает
curl -s https://ДОМЕН/readyz      # трогает базу
curl -sI http://ДОМЕН             # ждём 308 на https
```

`/healthz` не ходит в базу намеренно, `/readyz` ходит: иначе моргнувший
Postgres перезапустил бы всё разом.

Локальная проверка compose-файлов перед пушем:

```bash
docker compose config -q                          # локальный
docker compose -f deploy/docker-compose.yml config -q
```

---

## Новая переменная окружения

Добавляется **в трёх местах одновременно**, иначе приложение на сервере её не
увидит:

1. поле в `Settings` (`app/config.py`), префикс `KOSYNKA_`;
2. `deploy/docker-compose.yml`;
3. локальный `docker-compose.yml`, если нужна в разработке.

Значение — на сервере в `/opt/kosynka/.env.app`, руками. В git не коммитим.

---

## Ловушки

- **Пакеты в GHCR по умолчанию приватные.** Без `docker login ghcr.io` на
  сервере `docker compose pull` падает с `denied: unauthorized`.
- **Джоба `deploy` красная, пока нет секретов `SSH_HOST`, `SSH_USER`,
  `SSH_PRIVATE_KEY`, `SSH_KNOWN_HOSTS`.** Это ожидаемо до покупки сервера, а не
  поломка пайплайна. Шаги проверки в `ci.yml` специально превращают код 255 от
  ssh в осмысленное сообщение.
- **`SSH_KNOWN_HOSTS` должен совпадать с `SSH_HOST` посимвольно**, иначе
  «Host key verification failed». Ключ хоста берётся из секрета, а не
  `ssh-keyscan` на месте: keyscan доверяет тому, кто ответил.
- **Пароль базы лежит в двух файлах** — `.env.db` и `.env.app`. Разойдутся —
  `password authentication failed`. Меняются только вместе.
- **Том `caddy_data` терять нельзя**: в нём сертификаты и ACME-аккаунт. После
  удаления Caddy выпустит всё заново и может упереться в лимит Let's Encrypt —
  50 сертификатов на домен в неделю.
- **`docker compose down -v` на сервере стирает `pgdata`**, то есть весь
  прогресс игроков. Автоматических бэкапов нет, владелец делает `pg_dump` сам.
- **В `postgres:18` том переехал** с `/var/lib/postgresql/data` на
  `/var/lib/postgresql`. По старому пути данные молча не сохраняются:
  контейнер поднимется, база будет пустой.
- **Версия Postgres одна и та же** в локальном compose, в CI-сервисе и на
  сервере. Расхождение мажора ловится не тестами, а продом.
- **Домен — бесплатный поддомен DuckDNS.** На голый IP Let's Encrypt выдаёт
  только 6-дневные сертификаты, требующие присмотра; запасной путь описан в
  `docs/tls.md`.
- `KOSYNKA_DB_POOL_SIZE` × число контейнеров не должно упираться в
  `max_connections`, и в тот же лимит лезет разовый запуск миграций.

---

## Правки в этой области

`.gitlab-ci.yml` — только линтеры и тесты, деплоя там нет; доставка живёт
исключительно в `.github/workflows/ci.yml`. Меняешь один — посмотри, не должен
ли измениться второй.

Перед коммитом изменений в `deploy/` или `Dockerfile`:

```bash
docker compose config -q && docker compose -f deploy/docker-compose.yml config -q
bash -n deploy/release.sh
poetry2 run pytest tests -q
```
