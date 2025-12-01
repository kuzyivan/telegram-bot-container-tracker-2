import sys
import os
import re
import asyncio
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse
from sqlalchemy import select, or_, desc
from sqlalchemy.ext.asyncio import AsyncSession

# --- Хак для импорта модулей из корня проекта ---
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
from models import Tracking, Train
from model.terminal_container import TerminalContainer
from utils.send_tracking import create_excel_file_from_strings, get_vladivostok_filename

router = APIRouter()

# --- Настройка путей к шаблонам ---
current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

async def get_db():
    async with SessionLocal() as session:
        yield session

# --- Вспомогательные функции ---

def normalize_search_input(text: str) -> list[str]:
    """
    Парсит текст на список уникальных номеров (контейнеры или вагоны).
    """
    if not text:
        return []
    text = text.upper().strip()
    items = re.split(r'[,\s;\n]+', text)
    
    valid_items = []
    for item in items:
        if re.fullmatch(r'[A-Z]{3}U\d{7}', item) or re.fullmatch(r'\d{8}', item):
            valid_items.append(item)
            
    return list(set(valid_items))

async def enrich_tracking_data(db: AsyncSession, tracking_items: list[Tracking]):
    """
    Добавляет к объектам Tracking дополнительные данные:
    - Прогресс (%)
    - Инфо о поезде и перегрузе
    - Расчетный прогноз
    """
    enriched_data = []
    
    for item in tracking_items:
        # 1. Расчет прогресса (%)
        progress_percent = 0
        total_dist = item.total_distance or 0
        km_left = item.km_left or 0
        
        if total_dist > 0:
            traveled = total_dist - km_left
            progress_percent = int((traveled / total_dist) * 100)
        
        progress_percent = max(0, min(100, progress_percent))

        # 2. Поиск информации о поезде
        terminal_train_info = {
            "number": None,
            "overload_station": None
        }
        
        tc_res = await db.execute(
            select(TerminalContainer.train)
            .where(TerminalContainer.container_number == item.container_number)
            .order_by(TerminalContainer.created_at.desc())
            .limit(1)
        )
        train_code = tc_res.scalar_one_or_none()
        
        if train_code:
            terminal_train_info["number"] = train_code
            t_res = await db.execute(
                select(Train.overload_station_name)
                .where(Train.terminal_train_number == train_code)
            )
            terminal_train_info["overload_station"] = t_res.scalar_one_or_none()

        # 3. Статус прибытия
        is_arrived = False
        if item.km_left == 0:
            is_arrived = True
        elif item.current_station and item.to_station and item.current_station.upper() == item.to_station.upper():
            is_arrived = True

        # 4. Расчет прогноза (дни)
        forecast_display = "—"
        if item.forecast_days:
            forecast_display = f"{item.forecast_days:.1f}"
        elif km_left > 0:
            try:
                calc_days = (km_left / 600) + 1
                forecast_display = f"{calc_days:.1f}"
            except:
                pass

        enriched_data.append({
            "obj": item,
            "progress": progress_percent,
            "train_info": terminal_train_info,
            "is_arrived": is_arrived,
            "forecast_days_display": forecast_display
        })
        
    return enriched_data

# --- Роуты (Endpoints) ---

@router.get("/")
async def read_root(request: Request):
    """Отображает главную страницу поиска."""
    return templates.TemplateResponse("index.html", {"request": request})

@router.post("/search")
async def search_handler(
    request: Request, 
    q: str = Form(""), 
    db: AsyncSession = Depends(get_db)
):
    """Обрабатывает поиск и возвращает результаты."""
    search_terms = normalize_search_input(q)
    
    if not search_terms:
        return templates.TemplateResponse("partials/search_results.html", {
            "request": request, "groups": [], "error": "Введите корректные номера."
        })

    # 1. Поиск в БД
    containers = [t for t in search_terms if len(t) == 11]
    wagons = [t for t in search_terms if len(t) == 8]
    
    conditions = []
    if containers: conditions.append(Tracking.container_number.in_(containers))
    if wagons: conditions.append(Tracking.wagon_number.in_(wagons))
    
    if not conditions:
         return templates.TemplateResponse("partials/search_results.html", {
            "request": request, "groups": [], "error": "Некорректный формат."
        })

    stmt = select(Tracking).where(or_(*conditions)).order_by(Tracking.operation_date.desc())
    results_raw = (await db.execute(stmt)).scalars().all()
    
    # 2. Дедупликация
    unique_map = {}
    for r in results_raw:
        key = r.container_number
        if r.wagon_number in wagons and r.container_number not in containers:
             key = r.wagon_number 
        if key not in unique_map:
            unique_map[key] = r
            
    final_results = list(unique_map.values())
    
    # 3. Обогащение
    enriched_results = await enrich_tracking_data(db, final_results)

    # 4. Группировка по поездам
    grouped_structure = []
    train_map = {} 

    for item in enriched_results:
        terminal_train_num = item['train_info']['number'] 
        
        if terminal_train_num:
            if terminal_train_num not in train_map:
                group_entry = {
                    "is_group": True,
                    "title": terminal_train_num,
                    "train_info": item['train_info'], 
                    "main_route": item['obj'], 
                    "containers": [] 
                }
                grouped_structure.append(group_entry)
                train_map[terminal_train_num] = len(grouped_structure) - 1
            
            group_idx = train_map[terminal_train_num]
            grouped_structure[group_idx]['containers'].append(item)
        else:
            grouped_structure.append({
                "is_group": False,
                "item": item
            })

    return templates.TemplateResponse("partials/search_results.html", {
        "request": request,
        "groups": grouped_structure,
        "query_string": q,
        "has_results": bool(grouped_structure)
    })

# --- ЭНДПОИНТ ДЛЯ АКТИВНЫХ ПОЕЗДОВ (С ФИЛЬТРАМИ) ---
@router.get("/active_trains")
async def get_active_trains(request: Request, db: AsyncSession = Depends(get_db)):
    """
    Возвращает список активных поездов.
    Фильтры:
    - Исключаем операции (39) Завоз и (49) Вывоз
    - Сортировка по номеру поезда
    - Лимит 10
    """
    stmt = (
        select(Train)
        .where(Train.last_operation_date.isnot(None))
        # ✅ ИСКЛЮЧАЕМ ОПЕРАЦИИ 39 и 49 (используем поиск подстроки)
        .where(Train.last_operation.not_ilike("%(39)%"))
        .where(Train.last_operation.not_ilike("%(49)%"))
        # -----------------------------------------------------
        .order_by(desc(Train.terminal_train_number)) 
        .limit(10)
    )
    result = await db.execute(stmt)
    trains = result.scalars().all()
    
    return templates.TemplateResponse("partials/active_trains.html", {
        "request": request,
        "trains": trains
    })

@router.post("/search/export")
async def export_search_results(
    q: str = Form(""),
    db: AsyncSession = Depends(get_db)
):
    """Экспорт в Excel."""
    search_terms = normalize_search_input(q)
    if not search_terms: return
        
    containers = [t for t in search_terms if len(t) == 11]
    wagons = [t for t in search_terms if len(t) == 8]
    
    conditions = []
    if containers: conditions.append(Tracking.container_number.in_(containers))
    if wagons: conditions.append(Tracking.wagon_number.in_(wagons))
    if not conditions: return

    stmt = select(Tracking).where(or_(*conditions)).order_by(Tracking.operation_date.desc())
    results = (await db.execute(stmt)).scalars().all()
    
    unique_map = {}
    for r in results:
        key = r.container_number
        if r.wagon_number in wagons and r.container_number not in containers: key = r.wagon_number
        if key not in unique_map: unique_map[key] = r
    
    final_data = list(unique_map.values())
    
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
        try:
            os.remove(file_path)
        except OSError:
            pass

    return StreamingResponse(
        iterfile(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )