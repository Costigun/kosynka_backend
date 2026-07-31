# Настройка доставки кода

Гайд проходится **один раз**, после покупки сервера. Дальше доставка работает сама:
пуш в `main` → GitHub Actions → образ в GHCR → ssh на сервер → `docker compose up -d`.

```
git push origin main
        │
        ▼
GitHub Actions (.github/workflows/ci.yml)
  ├── quality   ruff, mypy, poetry check --lock, unit-тесты,
  │             alembic upgrade head + alembic check, API-тесты (postgres:18)
  └── deploy    ← только при успехе quality
        docker build → ghcr.io/costigun/kosynka-backend:<sha>
        rsync deploy/ → /opt/kosynka
        ssh → bash release.sh
              ├── docker compose pull
              ├── alembic upgrade head      ← сначала схема
              ├── docker compose up -d      ← потом код
              └── ждём healthcheck          ← иначе деплой считается упавшим
```

На сервере три контейнера: Caddy (порты 80 и 443, TLS), приложение и PostgreSQL 18.
Наружу смотрит только Caddy — приложение и база доступны лишь внутри compose-сети.

## HTTPS

Включён. TLS терминирует Caddy, сертификат Let's Encrypt на бесплатный поддомен
DuckDNS — он получает и продлевает его сам, без внешних клиентов и таймеров.
Обращения по `http://` редиректятся на `https://` автоматически.

Как это было настроено и как переиграть — в [`tls.md`](tls.md).

---

## Что нужно до начала

- **Сервер.** 2 vCPU / 2 ГБ RAM достаточно. При создании выбирай **чистый образ ОС**
  (Ubuntu 24.04 LTS или Debian 13); преднастроенный «Docker» из списка приложений
  хостера тоже сгодится, но версия там обычно старее — проще поставить самому.
- **Код приложения в репозитории.** Сейчас его нет: `Dockerfile` копирует `app/`,
  `alembic/`, `alembic.ini`, `pyproject.toml`, `poetry.lock`. Пока их нет, джоба
  `deploy` упадёт на сборке образа. Шаги 1–4 можно пройти заранее, шаг 5 — только после.

Дальше подставляй свой адрес вместо `SERVER_IP`.

---

## Шаг 1. Docker и пользователь для деплоя

Если хостер при создании сервера предлагает поле **user-data / cloud-init** —
вставь туда `deploy/cloud-init.yaml`, предварительно подставив свой публичный
ключ, и весь этот шаг сделается сам. Ключ создаётся в шаге 2, так что его
удобно сгенерировать заранее.

> В это поле нельзя вставлять `deploy/docker-compose.yml`. На момент создания
> сервера образа ещё не существует, env-файлов нет, логина в GHCR нет — и, главное,
> compose-файл кладёт на сервер CI при каждом деплое. Копия от хостера окажется
> вторым compose-проектом, конкурирующим за порт 80.

> **Yandex Cloud:** поля «Логин» и «SSH-ключ» в форме создания ВМ конфликтуют с
> user-data. Если заполнить их, консоль подставляет собственный cloud-config, и
> `deploy/cloud-init.yaml` не применяется — машина поднимется с твоим личным
> ключом, но без пользователя `deploy`. Либо оставляй эти поля пустыми и отдавай
> только user-data, либо проходи этот шаг руками уже на созданной машине.

Руками то же самое:

```bash
ssh root@SERVER_IP

curl -fsSL https://get.docker.com | sh

# rsync-ом CI доставляет deploy/ на сервер; в минимальных образах его нет.
apt-get update && apt-get install -y rsync

# Отдельный непривилегированный пользователь: CI заходит им, а не root-ом.
adduser --disabled-password --gecos "" deploy
usermod -aG docker deploy      # только после установки Docker: раньше группы нет

mkdir -p /opt/kosynka
chown deploy:deploy /opt/kosynka
```

В файрволе хостера открой 22, 80 и 443. Порт 80 нужен не только для редиректа:
через него идёт проверка владения доменом при выпуске и продлении сертификата.

Проверка: `docker version`, `docker compose version` и `rsync --version` отвечают.

---

## Шаг 2. SSH-ключ для GitHub Actions

На **своей машине** заведи отдельный ключ (не тот, которым ходишь сам):

```bash
ssh-keygen -t ed25519 -f ~/.ssh/kosynka_deploy -C "github-actions" -N ""
```

Публичную часть — на сервер:

```bash
ssh-copy-id -i ~/.ssh/kosynka_deploy.pub deploy@SERVER_IP
```

Теперь ключ **самого сервера** — он пойдёт в секрет `SSH_KNOWN_HOSTS`:

```bash
ssh-keyscan -t ed25519 SERVER_IP
```

Вывод — уже готовая строка формата `known_hosts`. Сверь отпечаток с тем, что
сообщает сам сервер, — `ssh-keyscan` доверяет тому, кто ответил, и от подмены
не защищает:

```bash
ssh-keyscan -t ed25519 SERVER_IP | ssh-keygen -lf -
ssh -i ~/.ssh/kosynka_deploy deploy@SERVER_IP 'ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub'
```

Обе команды должны напечатать одинаковый `SHA256:...`.

---

## Шаг 3. Файлы окружения на сервере

PostgreSQL 18 работает контейнером на том же сервере — отдельно создавать
ничего не нужно, `deploy/docker-compose.yml` поднимет его сам. Наружу база не
публикуется: до неё достаёт только приложение по compose-сети.

Нужны три файла. Они создаются руками один раз, **никогда не попадают в git**
и не затираются деплоем — `rsync` идёт с `--exclude='.env*'`.

Пароль базы генерируется один раз и подставляется в оба файла сразу, чтобы они
гарантированно совпали:

```bash
ssh deploy@SERVER_IP
cd /opt/kosynka

PGPASS=$(openssl rand -hex 16)

cat > .env.db <<EOF
POSTGRES_USER=kosynka
POSTGRES_PASSWORD=$PGPASS
POSTGRES_DB=kosynka
EOF

cat > .env.app <<EOF
KOSYNKA_DATABASE_URL=postgresql+asyncpg://kosynka:$PGPASS@db:5432/kosynka
EOF

cat > .env.site <<EOF
SITE_ADDR=имя.duckdns.org
ACME_EMAIL=твоя@почта
EOF

chmod 600 .env.db .env.app .env.site
unset PGPASS
```

`.env.site` читает Caddy: `SITE_ADDR` — доменное имя, на которое он получит
сертификат, `ACME_EMAIL` — адрес для предупреждений Let's Encrypt. Файл должен
существовать **до** первого деплоя: без него compose не стартует.

Три момента, на которых легко споткнуться:

- Драйвер именно `postgresql+asyncpg`, а не `postgresql`.
- Хост — `db`, имя сервиса в compose. Не `localhost`: внутри контейнера
  это он сам, а не соседний контейнер.
- **Без `?ssl=require`.** Соединение не выходит за пределы compose-сети,
  а Postgres в контейнере TLS по умолчанию не поднимает — с этим параметром
  приложение просто не подключится.

Пароль менять потом больно: он лежит и в базе, и в DSN. Если всё же придётся —
меняй в обоих файлах и пересоздавай пользователя в базе.

### Бэкапы

Их **никто не делает автоматически** — это цена того, что база своя, а не
managed. Снять дамп:

```bash
ssh deploy@SERVER_IP 'cd /opt/kosynka && docker compose exec -T db pg_dump -U kosynka kosynka' > kosynka-$(date +%F).sql
```

Восстановить:

```bash
cat kosynka-2026-07-31.sql | ssh deploy@SERVER_IP 'cd /opt/kosynka && docker compose exec -T db psql -U kosynka kosynka'
```

Данные лежат в томе `pgdata` и переживают передеплой. Стирает их только
`docker compose down -v` — эту команду на сервере выполнять не нужно никогда.

### Образ из GHCR

Логин не требуется: пакет `kosynka-backend` публичный, `docker compose pull`
тянет его анонимно. Если однажды сделаешь пакет приватным, на сервере
понадобится `docker login ghcr.io -u Costigun` с classic PAT (скоуп
`read:packages`).

---

## Шаг 4. Секреты GitHub

`Settings → Secrets and variables → Actions → New repository secret`:

| Имя | Значение |
|---|---|
| `SSH_HOST` | `SERVER_IP` |
| `SSH_USER` | `deploy` |
| `SSH_PRIVATE_KEY` | содержимое `~/.ssh/kosynka_deploy` целиком, вместе со строками `-----BEGIN/END-----` |
| `SSH_KNOWN_HOSTS` | строка из шага 2 |

`GITHUB_TOKEN` для пуша образа в GHCR выдаётся автоматически — заводить не нужно.

Окружение `production` GitHub создаст сам при первом запуске. Если позже захочешь
ручное подтверждение перед раскаткой — `Settings → Environments → production →
Required reviewers`.

---

## Шаг 5. Первый деплой

Доставка срабатывает на пуш в `main`, а прямые коммиты в `main` в этом проекте
не делаются — значит, через merge PR:

```bash
git push -u origin feat/cd-k3s-werf
gh pr create --base main --title "Доставка через docker compose" --fill
# ревью → merge в main
```

Смотреть выкатку: `gh run watch` или вкладка Actions.

Проверка после зелёного пайплайна:

```bash
curl https://имя.duckdns.org/healthz
# {"status":"ok"}

curl -sI http://имя.duckdns.org/healthz | head -1
# HTTP/1.1 308 Permanent Redirect

ssh deploy@SERVER_IP 'cd /opt/kosynka && docker compose ps'
# caddy  ...  Up
# app    ...  Up (healthy)
# db     ...  Up (healthy)
```

Первый запрос после деплоя может занять несколько секунд — Caddy в этот момент
получает сертификат. Если не вышло: `docker compose logs caddy`.

---

## Дальше это выглядит так

```bash
git switch -c feat/что-то --no-track origin/main
# ... работа ...
git push -u origin feat/что-то
gh pr create --base main --fill
# merge → деплой едет сам
```

Откат на предыдущий образ, если новый оказался плохим:

```bash
ssh deploy@SERVER_IP
cd /opt/kosynka
echo "IMAGE_TAG=<sha предыдущего коммита>" > .env
docker compose up -d
```

**Откат не откатывает миграции.** Схема останется новой. Отсюда правило:
миграции пишутся так, чтобы предыдущая версия кода продолжала работать с новой
схемой — сначала добавить колонку nullable, и только следующим релизом сделать
её обязательной. Обратные миграции пишутся руками, Alembic сам этого не сделает.

Правильный откат — `git revert` и обычный деплой: git остаётся источником правды
о том, что крутится на сервере.

---


## Если упало

| Симптом | Причина и что делать |
|---|---|
| `Permission denied (publickey)` в джобе deploy | Не совпал `SSH_PRIVATE_KEY` или ключ не добавлен пользователю `deploy`. Проверь права: `/home/deploy/.ssh` должен быть 700, `authorized_keys` — 600, иначе sshd молча их игнорирует. |
| `Host key verification failed` | `SSH_KNOWN_HOSTS` пуст, от другого сервера или адрес в начале строки не совпадает с `SSH_HOST`. |
| `denied: ... unauthorized` при `docker compose pull` | На сервере не сделан `docker login ghcr.io`, либо PAT протух. |
| `password authentication failed for user "kosynka"` | Пароли в `.env.db` и `.env.app` разошлись. Проще пересоздать оба по шагу 3 и удалить том: `docker compose down -v` — но это стирает данные. |
| Деплой упал на «Контейнер app не стал healthy» | В выводе джобы уже приложены последние 50 строк логов контейнера. Чаще всего — неверный DSN. |
| `sslmode is an invalid keyword argument` | В DSN остался `?ssl=require` или `?sslmode=`. База в контейнере TLS не поднимает — параметр надо убрать. См. шаг 3. |
| `too many connections` | `KOSYNKA_DB_POOL_SIZE` вышел за `max_connections` (у postgres:18 по умолчанию 100). |
| Миграция упала, приложение не перезапустилось | Так и задумано: `release.sh` падает до `up -d`, старая версия продолжает работать. Чини миграцию и пушь заново. |
| `bind: address already in use` при `up -d` | Порт 80 занят чем-то ещё — чаще всего преднастроенным compose-проектом от хостера или системным nginx. |

Логи:

```bash
ssh deploy@SERVER_IP 'cd /opt/kosynka && docker compose logs -f --tail=100 app'
```
