"""player device_id

Идентичность устройства, отделённая от токена: позволяет вернуть игроку его
запись после переустановки приложения.

Миграция обратно совместима — колонка nullable, старый код продолжает работать
с новой схемой. Это требование порядка выкатки: alembic upgrade head идёт до
docker compose up -d, и в этот момент база уже новая, а код ещё старый.

Revision ID: 6be62dd928db
Revises: a2eee5721208
Create Date: 2026-07-31 21:29:45.500267

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "6be62dd928db"
down_revision: str | None = "a2eee5721208"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("players", sa.Column("device_id", sa.String(length=128), nullable=True))
    # UNIQUE, потому что device_id — ключ идемпотентности регистрации.
    # В PostgreSQL несколько NULL уникальности не нарушают, поэтому игроки
    # без device_id прекрасно сосуществуют.
    op.create_unique_constraint(op.f("uq_players_device_id"), "players", ["device_id"])


def downgrade() -> None:
    # Порядок обязателен: ограничение снимается до колонки, на которой стоит.
    op.drop_constraint(op.f("uq_players_device_id"), "players", type_="unique")
    op.drop_column("players", "device_id")
