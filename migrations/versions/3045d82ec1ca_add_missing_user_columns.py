"""Add missing user columns

Revision ID: 3045d82ec1ca
Revises: b1b7c58c8ce4
Create Date: 2025-10-21 13:30:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = '3045d82ec1ca'
down_revision: Union[str, None] = 'b1b7c58c8ce4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Заполнение NULL значений перед изменением колонки
    op.execute(
        sa.text("UPDATE terminal_containers SET created_at = NOW() WHERE created_at IS NULL")
    )

    # --- Создание новых таблиц (из твоего архива) ---
    op.create_table('stations_cache',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('original_name', sa.String(), nullable=False),
        sa.Column('found_name', sa.String(), nullable=True),
        sa.Column('latitude', sa.Float(), nullable=True),
        sa.Column('longitude', sa.Float(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('original_name')
    )
    op.create_index('ix_stations_cache_found_name', 'stations_cache', ['found_name'], unique=False)
    op.create_index('ix_stations_cache_original_name', 'stations_cache', ['original_name'], unique=False)

    op.create_table('train_event_log',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('container_number', sa.String(length=11), nullable=False),
        sa.Column('train_number', sa.String(), nullable=False),
        sa.Column('event_description', sa.Text(), nullable=False),
        sa.Column('station', sa.String(), nullable=False),
        sa.Column('event_time', sa.DateTime(timezone=True), nullable=False),
        sa.Column('notification_sent_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_train_event_log_container_number', 'train_event_log', ['container_number'], unique=False)
    op.create_index('ix_train_event_log_train_number', 'train_event_log', ['train_number'], unique=False)

    op.create_table('subscriptions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('subscription_name', sa.String(), nullable=False),
        sa.Column('containers', postgresql.ARRAY(sa.String()), nullable=False),
        sa.Column('notification_time', sa.Time(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_telegram_id'], ['users.telegram_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_subscriptions_subscription_name', 'subscriptions', ['subscription_name'], unique=False)

    op.create_table('user_requests',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('query_text', sa.Text(), nullable=False),
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_telegram_id'], ['users.telegram_id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    op.create_table('subscription_emails',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('subscription_id', sa.Integer(), nullable=False),
        sa.Column('email_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['email_id'], ['user_emails.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id')
    )

    # --- Удаление старых таблиц (если они были) ---
    # Мы их комментируем или используем IF EXISTS, но в твоем дампе были drop_table
    op.execute("DROP TABLE IF EXISTS railway_stations CASCADE")
    op.execute("DROP TABLE IF EXISTS subscription_email_association CASCADE")
    op.execute("DROP TABLE IF EXISTS stats CASCADE")
    op.execute("DROP TABLE IF EXISTS tracking_subscriptions CASCADE")
    op.execute("DROP TABLE IF EXISTS train_operation_events CASCADE")

    # --- Изменение колонок ---
    op.add_column('terminal_containers', sa.Column('accept_date', sa.Date(), nullable=True))
    op.add_column('terminal_containers', sa.Column('accept_time', sa.Time(), nullable=True))
    op.add_column('terminal_containers', sa.Column('status', sa.String(), nullable=True))
    op.add_column('terminal_containers', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    
    op.alter_column('terminal_containers', 'created_at',
               existing_type=postgresql.TIMESTAMP(),
               type_=sa.DateTime(timezone=True),
               existing_nullable=True,
               server_default=sa.text('now()'),
               nullable=False)

    # Удаление старых колонок из terminal_containers
    for col in ['destination_station', 'zone', 'terminal', 'raw_comment', 'short_name', 'stock', 'customs_mode', 'status_comment', 'inn', 'note']:
        op.drop_column('terminal_containers', col)

    op.alter_column('tracking', 'container_number',
               existing_type=sa.VARCHAR(),
               nullable=False)
    op.create_index('ix_tracking_container_number', 'tracking', ['container_number'], unique=False)

    # User Emails
    op.alter_column('user_emails', 'created_at',
               existing_type=postgresql.TIMESTAMP(timezone=True),
               nullable=False)
    # op.drop_constraint('_user_email_uc', 'user_emails', type_='unique') # Может не существовать
    op.drop_index('ix_user_emails_user_telegram_id', table_name='user_emails')
    op.create_index('ix_user_emails_email', 'user_emails', ['email'], unique=False)
    
    # Пытаемся удалить FK, если он есть (нужно имя констрейнта, но alembic сам попробует)
    # op.drop_constraint('user_emails_user_telegram_id_fkey', 'user_emails', type_='foreignkey')
    
    op.create_foreign_key(None, 'user_emails', 'users', ['user_telegram_id'], ['telegram_id'], ondelete='CASCADE')
    op.drop_column('user_emails', 'is_verified')

    # Users
    op.add_column('users', sa.Column('first_name', sa.String(), nullable=True))
    op.add_column('users', sa.Column('last_name', sa.String(), nullable=True))
    op.add_column('users', sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    op.add_column('users', sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False))
    
    # op.drop_constraint('users_telegram_id_key', 'users', type_='unique')
    op.create_index('ix_users_telegram_id', 'users', ['telegram_id'], unique=True)


def downgrade() -> None:
    pass