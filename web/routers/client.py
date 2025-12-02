# web/routers/client.py
import sys
import os
from pathlib import Path
from fastapi import APIRouter, Request, Depends, Query, HTTPException, status
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

# --- Хак для импорта модулей из корня ---
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
from models import User, Company, CompanyContainer, Tracking
from web.auth import login_required

router = APIRouter(prefix="/client", tags=["client"])

current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

async def get_db():
    async with SessionLocal() as session:
        yield session

async def get_client_kpi(session: AsyncSession, company_id: int):
    """
    Считает статистику для компании (Всего, В пути, Прибыло).
    """
    # 1. Получаем все контейнеры компании
    stmt = select(CompanyContainer.container_number).where(CompanyContainer.company_id == company_id)
    result = await session.execute(stmt)
    container_numbers = result.scalars().all()
    
    total_count = len(container_numbers)
    if total_count == 0:
        return {"total": 0, "in_transit": 0, "arrived": 0}

    # 2. Получаем актуальные статусы из Tracking
    # Берем все записи для этих контейнеров, сортируем по дате (свежие первые)
    tracking_stmt = (
        select(Tracking)
        .where(Tracking.container_number.in_(container_numbers))
        .order_by(Tracking.container_number, Tracking.operation_date.desc())
    )
    res = await session.execute(tracking_stmt)
    trackings = res.scalars().all()
    
    # Оставляем только уникальные (самые свежие для каждого контейнера)
    latest_map = {}
    for t in trackings:
        if t.container_number not in latest_map:
            latest_map[t.container_number] = t
            
    in_transit = 0
    arrived = 0
    
    # 3. Анализируем каждый контейнер
    # Если для контейнера нет данных в Tracking, считаем его "В пути" (или можно в отдельную категорию "Нет данных")
    # Здесь считаем общее количество из архива, а статусы проверяем по наличию
    
    # Проходимся по списку из архива, чтобы учесть даже те, у которых нет трекинга
    for c_num in container_numbers:
        t = latest_map.get(c_num)
        
        if not t:
            # Если нет данных трекинга, по умолчанию считаем "В пути" (ожидает данных)
            in_transit += 1
            continue

        # Логика "Прибыл": Осталось 0 км ИЛИ (Назначение == Текущая)
        is_arrived = False
        if t.km_left is not None and t.km_left == 0:
            is_arrived = True
        elif t.current_station and t.to_station and t.current_station.lower().strip() == t.to_station.lower().strip():
            is_arrived = True
            
        if is_arrived:
            arrived += 1
        else:
            in_transit += 1
            
    return {
        "total": total_count,
        "in_transit": in_transit,
        "arrived": arrived
    }

async def get_client_data(
    session: AsyncSession, 
    company_id: int, 
    query_str: str = ""
):
    """
    Основная функция выборки данных для таблицы.
    Возвращает список словарей: { 'number': str, 'added_at': dt, 'status': Tracking, 'progress': int }
    """
    
    # 1. Запрос к Архиву контейнеров компании
    stmt = (
        select(CompanyContainer)
        .where(CompanyContainer.company_id == company_id)
        .order_by(CompanyContainer.created_at.desc())
    )

    # 2. Фильтрация (Поиск)
    if query_str:
        q = query_str.strip().upper()
        stmt = stmt.where(CompanyContainer.container_number.contains(q))

    result = await session.execute(stmt)
    archive_containers = result.scalars().all()
    
    if not archive_containers:
        return []

    # 3. Собираем номера
    container_numbers = [c.container_number for c in archive_containers]

    # 4. Получаем ПОСЛЕДНИЙ статус
    tracking_stmt = (
        select(Tracking)
        .where(Tracking.container_number.in_(container_numbers))
        .order_by(Tracking.container_number, Tracking.operation_date.desc())
    )
    
    tracking_res = await session.execute(tracking_stmt)
    tracking_rows = tracking_res.scalars().all()

    # Карта {номер: TrackingObj} (первый = самый свежий)
    tracking_map = {}
    for t in tracking_rows:
        if t.container_number not in tracking_map:
            tracking_map[t.container_number] = t

    # 5. Собираем итоговые данные
    final_data = []
    for item in archive_containers:
        track_obj = tracking_map.get(item.container_number)
        
        # Расчет визуального прогресса
        progress = 0
        if track_obj and track_obj.total_distance and track_obj.km_left is not None:
            total = track_obj.total_distance
            left = track_obj.km_left
            if total > 0:
                progress = max(0, min(100, int(((total - left) / total) * 100)))
        
        final_data.append({
            "number": item.container_number,
            "added_at": item.created_at,
            "status": track_obj, # Может быть None
            "progress": progress
        })

    return final_data


@router.get("/dashboard")
async def client_dashboard(
    request: Request, 
    db: AsyncSession = Depends(get_db),
    user: User = Depends(login_required)
):
    """Главная страница ЛК Клиента."""
    
    # Проверка привязки к компании
    if not user.company_id:
        return templates.TemplateResponse("client_no_company.html", {"request": request, "user": user})

    # Данные компании
    company = await db.get(Company, user.company_id)
    if not company:
         return templates.TemplateResponse("client_no_company.html", {"request": request, "user": user})
    
    # Данные для таблицы
    containers_data = await get_client_data(db, user.company_id)
    
    # Данные для KPI (Дашборд)
    kpi_data = await get_client_kpi(db, user.company_id)

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
    db: AsyncSession = Depends(get_db),
    user: User = Depends(login_required)
):
    """HTMX-эндпоинт для живого поиска."""
    if not user.company_id:
        return "" 
        
    data = await get_client_data(db, user.company_id, q)
    
    return templates.TemplateResponse("partials/client_table.html", {
        "request": request,
        "containers": data
    })