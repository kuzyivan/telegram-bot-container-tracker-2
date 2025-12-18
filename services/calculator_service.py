import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models_finance import RailTariffRate, SystemSetting, Calculation, CalculationItem
from services.tariff_service import TariffStation # Если нужно для поиска имен

logger = logging.getLogger(__name__)

class PriceCalculator:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.settings = {}

    async def load_settings(self):
        """Загружает глобальные коэффициенты (НДС, маржа по умолчанию) в кэш"""
        stmt = select(SystemSetting)
        result = await self.session.execute(stmt)
        for setting in result.scalars():
            self.settings[setting.key] = setting.value

    def _get_float_setting(self, key: str, default: float = 0.0) -> float:
        """Безопасное получение настройки как float"""
        try:
            val = self.settings.get(key)
            return float(val) if val else default
        except ValueError:
            return default

    async def get_tariff(self, station_from_code: str, station_to_code: str, 
                         container_type: str, service_type: str = 'TRAIN') -> RailTariffRate | None:
        """Ищет базовый ЖД тариф в базе"""
        stmt = select(RailTariffRate).where(
            RailTariffRate.station_from_code == station_from_code,
            RailTariffRate.station_to_code == station_to_code,
            RailTariffRate.container_type == container_type,
            RailTariffRate.service_type == service_type
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def calculate_price(self, 
                            station_from_code: str, 
                            station_to_code: str, 
                            container_type: str, 
                            service_type: str = 'TRAIN') -> dict:
        """
        Главная функция расчета.
        Возвращает словарь с детализацией цены.
        """
        # 1. Загружаем настройки, если еще не загружены
        if not self.settings:
            await self.load_settings()

        # 2. Ищем тариф закупки (База)
        tariff = await self.get_tariff(station_from_code, station_to_code, container_type, service_type)
        
        if not tariff:
            return {"error": "Tariff not found", "details": "Тариф для данного направления не найден в базе."}

        # Базовая ставка (Закупка)
        base_rate = tariff.rate_no_vat

        # 3. Читаем настройки (Доп. расходы)
        # Пример: Если это повагонная отправка, можем добавить аренду вагона
        # Но пока берем общую логику.
        
        # Получаем маржу из настроек (по умолчанию 10 000 руб, если не задано)
        default_margin = self._get_float_setting("default_margin_fix", 10000.0)
        
        # НДС (20%)
        vat_percent = self._get_float_setting("vat_rate", 22.0)

        # --- ФОРМУЛА РАСЧЕТА ---
        # 1. Себестоимость = Тариф ЖД
        cost_price = base_rate
        
        # 2. Цена без НДС = Себестоимость + Маржа
        price_no_vat = cost_price + default_margin
        
        # 3. Сумма НДС
        vat_amount = price_no_vat * (vat_percent / 100)
        
        # 4. ИТОГО (С НДС)
        final_price = price_no_vat + vat_amount

        return {
            "success": True,
            "station_from": station_from_code, # Можно потом заменить на имя
            "station_to": station_to_code,
            "type": container_type,
            "service": service_type,
            
            # Финансы
            "base_rate": cost_price,       # Тариф закупки
            "margin": default_margin,      # Наша накрутка
            "price_no_vat": price_no_vat,  # Цена продажи без НДС
            "vat_amount": vat_amount,      # Сумма НДС
            "total_price": final_price     # Итого клиенту
        }