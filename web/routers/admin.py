from fastapi import APIRouter, Depends
from web.auth import admin_required

# 1. Создаем роутер
# ❌ УБИРАЕМ dependencies=[Depends(admin_required)] отсюда.
# Теперь права проверяются индивидуально в каждом модуле (dashboard, calculator и т.д.),
# что позволяет нам давать доступ менеджерам к отдельным страницам.
router = APIRouter(
    prefix="/admin", 
    tags=["admin"]
)

# 2. Импортируем модули
from web.routers.admin_modules import dashboard, calculator, schedule, companies

# 3. Подключаем роуты из модулей
router.include_router(dashboard.router)
router.include_router(calculator.router)
router.include_router(schedule.router)
router.include_router(companies.router)