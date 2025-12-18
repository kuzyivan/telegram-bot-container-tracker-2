from sqlalchemy.orm import Session
from models.system_setting import SystemSetting
# Импортируем наши константы
from web.constants import DEFAULT_VAT_RATE, DEFAULT_GONDOLA_COEFF

def seed_default_settings(db: Session):
    """
    Заполняет базу данных настройками по умолчанию, если они отсутствуют.
    """
    default_settings = [
        {"key": "vat_rate", "value": str(DEFAULT_VAT_RATE), "description": "Ставка НДС (%)"},
        # Используем константу для коэффициента
        {"key": "gondola_coeff", "value": str(DEFAULT_GONDOLA_COEFF), "description": "Понижающий коэффициент на полувагоны"},
        {"key": "default_profit_percent", "value": "10.0", "description": "Процент рентабельности по умолчанию (%)"},
        {"key": "overhead_cost_per_wagon", "value": "5000.0", "description": "Накладные расходы на вагон (руб)"},
        {"key": "usd_exchange_rate", "value": "90.0", "description": "Курс доллара для расчетов"},
        {"key": "key_rate", "value": "16.0", "description": "Ключевая ставка ЦБ (%)"},
    ]

    for setting in default_settings:
        exists = db.query(SystemSetting).filter_by(key=setting["key"]).first()
        if not exists:
            new_setting = SystemSetting(
                key=setting["key"],
                value=setting["value"],
                description=setting["description"]
            )
            db.add(new_setting)
    
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    print("Default settings seeded successfully.")