import secrets
import json
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, update, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from models import User, ScheduledTrain, ScheduleShareLink
from model.terminal_container import TerminalContainer 
from web.auth import admin_required, manager_required
from .common import templates, get_db

router = APIRouter()

# --- ПРОСМОТР (Доступно Менеджерам и Админам) ---

@router.get("/schedule_planner")
async def schedule_planner_page(
    request: Request, 
    user: User = Depends(manager_required)
):
    """Отдает HTML-страницу планировщика."""
    return templates.TemplateResponse("schedule_planner.html", {"request": request, "user": user})

# --- НОВЫЙ ЭНДПОИНТ: Получение списка активных стоков для Select ---
@router.get("/api/schedule/stocks_list")
async def get_active_stocks(
    db: AsyncSession = Depends(get_db), 
    user: User = Depends(manager_required)
):
    """Возвращает список доступных стоков с их текущим TEU и направлением."""
    # Группируем контейнеры, которые еще не отправлены (dispatch_date is None)
    stmt = (
        select(
            TerminalContainer.direction,
            TerminalContainer.stock,
            TerminalContainer.size,
            func.count(TerminalContainer.id)
        )
        .where(TerminalContainer.dispatch_date.is_(None)) 
        .group_by(TerminalContainer.direction, TerminalContainer.stock, TerminalContainer.size)
    )
    result = await db.execute(stmt)
    
    # Агрегация данных
    stocks_map = {}
    for row in result:
        # Нормализуем данные, так как в базе могут быть None или пробелы
        direction = (row.direction or "Без направления").strip()
        stock_name = (row.stock or "Основной").strip()
        size_val = str(row.size or "")
        count = row[3]
        
        # Уникальный ключ для стока (чтобы схлопнуть разные размеры контейнеров в одну запись стока)
        key = f"{direction}|{stock_name}"
        
        if key not in stocks_map:
            stocks_map[key] = {
                "direction": direction, 
                "name": stock_name, 
                "teu": 0
            }
            
        # Расчет TEU: 40 футов = 2 TEU, 20 футов = 1 TEU
        teu_add = count * 2 if '40' in size_val else count
        stocks_map[key]["teu"] += teu_add

    # Возвращаем список значений словаря
    return list(stocks_map.values())

@router.get("/api/schedule/events")
async def get_schedule_events(
    start: str, 
    end: str, 
    db: AsyncSession = Depends(get_db), 
    user: User = Depends(manager_required)
):
    """Возвращает JSON с событиями для FullCalendar, включая суммарные TEU.
       Теперь поле stock_info содержит JSON-строку с привязкой стоков к направлениям.
    """
    try:
        start_date = datetime.strptime(start.split('T')[0], "%Y-%m-%d").date()
        end_date = datetime.strptime(end.split('T')[0], "%Y-%m-%d").date()
        
        # 1. Получаем поезда в диапазоне дат
        stmt = select(ScheduledTrain).where(
            and_(ScheduledTrain.schedule_date >= start_date, ScheduledTrain.schedule_date <= end_date)
        )
        result = await db.execute(stmt)
        trains = result.scalars().all()
        
        # 2. Получаем статистику по стокам (кэш для расчета TEU)
        stock_stmt = (
            select(
                TerminalContainer.stock,
                TerminalContainer.size,
                func.count(TerminalContainer.id)
            )
            .where(TerminalContainer.dispatch_date.is_(None)) 
            .group_by(TerminalContainer.stock, TerminalContainer.size)
        )
        stock_res = await db.execute(stock_stmt)
        
        # Карта: StockName -> TEU
        stock_teu_map = {}
        for row in stock_res:
            s_name = (row.stock or "Основной").strip()
            count = row[2] # count(id)
            teu = count * 2 if '40' in str(row.size or "") else count
            
            stock_teu_map[s_name] = stock_teu_map.get(s_name, 0) + teu
        
        events = []
        for t in trains:
            # --- НОВАЯ ЛОГИКА РАСЧЕТА ТЕКУЩЕГО TEU И ЗАГОЛОВКА ---
            linked_teu = 0
            all_directions = []
            
            try:
                # Попытка разобрать JSON-строку из stock_info
                directional_stocks = json.loads(t.stock_info) if t.stock_info else []
                is_complex_structure = isinstance(directional_stocks, list)
            except (json.JSONDecodeError, TypeError):
                # Если это не JSON, то это старая простая строка стоков (через запятую)
                directional_stocks = []
                is_complex_structure = False
            
            if is_complex_structure and directional_stocks:
                # 1. Сбор всех направлений и подсчет TEU по новому формату
                all_linked_stocks = set()
                for item in directional_stocks:
                    direction = item.get("direction")
                    stocks = item.get("stocks", [])
                    
                    if direction:
                        all_directions.append(direction)
                    
                    for name in stocks:
                        name = name.strip()
                        if name:
                            all_linked_stocks.add(name)
                            linked_teu += stock_teu_map.get(name, 0)
                
                # Заголовок теперь формируется из всех направлений
                title = f"{t.service_name} -> {', '.join(all_directions)}"
                
                # ExtendedProps: храним JSON как строку для передачи на фронтенд
                stock_info_display = t.stock_info
                final_teu = linked_teu
            else:
                # 2. Обработка старого или простого формата (если directional_stocks не является массивом)
                title = f"{t.service_name} -> {t.destination}"
                stock_info_display = t.stock_info or ""
                
                # Если это старая строка, парсим её для TEU (как раньше)
                if stock_info_display:
                    stock_names = [s.strip() for s in stock_info_display.split(',') if s.strip()]
                    for name in stock_names:
                        linked_teu += stock_teu_map.get(name, 0)
                
                final_teu = linked_teu if stock_info_display else None


            bg_color = getattr(t, 'color', '#111111') or '#111111'
            overload = getattr(t, 'overload_station', "")
            owner = getattr(t, 'wagon_owner', "")

            events.append({
                "id": str(t.id), 
                "title": title, 
                "start": t.schedule_date.isoformat(),
                "allDay": True, 
                "backgroundColor": bg_color, 
                "borderColor": bg_color,
                "extendedProps": {
                    "service": t.service_name, 
                    # destination сохраняем как есть (для совместимости)
                    "dest": t.destination, 
                    # stock теперь содержит JSON-строку для обработки на фронтенде
                    "stock": stock_info_display, 
                    "current_teu": final_teu,  
                    "owner": owner or "", 
                    "overload": overload or "", 
                    "comment": t.comment or ""
                },
                "editable": True 
            })
        return JSONResponse(events)
    except Exception as e:
        print(f"Error getting schedule events: {e}")
        return JSONResponse([], status_code=200)


# --- ЧАСТИЧНОЕ РЕДАКТИРОВАНИЕ (Доступно Менеджерам) ---

@router.post("/api/schedule/{event_id}/update_details")
async def update_schedule_details(
    event_id: int,
    stock: str = Form(None), # Ожидается JSON-строка: [{"direction": "...", "stocks": ["...", "..."]}, ...]
    comment: str = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager_required)
):
    # Проверяем, что пришедшая строка stock является валидным JSON, если она не пуста
    if stock:
        try:
            # Просто проверяем на валидность, сохраняем как строку
            json.loads(stock)
        except json.JSONDecodeError:
            # Если не валидный JSON, сохраняем как есть (возможно, это старый формат или комментарий)
            pass 
    
    stmt = update(ScheduledTrain).where(ScheduledTrain.id == event_id).values(
        stock_info=stock, # Сохраняем JSON-строку с направлениями/стоками
        comment=comment
    )
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok"}


# --- ПОЛНОЕ УПРАВЛЕНИЕ (Только Админ) ---

@router.post("/api/schedule/create")
async def create_schedule_event(
    date_str: str = Form(...), 
    service: str = Form(...), 
    destination: str = Form(...), 
    stock: str = Form(None), # Ожидается JSON-строка: [{"direction": "...", "stocks": ["...", "..."]}, ...]
    owner: str = Form(None), 
    overload_station: str = Form(None), 
    color: str = Form("#111111"),
    db: AsyncSession = Depends(get_db), 
    user: User = Depends(admin_required)
):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        
        # Проверяем, что пришедшая строка stock является валидным JSON, если она не пуста
        # и приводим основной destination, если он не указан, к первому направлению из JSON
        if stock:
            try:
                directional_stocks = json.loads(stock)
                if isinstance(directional_stocks, list) and directional_stocks and 'direction' in directional_stocks[0]:
                    # Если destination не указан, берем его из первого направления
                    if not destination:
                        destination = directional_stocks[0]['direction']
            except json.JSONDecodeError:
                # Если не валидный JSON, оставляем как есть (возможно, это старый формат)
                pass 

        new_train = ScheduledTrain(
            schedule_date=dt, 
            service_name=service, 
            destination=destination, 
            stock_info=stock, # Сохраняем JSON-строку с направлениями/стоками
            wagon_owner=owner, 
            overload_station=overload_station, 
            color=color
        )
        db.add(new_train)
        await db.commit()
        return {"status": "ok", "id": new_train.id}
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

@router.post("/api/schedule/{event_id}/move")
async def move_schedule_event(
    event_id: int, 
    new_date: str = Form(...), 
    db: AsyncSession = Depends(get_db), 
    user: User = Depends(admin_required)
):
    dt = datetime.strptime(new_date, "%Y-%m-%d").date()
    stmt = update(ScheduledTrain).where(ScheduledTrain.id == event_id).values(schedule_date=dt)
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok"}

@router.delete("/api/schedule/{event_id}")
async def delete_schedule_event(
    event_id: int, 
    db: AsyncSession = Depends(get_db), 
    user: User = Depends(admin_required)
):
    stmt = select(ScheduledTrain).where(ScheduledTrain.id == event_id)
    res = await db.execute(stmt)
    obj = res.scalar_one_or_none()
    if obj: 
        await db.delete(obj)
        await db.commit()
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