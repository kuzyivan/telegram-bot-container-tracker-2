import secrets
from datetime import datetime
from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import JSONResponse
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models import User, ScheduledTrain, ScheduleShareLink
from web.auth import admin_required
from .common import templates, get_db

router = APIRouter()

@router.get("/schedule_planner")
async def schedule_planner_page(request: Request, user: User = Depends(admin_required)):
    return templates.TemplateResponse("schedule_planner.html", {"request": request, "user": user})

@router.get("/api/schedule/events")
async def get_schedule_events(
    start: str, end: str, db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)
):
    try:
        start_date = datetime.strptime(start.split('T')[0], "%Y-%m-%d").date()
        end_date = datetime.strptime(end.split('T')[0], "%Y-%m-%d").date()
        stmt = select(ScheduledTrain).where(and_(ScheduledTrain.schedule_date >= start_date, ScheduledTrain.schedule_date <= end_date))
        result = await db.execute(stmt)
        trains = result.scalars().all()
        
        events = []
        for t in trains:
            title = f"{t.service_name} -> {t.destination}"
            bg_color = getattr(t, 'color', '#111111') or '#111111'
            overload = getattr(t, 'overload_station', "")
            owner = getattr(t, 'wagon_owner', "")
            events.append({
                "id": str(t.id), "title": title, "start": t.schedule_date.isoformat(),
                "allDay": True, "backgroundColor": bg_color, "borderColor": bg_color,
                "extendedProps": {"service": t.service_name, "dest": t.destination, "stock": t.stock_info or "", "owner": owner or "", "overload": overload or "", "comment": t.comment or ""},
                "editable": True, "startEditable": True, "durationEditable": False
            })
        return JSONResponse(events)
    except Exception as e:
        return JSONResponse([], status_code=200)

@router.post("/api/schedule/create")
async def create_schedule_event(
    date_str: str = Form(...), service: str = Form(...), destination: str = Form(...), 
    stock: str = Form(None), owner: str = Form(None), overload_station: str = Form(None), color: str = Form("#111111"),
    db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)
):
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        new_train = ScheduledTrain(schedule_date=dt, service_name=service, destination=destination, stock_info=stock, wagon_owner=owner, overload_station=overload_station, color=color)
        db.add(new_train)
        await db.commit()
        return {"status": "ok", "id": new_train.id}
    except Exception as e:
        return JSONResponse({"status": "error", "detail": str(e)}, status_code=500)

@router.post("/api/schedule/{event_id}/move")
async def move_schedule_event(event_id: int, new_date: str = Form(...), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    dt = datetime.strptime(new_date, "%Y-%m-%d").date()
    stmt = update(ScheduledTrain).where(ScheduledTrain.id == event_id).values(schedule_date=dt)
    await db.execute(stmt)
    await db.commit()
    return {"status": "ok"}

@router.delete("/api/schedule/{event_id}")
async def delete_schedule_event(event_id: int, db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    stmt = select(ScheduledTrain).where(ScheduledTrain.id == event_id)
    res = await db.execute(stmt)
    obj = res.scalar_one_or_none()
    if obj: await db.delete(obj); await db.commit()
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