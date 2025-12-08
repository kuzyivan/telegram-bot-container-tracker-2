import sys
import os
import json
import secrets
from datetime import datetime, timedelta, date
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query, Form, status
from fastapi.responses import RedirectResponse, JSONResponse, HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func, desc, update, and_, case, distinct
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
from models import User, UserRequest, Train, Company, UserRole, ScheduledTrain, ScheduleShareLink, Tracking
from model.terminal_container import TerminalContainer
from web.auth import admin_required, get_current_user

# --- ИМПОРТЫ ФИНАНСОВОГО МОДУЛЯ ---
from models_finance import (
    Calculation, CalculationItem, RailTariffRate, 
    SystemSetting, ServiceType, WagonType, MarginType, CalculationStatus
)
from services.calculator_service import PriceCalculator
from services.tariff_service import TariffStation # Нужно для названий станций

router = APIRouter(prefix="/admin", tags=["admin"])

current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

async def get_db():
    async with SessionLocal() as session:
        yield session

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

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

    # График: Ритмичность
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

    # Тренд
    trend_values = []
    n = len(rhythm_values)
    if n > 1:
        x = list(range(n))
        y = rhythm_values
        sum_x, sum_y = sum(x), sum(y)
        sum_xy = sum(xi * yi for xi, yi in zip(x, y))
        sum_xx = sum(xi ** 2 for xi in x)
        denominator = n * sum_xx - sum_x ** 2
        if denominator != 0:
            m = (n * sum_xy - sum_x * sum_y) / denominator
            c = (sum_y - m * sum_x) / n
            trend_values = [max(0, round(m * xi + c, 1)) for xi in x]
        else:
            trend_values = [0] * n
    else:
        trend_values = rhythm_values

    # График: Клиенты
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

    # График: Запросы
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

async def get_tariff_stations(session: AsyncSession, is_departure: bool, filter_from_code: str = None, service_type: str = None):
    """
    Возвращает список станций (код, имя), для которых ЕСТЬ заведенные тарифы.
    """
    # Выбираем колонку (откуда или куда) из таблицы тарифов
    target_col = RailTariffRate.station_from_code if is_departure else RailTariffRate.station_to_code
    
    # Строим запрос: SELECT DISTINCT code, name FROM rates JOIN stations ON code
    query = select(
        target_col, 
        TariffStation.name
    ).distinct().join(
        TariffStation, 
        TariffStation.code == target_col
    )

    # Если ищем "Куда", то фильтруем по "Откуда" и "Сервису"
    if not is_departure:
        if filter_from_code:
            query = query.where(RailTariffRate.station_from_code == filter_from_code)
        if service_type:
            # SQLAlchemy может потребовать приведения типа, если в базе ENUM, 
            # но часто работает сравнение со строкой.
            # Если возникнет ошибка, нужно будет использовать cast или import ServiceType
            query = query.where(RailTariffRate.service_type == service_type)

    result = await session.execute(query)
    # Возвращаем список словарей [{'code': '...', 'name': '...'}, ...]
    return [{"code": row[0], "name": row[1]} for row in result.all()]


# --- РОУТЫ КАЛЬКУЛЯТОРА ---

@router.get("/calculator")
async def calculator_list(
    request: Request, 
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    """Список всех расчетов (КП)."""
    stmt = select(Calculation).order_by(desc(Calculation.created_at))
    result = await db.execute(stmt)
    calculations = result.scalars().all()
    
    return templates.TemplateResponse("admin_calculator_list.html", {
        "request": request,
        "user": user,
        "calculations": calculations,
        "CalculationStatus": CalculationStatus
    })

@router.get("/calculator/new")
async def calculator_create_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    """Страница конструктора нового расчета."""
    # 1. Загружаем настройки (кэфы, НДС)
    settings_stmt = select(SystemSetting)
    settings_res = await db.execute(settings_stmt)
    settings = {s.key: s.value for s in settings_res.scalars()}
    
    # 2. ✅ Загружаем список станций ОТПРАВЛЕНИЯ (из тарифов)
    stations_from = await get_tariff_stations(db, is_departure=True)
    
    return templates.TemplateResponse("admin_calculator_form.html", {
        "request": request,
        "user": user,
        "settings": settings,
        "today": datetime.now().date(),
        "ServiceType": ServiceType,
        "WagonType": WagonType,
        "MarginType": MarginType,
        "stations_from": stations_from # <-- Передаем список в шаблон
    })

@router.get("/api/calc/destinations")
async def get_available_destinations(
    request: Request,
    station_from: str = Query(...),
    service_type: str = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    """
    HTMX: Возвращает HTML-опции для селекта 'Куда' на основе выбранного 'Откуда' и 'Сервиса'.
    """
    destinations = await get_tariff_stations(
        db, 
        is_departure=False, 
        filter_from_code=station_from, 
        service_type=service_type
    )
    
    # Генерируем HTML опций
    options_html = '<option value="" disabled selected>— Выберите станцию —</option>'
    for st in destinations:
        options_html += f'<option value="{st["code"]}">{st["name"]}</option>'
        
    if not destinations:
        options_html = '<option value="" disabled>Нет тарифов для этого направления</option>'

    return HTMLResponse(options_html)

@router.post("/api/calc/preview")
async def calculator_preview(
    request: Request,
    station_from: str = Form(...),
    station_to: str = Form(None), # Может быть None, если список только загрузился
    container_type: str = Form(...),
    service_type: str = Form(...),
    wagon_type: str = Form(...),
    margin_type: str = Form(...),
    margin_value: float = Form(0.0),
    extra_expenses: float = Form(0.0),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    """
    HTMX: Живой расчет цены при изменении любого поля формы.
    """
    # Если станция назначения еще не выбрана, возвращаем пустую заглушку
    if not station_to:
        return templates.TemplateResponse("partials/calc_summary.html", {
            "request": request, "tariff_found": False, "base_rate": 0
        })

    calc_service = PriceCalculator(db)
    
    # 1. Получаем базовый тариф
    tariff = await calc_service.get_tariff(station_from, station_to, container_type, service_type)
    base_rate = tariff.rate_no_vat if tariff else 0.0
    
    # 2. Применяем коэффициенты
    gondola_coeff = 1.0
    if wagon_type == WagonType.GONDOLA:
        setting = await db.get(SystemSetting, "gondola_coeff")
        if setting:
            gondola_coeff = float(setting.value)
    
    adjusted_base_rate = base_rate * gondola_coeff
    
    # 3. Полная себестоимость
    total_cost = adjusted_base_rate + extra_expenses
    
    # 4. Цена продажи
    sales_price_netto = 0.0
    if margin_type == MarginType.FIX:
        sales_price_netto = total_cost + margin_value
    else: # PERCENT
        sales_price_netto = total_cost * (1 + margin_value / 100)
        
    # 5. НДС
    vat_setting = await db.get(SystemSetting, "vat_rate")
    vat_rate = float(vat_setting.value) if vat_setting else 20.0
    vat_amount = sales_price_netto * (vat_rate / 100)
    total_price_with_vat = sales_price_netto + vat_amount
    
    return templates.TemplateResponse("partials/calc_summary.html", {
        "request": request,
        "base_rate": base_rate,
        "gondola_coeff": gondola_coeff,
        "adjusted_base_rate": adjusted_base_rate,
        "extra_expenses": extra_expenses,
        "total_cost": total_cost,
        "sales_price_netto": sales_price_netto,
        "vat_amount": vat_amount,
        "total_price_with_vat": total_price_with_vat,
        "tariff_found": bool(tariff)
    })

@router.post("/calculator/create")
async def calculator_save(
    request: Request,
    title: str = Form(...),
    # Пока заглушка сохранения, реализуем позже
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    return RedirectResponse("/admin/calculator", status_code=303)


# --- ОСТАЛЬНЫЕ СТАНДАРТНЫЕ РОУТЫ (Companies, Dashboard, Schedule) ---

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

@router.get("/schedule_planner")
async def schedule_planner_page(request: Request, user: User = Depends(admin_required)):
    return templates.TemplateResponse("schedule_planner.html", {"request": request, "user": user})

# --- КАЛЕНДАРЬ API ---

@router.get("/api/schedule/events")
async def get_schedule_events(
    start: str, end: str, db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)
):
    try:
        start_date = datetime.strptime(start.split('T')[0], "%Y-%m-%d").date()
        end_date = datetime.strptime(end.split('T')[0], "%Y-%m-%d").date()
        stmt = select(ScheduledTrain).where(and_(ScheduledTrain.schedule_date >= start_date, ScheduledTrain.schedule_date <= end_date))
        result = await db.execute(stmt)
        trains = result.scalars().all()
        
        events = []
        for t in trains:
            title = f"{t.service_name} -> {t.destination}"
            bg_color = getattr(t, 'color', '#111111') or '#111111'
            overload = getattr(t, 'overload_station', "")
            owner = getattr(t, 'wagon_owner', "")
            events.append({
                "id": str(t.id), "title": title, "start": t.schedule_date.isoformat(),
                "allDay": True, "backgroundColor": bg_color, "borderColor": bg_color,
                "extendedProps": {"service": t.service_name, "dest": t.destination, "stock": t.stock_info or "", "owner": owner or "", "overload": overload or "", "comment": t.comment or ""},
                "editable": True, "startEditable": True, "durationEditable": False
            })
        return JSONResponse(events)
    except Exception as e:
        return JSONResponse([], status_code=200)

@router.post("/api/schedule/create")
async def create_schedule_event(
    date_str: str = Form(...), service: str = Form(...), destination: str = Form(...), 
    stock: str = Form(None), owner: str = Form(None), overload_station: str = Form(None), color: str = Form("#111111"),
    db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)
):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        new_train = ScheduledTrain(schedule_date=dt, service_name=service, destination=destination, stock_info=stock, wagon_owner=owner, overload_station=overload_station, color=color)
        db.add(new_train)
        await db.commit()
        return {"status": "ok", "id": new_train.id}
    except Exception as e:
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
    if obj: await db.delete(obj); await db.commit()
    return {"status": "ok"}

@router.get("/api/schedule/links")
async def get_share_links(db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    res = await db.execute(select(ScheduleShareLink).order_by(ScheduleShareLink.created_at.desc()))
    return res.scalars().all()

@router.post("/api/schedule/links/create")
async def create_share_link(name: str = Form(...), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    token = secrets.token_urlsafe(16)
    db.add(ScheduleShareLink(name=name, token=token))
    await db.commit()
    return {"status": "ok", "token": token, "link": f"/schedule/share/{token}"}

@router.delete("/api/schedule/links/{link_id}")
async def delete_share_link(link_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    res = await db.execute(select(ScheduleShareLink).where(ScheduleShareLink.id == link_id))
    link = res.scalar_one_or_none()
    if link: await db.delete(link); await db.commit()
    return {"status": "ok"}

# --- КОМПАНИИ И ПОЛЬЗОВАТЕЛИ ---

@router.get("/companies")
async def admin_companies(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(admin_required)):
    companies = (await db.execute(select(Company).order_by(Company.created_at.desc()).options(selectinload(Company.users)))).scalars().all()
    users = (await db.execute(select(User).order_by(User.id.desc()).options(selectinload(User.company)))).scalars().all()
    return templates.TemplateResponse("admin_companies.html", {"request": request, "user": current_user, "companies": companies, "users": users, "UserRole": UserRole})

@router.post("/companies/create")
async def create_company(request: Request, name: str = Form(...), inn: str = Form(None), import_key: str = Form(None), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    db.add(Company(name=name, inn=inn, import_mapping_key=import_key))
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
    await db.execute(update(User).where(User.id == user_id).values(role=role, company_id=company_val))
    await db.commit()
    return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/users/create")
async def create_web_user(request: Request, login: str = Form(...), password: str = Form(...), name: str = Form(...), company_id: int = Form(0), role: str = Form("viewer"), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    from web.auth import get_password_hash
    if (await db.execute(select(User).where(User.email_login == login))).scalar_one_or_none():
        return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)
    company_val = company_id if company_id > 0 else None
    db.add(User(email_login=login, password_hash=get_password_hash(password), first_name=name, company_id=company_val, role=role))
    await db.commit()
    return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)