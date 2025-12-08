from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Query, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import select, desc, distinct, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from models import User
from models_finance import (
    Calculation, CalculationItem, RailTariffRate, 
    SystemSetting, ServiceType, WagonType, MarginType, CalculationStatus
)
from services.calculator_service import PriceCalculator
from services.tariff_service import TariffStation
from db import TariffSessionLocal
from web.auth import admin_required
from .common import templates, get_db

router = APIRouter()

# --- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ---

def calculate_prr_cost_internal(wagon_type: str, container_type: str) -> float:
    """
    Внутренняя функция для получения константы ПРР.
    """
    # Константы (можно вынести в SystemSettings позже)
    PRR_PV_20 = 15000.00
    PRR_PV_40 = 21700.00 # 21 666,666 -> округлил для удобства
    PRR_PF_20 = 6700.00
    PRR_PF_40 = 8350.00

    c_type = container_type.upper() if container_type else ""
    
    if wagon_type == WagonType.GONDOLA:
        if "20" in c_type: return PRR_PV_20
        elif "40" in c_type: return PRR_PV_40
    elif wagon_type == WagonType.PLATFORM: 
        if "20" in c_type: return PRR_PF_20
        elif "40" in c_type: return PRR_PF_40
    
    return 0.0

async def get_tariff_stations(session: AsyncSession, is_departure: bool, filter_from_code: str = None, service_type: str = None):
    """Возвращает список станций (код, имя)."""
    target_col = RailTariffRate.station_from_code if is_departure else RailTariffRate.station_to_code
    query = select(target_col).distinct()

    if not is_departure:
        if filter_from_code:
            query = query.where(RailTariffRate.station_from_code == filter_from_code)
        if service_type:
            query = query.where(RailTariffRate.service_type == service_type)

    result_codes = await session.execute(query)
    codes_list = result_codes.scalars().all()

    if not codes_list: return []

    if not TariffSessionLocal:
        return [{"code": c, "name": f"Станция {c}"} for c in codes_list]

    async with TariffSessionLocal() as tariff_db:
        stmt = select(TariffStation.code, TariffStation.name).where(TariffStation.code.in_(codes_list))
        res = await tariff_db.execute(stmt)
        rows = res.all()

    unique_stations = {}
    for code, name in rows:
        clean_name = name.strip()
        if code not in unique_stations or len(clean_name) < len(unique_stations[code]):
            unique_stations[code] = clean_name

    result_list = [{"code": k, "name": v} for k, v in unique_stations.items()]
    result_list.sort(key=lambda x: x['name'])
    return result_list

# --- РОУТЫ ---

@router.get("/calculator")
async def calculator_list(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    stmt = select(Calculation).order_by(desc(Calculation.created_at))
    result = await db.execute(stmt)
    calculations = result.scalars().all()
    return templates.TemplateResponse("admin_calculator_list.html", {
        "request": request, "user": user, "calculations": calculations, "CalculationStatus": CalculationStatus
    })

@router.get("/calculator/new")
async def calculator_create_page(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    settings_stmt = select(SystemSetting)
    settings_res = await db.execute(settings_stmt)
    settings = {s.key: s.value for s in settings_res.scalars()}
    
    stations_from = await get_tariff_stations(db, is_departure=True)
    
    return templates.TemplateResponse("admin_calculator_form.html", {
        "request": request, "user": user, 
        "settings": settings, 
        "today": datetime.now().date(),
        "ServiceType": ServiceType, "WagonType": WagonType, "MarginType": MarginType, 
        "stations_from": stations_from,
        "calc": None # Новый расчет
    })

# 🔥 НОВЫЙ РОУТ: РЕДАКТИРОВАНИЕ
@router.get("/calculator/{calc_id}")
async def calculator_edit_page(
    request: Request, 
    calc_id: int, 
    db: AsyncSession = Depends(get_db), 
    user: User = Depends(admin_required)
):
    # Загружаем расчет со строками
    stmt = select(Calculation).options(selectinload(Calculation.items)).where(Calculation.id == calc_id)
    result = await db.execute(stmt)
    calc = result.scalar_one_or_none()
    
    if not calc:
        raise HTTPException(status_code=404, detail="Расчет не найден")

    # Настройки
    settings_stmt = select(SystemSetting)
    settings_res = await db.execute(settings_stmt)
    settings = {s.key: s.value for s in settings_res.scalars()}
    
    # Списки станций
    stations_from = await get_tariff_stations(db, is_departure=True)
    # Для "Куда" нужно подгрузить список с учетом "Откуда" этого расчета
    stations_to = await get_tariff_stations(db, is_departure=False, filter_from_code=calc.station_from, service_type=calc.service_type)

    # Ищем сохраненную стоимость ПРР в строках, чтобы подставить в input
    saved_prr = 0.0
    for item in calc.items:
        if "ПРР" in item.name:
            saved_prr = item.cost_price
            break
            
    # Если в базе нет строки ПРР (старый расчет), считаем по умолчанию
    if saved_prr == 0:
        saved_prr = calculate_prr_cost_internal(calc.wagon_type, calc.container_type)

    return templates.TemplateResponse("admin_calculator_form.html", {
        "request": request, "user": user,
        "settings": settings,
        "today": datetime.now().date(),
        "ServiceType": ServiceType, "WagonType": WagonType, "MarginType": MarginType,
        "stations_from": stations_from,
        "preloaded_stations_to": stations_to, # Передаем список "Куда" для предзаполнения
        "calc": calc, # Существующий расчет
        "saved_prr": saved_prr
    })

# 🔥 HTMX API: ПОЛУЧЕНИЕ ПРР (для обновления инпута)
@router.get("/api/calc/get_prr_input")
async def get_prr_input_html(
    wagon_type: str = Query(...),
    container_type: str = Query(...)
):
    """Возвращает HTML-инпут с обновленным значением ПРР"""
    cost = calculate_prr_cost_internal(wagon_type, container_type)
    # Возвращаем сам input с новым value. HTMX заменит старый input.
    return HTMLResponse(f"""
        <input type="number" name="prr_value" id="prr_input" value="{cost}" step="100"
               class="w-full px-4 py-3 bg-mono-bg border-transparent rounded-xl text-sm font-mono focus:bg-white focus:ring-2 focus:ring-mono-black transition outline-none">
    """)

@router.get("/api/calc/destinations")
async def get_available_destinations(
    request: Request, 
    station_from: Optional[str] = Query(None),
    service_type: Optional[str] = Query(None), 
    db: AsyncSession = Depends(get_db), 
    user: User = Depends(admin_required)
):
    if not station_from:
        return HTMLResponse('<option value="" disabled selected>Сначала выберите пункт отправления</option>')

    destinations = await get_tariff_stations(db, is_departure=False, filter_from_code=station_from, service_type=service_type)
    
    options_html = '<option value="" disabled selected>— Выберите станцию —</option>'
    for st in destinations:
        options_html += f'<option value="{st["code"]}">{st["name"]}</option>'
    
    if not destinations:
        options_html = '<option value="" disabled>Нет тарифов для этого направления</option>'
        
    return HTMLResponse(options_html)

@router.post("/api/calc/preview")
async def calculator_preview(
    request: Request,
    station_from: Optional[str] = Form(None),
    station_to: Optional[str] = Form(None), 
    container_type: str = Form(...),
    service_type: str = Form(...),
    wagon_type: str = Form(...),
    margin_type: str = Form(...),
    margin_value: float = Form(0.0),
    prr_value: float = Form(0.0), # 🔥 Теперь берем из формы
    expense_names: List[str] = Form([]),
    expense_values: List[float] = Form([]),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    """HTMX: Живой расчет."""
    extra_expenses_total = sum(expense_values)
    
    # ПРР берем прямо из инпута, который прислал фронт
    # (Фронт сам обновляет этот инпут через get_prr_input при смене параметров)
    prr_cost = prr_value 

    if not station_from or not station_to:
        return templates.TemplateResponse("partials/calc_summary.html", {
            "request": request, "tariff_found": False, "base_rate": 0, 
            "extra_expenses": extra_expenses_total, "prr_cost": prr_cost, "total_cost": extra_expenses_total + prr_cost
        })

    calc_service = PriceCalculator(db)
    tariff = await calc_service.get_tariff(station_from, station_to, container_type, service_type)
    base_rate = tariff.rate_no_vat if tariff else 0.0
    
    gondola_coeff = 1.0
    if wagon_type == WagonType.GONDOLA:
        setting = await db.get(SystemSetting, "gondola_coeff")
        if setting: gondola_coeff = float(setting.value)
    
    adjusted_base_rate = base_rate * gondola_coeff
    
    total_cost = adjusted_base_rate + extra_expenses_total + prr_cost
    
    sales_price_netto = total_cost + margin_value if margin_type == MarginType.FIX else total_cost * (1 + margin_value / 100)
    
    vat_setting = await db.get(SystemSetting, "vat_rate")
    vat_rate = float(vat_setting.value) if vat_setting else 20.0
    vat_amount = sales_price_netto * (vat_rate / 100)
    total_price_with_vat = sales_price_netto + vat_amount
    
    return templates.TemplateResponse("partials/calc_summary.html", {
        "request": request,
        "base_rate": base_rate,
        "gondola_coeff": gondola_coeff,
        "adjusted_base_rate": adjusted_base_rate,
        "extra_expenses": extra_expenses_total,
        "prr_cost": prr_cost,
        "total_cost": total_cost,
        "sales_price_netto": sales_price_netto,
        "vat_amount": vat_amount,
        "total_price_with_vat": total_price_with_vat,
        "tariff_found": bool(tariff)
    })

# ОБЩАЯ ФУНКЦИЯ СОХРАНЕНИЯ (Используется и для Create, и для Update)
async def _save_calculation_logic(
    db: AsyncSession,
    title: str, station_from: str, station_to: str, container_type: str,
    service_type: str, wagon_type: str, margin_type: str, margin_value: float,
    service_provider: str, expense_names: List[str], expense_values: List[float],
    prr_value: float,
    calc_id: Optional[int] = None # Если передан, то update
):
    calc_service = PriceCalculator(db)
    tariff = await calc_service.get_tariff(station_from, station_to, container_type, service_type)
    base_rate = tariff.rate_no_vat if tariff else 0.0
    
    gondola_coeff = 1.0
    if wagon_type == WagonType.GONDOLA:
        setting = await db.get(SystemSetting, "gondola_coeff")
        if setting: gondola_coeff = float(setting.value)
    
    adjusted_base_rate = base_rate * gondola_coeff
    extra_expenses_total = sum(expense_values)
    
    # ИТОГ (Берем ПРР из формы)
    total_cost = adjusted_base_rate + extra_expenses_total + prr_value
    
    sales_price_netto = total_cost + margin_value if margin_type == MarginType.FIX else total_cost * (1 + margin_value / 100)
    vat_setting = await db.get(SystemSetting, "vat_rate")
    vat_rate = float(vat_setting.value) if vat_setting else 20.0

    if calc_id:
        # UPDATE
        calc = await db.get(Calculation, calc_id)
        if not calc: return None
        # Очищаем старые items
        calc.items = []
    else:
        # CREATE
        calc = Calculation(created_at=func.now())
        db.add(calc)

    # Обновляем поля
    calc.title = title
    calc.service_provider = service_provider
    calc.service_type = service_type
    calc.wagon_type = wagon_type
    calc.container_type = container_type
    calc.station_from = station_from
    calc.station_to = station_to
    calc.valid_from = datetime.now().date()
    calc.total_cost = total_cost
    calc.margin_type = margin_type
    calc.margin_value = margin_value
    calc.total_price_netto = sales_price_netto
    calc.vat_rate = vat_rate
    calc.status = CalculationStatus.PUBLISHED

    await db.flush() # Получаем ID, если новый

    # Сохраняем строки
    db.add(CalculationItem(calculation_id=calc.id, name="Железнодорожный тариф", cost_price=adjusted_base_rate, is_auto_calculated=True))

    if prr_value > 0:
        prr_label = "ПРР"
        if wagon_type == WagonType.GONDOLA: prr_label = f"ПРР в ПВ ({container_type})"
        elif wagon_type == WagonType.PLATFORM: prr_label = f"ПРР на Платформе ({container_type})"
        
        db.add(CalculationItem(calculation_id=calc.id, name=prr_label, cost_price=prr_value, is_auto_calculated=True))
    
    for name, cost in zip(expense_names, expense_values):
        if name and name.strip(): 
            db.add(CalculationItem(calculation_id=calc.id, name=name.strip(), cost_price=cost, is_auto_calculated=False))
            
    await db.commit()
    return calc

@router.post("/calculator/create")
async def calculator_create(
    request: Request,
    title: str = Form(...), station_from: str = Form(...), station_to: str = Form(...),
    container_type: str = Form(...), service_type: str = Form(...), wagon_type: str = Form(...),
    margin_type: str = Form(...), margin_value: float = Form(0.0), service_provider: str = Form(...),
    prr_value: float = Form(0.0), # 🔥
    expense_names: List[str] = Form([]), expense_values: List[float] = Form([]),
    db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)
):
    await _save_calculation_logic(db, title, station_from, station_to, container_type, service_type, wagon_type, margin_type, margin_value, service_provider, expense_names, expense_values, prr_value, None)
    return RedirectResponse("/admin/calculator", status_code=303)

@router.post("/calculator/{calc_id}/update")
async def calculator_update(
    calc_id: int, request: Request,
    title: str = Form(...), station_from: str = Form(...), station_to: str = Form(...),
    container_type: str = Form(...), service_type: str = Form(...), wagon_type: str = Form(...),
    margin_type: str = Form(...), margin_value: float = Form(0.0), service_provider: str = Form(...),
    prr_value: float = Form(0.0), # 🔥
    expense_names: List[str] = Form([]), expense_values: List[float] = Form([]),
    db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)
):
    await _save_calculation_logic(db, title, station_from, station_to, container_type, service_type, wagon_type, margin_type, margin_value, service_provider, expense_names, expense_values, prr_value, calc_id)
    return RedirectResponse("/admin/calculator", status_code=303)