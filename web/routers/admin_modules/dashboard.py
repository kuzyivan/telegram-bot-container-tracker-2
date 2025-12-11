import json
from datetime import datetime, timedelta, date
from typing import Optional
from fastapi import APIRouter, Request, Depends, Query
from sqlalchemy import select, func, desc, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models import User, UserRequest, Train, Tracking
from model.terminal_container import TerminalContainer
from web.auth import admin_required
from .common import templates, get_db

router = APIRouter()

async def get_dashboard_stats(session: AsyncSession, date_from: date, date_to: date):
    """Собирает статистику для дашборда."""
    def filter_date(query, column):
        return query.where(column >= date_from).where(column <= date_to)

    # 1. Новые пользователи
    new_users = await session.scalar(filter_date(select(func.count(User.id)), User.created_at)) or 0
    
    # 2. Активные поезда (за последние 45 дней, не выгруженные)
    active_trains = await session.scalar(
        select(func.count(Train.id))
        .where(Train.last_operation_date >= (datetime.now() - timedelta(days=45)))
        .where(and_(Train.last_operation.not_ilike('%выгрузка%'), Train.last_operation.isnot(None)))
    ) or 0

    # 3. Всего отправлено (по дате создания в системе или dispatch_date - берем dispatch_date для точности факта)
    # Если нужно "Сколько добавлено в систему", то created_at. Если "Сколько уехало", то dispatch_date.
    # Оставим created_at для метрики "Обработано заявок/импортов", а ритмичность сделаем по dispatch_date.
    total_sent_stmt = select(func.count(TerminalContainer.id))
    total_sent = await session.scalar(filter_date(total_sent_stmt, TerminalContainer.created_at)) or 0

    # 4. Средний срок доставки
    avg_delivery_stmt = (
        select(func.avg(func.extract('day', Tracking.trip_end_datetime - Tracking.trip_start_datetime)))
        .where(Tracking.trip_end_datetime.isnot(None))
        .where(Tracking.trip_start_datetime.isnot(None))
        .where(func.date(Tracking.trip_end_datetime) >= date_from)
        .where(func.date(Tracking.trip_end_datetime) <= date_to)
    )
    avg_delivery_days = await session.scalar(avg_delivery_stmt) or 0

    # --- 🔥 ГРАФИК: Ритмичность погрузки (по dispatch_date) ---
    # Считаем количество контейнеров, отправленных в каждый конкретный день
    rhythm_stmt = (
        select(TerminalContainer.dispatch_date, func.count(TerminalContainer.id))
        .where(TerminalContainer.dispatch_date.isnot(None))  # Только отправленные
        .where(TerminalContainer.dispatch_date >= date_from)
        .where(TerminalContainer.dispatch_date <= date_to)
        .group_by(TerminalContainer.dispatch_date)
        .order_by(TerminalContainer.dispatch_date)
    )
    rhythm_res = await session.execute(rhythm_stmt)
    rhythm_rows = rhythm_res.all()
    
    # Преобразуем в словарь {дата: кол-во}
    rhythm_dict = {r[0]: r[1] for r in rhythm_rows if r[0]}
    
    rhythm_labels = []
    rhythm_values = []
    
    # Проходим по всем дням диапазона, чтобы заполнить пробелы нулями
    current = date_from
    while current <= date_to:
        rhythm_labels.append(current.strftime('%d.%m')) # Формат для графика
        val = rhythm_dict.get(current, 0)
        rhythm_values.append(val)
        current += timedelta(days=1)

    # Для линии тренда можно использовать те же данные или сгладить их
    trend_values = rhythm_values 

    # 5. Топ Клиенты (по количеству контейнеров)
    clients_stmt = (
        select(TerminalContainer.client, func.count(TerminalContainer.id).label('cnt'))
        .where(func.date(TerminalContainer.created_at) >= date_from)
        .where(func.date(TerminalContainer.created_at) <= date_to)
        .where(TerminalContainer.client.isnot(None))
        .group_by(TerminalContainer.client)
        .order_by(desc('cnt'))
        .limit(8)
    )
    clients_res = await session.execute(clients_stmt)
    clients_rows = clients_res.all()
    clients_labels = [r.client for r in clients_rows]
    clients_values = [r.cnt for r in clients_rows]

    # 6. Статистика запросов (UserRequest)
    req_stmt = (
        select(func.date(UserRequest.timestamp).label("date"), func.count(UserRequest.id))
        .where(func.date(UserRequest.timestamp) >= date_from)
        .where(func.date(UserRequest.timestamp) <= date_to)
        .group_by('date')
        .order_by('date')
    )
    req_res = await session.execute(req_stmt)
    req_rows = req_res.all()
    
    # Также заполняем пропуски для графика запросов, чтобы даты совпадали
    req_dict = {r.date: r[1] for r in req_rows if r.date}
    req_labels = []
    req_values = []
    current_req = date_from
    while current_req <= date_to:
        req_labels.append(current_req.strftime('%d.%m'))
        req_values.append(req_dict.get(current_req, 0))
        current_req += timedelta(days=1)

    return {
        "new_users": new_users,
        "active_trains": active_trains,
        "total_sent": total_sent,
        "avg_delivery_days": round(avg_delivery_days, 1),
        "rhythm_labels": json.dumps(rhythm_labels),
        "rhythm_values": json.dumps(rhythm_values),
        "trend_values": json.dumps(trend_values),
        "clients_labels": json.dumps(clients_labels),
        "clients_values": json.dumps(clients_values),
        "req_labels": json.dumps(req_labels),
        "req_values": json.dumps(req_values),
    }

@router.get("/dashboard")
async def dashboard(
    request: Request, 
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_required)
):
    today = datetime.now().date()
    # По умолчанию берем последние 30 дней
    d_from = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else today - timedelta(days=30)
    d_to = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else today

    stats = await get_dashboard_stats(db, d_from, d_to)
    
    # Лента последних действий
    feed_stmt = select(UserRequest, User).join(User, UserRequest.user_telegram_id == User.telegram_id, isouter=True).order_by(desc(UserRequest.timestamp)).limit(8)
    feed_res = await db.execute(feed_stmt)
    feed_data = []
    for req, usr in feed_res:
        username = usr.username or (f"ID: {usr.telegram_id}" if usr else "Неизвестный")
        feed_data.append({"username": username, "query": req.query_text, "time": req.timestamp.strftime("%H:%M %d.%m")})

    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": current_user, "feed_data": feed_data,
        "current_date_from": d_from, "current_date_to": d_to, **stats
    })