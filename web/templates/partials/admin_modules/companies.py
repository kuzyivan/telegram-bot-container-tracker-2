from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from models import User, Company, UserRole
from web.auth import admin_required, get_password_hash
from .common import templates, get_db

router = APIRouter()

@router.get("/companies")
async def admin_companies(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(admin_required)):
    companies = (await db.execute(select(Company).order_by(Company.created_at.desc()).options(selectinload(Company.users)))).scalars().all()
    users = (await db.execute(select(User).order_by(User.id.desc()).options(selectinload(User.company)))).scalars().all()
    return templates.TemplateResponse("admin_companies.html", {"request": request, "user": current_user, "companies": companies, "users": users, "UserRole": UserRole})

@router.post("/companies/create")
async def create_company(request: Request, name: str = Form(...), inn: str = Form(None), import_key: str = Form(None), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    db.add(Company(name=name, inn=inn, import_mapping_key=import_key))
    await db.commit()
    return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/companies/sync")
async def sync_companies_data(request: Request, db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    from queries.company_queries import sync_terminal_to_company_containers
    await sync_terminal_to_company_containers(db)
    return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/users/{user_id}/update")
async def update_user_role(request: Request, user_id: int, role: str = Form(...), company_id: int = Form(None), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    company_val = company_id if company_id and company_id > 0 else None
    await db.execute(update(User).where(User.id == user_id).values(role=role, company_id=company_val))
    await db.commit()
    return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)

@router.post("/users/create")
async def create_web_user(request: Request, login: str = Form(...), password: str = Form(...), name: str = Form(...), company_id: int = Form(0), role: str = Form("viewer"), db: AsyncSession = Depends(get_db), user: User = Depends(admin_required)):
    if (await db.execute(select(User).where(User.email_login == login))).scalar_one_or_none():
        return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)
    company_val = company_id if company_id > 0 else None
    db.add(User(email_login=login, password_hash=get_password_hash(password), first_name=name, company_id=company_val, role=role))
    await db.commit()
    return RedirectResponse(url="/admin/companies", status_code=status.HTTP_303_SEE_OTHER)