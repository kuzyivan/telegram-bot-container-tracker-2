# web/routers/client.py
import sys
import os
import asyncio
from pathlib import Path
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import StreamingResponse, RedirectResponse, HTMLResponse 
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, desc 
from sqlalchemy.ext.asyncio import AsyncSession

# --- Импорты из корня проекта ---
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
from models import User, Company, CompanyContainer, Tracking
from model.terminal_container import TerminalContainer
from web.auth import login_required
from utils.send_tracking import create_excel_file_from_strings, get_vladivostok_filename

router = APIRouter(prefix="/client", tags=["client"])

current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

async def get_db():
    async with SessionLocal() as session:
        yield session

# --- Логика определения статуса ---
def get_container_status_code(tracking: Tracking | None) -> str:
    if not tracking: return 'terminal'
    if tracking.km_left is not None and tracking.km_left == 0: return 'arrived'
    if tracking.current_station and tracking.to_station:
        if tracking.current_station.lower().strip() == tracking.to_station.lower().strip(): return 'arrived'
    return 'transit'

# --- Получение данных для клиента (Основная функция) ---
async def get_client_data(
    session: AsyncSession, 
    company_id: int, 
    query_str: str = "", 
    status_filter: str = "all", 
    train_filter: str = "", 
    date_from: Optional[date] = None, 
    date_to: Optional[date] = None
):
    # 1. Получаем список контейнеров компании
    stmt = (
        select(CompanyContainer.container_number, TerminalContainer.train)
        .join(TerminalContainer, TerminalContainer.container_number == CompanyContainer.container_number, isouter=True)
        .where(CompanyContainer.company_id == company_id)
        .order_by(CompanyContainer.created_at.desc())
    )

    if query_str:
        stmt = stmt.where(CompanyContainer.container_number.contains(query_str.strip().upper()))
        
    if train_filter:
        stmt = stmt.where(TerminalContainer.train.contains(train_filter.strip().upper()))

    result = await session.execute(stmt)
    rows = result.all()
    
    if not rows:
        return []

    container_train_map = {row[0]: row[1] for row in rows}
    target_containers = list(container_train_map.keys())

    # 2. Получаем актуальный трекинг для этих контейнеров
    tracking_stmt = (
        select(Tracking)
        .where(Tracking.container_number.in_(target_containers))
        .order_by(Tracking.container_number, Tracking.operation_date.desc())
    )
    
    tracking_res = await session.execute(tracking_stmt)
    all_trackings = tracking_res.scalars().all()

    # Берем только последнюю запись для каждого контейнера
    latest_tracking_map = {}
    for t in all_trackings:
        if t.container_number not in latest_tracking_map:
            latest_tracking_map[t.container_number] = t

    final_data = []
    
    # 3. Фильтрация и сборка данных
    for c_num in target_containers:
        track_obj = latest_tracking_map.get(c_num)
        current_status = get_container_status_code(track_obj)

        # Фильтр по статусу
        if status_filter != 'all':
            if status_filter != current_status:
                continue

        # Фильтр по дате
        if date_from or date_to:
            check_date = None
            if track_obj:
                check_date = track_obj.operation_date.date() if track_obj.operation_date else None
                if not check_date and track_obj.trip_start_datetime:
                     check_date = track_obj.trip_start_datetime.date()
            
            if check_date:
                if date_from and check_date < date_from:
                    continue
                if date_to and check_date > date_to:
                    continue
            else:
                # Если даты нет, но фильтр включен — пропускаем
                continue

        # Расчет прогресса
        progress = 0
        if track_obj and track_obj.total_distance and track_obj.km_left is not None:
            total = track_obj.total_distance
            left = track_obj.km_left
            if total > 0:
                progress = max(0, min(100, int(((total - left) / total) * 100)))

        final_data.append({
            "number": c_num,
            "train": container_train_map.get(c_num),
            "status": track_obj,
            "progress": progress,
            "status_code": current_status
        })

    return final_data

# --- Расчет KPI ---
async def get_client_kpi(session: AsyncSession, company_id: int):
    # Получаем все данные (без фильтров) для корректного подсчета
    data = await get_client_data(session, company_id)
    
    total = len(data)
    terminal = sum(1 for x in data if x['status_code'] == 'terminal')
    transit = sum(1 for x in data if x['status_code'] == 'transit')
    arrived = sum(1 for x in data if x['status_code'] == 'arrived')
    
    return {
        "total": total,
        "terminal": terminal,
        "in_transit": transit,
        "arrived": arrived
    }

# --- РОУТЫ ---

@router.get("/dashboard")
async def client_dashboard(
    request: Request, 
    db: AsyncSession = Depends(get_db),
    user: User = Depends(login_required)
):
    if not user.company_id:
        return templates.TemplateResponse("client_no_company.html", {"request": request, "user": user})

    company = await db.get(Company, user.company_id)
    kpi_data = await get_client_kpi(db, user.company_id)
    containers_data = await get_client_data(db, user.company_id)

    return templates.TemplateResponse("client_dashboard.html", {
        "request": request,
        "user": user,
        "company": company,
        "containers": containers_data,
        "kpi": kpi_data
    })

# 🔥 ИСТОРИЯ ДВИЖЕНИЯ (НОВЫЙ РОУТ) 🔥
@router.get("/history/{container_number}")
async def get_container_history(
    request: Request,
    container_number: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(login_required)
):
    """
    Возвращает HTML-модалку с полной историей контейнера.
    """
    if not user.company_id:
        return HTMLResponse("<div>Нет доступа</div>")

    # 1. Получаем всю историю операций (сортировка от новых к старым)
    stmt = select(Tracking).where(Tracking.container_number == container_number).order_by(desc(Tracking.operation_date))
    result = await db.execute(stmt)
    history = result.scalars().all()
    
    if not history:
        return HTMLResponse("<div class='p-4 text-center text-mono-gray'>История не найдена</div>")

    # 2. Получаем номер поезда (для заголовка, чтобы было красиво)
    stmt_train = select(TerminalContainer.train).where(TerminalContainer.container_number == container_number).limit(1)
    train_res = await db.execute(stmt_train)
    train_number = train_res.scalar_one_or_none()

    return templates.TemplateResponse("partials/history_modal.html", {
        "request": request,
        "container_number": container_number,
        "train_number": train_number,
        "history": history
    })

@router.get("/containers/search")
async def search_containers(
    request: Request,
    q: str = Query(""),
    status: str = Query("all"),
    train: str = Query(""),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(login_required)
):
    if not user.company_id: return "" 
    
    d_from, d_to = None, None
    if date_from:
        try: d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
        except: pass
    if date_to:
        try: d_to = datetime.strptime(date_to, "%Y-%m-%d").date()
        except: pass

    data = await get_client_data(
        db, 
        user.company_id, 
        query_str=q, 
        status_filter=status, 
        train_filter=train,
        date_from=d_from, 
        date_to=d_to
    )
    
    return templates.TemplateResponse("partials/client_table.html", {
        "request": request,
        "containers": data
    })

@router.get("/export")
async def export_client_excel(
    q: str = Query(""),
    status: str = Query("all"),
    train: str = Query(""),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(login_required)
):
    if not user.company_id: return RedirectResponse("/client/dashboard")

    d_from, d_to = None, None
    if date_from:
        try: d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
        except: pass
    if date_to:
        try: d_to = datetime.strptime(date_to, "%Y-%m-%d").date()
        except: pass

    data = await get_client_data(
        db, 
        user.company_id, 
        query_str=q, 
        status_filter=status, 
        train_filter=train,
        date_from=d_from, 
        date_to=d_to
    )

    headers = [
        'Контейнер', 'Поезд', 'Статус', 'Станция отправления', 'Станция назначения',
        'Текущая станция', 'Операция', 'Дата операции (UTC)', 
        'Вагон', 'Осталось км', 'Прогноз (дней)'
    ]
    
    rows = []
    for item in data:
        t = item['status']
        status_text = {
            'terminal': 'На терминале',
            'transit': 'В пути',
            'arrived': 'Прибыл'
        }.get(item['status_code'], 'Неизвестно')

        op_date = t.operation_date.strftime('%d.%m.%Y %H:%M') if (t and t.operation_date) else ""
        km_left = str(t.km_left) if (t and t.km_left is not None) else ""
        forecast = str(t.forecast_days) if (t and t.forecast_days is not None) else ""

        rows.append([
            item['number'], 
            item.get('train') or "", 
            status_text, 
            t.from_station if t else "", 
            t.to_station if t else "", 
            t.current_station if t else "", 
            t.operation if t else "", 
            op_date, 
            t.wagon_number if t else "", 
            km_left, 
            forecast
        ])

    file_path = await asyncio.to_thread(create_excel_file_from_strings, rows, headers)
    filename = get_vladivostok_filename(prefix=f"Report_{datetime.now().strftime('%Y%m%d')}")

    def iterfile():
        with open(file_path, mode="rb") as file_like:
            yield from file_like
        try: os.remove(file_path)
        except OSError: pass

    return StreamingResponse(
        iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )