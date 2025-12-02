# web/routers/client.py
import sys
import os
from pathlib import Path
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Request, Depends, Query
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

# --- Импорты ---
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
from models import User, Company, CompanyContainer, Tracking
from model.terminal_container import TerminalContainer
from web.auth import login_required
from fastapi.responses import StreamingResponse
from utils.send_tracking import create_excel_file_from_strings, get_vladivostok_filename

router = APIRouter(prefix="/client", tags=["client"])

current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

async def get_db():
    async with SessionLocal() as session:
        yield session

# --- Вспомогательная функция определения статуса ---
def get_container_status_code(tracking: Tracking | None) -> str:
    """Возвращает 'transit' или 'arrived'."""
    if not tracking:
        return 'transit' # Если данных нет, считаем "в процессе"
    
    # Логика прибытия
    if tracking.km_left is not None and tracking.km_left == 0:
        return 'arrived'
    
    if tracking.current_station and tracking.to_station:
        if tracking.current_station.lower().strip() == tracking.to_station.lower().strip():
            return 'arrived'
            
    return 'transit'

# --- Основная функция получения данных ---
async def get_client_data(
    session: AsyncSession, 
    company_id: int, 
    query_str: str = "",
    status_filter: str = "all", # all, transit, arrived
    train_filter: str = "",
    date_from: Optional[date] = None,
    date_to: Optional[date] = None
):
    """
    Умная выборка данных с фильтрацией.
    """
    # 1. Получаем список контейнеров Компании + их Поезд (из TerminalContainer)
    # Используем OUTER JOIN, чтобы найти поезд, если он есть
    stmt = (
        select(CompanyContainer.container_number, TerminalContainer.train)
        .join(TerminalContainer, TerminalContainer.container_number == CompanyContainer.container_number, isouter=True)
        .where(CompanyContainer.company_id == company_id)
        .order_by(CompanyContainer.created_at.desc())
    )

    # Фильтр по строке поиска (Контейнер)
    if query_str:
        q = query_str.strip().upper()
        stmt = stmt.where(CompanyContainer.container_number.contains(q))
        
    # Фильтр по Номеру Поезда
    if train_filter:
        t_q = train_filter.strip().upper()
        stmt = stmt.where(TerminalContainer.train.contains(t_q))

    result = await session.execute(stmt)
    # rows = список кортежей (container_number, train_number)
    rows = result.all()
    
    if not rows:
        return []

    # Собираем словарь {container: train_number}
    container_train_map = {row[0]: row[1] for row in rows}
    target_containers = list(container_train_map.keys())

    # 2. Получаем актуальный трекинг
    tracking_stmt = (
        select(Tracking)
        .where(Tracking.container_number.in_(target_containers))
        .order_by(Tracking.container_number, Tracking.operation_date.desc())
    )
    
    tracking_res = await session.execute(tracking_stmt)
    all_trackings = tracking_res.scalars().all()

    # Берем только самые свежие записи
    latest_tracking_map = {}
    for t in all_trackings:
        if t.container_number not in latest_tracking_map:
            latest_tracking_map[t.container_number] = t

    # 3. Сборка и Фильтрация в Python (Статус и Даты)
    final_data = []
    
    for c_num in target_containers:
        track_obj = latest_tracking_map.get(c_num)
        train_num = container_train_map.get(c_num)
        
        # --- Фильтр по Дате (по дате операции или дате отправления) ---
        if date_from or date_to:
            check_date = None
            if track_obj:
                # Приоритет: Дата операции, иначе Дата отправления
                check_date = track_obj.operation_date.date() if track_obj.operation_date else None
                if not check_date and track_obj.trip_start_datetime:
                     check_date = track_obj.trip_start_datetime.date()
            
            if check_date:
                if date_from and check_date < date_from:
                    continue
                if date_to and check_date > date_to:
                    continue
            else:
                # Если фильтр дат включен, а у контейнера нет дат — пропускаем его
                if date_from or date_to:
                    continue

        # --- Фильтр по Статусу ---
        current_status = get_container_status_code(track_obj)
        
        if status_filter != 'all':
            if status_filter != current_status:
                continue

        # --- Расчет прогресса ---
        progress = 0
        if track_obj and track_obj.total_distance and track_obj.km_left is not None:
            total = track_obj.total_distance
            left = track_obj.km_left
            if total > 0:
                progress = max(0, min(100, int(((total - left) / total) * 100)))

        final_data.append({
            "number": c_num,
            "train": train_num, # Добавили поезд
            "status": track_obj,
            "progress": progress,
            "status_code": current_status
        })

    return final_data

async def get_client_kpi(session: AsyncSession, company_id: int):
    """
    Считает простую статистику (без учета фильтров дат, чтобы показывать общую картину).
    """
    # ... (логика KPI остается прежней, считаем по всем контейнерам компании) ...
    # Для краткости используем упрощенный вызов get_client_data без фильтров
    data = await get_client_data(session, company_id)
    
    total = len(data)
    transit = sum(1 for x in data if x['status_code'] == 'transit')
    arrived = sum(1 for x in data if x['status_code'] == 'arrived')
    
    return {"total": total, "in_transit": transit, "arrived": arrived}


# --- Роуты ---

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
    
    # Первичная загрузка - все данные
    containers_data = await get_client_data(db, user.company_id)

    return templates.TemplateResponse("client_dashboard.html", {
        "request": request,
        "user": user,
        "company": company,
        "containers": containers_data,
        "kpi": kpi_data
    })

@router.get("/containers/search")
async def search_containers(
    request: Request,
    q: str = Query(""),
    status: str = Query("all"),
    train: str = Query(""),
    date_from: Optional[str] = Query(None), # Получаем как строки с фронта
    date_to: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(login_required)
):
    """HTMX-эндпоинт для фильтрации."""
    if not user.company_id:
        return "" 
    
    # Преобразование дат
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
    """Генерация Excel-отчета для клиента с учетом фильтров."""
    if not user.company_id:
        return RedirectResponse("/client/dashboard")

    # 1. Парсинг дат
    d_from, d_to = None, None
    if date_from:
        try: d_from = datetime.strptime(date_from, "%Y-%m-%d").date()
        except: pass
    if date_to:
        try: d_to = datetime.strptime(date_to, "%Y-%m-%d").date()
        except: pass

    # 2. Получение отфильтрованных данных (используем ту же функцию, что и для таблицы)
    data = await get_client_data(
        db, 
        user.company_id, 
        query_str=q, 
        status_filter=status, 
        train_filter=train,
        date_from=d_from, 
        date_to=d_to
    )

    # 3. Подготовка строк для Excel
    headers = [
        'Контейнер', 'Поезд', 'Станция отправления', 'Станция назначения',
        'Текущая станция', 'Операция', 'Дата операции (UTC)', 
        'Вагон', 'Осталось км', 'Прогноз (дней)'
    ]
    
    rows = []
    for item in data:
        # item['status'] — это объект Tracking или None
        t = item['status']
        
        # Безопасное извлечение полей
        cont_num = item['number']
        train_num = item.get('train') or ""
        
        from_st = t.from_station if t else ""
        to_st = t.to_station if t else ""
        curr_st = t.current_station if t else ""
        oper = t.operation if t else "Нет данных"
        
        op_date = ""
        if t and t.operation_date:
            op_date = t.operation_date.strftime('%d.%m.%Y %H:%M')
            
        wagon = t.wagon_number if t else ""
        km_left = str(t.km_left) if (t and t.km_left is not None) else ""
        forecast = str(t.forecast_days) if (t and t.forecast_days is not None) else ""

        rows.append([
            cont_num, train_num, from_st, to_st, 
            curr_st, oper, op_date, 
            wagon, km_left, forecast
        ])

    # 4. Генерация файла
    file_path = await asyncio.to_thread(create_excel_file_from_strings, rows, headers)
    
    # Имя файла с датой
    filename = get_vladivostok_filename(prefix=f"Report_{datetime.now().strftime('%Y%m%d')}")

    # 5. Отдача файла (Streaming)
    def iterfile():
        with open(file_path, mode="rb") as file_like:
            yield from file_like
        try:
            os.remove(file_path)
        except OSError:
            pass

    return StreamingResponse(
        iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )