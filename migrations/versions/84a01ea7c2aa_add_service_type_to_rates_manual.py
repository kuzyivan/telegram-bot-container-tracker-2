"""add_service_type_to_rates_manual

Revision ID: <ОСТАВЬ_ТОТ_ЧТО_СГЕНЕРИРОВАЛСЯ>
Revises: 44c171840ca0
Create Date: ...

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# !!! НЕ МЕНЯЙ revision ID, который был в файле !!!
# revision = ... (оставь как есть)
down_revision: Union[str, None] = '44c171840ca0' # Ссылка на предыдущую (Finance Full)
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Создаем Enum тип, если его нет (checkfirst=True сложно в alembic, поэтому просто пробуем)
    # Но так как ServiceType уже используется в calculations, тип в базе уже есть.
    # Мы просто используем его имя 'servicetype'.

    # 2. Добавляем колонку с дефолтным значением 'TRAIN'
    # server_default нужен, чтобы заполнить существующие строки
    op.add_column('rail_tariff_rates', 
        sa.Column('service_type', postgresql.ENUM('TRAIN', 'SINGLE', name='servicetype', create_type=False), 
                  nullable=False, 
                  server_default='TRAIN')
    )

    # 3. Удаляем старое ограничение уникальности (from + to + type)
    op.drop_constraint('uq_tariff_route_type', 'rail_tariff_rates', type_='unique')

    # 4. Создаем новое ограничение (from + to + type + SERVICE)
    op.create_unique_constraint(
        'uq_tariff_route_type_service', 
        'rail_tariff_rates', 
        ['station_from_code', 'station_to_code', 'container_type', 'service_type']
    )


def downgrade() -> None:
    # Возвращаем как было
    op.drop_constraint('uq_tariff_route_type_service', 'rail_tariff_rates', type_='unique')
    op.create_unique_constraint('uq_tariff_route_type', 'rail_tariff_rates', ['station_from_code', 'station_to_code', 'container_type'])
    op.drop_column('rail_tariff_rates', 'service_type')