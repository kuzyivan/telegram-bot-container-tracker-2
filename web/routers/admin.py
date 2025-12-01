# web/routers/admin.py
import sys
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc, case
from sqlalchemy.ext.asyncio import AsyncSession

# Импорты из корня
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))
from db import SessionLocal
from models import Train
from model.terminal_container import TerminalContainer

router = APIRouter(prefix="/admin", tags=["admin"])

# Путь к шаблонам
current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

async def get_db():
    async with SessionLocal() as session:
        yield session

@router.get("/dashboard")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """Главный дашборд статистики."""
    
    # 1. KPI: Общее количество отправленных поездов
    # Считаем поезда, у которых есть дата отправления или они созданы
    trains_count = await db.scalar(select(func.count(Train.id)))
    
    # 2. KPI: Общее количество отправленных контейнеров
    # Считаем контейнеры, привязанные к поездам
    containers_count = await db.scalar(
        select(func.count(TerminalContainer.id))
        .where(TerminalContainer.train.isnot(None))
    )

    # 3. График: Топ-10 Клиентов (Разбивка)
    clients_stmt = (
        select(TerminalContainer.client, func.count(TerminalContainer.id).label("count"))
        .where(TerminalContainer.train.isnot(None))
        .where(TerminalContainer.client.isnot(None))
        .group_by(TerminalContainer.client)
        .order_by(desc("count"))
        .limit(10)
    )
    clients_res = await db.execute(clients_stmt)
    clients_data = clients_res.all()
    
    # Подготовка данных для Chart.js (Клиенты)
    chart_clients_labels = [row.client for row in clients_data]
    chart_clients_values = [row.count for row in clients_data]

    # 4. График: Ритмичность погрузки (за последние 30 дней)
    # Группируем по дате приема (accept_date)
    thirty_days_ago = datetime.now() - timedelta(days=30)
    rhythm_stmt = (
        select(TerminalContainer.accept_date, func.count(TerminalContainer.id).label("count"))
        .where(TerminalContainer.accept_date >= thirty_days_ago.date())
        .group_by(TerminalContainer.accept_date)
        .order_by(TerminalContainer.accept_date)
    )
    rhythm_res = await db.execute(rhythm_stmt)
    rhythm_data = rhythm_res.all()

    # Подготовка данных для Chart.js (Ритмичность)
    # Форматируем дату в строку DD.MM
    chart_rhythm_labels = [row.accept_date.strftime("%d.%m") if row.accept_date else "Н/Д" for row in rhythm_data]
    chart_rhythm_values = [row.count for row in rhythm_data]

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "kpi_trains": trains_count,
        "kpi_containers": containers_count,
        # Передаем JSON-строки для JS
        "chart_clients_labels": json.dumps(chart_clients_labels),
        "chart_clients_values": json.dumps(chart_clients_values),
        "chart_rhythm_labels": json.dumps(chart_rhythm_labels),
        "chart_rhythm_values": json.dumps(chart_rhythm_values),
    })

@router.get("/schedule")
async def train_schedule(request: Request, db: AsyncSession = Depends(get_db)):
    """Страница графика отправки поездов на будущий месяц."""
    
    # Берем текущую дату
    today = datetime.now().date()
    # Дата через месяц
    next_month = today + timedelta(days=30)

    # Запрос: Поезда с датой отправления >= сегодня
    # Если departure_date нет, можно брать по created_at или показывать все "активные"
    stmt = (
        select(Train)
        .where(Train.departure_date >= today)
        .order_by(Train.departure_date)
    )
    result = await db.execute(stmt)
    trains = result.scalars().all()

    return templates.TemplateResponse("schedule.html", {
        "request": request,
        "trains": trains,
        "period_start": today,
        "period_end": next_month
    })