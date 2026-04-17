"""drop keywords from topics

Revision ID: 640968141458
Revises: 6a8262812ad0
Create Date: 2026-04-17 16:19:03.126535

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '640968141458'
down_revision: Union[str, None] = '6a8262812ad0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('topics', 'keywords')


def downgrade() -> None:
    op.add_column('topics', sa.Column('keywords', postgresql.ARRAY(sa.Text()), nullable=True))
