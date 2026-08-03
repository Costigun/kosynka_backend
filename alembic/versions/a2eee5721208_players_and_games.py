"""players and games

Первая миграция: игрок и партия.

Revision ID: a2eee5721208
Revises:
Create Date: 2026-07-31 18:59:28.521246

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "a2eee5721208"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "players",
        sa.Column("id", sa.Uuid(), nullable=False),
        # sha256 в hex — 64 символа. Сам токен не хранится.
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("xp_total", sa.Integer(), server_default="0", nullable=False),
        # nullable=False и server_default здесь обязательны оба: расхождение
        # по ним у timestamp-колонок уже ловилось alembic check.
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_players")),
        # Рабочий индекс горячего пути: поиск игрока по токену на каждом запросе.
        sa.UniqueConstraint("token_hash", name=op.f("uq_players_token_hash")),
    )
    op.create_table(
        "games",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("player_id", sa.Uuid(), nullable=False),
        sa.Column("client_game_id", sa.Uuid(), nullable=False),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("xp_awarded", sa.Integer(), nullable=False),
        sa.Column("xp_formula_version", sa.Integer(), nullable=False),
        # Задел на итерацию 2: складывается без проверки.
        sa.Column(
            "deal_cards",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "replay",
            postgresql.JSONB(none_as_null=True, astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["player_id"],
            ["players.id"],
            name=op.f("fk_games_player_id_players"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_games")),
        # Шлюз идемпотентности: повтор запроса от клиента отсекается здесь,
        # до того как будет тронут xp_total.
        sa.UniqueConstraint(
            "player_id", "client_game_id", name=op.f("uq_games_player_id_client_game_id")
        ),
    )


def downgrade() -> None:
    # Порядок обязателен: games ссылается на players внешним ключом.
    op.drop_table("games")
    op.drop_table("players")
