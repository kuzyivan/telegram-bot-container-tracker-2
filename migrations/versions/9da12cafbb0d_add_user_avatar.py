"""add user avatar

Revision ID: 9da12cafbb0d
Revises: 84a01ea7c2aa
Create Date: 2025-12-09 22:50:48.610649

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '9da12cafbb0d'
down_revision: Union[str, None] = '84a01ea7c2aa'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Оставляем ТОЛЬКО добавление колонок
    op.add_column('users', sa.Column('avatar_url', sa.String(), nullable=True))
    op.add_column('users', sa.Column('job_title', sa.String(), nullable=True))
    op.add_column('users', sa.Column('phone', sa.String(), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    # Оставляем ТОЛЬКО удаление колонок
    op.drop_column('users', 'phone')
    op.drop_column('users', 'job_title')
    op.drop_column('users', 'avatar_url')