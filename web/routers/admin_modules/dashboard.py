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

    # 3. Всего отправлено (по dispatch_date для точности факта)
    total_sent_stmt = select(func.count(TerminalContainer.id))
    total_sent = await session.scalar(filter_date(total_sent_stmt, TerminalContainer.dispatch_date)) or 0

    # 4. Средний срок доставки
    avg_delivery_stmt = (
        select(func.avg(func.extract('day', Tracking.trip_end_datetime - Tracking.trip_start_datetime)))
        .where(Tracking.trip_end_datetime.isnot(None))
        .where(Tracking.trip_start_datetime.isnot(None))
        .where(func.date(Tracking.trip_end_datetime) >= date_from)
        .where(func.date(Tracking.trip_end_datetime) <= date_to)
    )
    avg_delivery_days = await session.scalar(avg_delivery_stmt) or 0

    # 5. Динамика грузооборота (Accepted vs Dispatched)
    # Принятые (Accepted)
    accepted_stmt = (
        select(TerminalContainer.accept_date, func.count(TerminalContainer.id))
        .where(TerminalContainer.accept_date.isnot(None))
        .where(TerminalContainer.accept_date >= date_from)
        .where(TerminalContainer.accept_date <= date_to)
        .group_by(TerminalContainer.accept_date)
        .order_by(TerminalContainer.accept_date)
    )
    accepted_res = await session.execute(accepted_stmt)
    accepted_dict = {r[0]: r[1] for r in accepted_res.all() if r[0]}

    # Отгруженные (Dispatched)
    dispatched_stmt = (
        select(TerminalContainer.dispatch_date, func.count(TerminalContainer.id))
        .where(TerminalContainer.dispatch_date.isnot(None))
        .where(TerminalContainer.dispatch_date >= date_from)
        .where(TerminalContainer.dispatch_date <= date_to)
        .group_by(TerminalContainer.dispatch_date)
        .order_by(TerminalContainer.dispatch_date)
    )
    dispatched_res = await session.execute(dispatched_stmt)
    dispatched_dict = {r[0]: r[1] for r in dispatched_res.all() if r[0]}

    # Выравнивание по датам
    turnover_labels = []
    accepted_values = []
    dispatched_values = []
    
    current = date_from
    while current <= date_to:
        turnover_labels.append(current.strftime('%d.%m'))
        accepted_values.append(accepted_dict.get(current, 0))
        dispatched_values.append(dispatched_dict.get(current, 0))
        current += timedelta(days=1)

    # 6. Топ Клиенты
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

    # 7. Статистика запросов
    req_stmt = (
        select(func.date(UserRequest.timestamp).label("date"), func.count(UserRequest.id))
        .where(func.date(UserRequest.timestamp) >= date_from)
        .where(func.date(UserRequest.timestamp) <= date_to)
        .group_by('date')
        .order_by('date')
    )
    req_res = await session.execute(req_stmt)
    req_rows = req_res.all()
    req_dict = {r.date: r[1] for r in req_rows if r.date}
    
    req_labels = []
    req_values = []
    
    current_req = date_from
    while current_req <= date_to:
        req_labels.append(current_req.strftime('%d.%m'))
        req_values.append(req_dict.get(current_req, 0))
        current_req += timedelta(days=1)

    # === 🔥 НОВОЕ: Диаграммы стоков (Разбивка по направлениям) ===
    # Группируем по Направлению, Стоку и Размеру, чтобы посчитать TEU и состав
    stock_stmt = (
        select(
            TerminalContainer.direction,
            TerminalContainer.stock,
            TerminalContainer.size,
            func.count(TerminalContainer.id)
        )
        .where(TerminalContainer.dispatch_date.is_(None)) # Только те, что сейчас на терминале
        .group_by(TerminalContainer.direction, TerminalContainer.stock, TerminalContainer.size)
    )
    
    stock_res = await session.execute(stock_stmt)
    
    # Обработка данных в Python для удобной структуры
    # Structure: Key=(Direction, Stock) -> {c20: int, c40: int, teu: int}
    stocks_map = {}
    
    for row in stock_res:
        direction = row.direction or "Без направления"
        stock = row.stock or "Основной"
        size_val = str(row.size or "")
        count = row[3]
        
        key = (direction, stock)
        if key not in stocks_map:
            stocks_map[key] = {
                "title": f"{direction}",
                "subtitle": stock,
                "c20": 0,
                "c40": 0,
                "teu": 0
            }
        
        # Расчет TEU и типов
        # Если в размере есть '40', считаем как 2 TEU, иначе как 1
        if '40' in size_val:
            stocks_map[key]["c40"] += count
            stocks_map[key]["teu"] += count * 2
        else:
            stocks_map[key]["c20"] += count
            stocks_map[key]["teu"] += count * 1
            
    # Превращаем в список и сортируем по заполнению (TEU)
    stock_charts_data = list(stocks_map.values())
    stock_charts_data.sort(key=lambda x: x['teu'], reverse=True)

    return {
        "new_users": new_users,
        "active_trains": active_trains,
        "total_sent": total_sent,
        "avg_delivery_days": round(avg_delivery_days, 1),
        
        "turnover_labels": json.dumps(turnover_labels),
        "accepted_values": json.dumps(accepted_values),
        "dispatched_values": json.dumps(dispatched_values),
        
        "clients_labels": json.dumps(clients_labels),
        "clients_values": json.dumps(clients_values),
        "req_labels": json.dumps(req_labels),
        "req_values": json.dumps(req_values),
        
        # Передаем готовый список объектов для рендера
        "stock_charts_data": stock_charts_data
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
    
    # Лента последних действий
    feed_stmt = select(UserRequest, User).join(User, UserRequest.user_telegram_id == User.telegram_id, isouter=True).order_by(desc(UserRequest.timestamp)).limit(8)
    feed_res = await db.execute(feed_stmt)
    feed_data = []
    for req, usr in feed_res:
        username = usr.username or (f"ID: {usr.telegram_id}" if usr else "Неизвестный")
        feed_data.append({"username": username, "query": req.query_text, "time": req.timestamp.strftime("%H:%M %d.%m")})

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "user": current_user,
        "feed_data": feed_data,
        "current_date_from": d_from,
        "current_date_to": d_to,
        **stats
    })