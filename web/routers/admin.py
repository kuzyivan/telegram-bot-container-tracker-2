# web/routers/admin.py
import sys
import os
import json
import secrets
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query, Form, status
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc, update, and_, case, distinct
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
from models import User, UserRequest, Train, Company, UserRole, ScheduledTrain, ScheduleShareLink, Tracking
from model.terminal_container import TerminalContainer
from web.auth import admin_required, get_current_user

router = APIRouter(prefix="/admin", tags=["admin"])

current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

async def get_db():
    async with SessionLocal() as session:
        yield session

# --- 🔥 НОВАЯ СТАТИСТИКА (V3 + Trend) ---
async def get_dashboard_stats(session: AsyncSession, date_from: date, date_to: date):
    """
    Собирает статистику и рассчитывает линию тренда.
    """
    
    def filter_date(query, column):
        return query.where(column >= date_from).where(column <= date_to)

    # 1. KPI
    new_users = await session.scalar(filter_date(select(func.count(User.id)), User.created_at)) or 0
    
    active_trains = await session.scalar(
        select(func.count(Train.id))
        .where(Train.last_operation_date >= (datetime.now() - timedelta(days=45)))
        .where(and_(Train.last_operation.not_ilike('%выгрузка%'), Train.last_operation.isnot(None)))
    ) or 0

    # 2. Всего отправлено
    total_sent_stmt = select(func.count(TerminalContainer.id))
    total_sent = await session.scalar(filter_date(total_sent_stmt, TerminalContainer.created_at)) or 0

    # 3. Сроки доставки
    avg_delivery_stmt = (
        select(func.avg(func.extract('day', Tracking.trip_end_datetime - Tracking.trip_start_datetime)))
        .where(Tracking.trip_end_datetime.isnot(None))
        .where(Tracking.trip_start_datetime.isnot(None))
        .where(func.date(Tracking.trip_end_datetime) >= date_from)
        .where(func.date(Tracking.trip_end_datetime) <= date_to)
    )
    avg_delivery_days = await session.scalar(avg_delivery_stmt) or 0

    # 4. 📈 Ритмичность погрузки + ТРЕНД
    rhythm_stmt = (
        select(func.date(TerminalContainer.created_at).label('date'), func.count(TerminalContainer.id))
        .where(func.date(TerminalContainer.created_at) >= date_from)
        .where(func.date(TerminalContainer.created_at) <= date_to)
        .group_by('date')
        .order_by('date')
    )
    rhythm_res = await session.execute(rhythm_stmt)
    rhythm_rows = rhythm_res.all()
    
    # Заполняем пропуски дат нулями (чтобы график был честным)
    rhythm_dict = {r.date: r[1] for r in rhythm_rows}
    rhythm_labels = []
    rhythm_values = []
    
    current = date_from
    while current <= date_to:
        rhythm_labels.append(current.strftime('%d.%m'))
        rhythm_values.append(rhythm_dict.get(current, 0))
        current += timedelta(days=1)

    # --- 🧮 Расчет Линейной Регрессии (y = mx + c) ---
    trend_values = []
    n = len(rhythm_values)
    if n > 1:
        x = list(range(n)) # [0, 1, 2, ...]
        y = rhythm_values
        
        sum_x = sum(x)
        sum_y = sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_xx = sum(xi ** 2 for xi in x)
        
        denominator = n * sum_xx - sum_x ** 2
        
        if denominator != 0:
            m = (n * sum_xy - sum_x * sum_y) / denominator # Наклон
            c = (sum_y - m * sum_x) / n                 # Смещение
            
            # Генерируем точки линии
            trend_values = [max(0, round(m * xi + c, 1)) for xi in x] # max(0) чтобы не уходило в минус
        else:
            trend_values = [0] * n
    else:
        trend_values = rhythm_values # Если 1 точка, тренд равен точке

    # 5. Клиенты
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

    # 6. Запросы
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
        "trend_values": json.dumps(trend_values), # <--- НОВОЕ
        "clients_labels": json.dumps(clients_labels),
        "clients_values": json.dumps(clients_values),
        "req_labels": json.dumps(req_labels),
        "req_values": json.dumps(req_values),
    }

# --- РОУТЫ ---

@router.get("/dashboard")
async def dashboard(
    request: Request, 
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_required)
):
    today = datetime.now().date()
    
    if date_from:
        d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
    else:
        d_from = today - timedelta(days=30)
        
    if date_to:
        d_to = datetime.strptime(date_to, "%Y-%m-%d").date()
    else:
        d_to = today

    stats = await get_dashboard_stats(db, d_from, d_to)
    
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

# ... (остальные роуты schedule_planner, events, links, companies, users без изменений) ...
@router.get("/schedule_planner")
async def schedule_planner_page(request: Request, user: User = Depends(admin_required)):
    return templates.TemplateResponse("schedule_planner.html", {"request": request, "user": user})

@router.get("/api/schedule/events")
async def get_schedule_events(
    start: str, 
    end: str, 
    db: AsyncSession = Depends(get_db), 
    user: User = Depends(admin_required)
):
    try:
        # Парсим даты
        start_date = datetime.strptime(start.split('T')[0], "%Y-%m-%d").date()
        end_date = datetime.strptime(end.split('T')[0], "%Y-%m-%d").date()
        
        # Запрос к БД
        stmt = select(ScheduledTrain).where(
            and_(ScheduledTrain.schedule_date >= start_date, ScheduledTrain.schedule_date <= end_date)
        )
        result = await db.execute(stmt)
        trains = result.scalars().all()
        
        events = []
        for t in trains:
            title = f"{t.service_name} -> {t.destination}"
            
            # --- ВОССТАНОВЛЕНИЕ ЦВЕТА ---
            # Берем цвет из базы. Если поля нет или оно пустое — ставим дефолтный синий или черный
            # Используем getattr для безопасности, если модель в памяти старая
            train_color = getattr(t, 'color', '#111111') 
            if not train_color:
                train_color = '#111111' 

            extendedProps = {
                "service": t.service_name,
                "dest": t.destination,
                "stock": t.stock_info or "",
                "owner": t.wagon_owner or "",
                "comment": t.comment or ""
            }
            
            events.append({
                "id": t.id,
                "title": title,
                "start": t.schedule_date.isoformat(),
                "allDay": True,
                # Передаем цвет в свойства календаря
                "backgroundColor": train_color, 
                "borderColor": train_color,
                "extendedProps": extendedProps
            })
            
        return JSONResponse(events)
        
    except Exception as e:
        print(f"❌ Ошибка API Calendar: {e}")
        return JSONResponse([], status_code=500)

@router.post("/api/schedule/create")
async def create_schedule_event(
    date_str: str = Form(...), 
    service: str = Form(...), 
    destination: str = Form(...), 
    stock: str = Form(None), 
    owner: str = Form(None), 
    color: str = Form("#111111"), # <--- Принимаем цвет
    db: AsyncSession = Depends(get_db), 
    user: User = Depends(admin_required)
):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        # Сохраняем цвет в базу
        new_train = ScheduledTrain(
            schedule_date=dt, 
            service_name=service, 
            destination=destination, 
            stock_info=stock, 
            wagon_owner=owner, 
            color=color # <--- Важно
        )
        db.add(new_train)
        await db.commit()
        return {"status": "ok", "id": new_train.id}
    except Exception as e:
        print(f"❌ Ошибка создания события: {e}")
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

@router.post("/api/schedule/{event_id}/move")
async def move_schedule_event(event_id: int, new_date: str = Form(...), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    dt = datetime.strptime(new_date, "%Y-%m-%d").date()
    stmt = update(ScheduledTrain).where(ScheduledTrain.id == event_id).values(schedule_date=dt)
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok"}

@router.delete("/api/schedule/{event_id}")
async def delete_schedule_event(event_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    stmt = select(ScheduledTrain).where(ScheduledTrain.id == event_id)
    res = await db.execute(stmt)
    obj = res.scalar_one_or_none()
    if obj:
        await db.delete(obj)
        await db.commit()
    return {"status": "ok"}

@router.get("/api/schedule/links")
async def get_share_links(db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    stmt = select(ScheduleShareLink).order_by(ScheduleShareLink.created_at.desc())
    res = await db.execute(stmt)
    links = res.scalars().all()
    return links

@router.post("/api/schedule/links/create")
async def create_share_link(name: str = Form(...), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    token = secrets.token_urlsafe(16)
    new_link = ScheduleShareLink(name=name, token=token)
    db.add(new_link)
    await db.commit()
    return {"status": "ok", "token": token, "link": f"/schedule/share/{token}"}

@router.delete("/api/schedule/links/{link_id}")
async def delete_share_link(link_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    stmt = select(ScheduleShareLink).where(ScheduleShareLink.id == link_id)
    res = await db.execute(stmt)
    link = res.scalar_one_or_none()
    if link:
        await db.delete(link)
        await db.commit()
    return {"status": "ok"}

@router.get("/companies")
async def admin_companies(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(admin_required)):
    companies_res = await db.execute(select(Company).order_by(Company.created_at.desc()).options(selectinload(Company.users)))
    companies = companies_res.scalars().all()
    users_res = await db.execute(select(User).order_by(User.id.desc()).options(selectinload(User.company)))
    users = users_res.scalars().all()
    return templates.TemplateResponse("admin_companies.html", {"request": request, "user": current_user, "companies": companies, "users": users, "UserRole": UserRole})

@router.post("/companies/create")
async def create_company(request: Request, name: str = Form(...), inn: str = Form(None), import_key: str = Form(None), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    new_company = Company(name=name, inn=inn, import_mapping_key=import_key)
    db.add(new_company)
    await db.commit()
    return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/companies/sync")
async def sync_companies_data(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    from queries.company_queries import sync_terminal_to_company_containers
    await sync_terminal_to_company_containers(db)
    return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/users/{user_id}/update")
async def update_user_role(request: Request, user_id: int, role: str = Form(...), company_id: int = Form(None), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    company_val = company_id if company_id and company_id > 0 else None
    stmt = update(User).where(User.id == user_id).values(role=role, company_id=company_val)
    await db.execute(stmt)
    await db.commit()
    return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/users/create")
async def create_web_user(request: Request, login: str = Form(...), password: str = Form(...), name: str = Form(...), company_id: int = Form(0), role: str = Form("viewer"), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    from web.auth import get_password_hash
    stmt = select(User).where(User.email_login == login)
    existing = await db.execute(stmt)
    if existing.scalar_one_or_none():
        return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)
    hashed_password = get_password_hash(password)
    company_val = company_id if company_id > 0 else None
    new_user = User(email_login=login, password_hash=hashed_password, first_name=name, company_id=company_val, role=role)
    db.add(new_user)
    await db.commit()
    return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)