# web/routers/admin_modules/trains.py
from datetime import datetime, date
from typing import List, Optional
from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, desc, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from models import User, Train, UserRole
from model.terminal_container import TerminalContainer
from models_finance import ContainerFinance, Calculation
from web.auth import manager_required, admin_required
from .common import templates, get_db

router = APIRouter()

# --- 1. СПИСОК ПОЕЗДОВ ---
@router.get("/trains")
async def admin_trains_list(
    request: Request,
    q: str = "",
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager_required)
):
    stmt = select(Train).order_by(desc(Train.departure_date))
    
    if q:
        stmt = stmt.where(Train.terminal_train_number.ilike(f"%{q}%"))
        
    result = await db.execute(stmt)
    trains = result.scalars().all()
    
    return templates.TemplateResponse("admin_trains_list.html", {
        "request": request, 
        "user": user, 
        "trains": trains,
        "q": q
    })

# --- 2. ДЕТАЛЬНАЯ СТРАНИЦА ПОЕЗДА ---
@router.get("/trains/{train_id}")
async def admin_train_detail(
    request: Request,
    train_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager_required)
):
    # 1. Получаем поезд
    train = await db.get(Train, train_id)
    if not train:
        raise HTTPException(404, "Поезд не найден")

    # 2. Получаем контейнеры поезда + Финансы
    # Используем outerjoin, так как финансы могут быть еще не созданы
    stmt = (
        select(TerminalContainer, ContainerFinance)
        .join(ContainerFinance, TerminalContainer.id == ContainerFinance.terminal_container_id, isouter=True)
        .where(TerminalContainer.train == train.terminal_train_number)
        .order_by(TerminalContainer.container_number)
    )
    result = await db.execute(stmt)
    rows = result.all() # Список кортежей (TerminalContainer, ContainerFinance)

    containers_data = []
    total_cost = 0.0
    total_sales = 0.0
    
    for tc, fin in rows:
        cost = fin.cost_value if fin else 0.0
        sale = fin.sales_price if fin else 0.0
        margin = sale - cost
        
        total_cost += cost
        total_sales += sale
        
        containers_data.append({
            "tc": tc,
            "fin": fin, # Может быть None
            "cost": cost,
            "sale": sale,
            "margin": margin
        })

    total_margin = total_sales - total_cost
    
    # 3. Загружаем доступные расчеты (Calculations) для выпадающего списка
    # Берем только опубликованные расчеты типа TRAIN
    calcs_res = await db.execute(
        select(Calculation)
        .where(Calculation.service_type == 'TRAIN')
        .order_by(desc(Calculation.created_at))
    )
    calculations = calcs_res.scalars().all()

    return templates.TemplateResponse("admin_train_detail.html", {
        "request": request,
        "user": user,
        "train": train,
        "containers": containers_data,
        "calculations": calculations,
        "kpi": {
            "total_cost": total_cost,
            "total_sales": total_sales,
            "total_margin": total_margin
        }
    })

# --- 3. ОБНОВЛЕНИЕ ДАТ (HEADER) ---
@router.post("/trains/{train_id}/update_dates")
async def update_train_dates(
    train_id: int,
    departure_date: str = Form(None),
    arrival_date: str = Form(None),
    overload_station: str = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager_required)
):
    train = await db.get(Train, train_id)
    if not train: return RedirectResponse("/admin/trains", 303)

    if departure_date:
        try: train.departure_date = datetime.strptime(departure_date, "%Y-%m-%d").date()
        except: pass
    
    if arrival_date:
        try: train.arrival_date = datetime.strptime(arrival_date, "%Y-%m-%d").date()
        except: pass
        
    if overload_station is not None:
        train.overload_station_name = overload_station

    await db.commit()
    # Возвращаемся на ту же страницу
    return RedirectResponse(f"/admin/trains/{train_id}", status_code=303)

# --- 4. INLINE ОБНОВЛЕНИЕ ФИНАНСОВ (HTMX) ---
@router.post("/trains/container/{tc_id}/update_finance")
async def update_container_finance(
    tc_id: int,
    sales_price: float = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager_required)
):
    # Ищем или создаем запись финансов
    fin = await db.scalar(select(ContainerFinance).where(ContainerFinance.terminal_container_id == tc_id))
    
    if not fin:
        fin = ContainerFinance(terminal_container_id=tc_id, cost_value=0.0)
        db.add(fin)
    
    fin.sales_price = sales_price
    # Пересчитываем абсолютную маржу (если храним её в базе, или просто для UI)
    fin.margin_abs = fin.sales_price - fin.cost_value
    
    await db.commit()
    
    # Возвращаем HTML фрагмент ячейки с маржой
    margin_class = "text-green-600" if fin.margin_abs > 0 else "text-red-600"
    return HTMLResponse(f'<span class="font-bold {margin_class}">{fin.margin_abs:,.0f}</span>'.replace(',', ' '))

# --- 5. МАССОВОЕ ПРИМЕНЕНИЕ РАСЧЕТА (LINK CALCULATION) ---
@router.post("/trains/{train_id}/apply_calculation")
async def apply_calculation_to_train(
    train_id: int,
    calculation_id: int = Form(...),
    selected_containers: List[int] = Form(...), # Список ID TerminalContainer
    db: AsyncSession = Depends(get_db),
    user: User = Depends(manager_required)
):
    # 1. Получаем расчет (себестоимость)
    calc = await db.get(Calculation, calculation_id)
    if not calc:
        raise HTTPException(404, "Расчет не найден")
    
    # Берем себестоимость БЕЗ НДС (так как маржинальность обычно считается net-net)
    cost_to_apply = calc.total_cost 

    # 2. Обновляем контейнеры
    for tc_id in selected_containers:
        fin = await db.scalar(select(ContainerFinance).where(ContainerFinance.terminal_container_id == tc_id))
        
        if not fin:
            fin = ContainerFinance(terminal_container_id=tc_id, sales_price=0.0)
            db.add(fin)
        
        fin.source_calculation_id = calc.id
        fin.cost_value = cost_to_apply
        fin.margin_abs = fin.sales_price - fin.cost_value
    
    await db.commit()
    return RedirectResponse(f"/admin/trains/{train_id}", status_code=303)

# --- 6. (ADMIN) РУЧНОЕ УПРАВЛЕНИЕ СОСТАВОМ ---
@router.post("/trains/{train_id}/add_container")
async def add_container_to_train(
    train_id: int,
    container_number: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    train = await db.get(Train, train_id)
    if not train: return RedirectResponse("/admin/trains", 303)
    
    # Ищем контейнер
    tc = await db.scalar(select(TerminalContainer).where(TerminalContainer.container_number == container_number.strip().upper()))
    if tc:
        tc.train = train.terminal_train_number
        await db.commit()
    
    return RedirectResponse(f"/admin/trains/{train_id}", status_code=303)

@router.post("/trains/{train_id}/remove_container")
async def remove_container_from_train(
    train_id: int,
    tc_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    tc = await db.get(TerminalContainer, tc_id)
    if tc:
        tc.train = None # Отвязываем от поезда
        await db.commit()
        
    return RedirectResponse(f"/admin/trains/{train_id}", status_code=303)