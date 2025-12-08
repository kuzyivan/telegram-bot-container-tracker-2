from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Query, Form, status
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import select, desc, distinct
from sqlalchemy.ext.asyncio import AsyncSession

# Импорты проекта
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

async def get_tariff_stations(session: AsyncSession, is_departure: bool, filter_from_code: str = None, service_type: str = None):
    """Возвращает список станций (код, имя) из тарифной БД."""
    target_col = RailTariffRate.station_from_code if is_departure else RailTariffRate.station_to_code
    query = select(target_col).distinct()

    if not is_departure:
        if filter_from_code:
            query = query.where(RailTariffRate.station_from_code == filter_from_code)
        if service_type:
            query = query.where(RailTariffRate.service_type == service_type)

    result_codes = await session.execute(query)
    codes_list = result_codes.scalars().all()

    if not codes_list:
        return []

    if not TariffSessionLocal:
        return [{"code": c, "name": f"Station {c}"} for c in codes_list]

    async with TariffSessionLocal() as tariff_db:
        stmt = select(TariffStation.code, TariffStation.name).where(TariffStation.code.in_(codes_list))
        res = await tariff_db.execute(stmt)
        rows = res.all()

    return [{"code": row.code, "name": row.name} for row in rows]

# --- РОУТЫ ---

@router.get("/calculator")
async def calculator_list(
    request: Request, 
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    stmt = select(Calculation).order_by(desc(Calculation.created_at))
    result = await db.execute(stmt)
    calculations = result.scalars().all()
    
    return templates.TemplateResponse("admin_calculator_list.html", {
        "request": request,
        "user": user,
        "calculations": calculations,
        "CalculationStatus": CalculationStatus
    })

@router.get("/calculator/new")
async def calculator_create_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    settings_stmt = select(SystemSetting)
    settings_res = await db.execute(settings_stmt)
    settings = {s.key: s.value for s in settings_res.scalars()}
    
    stations_from = await get_tariff_stations(db, is_departure=True)
    
    return templates.TemplateResponse("admin_calculator_form.html", {
        "request": request,
        "user": user,
        "settings": settings,
        "today": datetime.now().date(),
        "ServiceType": ServiceType,
        "WagonType": WagonType,
        "MarginType": MarginType,
        "stations_from": stations_from 
    })

@router.get("/api/calc/destinations")
async def get_available_destinations(
    request: Request,
    station_from: str = Query(...),
    service_type: str = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
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
    station_from: str = Form(...),
    station_to: str = Form(None), 
    container_type: str = Form(...),
    service_type: str = Form(...),
    wagon_type: str = Form(...),
    margin_type: str = Form(...),
    margin_value: float = Form(0.0),
    expense_names: List[str] = Form([]),
    expense_values: List[float] = Form([]),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    extra_expenses_total = sum(expense_values)
    if not station_to:
        return templates.TemplateResponse("partials/calc_summary.html", {
            "request": request, "tariff_found": False, "base_rate": 0, "extra_expenses": extra_expenses_total
        })

    calc_service = PriceCalculator(db)
    tariff = await calc_service.get_tariff(station_from, station_to, container_type, service_type)
    base_rate = tariff.rate_no_vat if tariff else 0.0
    
    gondola_coeff = 1.0
    if wagon_type == WagonType.GONDOLA:
        setting = await db.get(SystemSetting, "gondola_coeff")
        if setting: gondola_coeff = float(setting.value)
    
    adjusted_base_rate = base_rate * gondola_coeff
    total_cost = adjusted_base_rate + extra_expenses_total
    
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
        "total_cost": total_cost,
        "sales_price_netto": sales_price_netto,
        "vat_amount": vat_amount,
        "total_price_with_vat": total_price_with_vat,
        "tariff_found": bool(tariff)
    })

@router.post("/calculator/create")
async def calculator_save(
    request: Request,
    title: str = Form(...),
    station_from: str = Form(...),
    station_to: str = Form(...),
    container_type: str = Form(...),
    service_type: str = Form(...),
    wagon_type: str = Form(...),
    margin_type: str = Form(...),
    margin_value: float = Form(0.0),
    service_provider: str = Form(...),
    expense_names: List[str] = Form([]),
    expense_values: List[float] = Form([]),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    # 1. Расчет
    calc_service = PriceCalculator(db)
    tariff = await calc_service.get_tariff(station_from, station_to, container_type, service_type)
    base_rate = tariff.rate_no_vat if tariff else 0.0
    
    gondola_coeff = 1.0
    if wagon_type == WagonType.GONDOLA:
        setting = await db.get(SystemSetting, "gondola_coeff")
        if setting: gondola_coeff = float(setting.value)
    
    adjusted_base_rate = base_rate * gondola_coeff
    extra_expenses_total = sum(expense_values)
    total_cost = adjusted_base_rate + extra_expenses_total
    
    sales_price_netto = total_cost + margin_value if margin_type == MarginType.FIX else total_cost * (1 + margin_value / 100)
        
    vat_setting = await db.get(SystemSetting, "vat_rate")
    vat_rate = float(vat_setting.value) if vat_setting else 20.0

    # 2. Сохранение заголовка
    new_calc = Calculation(
        title=title,
        service_provider=service_provider,
        service_type=service_type,
        wagon_type=wagon_type,
        container_type=container_type,
        station_from=station_from,
        station_to=station_to,
        valid_from=datetime.now().date(),
        total_cost=total_cost,
        margin_type=margin_type,
        margin_value=margin_value,
        total_price_netto=sales_price_netto,
        vat_rate=vat_rate,
        status=CalculationStatus.PUBLISHED
    )
    
    db.add(new_calc)
    await db.flush()
    
    # 3. Сохранение строк
    db.add(CalculationItem(
        calculation_id=new_calc.id,
        name="Железнодорожный тариф",
        cost_price=adjusted_base_rate,
        is_auto_calculated=True
    ))
    
    for name, cost in zip(expense_names, expense_values):
        if name.strip(): 
            db.add(CalculationItem(
                calculation_id=new_calc.id,
                name=name.strip(),
                cost_price=cost,
                is_auto_calculated=False
            ))
            
    await db.commit()
    return RedirectResponse("/admin/calculator", status_code=303)