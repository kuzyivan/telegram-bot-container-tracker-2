# web/routers/admin.py
import sys
import os
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query, Form, status
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

# --- Хак для импортов из корня проекта ---
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
from models import User, UserRequest, Train, Company, UserRole
from model.terminal_container import TerminalContainer
from web.auth import admin_required, get_current_user # Проверка прав
from web.auth import get_password_hash  # <--- Импортируем функцию хеширования

router = APIRouter(prefix="/admin", tags=["admin"])

# Настройка шаблонов
current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

# Dependency для получения сессии БД
async def get_db():
    async with SessionLocal() as session:
        yield session

# =========================================================================
# === ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (KPI, СТАТИСТИКА) ===
# =========================================================================

async def get_kpi_data(session: AsyncSession, period: str):
    """Рассчитывает KPI для карточек дашборда."""
    now = datetime.now()
    start_date = None
    period_label = ""

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
        start_date = None
        period_label = "Все время"
    
    # 1. Запросы
    req_query = select(func.count(UserRequest.id))
    if start_date:
        # Для "сегодня" фильтруем точное совпадение даты, для остальных - диапазон
        if period == "today":
            req_query = req_query.where(func.date(UserRequest.timestamp) == start_date)
        else:
            req_query = req_query.where(func.date(UserRequest.timestamp) >= start_date)
    kpi_requests = await session.scalar(req_query) or 0

    # 2. Новые пользователи
    user_query = select(func.count(User.id))
    if start_date:
        user_query = user_query.where(func.date(User.created_at) >= start_date)
    kpi_users = await session.scalar(user_query) or 0

    # 3. Принято контейнеров (по дате приема на терминал)
    cont_query = select(func.count(TerminalContainer.id))
    if start_date:
        cont_query = cont_query.where(TerminalContainer.accept_date >= start_date)
    kpi_containers = await session.scalar(cont_query) or 0

    # 4. Отправлено поездов
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

async def get_clients_stats(session: AsyncSession, period: str):
    """Считает топ клиентов по объемам контейнеров."""
    now = datetime.now()
    start_date = None

    if period == "today":
        start_date = now.date()
    elif period == "week":
        start_date = (now - timedelta(days=7)).date()
    elif period == "month":
        start_date = (now - timedelta(days=30)).date()
    
    stmt = (
        select(TerminalContainer.client, func.count(TerminalContainer.id).label("count"))
        .where(TerminalContainer.train.isnot(None))
        .where(TerminalContainer.client.isnot(None))
        .where(TerminalContainer.client != "")
    )

    if start_date:
        stmt = stmt.where(TerminalContainer.accept_date >= start_date)

    stmt = (
        stmt
        .group_by(TerminalContainer.client)
        .order_by(desc("count"))
        .limit(7)
    )
    
    clients_res = await session.execute(stmt)
    clients_data = clients_res.all()
    
    return {
        "chart_clients_labels": json.dumps([row.client for row in clients_data]),
        "chart_clients_values": json.dumps([row.count for row in clients_data])
    }

# =========================================================================
# === РОУТЫ: ДАШБОРД И СТАТИСТИКА ===
# =========================================================================

@router.get("/dashboard")
async def dashboard(
    request: Request, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_required) # Защита: только админ
):
    """Главная страница дашборда."""
    
    # 1. KPI
    kpi_data = await get_kpi_data(db, "today")

    # 2. Клиенты
    clients_data = await get_clients_stats(db, "month")

    # 3. График Активности (за последние 14 дней)
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
    
    # Форматируем даты для Chart.js
    chart_activity_labels = [row.date.strftime("%d.%m") for row in activity_data]
    chart_activity_values = [row.count for row in activity_data]

    # 4. Лента последних запросов
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
        "user": current_user, # Передаем юзера в шаблон (для меню)
        **kpi_data,
        **clients_data,
        "chart_activity_labels": json.dumps(chart_activity_labels),
        "chart_activity_values": json.dumps(chart_activity_values),
        "feed_data": feed_data
    })

# --- HTMX Endpoint: Обновление KPI ---
@router.get("/dashboard/kpi")
async def dashboard_kpi_update(
    request: Request, 
    period: str = Query("today"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    kpi_data = await get_kpi_data(db, period)
    return templates.TemplateResponse("partials/kpi_cards.html", {
        "request": request,
        **kpi_data
    })

# --- HTMX Endpoint: Обновление графика клиентов ---
@router.get("/dashboard/clients")
async def dashboard_clients_update(
    request: Request,
    period: str = Query("month"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    clients_data = await get_clients_stats(db, period)
    return templates.TemplateResponse("partials/clients_chart.html", {
        "request": request,
        **clients_data
    })

# --- Страница: Расписание поездов ---
@router.get("/schedule")
async def train_schedule(
    request: Request, 
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    today = datetime.now().date()
    next_month = today + timedelta(days=30)
    
    stmt = select(Train).where(Train.departure_date >= today).order_by(Train.departure_date)
    result = await db.execute(stmt)
    
    return templates.TemplateResponse("schedule.html", {
        "request": request, 
        "trains": result.scalars().all(), 
        "period_start": today, 
        "period_end": next_month,
        "user": user
    })

# =========================================================================
# === РОУТЫ: УПРАВЛЕНИЕ КОМПАНИЯМИ И ПОЛЬЗОВАТЕЛЯМИ (NEW) ===
# =========================================================================

@router.get("/companies")
async def admin_companies(
    request: Request, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_required)
):
    """Страница управления компаниями и назначением ролей."""
    
    # 1. Загружаем список всех компаний (с юзерами для подсчета)
    companies_res = await db.execute(
        select(Company)
        .order_by(Company.created_at.desc())
        .options(selectinload(Company.users))
    )
    companies = companies_res.scalars().all()

    # 2. Загружаем список всех пользователей (с привязанной компанией)
    users_res = await db.execute(
        select(User)
        .order_by(User.id.desc())
        .options(selectinload(User.company))
    )
    users = users_res.scalars().all()

    return templates.TemplateResponse("admin_companies.html", {
        "request": request,
        "user": current_user,
        "companies": companies,
        "users": users,
        "UserRole": UserRole # Чтобы использовать Enum в шаблоне
    })

@router.post("/users/create")
async def create_web_user(
    request: Request,
    login: str = Form(...),
    password: str = Form(...),
    name: str = Form(...),
    company_id: int = Form(0), # 0 = нет компании
    role: str = Form("viewer"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    """Создает нового пользователя для Web-доступа."""

    # Проверяем, нет ли уже такого логина
    stmt = select(User).where(User.email_login == login)
    existing = await db.execute(stmt)
    if existing.scalar_one_or_none():
        # В идеале нужно вернуть ошибку, но для простоты редиректим
        return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)

    hashed_password = get_password_hash(password)
    company_val = company_id if company_id > 0 else None

    new_user = User(
        email_login=login,
        password_hash=hashed_password,
        first_name=name,
        company_id=company_val,
        role=role
    )

    db.add(new_user)
    await db.commit()

    return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/companies/create")
async def create_company(
    request: Request,
    name: str = Form(...),
    inn: str = Form(None),
    import_key: str = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    """Обработчик формы создания компании."""
    new_company = Company(
        name=name,
        inn=inn,
        import_mapping_key=import_key
    )
    db.add(new_company)
    await db.commit()
    
    # Редирект обратно на страницу компаний
    return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/users/{user_id}/update")
async def update_user_role(
    request: Request,
    user_id: int,
    role: str = Form(...),
    company_id: int = Form(None), # Может быть 0 или None из формы
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    """Обновление роли и привязки к компании для конкретного пользователя."""
    
    # Валидация company_id (HTML select может прислать '0' как 'нет компании')
    company_val = company_id if company_id and company_id > 0 else None
    
    # Обновляем поля
    stmt = (
        update(User)
        .where(User.id == user_id)
        .values(role=role, company_id=company_val)
    )
    await db.execute(stmt)
    await db.commit()

    return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)