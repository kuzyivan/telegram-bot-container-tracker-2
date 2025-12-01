import sys
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from fastapi import APIRouter, Request, Depends
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

# --- Хак для импорта из родительской папки ---
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
# Импортируем модели для аналитики
from models import User, Subscription, UserRequest, Train
from model.terminal_container import TerminalContainer

router = APIRouter(prefix="/admin", tags=["admin"])

# --- НАСТРОЙКА ШАБЛОНОВ (Абсолютный путь) ---
current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))
# --------------------------------------------

async def get_db():
    async with SessionLocal() as session:
        yield session

@router.get("/dashboard")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Главный дашборд статистики.
    Собирает KPI, данные для графиков и лог последних запросов.
    """
    
    # --- БЛОК 1: KPI Карточки ---
    
    # 1. Всего пользователей
    total_users = await db.scalar(select(func.count(User.id))) or 0
    
    # 2. Активные подписки
    active_subs = await db.scalar(
        select(func.count(Subscription.id))
        .where(Subscription.is_active == True)
    ) or 0
    
    # 3. Запросов за сегодня
    # Используем func.date() для приведения timestamp к дате
    requests_today = await db.scalar(
        select(func.count(UserRequest.id))
        .where(func.date(UserRequest.timestamp) == datetime.now().date())
    ) or 0

    # 4. Общее количество отправленных поездов (из таблицы Train)
    trains_count = await db.scalar(select(func.count(Train.id))) or 0

    # --- БЛОК 2: График "Активность запросов" (за последние 14 дней) ---
    fourteen_days_ago = datetime.now() - timedelta(days=14)
    
    activity_stmt = (
        select(
            func.date(UserRequest.timestamp).label("date"), 
            func.count(UserRequest.id).label("count")
        )
        .where(UserRequest.timestamp >= fourteen_days_ago)
        .group_by(func.date(UserRequest.timestamp))
        .order_by("date")
    )
    activity_res = await db.execute(activity_stmt)
    activity_data = activity_res.all()
    
    # Подготовка данных для Chart.js (JSON)
    # strftime нужен, чтобы дата стала строкой
    chart_activity_labels = [row.date.strftime("%d.%m") for row in activity_data]
    chart_activity_values = [row.count for row in activity_data]

    # --- БЛОК 3: График "Топ Клиентов" ---
    clients_stmt = (
        select(TerminalContainer.client, func.count(TerminalContainer.id).label("count"))
        .where(TerminalContainer.train.isnot(None))
        .where(TerminalContainer.client.isnot(None))
        .where(TerminalContainer.client != "")
        .group_by(TerminalContainer.client)
        .order_by(desc("count"))
        .limit(7)
    )
    clients_res = await db.execute(clients_stmt)
    clients_data = clients_res.all()
    
    chart_clients_labels = [row.client for row in clients_data]
    chart_clients_values = [row.count for row in clients_data]

    # --- БЛОК 4: Таблица "Живой фид" (Последние 10 запросов) ---
    feed_stmt = (
        select(UserRequest, User)
        .join(User, UserRequest.user_telegram_id == User.telegram_id, isouter=True)
        .order_by(desc(UserRequest.timestamp))
        .limit(10)
    )
    feed_res = await db.execute(feed_stmt)
    
    feed_data = []
    for req, usr in feed_res:
        username_display = "Неизвестный"
        if usr:
            username_display = usr.username or f"ID: {usr.telegram_id}"
            
        feed_data.append({
            "username": username_display,
            "query": req.query_text,
            "time": req.timestamp.strftime("%H:%M %d.%m")
        })

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        # KPI
        "kpi_users": total_users,
        "kpi_subs": active_subs,
        "kpi_requests_today": requests_today,
        "kpi_trains": trains_count,
        # Charts (передаем как JSON строки)
        "chart_activity_labels": json.dumps(chart_activity_labels),
        "chart_activity_values": json.dumps(chart_activity_values),
        "chart_clients_labels": json.dumps(chart_clients_labels),
        "chart_clients_values": json.dumps(chart_clients_values),
        # Table
        "feed_data": feed_data
    })

@router.get("/schedule")
async def train_schedule(request: Request, db: AsyncSession = Depends(get_db)):
    """Страница графика отправки поездов на будущий месяц."""
    
    today = datetime.now().date()
    next_month = today + timedelta(days=30)

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