from sqlalchemy.orm import Session
from models.system_setting import SystemSetting
# Импортируем нашу новую константу
from web.constants import DEFAULT_VAT_RATE

def seed_default_settings(db: Session):
    """
    Заполняет базу данных настройками по умолчанию, если они отсутствуют.
    """
    default_settings = [
        # Используем str(DEFAULT_VAT_RATE), чтобы значение всегда совпадало с константой
        {"key": "vat_rate", "value": str(DEFAULT_VAT_RATE), "description": "Ставка НДС (%)"},
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
    
    # Не делаем commit здесь, если сессия управляется снаружи, 
    # но обычно в seed-скриптах коммит нужен.
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    print("Default settings seeded successfully.")