#!/usr/bin/env bash
# Выполняется НА СЕРВЕРЕ: CI кладёт этот файл в /opt/kosynka через rsync
# и запускает по ssh, передав IMAGE_TAG.
#
# Логика деплоя живёт здесь, а не в yaml-е workflow: так её видно целиком,
# и её можно прогнать руками, когда что-то пошло не так.

set -euo pipefail

cd /opt/kosynka

: "${IMAGE_TAG:?IMAGE_TAG не передан}"

# Compose подставляет ${IMAGE_TAG} в image: — тег коммита, а не latest,
# чтобы всегда было понятно, что именно крутится, и чтобы работал откат.
echo "IMAGE_TAG=${IMAGE_TAG}" > .env

docker compose pull

# База поднимается до миграций отдельным шагом: на первом деплое не запущено
# ничего, а `run --no-deps` сам её не поднял бы. --wait держит паузу,
# пока healthcheck не позеленеет, иначе миграции упрутся в неготовый Postgres.
docker compose up -d --wait db

# Миграции — ДО перезапуска приложения. В этот момент старый код работает
# с новой схемой, поэтому миграции должны быть обратно совместимыми:
# сначала добавить колонку nullable, сделать обязательной — следующим релизом.
docker compose run --rm --no-deps app alembic upgrade head

docker compose up -d --remove-orphans

# Деплой считается успешным только когда healthcheck позеленел.
status=starting
for _ in $(seq 1 30); do
	status=$(docker inspect --format '{{.State.Health.Status}}' "$(docker compose ps -q app)" 2>/dev/null || echo starting)
	[ "$status" = healthy ] && break
	sleep 2
done

if [ "$status" != healthy ]; then
	echo "Контейнер app не стал healthy (статус: ${status}). Последние логи:"
	docker compose logs --tail=50 app
	exit 1
fi

# Старые образы иначе съедают диск за пару месяцев.
docker image prune -f

echo "Задеплачено: ${IMAGE_TAG}"
