import sys
import os
import re
import asyncio
from pathlib import Path
from datetime import datetime, timedelta, date
from typing import Optional

from fastapi import APIRouter, Request, Depends, Form
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse, HTMLResponse, RedirectResponse, JSONResponse
from sqlalchemy import select, or_, desc, and_, not_, func
from sqlalchemy.ext.asyncio import AsyncSession

# Добавляем корневую директорию в путь
sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
from models import Tracking, Train, User, UserRole, ScheduledTrain, ScheduleShareLink, UserRequest
from model.terminal_container import TerminalContainer
from utils.send_tracking import create_excel_file_from_strings, get_vladivostok_filename
from web.auth import get_current_user
from utils.notify import notify_admin 
from services.tariff_service import get_tariff_distance, TariffService

router = APIRouter(tags=["public"])

current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

async def get_db():
    async with SessionLocal() as session:
        yield session

# --- Вспомогательные функции ---

def normalize_search_input(text: str) -> list[str]:
    """Очищает ввод пользователя, извлекает номера контейнеров и вагонов."""
    if not text:
        return []
    text = text.upper().strip()
    items = re.split(r'[,\\s;\n]+', text)
    valid_items = []
    for item in items:
        # Простая валидация: Контейнер (4 буквы + 7 цифр) или Вагон (8 цифр)
        if re.fullmatch(r'[A-Z]{3}U\d{7}', item) or re.fullmatch(r'\d{8}', item):
            valid_items.append(item)
    return list(set(valid_items))

async def enrich_tracking_data(db: AsyncSession, tracking_items: list[Tracking]):
    """Обогащает данные трекинга (расчет прогресса, прогноз, инфо о поезде)."""
    enriched_data = []
    for item in tracking_items:
        progress_percent = 0
        total_dist = item.total_distance or 0
        km_left = item.km_left or 0
        if total_dist > 0:
            traveled = total_dist - km_left
            progress_percent = int((traveled / total_dist) * 100)
        progress_percent = max(0, min(100, progress_percent))

        terminal_train_info = {"number": None, "overload_station": None}
        
        # Ищем, с каким поездом терминала связан контейнер
        tc_res = await db.execute(
            select(TerminalContainer.train)
            .where(TerminalContainer.container_number == item.container_number)
            .order_by(TerminalContainer.created_at.desc())
            .limit(1)
        )
        train_code = tc_res.scalar_one_or_none()
        
        if train_code:
            terminal_train_info["number"] = train_code
            # Ищем инфо о перегрузе этого поезда
            t_res = await db.execute(select(Train.overload_station_name).where(Train.terminal_train_number == train_code))
            terminal_train_info["overload_station"] = t_res.scalar_one_or_none()

        is_arrived = False
        if item.km_left == 0:
            is_arrived = True
        elif item.current_station and item.to_station and item.current_station.upper() == item.to_station.upper():
            is_arrived = True
        elif item.operation and "выгрузка" in item.operation.lower():
            is_arrived = True

        forecast_display = "—"
        if item.forecast_days:
            forecast_display = f"{item.forecast_days:.1f}"
        elif km_left > 0:
            try:
                calc_days = (km_left / 500) + 1 # Примерная скорость
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

# --- Роуты ---

@router.get("/", response_class=HTMLResponse)
async def read_root(request: Request, user: Optional[User] = Depends(get_current_user)):
    """Главная страница (Поиск)."""
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

@router.get("/landing", response_class=HTMLResponse)
async def landing_page_hidden(request: Request, user: Optional[User] = Depends(get_current_user)):
    """Лендинг (доступен только админу)."""
    if not user or user.role != UserRole.ADMIN:
        return RedirectResponse("/")
    return templates.TemplateResponse("landing.html", {"request": request, "user": user})

@router.post("/contact_form")
async def handle_contact_form(request: Request, name: str = Form(...), phone: str = Form(...), message: str = Form(None)):
    """Обработка формы контактов."""
    text = f"📩 *Заявка с сайта!*\n👤 {name}\n📞 {phone}\n💬 {message or '-'}"
    try:
        await notify_admin(text, silent=False, parse_mode="Markdown")
    except:
        print("Ошибка отправки уведомления в Telegram")
        
    return HTMLResponse("""
        <div class="bg-green-50 p-6 rounded-xl text-center animate-fade-in border border-green-200">
            <h3 class="text-xl font-bold mb-2 text-green-800">Спасибо!</h3>
            <p class="text-green-700">Ваша заявка принята.</p>
        </div>
    """)

@router.post("/search")
async def search_handler(request: Request, q: str = Form(""), db: AsyncSession = Depends(get_db)):
    """Основной поиск (HTMX)."""
    search_terms = normalize_search_input(q)
    if not search_terms:
        return templates.TemplateResponse("partials/search_results.html", {"request": request, "groups": [], "error": "Введите корректные номера."})

    # Лог запроса
    try:
        new_req = UserRequest(query_text=q[:500], ip_address=request.client.host)
        db.add(new_req)
        await db.commit()
    except: pass

    containers = [t for t in search_terms if len(t) == 11]
    wagons = [t for t in search_terms if len(t) == 8]
    conditions = []
    if containers: conditions.append(Tracking.container_number.in_(containers))
    if wagons: conditions.append(Tracking.wagon_number.in_(wagons))
    
    if not conditions:
         return templates.TemplateResponse("partials/search_results.html", {"request": request, "groups": [], "error": "Некорректный формат."})

    stmt = select(Tracking).where(or_(*conditions)).order_by(Tracking.operation_date.desc())
    results_raw = (await db.execute(stmt)).scalars().all()
    
    # Убираем дубли (оставляем свежие)
    unique_map = {}
    for r in results_raw:
        key = r.container_number
        if r.wagon_number in wagons and r.container_number not in containers: key = r.wagon_number 
        if key not in unique_map: unique_map[key] = r
    final_results = list(unique_map.values())
    
    enriched_results = await enrich_tracking_data(db, final_results)

    # Группировка по поездам
    grouped_structure = []
    train_map = {} 
    for item in enriched_results:
        terminal_train_num = item['train_info']['number'] 
        if terminal_train_num:
            if terminal_train_num not in train_map:
                group_entry = {"is_group": True, "title": terminal_train_num, "train_info": item['train_info'], "main_route": item['obj'], "containers": []}
                grouped_structure.append(group_entry)
                train_map[terminal_train_num] = len(grouped_structure) - 1
            group_idx = train_map[terminal_train_num]
            grouped_structure[group_idx]['containers'].append(item)
        else:
            grouped_structure.append({"is_group": False, "item": item})

    return templates.TemplateResponse("partials/search_results.html", {"request": request, "groups": grouped_structure, "query_string": q, "has_results": bool(grouped_structure)})

@router.get("/active_trains")
async def get_active_trains(request: Request, db: AsyncSession = Depends(get_db)):
    """Виджет активных поездов."""
    five_days_ago = datetime.now() - timedelta(days=5)
    
    # Фильтруем завершенные и архивные поезда
    stmt = select(Train).where(Train.last_operation_date.isnot(None))\
        .where(Train.last_operation.not_ilike("%(39)%"))\
        .where(Train.last_operation.not_ilike("%(49)%"))\
        .where(not_(and_(func.lower(Train.destination_station) == func.lower(Train.last_known_station), Train.last_operation.ilike("%выгрузка%"), Train.last_operation_date < five_days_ago)))\
        .order_by(desc(Train.terminal_train_number)).limit(10)
    
    result = await db.execute(stmt)
    trains = result.scalars().all()

    # Подсчет оставшегося расстояния
    for train in trains:
        if train.last_known_station and train.destination_station:
            try:
                calc_result = await get_tariff_distance(train.last_known_station, train.destination_station)
                if calc_result and calc_result.get('distance', 0) > 0:
                    train.km_remaining = calc_result['distance']
            except: pass

    return templates.TemplateResponse("partials/active_trains.html", {"request": request, "trains": trains})

@router.post("/search/export")
async def export_search_results(q: str = Form(""), db: AsyncSession = Depends(get_db)):
    """Экспорт результатов поиска в Excel."""
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
    headers = ['Номер', 'Дата отправления', 'Станция отправления', 'Станция назначения', 'Станция операции', 'Операция', 'Дата операции', 'Вагон', 'Индекс поезда', 'Осталось км', 'Прогноз (дней)']
    rows = []
    for item in final_data:
        rows.append([
            item.container_number,
            item.trip_start_datetime.strftime('%d.%m.%Y') if item.trip_start_datetime else '',
            item.from_station, item.to_station, item.current_station, item.operation,
            item.operation_date.strftime('%d.%m.%Y %H:%M') if item.operation_date else '',
            item.wagon_number, item.train_index_full, item.km_left, item.forecast_days
        ])
    
    file_path = await asyncio.to_thread(create_excel_file_from_strings, rows, headers)
    filename = get_vladivostok_filename("Search_Result")
    
    def iterfile():
        with open(file_path, mode="rb") as file_like:
            yield from file_like
        try: os.remove(file_path)
        except OSError: pass
        
    return StreamingResponse(iterfile(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", headers={"Content-Disposition": f"attachment; filename={filename}"})

# --- 📏 КАЛЬКУЛЯТОР РАССТОЯНИЙ ---

@router.get("/distance", response_class=HTMLResponse)
async def distance_page(request: Request, user: Optional[User] = Depends(get_current_user)):
    return templates.TemplateResponse("distance.html", {"request": request, "user": user})

@router.post("/distance")
async def calculate_distance(request: Request, station_a: str = Form(None), station_b: str = Form(None)):
    """Расчет расстояния через TariffService."""
    if not station_a or not station_b:
        return templates.TemplateResponse("partials/distance_result.html", {"request": request, "error": "Заполните обе станции."})
    try:
        service = TariffService()
        result = await service.get_tariff_distance(station_a, station_b)
        if not result:
            return templates.TemplateResponse("partials/distance_result.html", {"request": request, "error": "Маршрут не найден."})
        return templates.TemplateResponse("partials/distance_result.html", {"request": request, "result": result})
    except Exception as e:
        return templates.TemplateResponse("partials/distance_result.html", {"request": request, "error": f"Ошибка: {str(e)}"})

@router.post("/tracking/recalc/{container_id}")
async def recalc_tracking_distance(request: Request, container_id: int, db: AsyncSession = Depends(get_db)):
    """Пересчет расстояния для конкретного контейнера в выдаче."""
    stmt = select(Tracking).where(Tracking.id == container_id)
    track = (await db.execute(stmt)).scalar_one_or_none()
    
    if not track or not track.current_station or not track.to_station:
        return HTMLResponse('<span class="text-xs text-red-500">Нет данных</span>')
    
    try:
        service = TariffService()
        res = await service.get_tariff_distance(track.current_station, track.to_station)
        if res and res.get('distance'):
            dist = res['distance']
            track.km_left = dist 
            await db.commit()
            return HTMLResponse(f"""
                <div id="dist-{container_id}" class="flex flex-col items-center">
                    <span class="font-bold text-mono-black text-sm">{dist} км</span>
                    <span class="text-[9px] text-green-600 font-bold">10-01 (Обновлено)</span>
                </div>
            """)
    except: pass
    return HTMLResponse('<span class="text-xs text-red-500">Ошибка</span>')

# ==========================================
# === 🗓 ПУБЛИЧНЫЙ ГРАФИК (SHARE) ===
# ==========================================

@router.get("/schedule/share/{token}")
async def view_shared_schedule_page(request: Request, token: str, db: AsyncSession = Depends(get_db)):
    """Публичная страница календаря."""
    stmt = select(ScheduleShareLink).where(ScheduleShareLink.token == token)
    link = (await db.execute(stmt)).scalar_one_or_none()
    
    if not link:
        return templates.TemplateResponse("client_no_company.html", {"request": request, "error_message": "Ссылка недействительна."}, status_code=404)
        
    return templates.TemplateResponse("public_schedule.html", {"request": request, "token": token, "link_name": link.name})

@router.get("/api/share/{token}/events")
async def get_shared_schedule_events(token: str, start: str, end: str, db: AsyncSession = Depends(get_db)):
    """API событий для публичного календаря (восстановлено)."""
    # 1. Проверка токена
    stmt_link = select(ScheduleShareLink).where(ScheduleShareLink.token == token)
    if not (await db.execute(stmt_link)).scalar_one_or_none():
        return []

    try:
        start_date = datetime.strptime(start.split('T')[0], "%Y-%m-%d").date()
        end_date = datetime.strptime(end.split('T')[0], "%Y-%m-%d").date()
    except:
        return []
    
    # 2. Выборка событий
    stmt = select(ScheduledTrain).where(and_(ScheduledTrain.schedule_date >= start_date, ScheduledTrain.schedule_date <= end_date))
    trains = (await db.execute(stmt)).scalars().all()
    
    events = []
    for t in trains:
        # Безопасное получение полей
        overload = getattr(t, 'overload_station', "")
        owner = getattr(t, 'wagon_owner', "")
        bg_color = getattr(t, 'color', '#111111') or '#111111'

        events.append({
            "id": t.id,
            "title": f"{t.service_name} -> {t.destination}",
            "start": t.schedule_date.isoformat(),
            "allDay": True,
            "backgroundColor": bg_color, 
            "borderColor": bg_color,
            "extendedProps": {
                "service": t.service_name,
                "dest": t.destination,
                "stock": t.stock_info or "",
                "owner": owner or "",
                "overload": overload or "",
                "comment": t.comment or ""
            }
        })
    return JSONResponse(events)