# web/main.py
import sys
import os
import asyncio
from fastapi import FastAPI, Request, Depends, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# --- Хак для импорта из родительской папки ---
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from db import SessionLocal
from models import Tracking

app = FastAPI(title="Logistrail Tracker")

# Подключаем шаблоны
templates = Jinja2Templates(directory="templates")

# Зависимость для БД
async def get_db():
    async with SessionLocal() as session:
        yield session

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "data": None,
        "query": ""
    })

@app.get("/search", response_class=HTMLResponse)
async def search_container(
    request: Request, 
    q: str = "", 
    db: AsyncSession = Depends(get_db)
):
    query_str = q.strip().upper()
    tracking_info = None

    if query_str:
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