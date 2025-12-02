# web/routers/admin.py
import sys
import os
import json
import secrets # <--- Для генерации токенов
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query, Form, status
from fastapi.responses import RedirectResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc, update, and_
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
from models import User, UserRequest, Train, Company, UserRole, ScheduledTrain, ScheduleShareLink # <--- Импорт Link
from model.terminal_container import TerminalContainer
from web.auth import admin_required, get_current_user

router = APIRouter(prefix="/admin", tags=["admin"])

current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

async def get_db():
    async with SessionLocal() as session:
        yield session

# --- Старые функции KPI ---
async def get_kpi_data(session: AsyncSession, period: str):
    now = datetime.now()
    start_date = None
    period_label = ""
    if period == "today": start_date = now.date()
    elif period == "week": start_date = (now - timedelta(days=7)).date()
    elif period == "month": start_date = (now - timedelta(days=30)).date()
    req_query = select(func.count(UserRequest.id))
    if start_date: 
        if period == "today": req_query = req_query.where(func.date(UserRequest.timestamp) == start_date)
        else: req_query = req_query.where(func.date(UserRequest.timestamp) >= start_date)
    kpi_requests = await session.scalar(req_query) or 0
    user_query = select(func.count(User.id))
    if start_date: user_query = user_query.where(func.date(User.created_at) >= start_date)
    kpi_users = await session.scalar(user_query) or 0
    cont_query = select(func.count(TerminalContainer.id))
    if start_date: cont_query = cont_query.where(TerminalContainer.accept_date >= start_date)
    kpi_containers = await session.scalar(cont_query) or 0
    train_query = select(func.count(Train.id))
    if start_date: train_query = train_query.where(func.date(Train.created_at) >= start_date)
    kpi_trains = await session.scalar(train_query) or 0
    return {"kpi_requests": kpi_requests, "kpi_users": kpi_users, "kpi_containers": kpi_containers, "kpi_trains": kpi_trains, "period_label": period_label}

async def get_clients_stats(session: AsyncSession, period: str):
    now = datetime.now()
    start_date = None
    if period == "today": start_date = now.date()
    elif period == "week": start_date = (now - timedelta(days=7)).date()
    elif period == "month": start_date = (now - timedelta(days=30)).date()
    stmt = select(TerminalContainer.client, func.count(TerminalContainer.id).label("count")).where(TerminalContainer.train.isnot(None)).where(TerminalContainer.client.isnot(None)).where(TerminalContainer.client != "")
    if start_date: stmt = stmt.where(TerminalContainer.accept_date >= start_date)
    stmt = stmt.group_by(TerminalContainer.client).order_by(desc("count")).limit(7)
    clients_res = await session.execute(stmt)
    clients_data = clients_res.all()
    return {"chart_clients_labels": json.dumps([row.client for row in clients_data]), "chart_clients_values": json.dumps([row.count for row in clients_data])}


# ==========================================
# === 📅 КАЛЕНДАРЬ ПЛАНИРОВАНИЯ ===
# ==========================================

@router.get("/schedule_planner")
async def schedule_planner_page(request: Request, user: User = Depends(admin_required)):
    return templates.TemplateResponse("schedule_planner.html", {"request": request, "user": user})

@router.get("/api/schedule/events")
async def get_schedule_events(start: str, end: str, db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    start_date = datetime.strptime(start.split('T')[0], "%Y-%m-%d").date()
    end_date = datetime.strptime(end.split('T')[0], "%Y-%m-%d").date()
    stmt = select(ScheduledTrain).where(and_(ScheduledTrain.schedule_date >= start_date, ScheduledTrain.schedule_date <= end_date))
    result = await db.execute(stmt)
    trains = result.scalars().all()
    events = []
    for t in trains:
        title = f"{t.service_name} -> {t.destination}"
        extendedProps = {"service": t.service_name, "dest": t.destination, "stock": t.stock_info or "", "owner": t.wagon_owner or "", "comment": t.comment or ""}
        events.append({"id": t.id, "title": title, "start": t.schedule_date.isoformat(), "allDay": True, "backgroundColor": "#3b82f6", "borderColor": "#2563eb", "extendedProps": extendedProps})
    return JSONResponse(events)

@router.post("/api/schedule/create")
async def create_schedule_event(date_str: str = Form(...), service: str = Form(...), destination: str = Form(...), stock: str = Form(None), owner: str = Form(None), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    dt = datetime.strptime(date_str, "%Y-%m-%d").date()
    new_train = ScheduledTrain(schedule_date=dt, service_name=service, destination=destination, stock_info=stock, wagon_owner=owner)
    db.add(new_train)
    await db.commit()
    return {"status": "ok", "id": new_train.id}

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

# ==========================================
# === 🔗 УПРАВЛЕНИЕ ССЫЛКАМИ (SHARING) ===
# ==========================================

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


# ==========================================
# === ДАШБОРД / КОМПАНИИ ===
# ==========================================

@router.get("/dashboard")
async def dashboard(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(admin_required)):
    kpi_data = await get_kpi_data(db, "today")
    clients_data = await get_clients_stats(db, "month")
    fourteen_days_ago = datetime.now() - timedelta(days=14)
    activity_stmt = select(func.date(UserRequest.timestamp).label("date"), func.count(UserRequest.id).label("count")).where(UserRequest.timestamp >= fourteen_days_ago).group_by(func.date(UserRequest.timestamp)).order_by("date")
    activity_res = await db.execute(activity_stmt)
    activity_data = activity_res.all()
    chart_activity_labels = [row.date.strftime("%d.%m") for row in activity_data]
    chart_activity_values = [row.count for row in activity_data]
    feed_stmt = select(UserRequest, User).join(User, UserRequest.user_telegram_id == User.telegram_id, isouter=True).order_by(desc(UserRequest.timestamp)).limit(10)
    feed_res = await db.execute(feed_stmt)
    feed_data = []
    for req, usr in feed_res:
        username = usr.username or f"ID: {usr.telegram_id}" if usr else "Неизвестный"
        feed_data.append({"username": username, "query": req.query_text, "time": req.timestamp.strftime("%H:%M %d.%m")})
    return templates.TemplateResponse("dashboard.html", {"request": request, "user": current_user, **kpi_data, **clients_data, "chart_activity_labels": json.dumps(chart_activity_labels), "chart_activity_values": json.dumps(chart_activity_values), "feed_data": feed_data})

@router.get("/dashboard/kpi")
async def dashboard_kpi_update(request: Request, period: str = Query("today"), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    kpi_data = await get_kpi_data(db, period)
    return templates.TemplateResponse("partials/kpi_cards.html", {"request": request, **kpi_data})

@router.get("/dashboard/clients")
async def dashboard_clients_update(request: Request, period: str = Query("month"), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    clients_data = await get_clients_stats(db, period)
    return templates.TemplateResponse("partials/clients_chart.html", {"request": request, **clients_data})

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