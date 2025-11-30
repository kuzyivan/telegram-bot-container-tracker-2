# web/main.py
import sys
import os
from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

# --- Хак для импорта из родительской папки ---
# Это нужно, чтобы Python видел файлы models.py, db.py и config.py
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from db import SessionLocal
from models import Tracking

# Инициализация приложения
app = FastAPI(title="Logistrail Tracker")

# Подключаем папку с шаблонами (HTML)
templates = Jinja2Templates(directory="templates")

# Подключаем статику (если захочешь добавить свои логотипы/картинки в папку static)
# app.mount("/static", StaticFiles(directory="static"), name="static")

# --- Зависимость (Dependency) для получения сессии БД ---
# FastAPI сам откроет сессию перед запросом и закроет после
async def get_db():
    async with SessionLocal() as session:
        yield session

# --- 1. Главная страница (GET /) ---
@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Отображает главную страницу с формой поиска."""
    return templates.TemplateResponse("index.html", {
        "request": request,
        "data": None,
        "query": ""
    })

# --- 2. Поиск (GET /search) ---
@app.get("/search", response_class=HTMLResponse)
async def search_container(
    request: Request, 
    q: str = "",  # q - это параметр из строки запроса ?q=...
    db: AsyncSession = Depends(get_db)
):
    """Обрабатывает поиск контейнера."""
    query_str = q.strip().upper()
    tracking_info = None

    if query_str:
        # Ищем последнюю запись по этому контейнеру
        # Используем существующую модель Tracking
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