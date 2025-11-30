# web/routers/public.py
import sys
import os
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# --- Хак для импорта из родительской папки (чтобы видеть db.py и models.py) ---
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
from models import Tracking

# Создаем роутер
router = APIRouter()

# Настраиваем шаблоны (путь указываем относительно корня запуска, обычно это web/)
templates = Jinja2Templates(directory="templates")

# Зависимость для получения сессии БД
async def get_db():
    async with SessionLocal() as session:
        yield session

@router.get("/")
async def read_root(request: Request):
    """Главная страница"""
    return templates.TemplateResponse("index.html", {
        "request": request,
        "data": None,
        "query": ""
    })

@router.get("/search")
async def search_container(
    request: Request, 
    q: str = "", 
    db: AsyncSession = Depends(get_db)
):
    """
    Поиск контейнера.
    Работает и как обычная страница (если открыть ссылку),
    и (в будущем) как API для HTMX.
    """
    query_str = q.strip().upper()
    tracking_info = None

    if query_str:
        # Ищем по номеру контейнера
        result = await db.execute(
            select(Tracking)
            .where(Tracking.container_number == query_str)
            .order_by(Tracking.operation_date.desc())
            .limit(1)
        )
        tracking_info = result.scalar_one_or_none()

    return templates.TemplateResponse("index.html", {
        "request": request,
        "data": tracking_info,
        "query": query_str
    })