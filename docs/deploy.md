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

На сервере один контейнер — приложение, слушает порт 80. Базы на сервере нет,
PostgreSQL managed у хостера.

## Про HTTPS

**Его нет.** Доменного имени у проекта нет по решению владельца, а Let's Encrypt не
выдаёт сертификаты на IP-адреса — значит TLS невозможен в принципе, и реверс-прокси
ради него не нужен. API работает по `http://SERVER_IP/`.

Из этого следует два факта, которые надо знать:

- Токен игрока ходит по сети **открытым текстом**. Он отвечает на вопрос «кто это»,
  а не защищает от накрутки (см. CLAUDE.md), но перехватить его в открытом Wi-Fi можно.
- **Android с API 28 блокирует незашифрованный HTTP по умолчанию.** В мобильном
  клиенте придётся явно разрешить cleartext — атрибутом `usesCleartextTraffic` в
  манифесте либо через `network_security_config.xml` с исключением для этого адреса.

Как это исправить, если решение изменится, — в разделе «Как добавить HTTPS» ниже.

---

## Что нужно до начала

- **Сервер.** 2 vCPU / 2 ГБ RAM достаточно. При создании выбирай **чистый образ ОС**
  (Ubuntu 24.04 LTS или Debian 13); преднастроенный «Docker» из списка приложений
  хостера тоже сгодится, но версия там обычно старее — проще поставить самому.
- **Managed PostgreSQL 18** у хостера.
- **Код приложения в репозитории.** Сейчас его нет: `Dockerfile` копирует `app/`,
  `alembic/`, `alembic.ini`, `pyproject.toml`, `poetry.lock`. Пока их нет, джоба
  `deploy` упадёт на сборке образа. Шаги 1–5 можно пройти заранее, шаг 6 — только после.

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

В файрволе хостера открой 22 и 80. Порт 443 не нужен — TLS нет.

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

## Шаг 3. Managed PostgreSQL

У хостера создай инстанс PostgreSQL 18, базу `kosynka` и пользователя для неё.
Разреши подключения с IP сервера.

DSN выглядит так:

```
postgresql+asyncpg://USER:PASSWORD@HOST:PORT/kosynka?ssl=require
```

Два момента, на которых легко споткнуться:

- Драйвер именно `postgresql+asyncpg`, а не `postgresql`.
- У asyncpg параметр называется `ssl`, а не `sslmode`. `?sslmode=require`
  уронит приложение на старте с невнятной ошибкой.

Посмотри `max_connections` у выбранного тарифа: в `deploy/docker-compose.yml`
стоит `KOSYNKA_DB_POOL_SIZE: "10"`, плюс соединения миграционного запуска.
На дешёвых тарифах лимит бывает 20–25 — тогда уменьшай.

---

## Шаг 4. Файл окружения на сервере

Он один, создаётся руками и **никогда не попадает в git**. CI его не трогает:
`rsync` идёт с `--exclude='.env*'`.

```bash
ssh deploy@SERVER_IP
cd /opt/kosynka

cat > .env.app <<'EOF'
KOSYNKA_DATABASE_URL=postgresql+asyncpg://USER:PASSWORD@HOST:PORT/kosynka?ssl=require
EOF

chmod 600 .env.app
```

Там же — логин в GHCR, иначе `docker compose pull` не вытянет приватный образ.
Нужен classic PAT со скоупом `read:packages`:

```bash
echo '<GitHub PAT с read:packages>' | docker login ghcr.io -u Costigun --password-stdin
```

Альтернатива: после первого деплоя сделать пакет публичным
(`github.com/users/Costigun/packages` → Package settings → Change visibility).
Тогда логин на сервере не нужен вовсе — в образе нет ничего секретного.

---

## Шаг 5. Секреты GitHub

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

## Шаг 6. Первый деплой

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
curl http://SERVER_IP/healthz

ssh deploy@SERVER_IP 'cd /opt/kosynka && docker compose ps'
# app   ...   Up (healthy)
```

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

## Как добавить HTTPS

Если решение по домену изменится, порядок такой:

1. **Получить имя.** Платить не обязательно: DuckDNS даёт бесплатный поддомен
   `что-нибудь.duckdns.org`, и он есть в Public Suffix List — значит лимиты
   Let's Encrypt считаются персонально, а не делятся со всеми пользователями
   сервиса. У `nip.io` и `sslip.io` этого свойства нет, там квота общая.
2. **Вернуть Caddy** в `deploy/docker-compose.yml` вторым сервисом: порты 80 и 443,
   тома `caddy_data` и `caddy_config` под сертификаты, `env_file: .env.site`.
   У приложения при этом `ports` меняется обратно на `expose: 8000`.
3. **`deploy/Caddyfile`** из двух строк: глобальный блок с `email {$ACME_EMAIL}`
   и блок `{$SITE_DOMAIN} { reverse_proxy app:8000 }`. Сертификат Caddy выпустит
   и будет продлевать сам.
4. **`/opt/kosynka/.env.site`** с `SITE_DOMAIN` и `ACME_EMAIL`, отдельно от `.env.app`:
   DSN базы не должен попадать в окружение прокси.
5. Открыть 443 в файрволе. Порт 80 оставить: ACME HTTP-01 проверяет домен через него.
6. В мобильном клиенте убрать разрешение cleartext-трафика.

История правок этих файлов лежит в git — восстанавливать с нуля не придётся.

---

## Если упало

| Симптом | Причина и что делать |
|---|---|
| `Permission denied (publickey)` в джобе deploy | Не совпал `SSH_PRIVATE_KEY` или ключ не добавлен пользователю `deploy`. Проверь права: `/home/deploy/.ssh` должен быть 700, `authorized_keys` — 600, иначе sshd молча их игнорирует. |
| `Host key verification failed` | `SSH_KNOWN_HOSTS` пуст, от другого сервера или адрес в начале строки не совпадает с `SSH_HOST`. |
| `denied: ... unauthorized` при `docker compose pull` | На сервере не сделан `docker login ghcr.io`, либо PAT протух. |
| Деплой упал на «Контейнер app не стал healthy» | В выводе джобы уже приложены последние 50 строк логов контейнера. Чаще всего — неверный DSN. |
| `sslmode is an invalid keyword argument` | В DSN `sslmode` вместо `ssl`. См. шаг 3. |
| `too many connections` | `KOSYNKA_DB_POOL_SIZE` вышел за `max_connections` managed-инстанса. |
| Миграция упала, приложение не перезапустилось | Так и задумано: `release.sh` падает до `up -d`, старая версия продолжает работать. Чини миграцию и пушь заново. |
| `bind: address already in use` при `up -d` | Порт 80 занят чем-то ещё — чаще всего преднастроенным compose-проектом от хостера или системным nginx. |

Логи:

```bash
ssh deploy@SERVER_IP 'cd /opt/kosynka && docker compose logs -f --tail=100 app'
```
