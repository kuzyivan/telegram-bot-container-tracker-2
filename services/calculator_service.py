import logging
from typing import Dict, Any, Optional
from sqlalchemy import select, and_
from models_finance import SystemSetting, RailTariffRate, ServiceType
# Убираем битый импорт RailTariffService
from web.constants import DEFAULT_VAT_RATE

logger = logging.getLogger(__name__)

class CalculatorService:
    def __init__(self, db_session):
        self.db_session = db_session

    async def _get_float_setting(self, key: str, default: float) -> float:
        """Получает настройку из БД асинхронно."""
        try:
            stmt = select(SystemSetting).where(SystemSetting.key == key)
            result = await self.db_session.execute(stmt)
            setting = result.scalar_one_or_none()
            if setting and setting.value:
                return float(setting.value)
            return default
        except Exception:
            return default

    async def get_tariff(self, station_from: str, station_to: str, container_type: str, service_type: str) -> Optional[RailTariffRate]:
        """
        Ищет тариф в базе данных.
        (Перенесено из несуществующего RailTariffService)
        """
        try:
            # Приводим типы
            sType = service_type
            if hasattr(service_type, 'value'):
                sType = service_type.value
            
            # Строим запрос
            stmt = select(RailTariffRate).where(
                and_(
                    RailTariffRate.station_from_code == station_from,
                    RailTariffRate.station_to_code == station_to,
                    RailTariffRate.container_type == container_type,
                    RailTariffRate.service_type == sType
                )
            )
            result = await self.db_session.execute(stmt)
            return result.scalar_one_or_none()
        except Exception as e:
            logger.error(f"Error fetching tariff: {e}")
            return None

    def _calculate_simple_tariff(self, distance: float, weight: float) -> float:
        """
        Простая математика тарифа (если нет в БД).
        """
        base_rate_per_km = 50.0 
        weight_coeff = 1.0 + (max(0, weight - 10) * 0.05)
        return round(distance * base_rate_per_km * weight_coeff, 2)

    async def calculate_cost(self, route_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Полный расчет себестоимости (Асинхронный).
        """
        try:
            distance = float(route_data.get('distance', 0))
            weight = float(route_data.get('weight', 0))
            
            # 1. Считаем тариф (упрощенно или через БД, если нужно расширить логику)
            tariff_cost = self._calculate_simple_tariff(distance, weight)

            # 2. Получаем настройки (асинхронно)
            vat_percent = await self._get_float_setting("vat_rate", DEFAULT_VAT_RATE)
            profit_percent = await self._get_float_setting("default_profit_percent", 10.0)
            overhead_cost = await self._get_float_setting("overhead_cost_per_wagon", 5000.0)
            
            # Заглушки для доп. расходов
            station_expenses = 1500.0
            security_cost = 0.0
            insurance_cost = tariff_cost * 0.001
            
            # Суммируем
            total_cost_no_vat = (
                tariff_cost + 
                station_expenses + 
                security_cost + 
                insurance_cost + 
                overhead_cost
            )
            
            # НДС
            vat_amount = total_cost_no_vat * (vat_percent / 100.0)
            total_cost_with_vat = total_cost_no_vat + vat_amount
            
            # Маржа
            margin_amount = total_cost_with_vat * (profit_percent / 100.0)
            final_price = total_cost_with_vat + margin_amount

            return {
                "success": True,
                "breakdown": {
                    "tariff_cost": tariff_cost,
                    "station_expenses": station_expenses,
                    "security_cost": security_cost,
                    "insurance_cost": insurance_cost,
                    "overhead_cost": overhead_cost,
                    "total_cost_no_vat": total_cost_no_vat,
                    "vat_rate": vat_percent,
                    "vat_amount": vat_amount,
                    "total_cost_with_vat": total_cost_with_vat,
                    "profit_percent": profit_percent,
                    "margin_amount": margin_amount,
                    "final_price": final_price
                }
            }

        except Exception as e:
            logger.error(f"Error in calculation: {str(e)}")
            return {
                "success": False, 
                "error": str(e)
            }