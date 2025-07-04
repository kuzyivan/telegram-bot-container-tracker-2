"""add delivery_channel to tracking

Revision ID: e5872c21d629
Revises: b1b7c58c8ce4
Create Date: 2025-07-04 14:21:17.583976

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5872c21d629'
down_revision: Union[str, None] = 'b1b7c58c8ce4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'tracking_subscriptions',
        sa.Column('delivery_channel', sa.String(), server_default='telegram')
    )

def downgrade() -> None:
    op.drop_column('tracking_subscriptions', 'delivery_channel')