from fastapi import APIRouter, Depends
from web.auth import admin_required

# 1. Создаем роутер в самом начале, чтобы он был доступен для импорта
router = APIRouter(
    prefix="/admin", 
    tags=["admin"],
    dependencies=[Depends(admin_required)] 
)

# 2. Импортируем модули (важно делать это ПОСЛЕ создания router, если бы модули зависели от него, 
# но в нашей архитектуре они независимы, поэтому просто подключаем их)
from web.routers.admin_modules import dashboard, calculator, schedule, companies

# 3. Подключаем роуты из модулей
router.include_router(dashboard.router)
router.include_router(calculator.router)
router.include_router(schedule.router)
router.include_router(companies.router)