import secrets
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
    """Возвращает JSON с событиями для FullCalendar, включая суммарные TEU."""
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
        # Нам нужно знать TEU каждого стока по имени, чтобы просуммировать их для поезда
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
        
        # Карта: StockName -> TEU. 
        # (Игнорируем направление здесь, так как в stock_info у поезда хранятся именно имена стоков)
        stock_teu_map = {}
        for row in stock_res:
            s_name = (row.stock or "Основной").strip()
            count = row[2] # count(id)
            teu = count * 2 if '40' in str(row.size or "") else count
            
            stock_teu_map[s_name] = stock_teu_map.get(s_name, 0) + teu
        
        events = []
        for t in trains:
            title = f"{t.service_name} -> {t.destination}"
            bg_color = getattr(t, 'color', '#111111') or '#111111'
            overload = getattr(t, 'overload_station', "")
            owner = getattr(t, 'wagon_owner', "")
            
            # --- РАСЧЕТ СУММАРНОГО TEU ---
            linked_teu = 0
            has_stocks = False
            
            if t.stock_info:
                # Разбиваем строку по запятой (формат: "Сток 1, Сток 2")
                stock_names = [s.strip() for s in t.stock_info.split(',') if s.strip()]
                if stock_names:
                    has_stocks = True
                    for name in stock_names:
                        # Суммируем TEU по каждому найденному стоку
                        # Ищем по точному совпадению имени
                        linked_teu += stock_teu_map.get(name, 0)
            
            # Если стоков нет, передаем None, чтобы не показывать "0 TEU" зря
            final_teu = linked_teu if has_stocks else None

            events.append({
                "id": str(t.id), 
                "title": title, 
                "start": t.schedule_date.isoformat(),
                "allDay": True, 
                "backgroundColor": bg_color, 
                "borderColor": bg_color,
                "extendedProps": {
                    "service": t.service_name, 
                    "dest": t.destination, 
                    "stock": t.stock_info or "",
                    "current_teu": final_teu,  # <-- Сумма TEU всех привязанных стоков
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
    stock: str = Form(None), # Придет строка вида "Сток 1, Сток 2"
    comment: str = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager_required)
):
    stmt = update(ScheduledTrain).where(ScheduledTrain.id == event_id).values(
        stock_info=stock,
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
    stock: str = Form(None), 
    owner: str = Form(None), 
    overload_station: str = Form(None), 
    color: str = Form("#111111"),
    db: AsyncSession = Depends(get_db), 
    user: User = Depends(admin_required)
):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        new_train = ScheduledTrain(
            schedule_date=dt, 
            service_name=service, 
            destination=destination, 
            stock_info=stock, 
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