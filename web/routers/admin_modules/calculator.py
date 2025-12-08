from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Query, Form, HTTPException
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import select, desc, distinct, func
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

def calculate_prr_cost(wagon_type: str, container_type: str) -> float:
    """
    Рассчитывает стоимость ПРР (Погрузо-разгрузочных работ).
    Поддерживает: Полувагон (ПВ) и Фитинговую платформу.
    """
    # 1. Константы для ПРР в ПВ (Полувагон)
    PRR_PV_20 = 15000.00
    PRR_PV_40 = 21700.00
    
    # 2. Константы для ПРР на Платформе (Фитинговая)
    PRR_PF_20 = 6700.00
    PRR_PF_40 = 8350.00

    # Приводим типы к верхнему регистру для надежности
    c_type = container_type.upper()
    
    # Логика для Полувагона
    if wagon_type == WagonType.GONDOLA:
        if "20" in c_type:
            return PRR_PV_20
        elif "40" in c_type:
            return PRR_PV_40
            
    # Логика для Платформы
    elif wagon_type == WagonType.PLATFORM: 
        if "20" in c_type:
            return PRR_PF_20
        elif "40" in c_type:
            return PRR_PF_40
    
    return 0.0

async def get_tariff_stations(session: AsyncSession, is_departure: bool, filter_from_code: str = None, service_type: str = None):
    """
    Возвращает список уникальных станций (код, имя).
    Для дублей кодов выбирает самое короткое название (чтобы убрать '(экспорт)' и т.д.).
    """
    # 1. Получаем список уникальных КОДОВ из таблицы тарифов
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

    # 2. Получаем имена для кодов из Тарифной БД
    if not TariffSessionLocal:
        return [{"code": c, "name": f"Станция {c}"} for c in codes_list]

    async with TariffSessionLocal() as tariff_db:
        # Используем группировку, чтобы для одного кода взять одно имя
        # Берем имя минимальной длины (обычно это самое "чистое" название)
        stmt = select(TariffStation.code, TariffStation.name).where(TariffStation.code.in_(codes_list))
        res = await tariff_db.execute(stmt)
        rows = res.all()

    # 3. Фильтрация дублей в Python (оставляем самое короткое название для каждого кода)
    unique_stations = {}
    for code, name in rows:
        clean_name = name.strip()
        if code not in unique_stations:
            unique_stations[code] = clean_name
        else:
            # Если новое имя короче уже сохраненного - берем его (Угловая < Угловая (эксп))
            if len(clean_name) < len(unique_stations[code]):
                unique_stations[code] = clean_name

    # Превращаем в список и сортируем по алфавиту
    result_list = [{"code": k, "name": v} for k, v in unique_stations.items()]
    result_list.sort(key=lambda x: x['name'])
    
    return result_list

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
        "request": request, "user": user, "settings": settings, "today": datetime.now().date(),
        "ServiceType": ServiceType, "WagonType": WagonType, "MarginType": MarginType, "stations_from": stations_from 
    })

@router.get("/api/calc/destinations")
async def get_available_destinations(
    request: Request, 
    station_from: Optional[str] = Query(None), # Может быть пустым
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
    # Делаем поля Optional, чтобы избежать 422 ошибок при частичном заполнении
    station_from: Optional[str] = Form(None),
    station_to: Optional[str] = Form(None), 
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
    """
    HTMX: Живой расчет цены.
    """
    extra_expenses_total = sum(expense_values)
    
    # 1. Рассчитываем ПРР
    prr_cost = calculate_prr_cost(wagon_type, container_type)

    # Если ключевые поля не заполнены, возвращаем нули + ПРР (если выбран вагон/контейнер)
    if not station_from or not station_to:
        return templates.TemplateResponse("partials/calc_summary.html", {
            "request": request, 
            "tariff_found": False, 
            "base_rate": 0, 
            "extra_expenses": extra_expenses_total,
            "prr_cost": prr_cost, # Передаем ПРР в шаблон
            "total_cost": extra_expenses_total + prr_cost
        })

    calc_service = PriceCalculator(db)
    tariff = await calc_service.get_tariff(station_from, station_to, container_type, service_type)
    base_rate = tariff.rate_no_vat if tariff else 0.0
    
    gondola_coeff = 1.0
    if wagon_type == WagonType.GONDOLA:
        setting = await db.get(SystemSetting, "gondola_coeff")
        if setting: gondola_coeff = float(setting.value)
    
    adjusted_base_rate = base_rate * gondola_coeff
    
    # 2. Суммируем: Тариф + Допы + ПРР
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
        "prr_cost": prr_cost, # <-- Передаем в шаблон для отображения
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
    """
    Сохраняет расчет.
    """
    # 1. Повторный расчет
    calc_service = PriceCalculator(db)
    tariff = await calc_service.get_tariff(station_from, station_to, container_type, service_type)
    
    base_rate = tariff.rate_no_vat if tariff else 0.0
    
    gondola_coeff = 1.0
    if wagon_type == WagonType.GONDOLA:
        setting = await db.get(SystemSetting, "gondola_coeff")
        if setting: gondola_coeff = float(setting.value)
    
    adjusted_base_rate = base_rate * gondola_coeff
    
    # Расчет ПРР
    prr_cost = calculate_prr_cost(wagon_type, container_type)
    
    extra_expenses_total = sum(expense_values)
    
    # Итоговая себестоимость
    total_cost = adjusted_base_rate + extra_expenses_total + prr_cost
    
    sales_price_netto = total_cost + margin_value if margin_type == MarginType.FIX else total_cost * (1 + margin_value / 100)
    vat_setting = await db.get(SystemSetting, "vat_rate")
    vat_rate = float(vat_setting.value) if vat_setting else 20.0

    # 2. Создаем запись
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
    
    # 3. Сохраняем строки
    # ЖД Тариф
    db.add(CalculationItem(
        calculation_id=new_calc.id,
        name="Железнодорожный тариф",
        cost_price=adjusted_base_rate,
        is_auto_calculated=True
    ))

    # ПРР как отдельная строка (если есть)
    if prr_cost > 0:
        prr_label = "ПРР"
        if wagon_type == WagonType.GONDOLA:
            prr_label = f"ПРР в ПВ ({container_type})"
        elif wagon_type == WagonType.PLATFORM:
            prr_label = f"ПРР на Платформе ({container_type})"
            
        db.add(CalculationItem(
            calculation_id=new_calc.id,
            name=prr_label,
            cost_price=prr_cost,
            is_auto_calculated=True
        ))
    
    # Доп расходы
    for name, cost in zip(expense_names, expense_values):
        if name and name.strip(): 
            db.add(CalculationItem(
                calculation_id=new_calc.id,
                name=name.strip(),
                cost_price=cost,
                is_auto_calculated=False
            ))
            
    await db.commit()
    
    return RedirectResponse("/admin/calculator", status_code=303)