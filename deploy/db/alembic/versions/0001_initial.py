"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-06-01

Génère l'ensemble du schéma à partir des modèles SQLAlchemy.
En production : `alembic upgrade head` (ou exécuter db/schema.sql qui inclut
les partitions + index GIN trigram non gérés automatiquement par autogenerate).
"""
from alembic import op
import sqlalchemy as sa
from models import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    Base.metadata.create_all(bind)
    # Index spécialisés (recherche plaque ultra-rapide)
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE INDEX IF NOT EXISTS idx_plates_plate_trgm ON plates USING gin (plate gin_trgm_ops)")


def downgrade():
    bind = op.get_bind()
    Base.metadata.drop_all(bind)
