import sys
import os
import json
from datetime import datetime, timedelta, date
from pathlib import Path
from fastapi import APIRouter, Request, Depends, Query
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
from models import User, Subscription, UserRequest, Train
from model.terminal_container import TerminalContainer

router = APIRouter(prefix="/admin", tags=["admin"])

current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

async def get_db():
    async with SessionLocal() as session:
        yield session

# --- Вспомогательная функция для подсчета KPI ---
async def get_kpi_data(session: AsyncSession, period: str):
    """Считает метрики в зависимости от выбранного периода."""
    
    now = datetime.now()
    start_date = None
    period_label = ""

    # Определение временных рамок
    if period == "today":
        start_date = now.date()
        period_label = "Сегодня"
    elif period == "week":
        start_date = (now - timedelta(days=7)).date()
        period_label = "7 дней"
    elif period == "month":
        start_date = (now - timedelta(days=30)).date()
        period_label = "30 дней"
    elif period == "all":
        start_date = None # За все время
        period_label = "Все время"
    
    # 1. Запросы (UserRequest)
    req_query = select(func.count(UserRequest.id))
    if start_date:
        if period == "today":
            req_query = req_query.where(func.date(UserRequest.timestamp) == start_date)
        else:
            req_query = req_query.where(func.date(UserRequest.timestamp) >= start_date)
    kpi_requests = await session.scalar(req_query) or 0

    # 2. Новые пользователи (User)
    user_query = select(func.count(User.id))
    if start_date:
        user_query = user_query.where(func.date(User.created_at) >= start_date)
    kpi_users = await session.scalar(user_query) or 0

    # 3. Контейнеры (TerminalContainer) - считаем по дате приема (accept_date)
    cont_query = select(func.count(TerminalContainer.id))
    if start_date:
        cont_query = cont_query.where(TerminalContainer.accept_date >= start_date)
    kpi_containers = await session.scalar(cont_query) or 0

    # 4. Поезда (Train) - считаем по дате создания или отправления
    # (Используем created_at как универсальный вариант, если departure_date нет)
    train_query = select(func.count(Train.id))
    if start_date:
        train_query = train_query.where(func.date(Train.created_at) >= start_date)
    kpi_trains = await session.scalar(train_query) or 0

    return {
        "kpi_requests": kpi_requests,
        "kpi_users": kpi_users,
        "kpi_containers": kpi_containers,
        "kpi_trains": kpi_trains,
        "period_label": period_label
    }

# --- Основной дашборд ---
@router.get("/dashboard")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    
    # По умолчанию показываем данные "За сегодня" (или "За все время", как решишь)
    # Давай по умолчанию "Сегодня", как было
    kpi_data = await get_kpi_data(db, "today")

    # --- Графики (оставляем логику 14 дней для графика активности) ---
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
    chart_activity_labels = [row.date.strftime("%d.%m") for row in activity_data]
    chart_activity_values = [row.count for row in activity_data]

    # --- Топ клиентов ---
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

    # --- Таблица фида ---
    feed_stmt = (
        select(UserRequest, User)
        .join(User, UserRequest.user_telegram_id == User.telegram_id, isouter=True)
        .order_by(desc(UserRequest.timestamp))
        .limit(10)
    )
    feed_res = await db.execute(feed_stmt)
    feed_data = []
    for req, usr in feed_res:
        username = usr.username or f"ID: {usr.telegram_id}" if usr else "Неизвестный"
        feed_data.append({
            "username": username,
            "query": req.query_text,
            "time": req.timestamp.strftime("%H:%M %d.%m")
        })

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        **kpi_data, # Распаковываем словарь KPI
        "chart_activity_labels": json.dumps(chart_activity_labels),
        "chart_activity_values": json.dumps(chart_activity_values),
        "chart_clients_labels": json.dumps(chart_clients_labels),
        "chart_clients_values": json.dumps(chart_clients_values),
        "feed_data": feed_data
    })

# --- НОВЫЙ ЭНДПОИНТ: Обновление только KPI (HTMX) ---
@router.get("/dashboard/kpi")
async def dashboard_kpi_update(
    request: Request, 
    period: str = Query("today"), # today, week, month, all
    db: AsyncSession = Depends(get_db)
):
    """Возвращает HTML-фрагмент с обновленными карточками."""
    kpi_data = await get_kpi_data(db, period)
    return templates.TemplateResponse("partials/kpi_cards.html", {
        "request": request,
        **kpi_data
    })

@router.get("/schedule")
async def train_schedule(request: Request, db: AsyncSession = Depends(get_db)):
    today = datetime.now().date()
    next_month = today + timedelta(days=30)
    stmt = select(Train).where(Train.departure_date >= today).order_by(Train.departure_date)
    result = await db.execute(stmt)
    return templates.TemplateResponse("schedule.html", {
        "request": request, "trains": result.scalars().all(), "period_start": today, "period_end": next_month
    })