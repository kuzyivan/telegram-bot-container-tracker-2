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

    new_users = await session.scalar(filter_date(select(func.count(User.id)), User.created_at)) or 0
    
    active_trains = await session.scalar(
        select(func.count(Train.id))
        .where(Train.last_operation_date >= (datetime.now() - timedelta(days=45)))
        .where(and_(Train.last_operation.not_ilike('%выгрузка%'), Train.last_operation.isnot(None)))
    ) or 0

    total_sent_stmt = select(func.count(TerminalContainer.id))
    total_sent = await session.scalar(filter_date(total_sent_stmt, TerminalContainer.created_at)) or 0

    avg_delivery_stmt = (
        select(func.avg(func.extract('day', Tracking.trip_end_datetime - Tracking.trip_start_datetime)))
        .where(Tracking.trip_end_datetime.isnot(None))
        .where(Tracking.trip_start_datetime.isnot(None))
        .where(func.date(Tracking.trip_end_datetime) >= date_from)
        .where(func.date(Tracking.trip_end_datetime) <= date_to)
    )
    avg_delivery_days = await session.scalar(avg_delivery_stmt) or 0

    # Ритмичность
    rhythm_stmt = (
        select(func.date(TerminalContainer.created_at).label('date'), func.count(TerminalContainer.id))
        .where(func.date(TerminalContainer.created_at) >= date_from)
        .where(func.date(TerminalContainer.created_at) <= date_to)
        .group_by('date')
        .order_by('date')
    )
    rhythm_res = await session.execute(rhythm_stmt)
    rhythm_rows = rhythm_res.all()
    rhythm_dict = {r.date: r[1] for r in rhythm_rows}
    rhythm_labels = []
    rhythm_values = []
    current = date_from
    while current <= date_to:
        rhythm_labels.append(current.strftime('%d.%m'))
        rhythm_values.append(rhythm_dict.get(current, 0))
        current += timedelta(days=1)

    trend_values = rhythm_values # Упрощение

    # Клиенты
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

    # Запросы
    req_stmt = (
        select(func.date(UserRequest.timestamp).label("date"), func.count(UserRequest.id))
        .where(func.date(UserRequest.timestamp) >= date_from)
        .where(func.date(UserRequest.timestamp) <= date_to)
        .group_by('date')
        .order_by('date')
    )
    req_res = await session.execute(req_stmt)
    req_rows = req_res.all()
    req_labels = [r.date.strftime('%d.%m') for r in req_rows]
    req_values = [r[1] for r in req_rows]

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
    d_from = datetime.strptime(date_from, "%Y-%m-%d").date() if date_from else today - timedelta(days=30)
    d_to = datetime.strptime(date_to, "%Y-%m-%d").date() if date_to else today

    stats = await get_dashboard_stats(db, d_from, d_to)
    
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