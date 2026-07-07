"""add password_hash to users for backend-owned credentials auth

Revision ID: 010_password_hash
Revises: 3805b3192baa
Create Date: 2026-07-07

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '010_password_hash'
down_revision: Union[str, None] = '3805b3192baa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: rows provisioned via Google OAuth (google_sub) have no password.
    op.add_column('users', sa.Column('password_hash', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'password_hash')
