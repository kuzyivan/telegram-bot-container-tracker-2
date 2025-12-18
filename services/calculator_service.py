import logging
from typing import Dict, Any, List, Optional
from services.rail_tariff_service import RailTariffService
from services.system_settings_service import SystemSettingsService
# Импортируем нашу новую константу
from web.constants import DEFAULT_VAT_RATE

logger = logging.getLogger(__name__)

class CalculatorService:
    def __init__(self, db_session):
        self.db_session = db_session
        self.settings_service = SystemSettingsService(db_session)
        self.rail_tariff_service = RailTariffService()

    def _get_float_setting(self, key: str, default: float) -> float:
        """Вспомогательный метод для получения числовой настройки"""
        try:
            value = self.settings_service.get_setting(key)
            if value is None:
                return default
            return float(value)
        except (ValueError, TypeError):
            return default

    def calculate_cost(self, route_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Расчет себестоимости перевозки
        """
        try:
            # Получаем базовые параметры
            distance = float(route_data.get('distance', 0))
            weight = float(route_data.get('weight', 0))
            wagon_type = route_data.get('wagon_type', 'box')
            
            # Получаем тариф РЖД
            rail_tariff = self.rail_tariff_service.calculate_tariff(
                distance=distance,
                weight=weight,
                wagon_type=wagon_type
            )

            # Получаем настройки из БД или используем константу
            # НДС теперь берется из DEFAULT_VAT_RATE, если в базе пусто
            vat_percent = self._get_float_setting("vat_rate", DEFAULT_VAT_RATE)
            profit_percent = self._get_float_setting("default_profit_percent", 10.0)
            overhead_cost = self._get_float_setting("overhead_cost_per_wagon", 5000.0)
            
            # Расчет составляющих
            tariff_cost = rail_tariff.get('total_cost', 0)
            
            # Расчет дополнительных расходов
            station_expenses = self._calculate_station_expenses(route_data)
            security_cost = self._calculate_security_cost(route_data)
            insurance_cost = self._calculate_insurance_cost(tariff_cost)
            
            # Полная себестоимость (без НДС)
            total_cost_no_vat = (
                tariff_cost + 
                station_expenses + 
                security_cost + 
                insurance_cost + 
                overhead_cost
            )
            
            # Расчет НДС
            vat_amount = total_cost_no_vat * (vat_percent / 100.0)
            
            # Итоговая себестоимость с НДС
            total_cost_with_vat = total_cost_no_vat + vat_amount
            
            # Расчет цены для клиента (с прибылью)
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

    def _calculate_station_expenses(self, data: Dict[str, Any]) -> float:
        return 1500.0

    def _calculate_security_cost(self, data: Dict[str, Any]) -> float:
        return 0.0

    def _calculate_insurance_cost(self, base_cost: float) -> float:
        return base_cost * 0.001