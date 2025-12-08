from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Query, Form, HTTPException, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse
from sqlalchemy import select, desc, distinct, func
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

# Импорт сервиса загрузки тарифов
from services.tariff_importer_service import process_tariff_import

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
    # Константы (в будущем можно вынести в SystemSettings)
    PRR_PV_20 = 15000.00
    PRR_PV_40 = 21700.00 # 21 666,666 -> округлено
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
    """
    Возвращает список уникальных станций (код, имя) из таблицы тарифов.
    """
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

    # Если базы тарифов нет, возвращаем коды
    if not TariffSessionLocal:
        return [{"code": c, "name": f"Станция {c}"} for c in codes_list]

    # Подгружаем имена из справочника станций
    async with TariffSessionLocal() as tariff_db:
        stmt = select(TariffStation.code, TariffStation.name).where(TariffStation.code.in_(codes_list))
        res = await tariff_db.execute(stmt)
        rows = res.all()

    # Фильтруем дубликаты имен, выбирая самое короткое (без уточнений типа 'эксп')
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
async def calculator_list(
    request: Request, 
    # Параметр фильтрации (по умолчанию TRAIN)
    type: str = Query("TRAIN"),
    db: AsyncSession = Depends(get_db), 
    user: User = Depends(admin_required)
):
    """Список расчетов с фильтрацией по типу (КП/Одиночная)."""
    
    # Фильтруем по типу сервиса
    stmt = select(Calculation).where(
        Calculation.service_type == type.upper()
    ).order_by(
        Calculation.service_provider,   # Группировка
        Calculation.container_type,     # Порядок внутри группы
        desc(Calculation.created_at)
    )
    
    result = await db.execute(stmt)
    calculations = result.scalars().all()
    
    return templates.TemplateResponse("admin_calculator_list.html", {
        "request": request, 
        "user": user, 
        "calculations": calculations, 
        "CalculationStatus": CalculationStatus,
        "today": datetime.now().date(), # Для проверки срока действия (неон)
        "current_type": type.upper()    # Для активной вкладки
    })

@router.get("/calculator/new")
async def calculator_create_page(
    request: Request, 
    # Параметр type для предустановки селекта (UX)
    type: str = Query("TRAIN"), 
    db: AsyncSession = Depends(get_db), 
    user: User = Depends(admin_required)
):
    """Страница создания нового расчета."""
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
        "calc": None,
        "default_service_type": type.upper() # Передаем в шаблон
    })

@router.get("/calculator/{calc_id}")
async def calculator_edit_page(
    request: Request, 
    calc_id: int, 
    db: AsyncSession = Depends(get_db), 
    user: User = Depends(admin_required)
):
    """Страница редактирования существующего расчета."""
    stmt = select(Calculation).options(selectinload(Calculation.items)).where(Calculation.id == calc_id)
    result = await db.execute(stmt)
    calc = result.scalar_one_or_none()
    
    if not calc:
        raise HTTPException(status_code=404, detail="Расчет не найден")

    settings_stmt = select(SystemSetting)
    settings_res = await db.execute(settings_stmt)
    settings = {s.key: s.value for s in settings_res.scalars()}
    
    stations_from = await get_tariff_stations(db, is_departure=True)
    stations_to = await get_tariff_stations(db, is_departure=False, filter_from_code=calc.station_from, service_type=calc.service_type)

    # Восстанавливаем состояние чекбоксов и значений из сохраненных строк
    saved_prr = 0.0
    saved_service_rate = 0.0
    include_rail_tariff = False
    include_prr = False

    for item in calc.items:
        if "ПРР" in item.name:
            saved_prr = item.cost_price
            include_prr = True
        elif "Железнодорожный тариф" in item.name:
            include_rail_tariff = True
        elif "Ставка сервиса" in item.name or "Транспортный сервис" in item.name:
            saved_service_rate = item.cost_price

    # Для старых расчетов (без явных строк) включаем ПРР по умолчанию, если сумма > 0
    if not include_prr and saved_prr == 0:
        default_prr = calculate_prr_cost_internal(calc.wagon_type, calc.container_type)
        if default_prr > 0:
            saved_prr = default_prr

    return templates.TemplateResponse("admin_calculator_form.html", {
        "request": request, "user": user,
        "settings": settings,
        "today": datetime.now().date(),
        "ServiceType": ServiceType, "WagonType": WagonType, "MarginType": MarginType,
        "stations_from": stations_from,
        "preloaded_stations_to": stations_to, 
        "calc": calc, 
        "saved_prr": saved_prr,
        "saved_service_rate": saved_service_rate,
        "include_rail_tariff": include_rail_tariff,
        "include_prr": include_prr
    })

@router.post("/calculator/{calc_id}/copy")
async def calculator_copy(
    calc_id: int,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    """Создает копию расчета."""
    stmt = select(Calculation).options(selectinload(Calculation.items)).where(Calculation.id == calc_id)
    result = await db.execute(stmt)
    original_calc = result.scalar_one_or_none()
    
    if not original_calc:
        return RedirectResponse("/admin/calculator", status_code=303)

    new_calc = Calculation(
        title=f"{original_calc.title} (копия)",
        service_provider=original_calc.service_provider,
        service_type=original_calc.service_type,
        wagon_type=original_calc.wagon_type,
        container_type=original_calc.container_type,
        station_from=original_calc.station_from,
        station_to=original_calc.station_to,
        valid_from=datetime.now().date(), # Обновляем дату начала на сегодня
        valid_to=original_calc.valid_to,
        total_cost=original_calc.total_cost,
        margin_type=original_calc.margin_type,
        margin_value=original_calc.margin_value,
        total_price_netto=original_calc.total_price_netto,
        vat_rate=original_calc.vat_rate,
        status=CalculationStatus.DRAFT,
        created_at=func.now()
    )
    
    db.add(new_calc)
    await db.flush()

    for item in original_calc.items:
        new_item = CalculationItem(
            calculation_id=new_calc.id,
            name=item.name,
            cost_price=item.cost_price,
            is_auto_calculated=item.is_auto_calculated
        )
        db.add(new_item)
        
    await db.commit()
    return RedirectResponse(f"/admin/calculator/{new_calc.id}", status_code=303)


# HTMX: Получение значения ПРР для инпута
@router.get("/api/calc/get_prr_input")
async def get_prr_input_html(
    wagon_type: str = Query(...),
    container_type: str = Query(...)
):
    cost = calculate_prr_cost_internal(wagon_type, container_type)
    return HTMLResponse(f"""
        <input type="number" name="prr_value" id="prr_input" value="{cost}" step="100"
               class="w-full px-4 py-3 bg-white border-transparent rounded-xl text-sm font-mono focus:bg-white focus:ring-2 focus:ring-mono-black transition outline-none shadow-sm"
               oninput="triggerUpdate()">
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

# ПРЕВЬЮ: Основная логика расчета (HTMX)
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
    # Новые поля
    prr_value: float = Form(0.0), 
    service_rate_value: float = Form(0.0), 
    include_rail_tariff: bool = Form(False), # Чекбокс
    include_prr: bool = Form(False),         # Чекбокс
    expense_names: List[str] = Form([]),
    expense_values: List[float] = Form([]),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    """Живой расчет цены."""
    extra_expenses_total = sum(expense_values)
    
    # 1. ЖД Тариф
    base_rate = 0.0
    tariff_found = False
    gondola_coeff = 1.0
    adjusted_base_rate = 0.0
    
    if include_rail_tariff and station_from and station_to:
        calc_service = PriceCalculator(db)
        tariff = await calc_service.get_tariff(station_from, station_to, container_type, service_type)
        if tariff:
            base_rate = tariff.rate_no_vat
            tariff_found = True
        
        # Коэффициент на вагон
        if wagon_type == WagonType.GONDOLA:
            setting = await db.get(SystemSetting, "gondola_coeff")
            if setting: gondola_coeff = float(setting.value)
        
        adjusted_base_rate = base_rate * gondola_coeff
    
    # 2. ПРР
    final_prr_cost = prr_value if include_prr else 0.0

    # 3. Итоговая себестоимость
    total_cost = adjusted_base_rate + final_prr_cost + service_rate_value + extra_expenses_total
    
    # НДС
    vat_setting = await db.get(SystemSetting, "vat_rate")
    vat_rate = float(vat_setting.value) if vat_setting else 20.0
    
    total_cost_with_vat = total_cost * (1 + vat_rate / 100)
    
    # 4. Цена продажи
    sales_price_netto = total_cost + margin_value if margin_type == MarginType.FIX else total_cost * (1 + margin_value / 100)
    vat_amount = sales_price_netto * (vat_rate / 100)
    total_price_with_vat = sales_price_netto + vat_amount
    
    return templates.TemplateResponse("partials/calc_summary.html", {
        "request": request,
        "base_rate": base_rate,
        "gondola_coeff": gondola_coeff,
        "adjusted_base_rate": adjusted_base_rate,
        "include_rail_tariff": include_rail_tariff,
        "tariff_found": tariff_found or (not include_rail_tariff),
        "prr_cost": final_prr_cost,
        "include_prr": include_prr,
        "service_rate": service_rate_value,
        "extra_expenses": extra_expenses_total,
        "total_cost": total_cost,
        "total_cost_with_vat": total_cost_with_vat,
        "vat_rate": vat_rate,
        "sales_price_netto": sales_price_netto,
        "vat_amount": vat_amount,
        "total_price_with_vat": total_price_with_vat,
    })

# ЛОГИКА СОХРАНЕНИЯ (Внутренняя функция)
async def _save_calculation_logic(
    db: AsyncSession,
    title: str, station_from: str, station_to: str, container_type: str,
    service_type: str, wagon_type: str, margin_type: str, margin_value: float,
    service_provider: str, expense_names: List[str], expense_values: List[float],
    prr_value: float, service_rate_value: float,
    include_rail_tariff: bool, include_prr: bool,
    valid_until: Optional[str] = None, # Дата окончания
    calc_id: Optional[int] = None
):
    # Повторяем расчет для БД
    base_rate = 0.0
    adjusted_base_rate = 0.0
    
    if include_rail_tariff:
        calc_service = PriceCalculator(db)
        tariff = await calc_service.get_tariff(station_from, station_to, container_type, service_type)
        base_rate = tariff.rate_no_vat if tariff else 0.0
        
        gondola_coeff = 1.0
        if wagon_type == WagonType.GONDOLA:
            setting = await db.get(SystemSetting, "gondola_coeff")
            if setting: gondola_coeff = float(setting.value)
        adjusted_base_rate = base_rate * gondola_coeff
    
    final_prr_cost = prr_value if include_prr else 0.0
    extra_expenses_total = sum(expense_values)
    
    total_cost = adjusted_base_rate + final_prr_cost + service_rate_value + extra_expenses_total
    
    sales_price_netto = total_cost + margin_value if margin_type == MarginType.FIX else total_cost * (1 + margin_value / 100)
    vat_setting = await db.get(SystemSetting, "vat_rate")
    vat_rate = float(vat_setting.value) if vat_setting else 20.0

    if calc_id:
        stmt = select(Calculation).options(selectinload(Calculation.items)).where(Calculation.id == calc_id)
        result = await db.execute(stmt)
        calc = result.scalar_one_or_none()
        if not calc: return None
        calc.items = []
    else:
        calc = Calculation(created_at=func.now())
        db.add(calc)

    # Парсинг даты валидности
    valid_to_date = None
    if valid_until:
        try:
            valid_to_date = datetime.strptime(valid_until, "%Y-%m-%d").date()
        except ValueError:
            pass

    # Обновляем поля
    calc.title = title
    calc.service_provider = service_provider
    calc.service_type = service_type
    calc.wagon_type = wagon_type
    calc.container_type = container_type
    calc.station_from = station_from
    calc.station_to = station_to
    calc.valid_from = datetime.now().date()
    calc.valid_to = valid_to_date # Сохраняем дату
    
    calc.total_cost = total_cost
    calc.margin_type = margin_type
    calc.margin_value = margin_value
    calc.total_price_netto = sales_price_netto
    calc.vat_rate = vat_rate
    calc.status = CalculationStatus.PUBLISHED

    await db.flush()

    # Сохраняем детализацию
    if include_rail_tariff:
        db.add(CalculationItem(
            calculation_id=calc.id, 
            name="Железнодорожный тариф", 
            cost_price=adjusted_base_rate, 
            is_auto_calculated=True
        ))

    if include_prr and final_prr_cost > 0:
        prr_label = f"ПРР в ПВ ({container_type})" if wagon_type == WagonType.GONDOLA else f"ПРР на Платформе ({container_type})"
        db.add(CalculationItem(
            calculation_id=calc.id, 
            name=prr_label, 
            cost_price=final_prr_cost, 
            is_auto_calculated=True
        ))
        
    if service_rate_value > 0:
        db.add(CalculationItem(
            calculation_id=calc.id, 
            name="Ставка сервиса", 
            cost_price=service_rate_value, 
            is_auto_calculated=True
        ))
    
    for name, cost in zip(expense_names, expense_values):
        if name and name.strip(): 
            db.add(CalculationItem(
                calculation_id=calc.id, 
                name=name.strip(), 
                cost_price=cost, 
                is_auto_calculated=False
            ))
            
    await db.commit()
    return calc

@router.post("/calculator/create")
async def calculator_create(
    request: Request,
    title: str = Form(...), station_from: str = Form(...), station_to: str = Form(...),
    container_type: str = Form(...), service_type: str = Form(...), wagon_type: str = Form(...),
    margin_type: str = Form(...), margin_value: float = Form(0.0), service_provider: str = Form(...),
    prr_value: float = Form(0.0), service_rate_value: float = Form(0.0),
    include_rail_tariff: bool = Form(False), include_prr: bool = Form(False),
    # Принимаем valid_until
    valid_until: Optional[str] = Form(None),
    expense_names: List[str] = Form([]), expense_values: List[float] = Form([]),
    db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)
):
    await _save_calculation_logic(db, title, station_from, station_to, container_type, service_type, wagon_type, margin_type, margin_value, service_provider, expense_names, expense_values, prr_value, service_rate_value, include_rail_tariff, include_prr, valid_until, None)
    return RedirectResponse("/admin/calculator", status_code=303)

@router.post("/calculator/{calc_id}/update")
async def calculator_update(
    calc_id: int, request: Request,
    title: str = Form(...), station_from: str = Form(...), station_to: str = Form(...),
    container_type: str = Form(...), service_type: str = Form(...), wagon_type: str = Form(...),
    margin_type: str = Form(...), margin_value: float = Form(0.0), service_provider: str = Form(...),
    prr_value: float = Form(0.0), service_rate_value: float = Form(0.0),
    include_rail_tariff: bool = Form(False), include_prr: bool = Form(False),
    # Принимаем valid_until
    valid_until: Optional[str] = Form(None),
    expense_names: List[str] = Form([]), expense_values: List[float] = Form([]),
    db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)
):
    await _save_calculation_logic(db, title, station_from, station_to, container_type, service_type, wagon_type, margin_type, margin_value, service_provider, expense_names, expense_values, prr_value, service_rate_value, include_rail_tariff, include_prr, valid_until, calc_id)
    return RedirectResponse("/admin/calculator", status_code=303)

@router.post("/tariffs/upload")
async def upload_tariffs_excel(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(admin_required)
):
    """
    Принимает Excel файл, обрабатывает и сохраняет тарифы.
    """
    content = await file.read()
    
    # Запуск логики импорта
    result = await process_tariff_import(content, db)
    
    if "error" in result:
        # Редирект с ошибкой
        error_msg = f"Ошибка: {result['error']}"
        return RedirectResponse(
            url=f"/admin/calculator?error_msg={error_msg}", 
            status_code=303
        )
    
    # Успех
    count = result['inserted']
    stations_preview = list(result['stations_found'])[:5]
    stations_str = ", ".join(stations_preview)
    if len(result['stations_found']) > 5:
        stations_str += "..."
        
    success_msg = f"Успешно загружено {count} тарифов. Станции: {stations_str}"
    
    if result.get("errors"):
        success_msg += f" (Предупреждений: {len(result['errors'])})"

    return RedirectResponse(
        url=f"/admin/calculator?success_msg={success_msg}", 
        status_code=303
    )