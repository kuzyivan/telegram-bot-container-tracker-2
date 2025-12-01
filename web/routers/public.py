import sys
import os
import re
import asyncio
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
from models import Tracking, Train
from model.terminal_container import TerminalContainer
from utils.send_tracking import create_excel_file_from_strings, get_vladivostok_filename
from services.railway_router import get_remaining_distance_on_route

router = APIRouter()

current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

async def get_db():
    async with SessionLocal() as session:
        yield session

def normalize_search_input(text: str) -> list[str]:
    """Парсит текст на список номеров (контейнеры или вагоны)."""
    if not text: return []
    text = text.upper().strip()
    # Разбиваем по запятым, пробелам, переносам строк
    items = re.split(r'[,\s;\n]+', text)
    # Фильтруем: оставляем только то, что похоже на контейнер (11 симв) или вагон (8 цифр)
    valid_items = []
    for item in items:
        if re.fullmatch(r'[A-Z]{3}U\d{7}', item) or re.fullmatch(r'\d{8}', item):
            valid_items.append(item)
    return list(set(valid_items)) # Удаляем дубликаты

async def enrich_tracking_data(db: AsyncSession, tracking_items: list[Tracking]):
    """
    Добавляет к объектам Tracking дополнительные данные:
    - Прогресс (процент выполнения)
    - Информацию о поезде (Терминал) и перегрузе
    """
    enriched_data = []
    
    for item in tracking_items:
        # 1. Расчет прогресса
        progress_percent = 0
        total_dist = item.total_distance or 0
        km_left = item.km_left or 0
        
        # Если есть total_distance, считаем от него
        if total_dist > 0:
            traveled = total_dist - km_left
            progress_percent = int((traveled / total_dist) * 100)
        # Если нет, но есть прогноз по дням, пробуем эвристику (не обязательно, но можно)
        
        progress_percent = max(0, min(100, progress_percent)) # Clamp 0-100

        # 2. Поиск информации о поезде (TerminalContainer -> Train)
        terminal_train_info = {
            "number": None,
            "overload_station": None
        }
        
        # Ищем связь в terminal_containers
        tc_res = await db.execute(
            select(TerminalContainer.train)
            .where(TerminalContainer.container_number == item.container_number)
            .order_by(TerminalContainer.created_at.desc())
            .limit(1)
        )
        train_code = tc_res.scalar_one_or_none()
        
        if train_code:
            terminal_train_info["number"] = train_code
            # Ищем станцию перегруза в таблице trains
            t_res = await db.execute(
                select(Train.overload_station_name)
                .where(Train.terminal_train_number == train_code)
            )
            terminal_train_info["overload_station"] = t_res.scalar_one_or_none()

        # Собираем словарь для шаблона
        enriched_data.append({
            "obj": item,
            "progress": progress_percent,
            "train_info": terminal_train_info,
            "is_arrived": item.km_left == 0 or (item.current_station == item.to_station)
        })
        
    return enriched_data

@router.get("/")
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@router.post("/search")
async def search_handler(
    request: Request, 
    q: str = Form(""), 
    db: AsyncSession = Depends(get_db)
):
    search_terms = normalize_search_input(q)
    
    if not search_terms:
        return templates.TemplateResponse("partials/search_results.html", {
            "request": request, "results": [], "error": "Введите номера контейнеров или вагонов."
        })

    # Ищем в базе (поддержка и контейнеров, и вагонов в одной таблице Tracking)
    # Предполагаем, что Tracking.container_number хранит идентификатор (контейнер ИЛИ вагон, если такая логика)
    # Если вагоны в отдельном поле wagon_number, запрос нужно усложнить.
    # В текущей схеме: ищем по container_number (для контейнеров) или wagon_number (для вагонов)
    
    # Разделяем на контейнеры и вагоны для точного поиска
    containers = [t for t in search_terms if len(t) == 11]
    wagons = [t for t in search_terms if len(t) == 8]
    
    conditions = []
    if containers:
        conditions.append(Tracking.container_number.in_(containers))
    if wagons:
        conditions.append(Tracking.wagon_number.in_(wagons))
    
    if not conditions:
         return templates.TemplateResponse("partials/search_results.html", {
            "request": request, "results": [], "error": "Некорректный формат номеров."
        })

    from sqlalchemy import or_
    stmt = select(Tracking).where(or_(*conditions)).order_by(Tracking.operation_date.desc())
    
    # Для уникальности (берем только последнюю запись для каждого номера)
    # В реальном SQL лучше использовать DISTINCT ON, но здесь сделаем python-фильтрацию для простоты
    results_raw = (await db.execute(stmt)).scalars().all()
    
    unique_map = {}
    for r in results_raw:
        # Ключ уникальности: если искали по вагону, то вагон, иначе контейнер
        key = r.container_number
        if r.wagon_number in wagons and r.container_number not in containers:
             key = r.wagon_number # Если нашли по вагону
             
        if key not in unique_map:
            unique_map[key] = r
            
    final_results = list(unique_map.values())
    
    # Обогащаем данными (прогресс, поезда)
    enriched_results = await enrich_tracking_data(db, final_results)

    return templates.TemplateResponse("partials/search_results.html", {
        "request": request,
        "results": enriched_results,
        "query_string": q # Возвращаем строку запроса для кнопки Excel
    })

@router.post("/search/export")
async def export_search_results(
    q: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    """Генерация Excel для найденных результатов."""
    search_terms = normalize_search_input(q)
    if not search_terms:
        return # Или ошибка
        
    containers = [t for t in search_terms if len(t) == 11]
    wagons = [t for t in search_terms if len(t) == 8]
    
    from sqlalchemy import or_
    conditions = []
    if containers: conditions.append(Tracking.container_number.in_(containers))
    if wagons: conditions.append(Tracking.wagon_number.in_(wagons))
    
    stmt = select(Tracking).where(or_(*conditions)).order_by(Tracking.operation_date.desc())
    results = (await db.execute(stmt)).scalars().all()
    
    # Дедупликация
    unique_map = {}
    for r in results:
        key = r.container_number
        if r.wagon_number in wagons and r.container_number not in containers: key = r.wagon_number
        if key not in unique_map: unique_map[key] = r
    
    final_data = list(unique_map.values())
    
    # Формируем Excel
    headers = [
        'Номер', 'Дата отправления', 'Станция отправления', 'Станция назначения',
        'Станция операции', 'Операция', 'Дата операции', 'Вагон', 'Индекс поезда', 
        'Осталось км', 'Прогноз (дней)'
    ]
    rows = []
    for item in final_data:
        rows.append([
            item.container_number,
            item.trip_start_datetime.strftime('%d.%m.%Y') if item.trip_start_datetime else '',
            item.from_station,
            item.to_station,
            item.current_station,
            item.operation,
            item.operation_date.strftime('%d.%m.%Y %H:%M') if item.operation_date else '',
            item.wagon_number,
            item.train_index_full,
            item.km_left,
            item.forecast_days
        ])
        
    file_path = await asyncio.to_thread(create_excel_file_from_strings, rows, headers)
    filename = get_vladivostok_filename("Search_Result")
    
    def iterfile():
        with open(file_path, mode="rb") as file_like:
            yield from file_like
        os.remove(file_path)

    return StreamingResponse(
        iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )