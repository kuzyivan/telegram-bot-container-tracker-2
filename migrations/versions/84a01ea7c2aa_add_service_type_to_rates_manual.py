"""add_service_type_to_rates_manual

Revision ID: 84a01ea7c2aa
Revises: 44c171840ca0
Create Date: 2025-12-08 08:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# ✅ ВОТ ЭТИ СТРОКИ ОЧЕНЬ ВАЖНЫ:
revision: str = '84a01ea7c2aa'          # ID текущего файла (из названия)
down_revision: Union[str, None] = '44c171840ca0'  # ID предыдущего файла (finance_full)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Добавляем колонку service_type
    # server_default='TRAIN' заполнит уже существующие строки значением TRAIN
    op.add_column('rail_tariff_rates', 
        sa.Column('service_type', postgresql.ENUM('TRAIN', 'SINGLE', name='servicetype', create_type=False), 
                  nullable=False, 
                  server_default='TRAIN')
    )

    # 2. Удаляем старое ограничение уникальности
    # (Используем имя, которое было создано в предыдущей миграции)
    op.drop_constraint('uq_tariff_route_type', 'rail_tariff_rates', type_='unique')

    # 3. Создаем новое ограничение (с учетом service_type)
    op.create_unique_constraint(
        'uq_tariff_route_type_service', 
        'rail_tariff_rates', 
        ['station_from_code', 'station_to_code', 'container_type', 'service_type']
    )


def downgrade() -> None:
    # Откат изменений
    op.drop_constraint('uq_tariff_route_type_service', 'rail_tariff_rates', type_='unique')
    op.create_unique_constraint('uq_tariff_route_type', 'rail_tariff_rates', ['station_from_code', 'station_to_code', 'container_type'])
    op.drop_column('rail_tariff_rates', 'service_type')