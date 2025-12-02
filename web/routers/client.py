# web/routers/client.py
import sys
import os
from pathlib import Path
from fastapi import APIRouter, Request, Depends, Query, HTTPException, status
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, or_, desc, func, and_
from sqlalchemy.orm import selectinload, aliased
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
from models import User, Company, CompanyContainer, Tracking, Train
from web.auth import login_required, UserRole

router = APIRouter(prefix="/client", tags=["client"])

current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

async def get_db():
    async with SessionLocal() as session:
        yield session

async def get_client_data(
    session: AsyncSession, 
    company_id: int, 
    query_str: str = ""
):
    """
    Основная функция выборки данных.
    Возвращает список словарей: { 'archive': CompanyContainer, 'status': Tracking, 'train': TrainInfo }
    """
    
    # 1. Базовый запрос к Архиву контейнеров компании
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

    # 3. Собираем номера контейнеров
    container_numbers = [c.container_number for c in archive_containers]

    # 4. Получаем ПОСЛЕДНИЙ статус для этих контейнеров
    # Используем Window Function (row_number) или DISTINCT ON (в PostgreSQL), 
    # но для универсальности сделаем через подзапрос или Python-агрегацию.
    # Для простоты и скорости на объемах до 10к контейнеров - Python-агрегация (Last Value).
    
    tracking_stmt = (
        select(Tracking)
        .where(Tracking.container_number.in_(container_numbers))
        .order_by(Tracking.container_number, Tracking.operation_date.desc())
    )
    
    tracking_res = await session.execute(tracking_stmt)
    tracking_rows = tracking_res.scalars().all()

    # Создаем карту {номер: TrackingObj} (берем только первый, т.к. сортировка DESC)
    tracking_map = {}
    for t in tracking_rows:
        if t.container_number not in tracking_map:
            tracking_map[t.container_number] = t

    # 5. Собираем итоговые данные
    final_data = []
    for item in archive_containers:
        track_obj = tracking_map.get(item.container_number)
        
        # Расчет прогресса (визуальная фича)
        progress = 0
        if track_obj and track_obj.total_distance and track_obj.km_left is not None:
            total = track_obj.total_distance
            left = track_obj.km_left
            if total > 0:
                progress = max(0, min(100, int(((total - left) / total) * 100)))
        
        final_data.append({
            "number": item.container_number,
            "added_at": item.created_at,
            "status": track_obj, # Может быть None, если нет данных
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
    
    # Проверка: есть ли у пользователя компания
    if not user.company_id:
        return templates.TemplateResponse("client_no_company.html", {"request": request, "user": user})

    # Загружаем название компании
    company = await db.get(Company, user.company_id)
    
    # Получаем данные (без фильтра)
    containers_data = await get_client_data(db, user.company_id)

    return templates.TemplateResponse("client_dashboard.html", {
        "request": request,
        "user": user,
        "company": company,
        "containers": containers_data
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
        return "" # Пустой ответ
        
    data = await get_client_data(db, user.company_id, q)
    
    return templates.TemplateResponse("partials/client_table.html", {
        "request": request,
        "containers": data
    })