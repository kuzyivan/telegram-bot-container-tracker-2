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

# --- 🔥 НОВАЯ ФУНКЦИЯ СБОРА СТАТИСТИКИ ---
async def get_dashboard_stats(session: AsyncSession):
    """
    Собирает всю статистику для обновленного дашборда.
    """
    today = datetime.now().date()
    month_ago = today - timedelta(days=30)
    
    # 1. KPI Карточки (Верхний ряд)
    # Новые пользователи за 30 дней
    new_users = await session.scalar(
        select(func.count(User.id)).where(User.created_at >= month_ago)
    ) or 0
    
    # Активные поезда (те, что не завершены)
    active_trains = await session.scalar(
        select(func.count(Train.id))
        .where(Train.last_operation_date >= month_ago)
        # Грубая оценка активности: есть операции за месяц и не "выгрузка" на станции назначения
        # (Упрощаем для скорости)
    ) or 0

    # 2. 📦 Типы контейнеров (20 vs 40) - берем из Tracking за 30 дней
    # (Ищем уникальные контейнеры и смотрим их тип)
    types_stmt = (
        select(
            case(
                (Tracking.container_type.ilike('%20%'), '20 ft'),
                (Tracking.container_type.ilike('%40%'), '40 ft'),
                else_='Other'
            ).label('ctype'),
            func.count(distinct(Tracking.container_number))
        )
        .where(Tracking.operation_date >= month_ago)
        .group_by('ctype')
    )
    types_res = await session.execute(types_stmt)
    types_data = {row.ctype: row[1] for row in types_res.all()}
    count_20 = types_data.get('20 ft', 0)
    count_40 = types_data.get('40 ft', 0)

    # 3. 🚚 Фактические сроки доставки (Train)
    # Берем поезда, у которых есть departure_date и last_operation_date
    # и считаем среднюю разницу
    avg_delivery_stmt = (
        select(func.avg(func.extract('day', Train.last_operation_date - Train.created_at))) # Используем created_at как прокси, если departure нет
        .where(Train.last_operation.ilike('%выгрузка%')) # Только завершенные
        .where(Train.last_operation_date >= month_ago)
    )
    avg_delivery_days = await session.scalar(avg_delivery_stmt) or 0

    # 4. ⏳ Средний простой (из Tracking)
    # Берем среднее от last_op_idle_days
    avg_idle_stmt = (
        select(func.avg(Tracking.last_op_idle_days))
        .where(Tracking.operation_date >= month_ago)
        .where(Tracking.last_op_idle_days > 0)
    )
    avg_idle_days = await session.scalar(avg_idle_stmt) or 0

    # 5. 📈 Ритмичность погрузки (TerminalContainer по дням)
    rhythm_stmt = (
        select(func.date(TerminalContainer.created_at).label('date'), func.count(TerminalContainer.id))
        .where(TerminalContainer.created_at >= month_ago)
        .group_by('date')
        .order_by('date')
    )
    rhythm_res = await session.execute(rhythm_stmt)
    rhythm_rows = rhythm_res.all()
    rhythm_labels = [r.date.strftime('%d.%m') for r in rhythm_rows]
    rhythm_values = [r[1] for r in rhythm_rows]

    # 6. 🍰 Клиенты (Pie Chart)
    clients_stmt = (
        select(TerminalContainer.client, func.count(TerminalContainer.id).label('cnt'))
        .where(TerminalContainer.created_at >= month_ago)
        .where(TerminalContainer.client.isnot(None))
        .group_by(TerminalContainer.client)
        .order_by(desc('cnt'))
        .limit(6) # Топ 6
    )
    clients_res = await session.execute(clients_stmt)
    clients_rows = clients_res.all()
    clients_labels = [r.client for r in clients_rows]
    clients_values = [r.cnt for r in clients_rows]

    # 7. 🤖 Динамика запросов в бота
    req_stmt = (
        select(func.date(UserRequest.timestamp).label("date"), func.count(UserRequest.id))
        .where(UserRequest.timestamp >= month_ago)
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
        "count_20": count_20,
        "count_40": count_40,
        "avg_delivery_days": round(avg_delivery_days, 1),
        "avg_idle_days": round(avg_idle_days, 1),
        "rhythm_labels": json.dumps(rhythm_labels),
        "rhythm_values": json.dumps(rhythm_values),
        "clients_labels": json.dumps(clients_labels),
        "clients_values": json.dumps(clients_values),
        "req_labels": json.dumps(req_labels),
        "req_values": json.dumps(req_values),
    }

# --- РОУТЫ ---

@router.get("/dashboard")
async def dashboard(
    request: Request, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_required)
):
    stats = await get_dashboard_stats(db)
    
    # Лента (как и была)
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
        **stats
    })

# ==========================================
# === 📅 КАЛЕНДАРЬ ПЛАНИРОВАНИЯ ===
# ==========================================

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
    # FullCalendar присылает даты как '2025-12-01T00:00:00'
    start_date = datetime.strptime(start.split('T')[0], "%Y-%m-%d").date()
    end_date = datetime.strptime(end.split('T')[0], "%Y-%m-%d").date()
    
    stmt = select(ScheduledTrain).where(
        and_(ScheduledTrain.schedule_date >= start_date, ScheduledTrain.schedule_date <= end_date)
    )
    result = await db.execute(stmt)
    trains = result.scalars().all()
    
    events = []
    for t in trains:
        title = f"{t.service_name} -> {t.destination}"
        
        extendedProps = {
            "service": t.service_name,
            "dest": t.destination,
            "stock": t.stock_info or "",
            "owner": t.wagon_owner or "",
            "comment": t.comment or ""
        }
        
        # Используем цвет из БД или дефолтный
        color = t.color if hasattr(t, 'color') else "#3b82f6"
        
        events.append({
            "id": t.id,
            "title": title,
            "start": t.schedule_date.isoformat(),
            "allDay": True,
            "backgroundColor": color, 
            "borderColor": color,
            "extendedProps": extendedProps
        })
        
    return JSONResponse(events)

@router.post("/api/schedule/create")
async def create_schedule_event(
    date_str: str = Form(...),
    service: str = Form(...),
    destination: str = Form(...),
    stock: str = Form(None),
    owner: str = Form(None),
    color: str = Form("#3b82f6"), # Принимаем цвет
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    dt = datetime.strptime(date_str, "%Y-%m-%d").date()
    
    new_train = ScheduledTrain(
        schedule_date=dt,
        service_name=service,
        destination=destination,
        stock_info=stock,
        wagon_owner=owner,
        color=color # Сохраняем цвет
    )
    db.add(new_train)
    await db.commit()
    
    return {"status": "ok", "id": new_train.id}

@router.post("/api/schedule/{event_id}/move")
async def move_schedule_event(
    event_id: int,
    new_date: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    dt = datetime.strptime(new_date, "%Y-%m-%d").date()
    stmt = update(ScheduledTrain).where(ScheduledTrain.id == event_id).values(schedule_date=dt)
    await db.execute(stmt)
    await db.commit()
    
    return {"status": "ok"}

@router.delete("/api/schedule/{event_id}")
async def delete_schedule_event(
    event_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    stmt = select(ScheduledTrain).where(ScheduledTrain.id == event_id)
    res = await db.execute(stmt)
    obj = res.scalar_one_or_none()
    
    if obj:
        await db.delete(obj)
        await db.commit()
    
    return {"status": "ok"}

# ==========================================
# === 🔗 УПРАВЛЕНИЕ ССЫЛКАМИ (SHARING) ===
# ==========================================

@router.get("/api/schedule/links")
async def get_share_links(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    stmt = select(ScheduleShareLink).order_by(ScheduleShareLink.created_at.desc())
    res = await db.execute(stmt)
    links = res.scalars().all()
    return links

@router.post("/api/schedule/links/create")
async def create_share_link(
    name: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    token = secrets.token_urlsafe(16)
    new_link = ScheduleShareLink(name=name, token=token)
    db.add(new_link)
    await db.commit()
    
    return {"status": "ok", "token": token, "link": f"/schedule/share/{token}"}

@router.delete("/api/schedule/links/{link_id}")
async def delete_share_link(
    link_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
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
