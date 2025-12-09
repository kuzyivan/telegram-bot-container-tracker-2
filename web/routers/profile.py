import os
import shutil
from pathlib import Path
from fastapi import APIRouter, Request, Depends, Form, UploadFile, File, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db import SessionLocal
from models import User
from web.auth import login_required, get_password_hash, verify_password
from web.routers.admin_modules.common import templates, get_db

router = APIRouter(prefix="/profile", tags=["profile"])

# Папка для сохранения аватарок
UPLOAD_DIR = Path("web/static/avatars")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

@router.get("/")
async def profile_page(request: Request, user: User = Depends(login_required)):
    return templates.TemplateResponse("profile.html", {"request": request, "user": user})

@router.post("/update")
async def update_profile_info(
    request: Request,
    first_name: str = Form(...),
    email: str = Form(...),  # <--- Добавили поле Email
    last_name: str = Form(None),
    job_title: str = Form(None),
    phone: str = Form(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(login_required)
):
    """Обновление текстовых данных"""
    # 1. Получаем пользователя внутри ТЕКУЩЕЙ сессии db
    db_user = await db.get(User, user.id)
    
    if not db_user:
        return RedirectResponse("/profile?error=Пользователь не найден", status_code=303)

    # 2. Проверка уникальности Email (если он изменился)
    # email_login используется для входа, поэтому он должен быть уникальным
    new_email = email.strip() if email else None
    
    if new_email and new_email != db_user.email_login:
        # Проверяем, не занят ли этот email другим пользователем
        existing_user = await db.scalar(
            select(User).where(User.email_login == new_email).where(User.id != db_user.id)
        )
        if existing_user:
            return RedirectResponse("/profile?error=Этот Email уже занят другим пользователем", status_code=303)
        
        db_user.email_login = new_email

    # 3. Обновляем остальные поля
    db_user.first_name = first_name
    db_user.last_name = last_name
    db_user.job_title = job_title
    db_user.phone = phone
    
    await db.commit()
    await db.refresh(db_user)
    
    return RedirectResponse("/profile?success=Данные обновлены", status_code=303)

@router.post("/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(login_required)
):
    """Загрузка аватарки"""
    try:
        db_user = await db.get(User, user.id)
        if not db_user:
             return RedirectResponse("/profile?error=Пользователь не найден", status_code=303)

        # Генерируем имя файла
        filename = f"user_{user.id}_{file.filename}"
        file_path = UPLOAD_DIR / filename
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        db_user.avatar_url = f"/static/avatars/{filename}"
        await db.commit()
        
    except Exception as e:
        print(f"Error uploading avatar: {e}")
        return RedirectResponse("/profile?error=Ошибка загрузки файла", status_code=303)
        
    return RedirectResponse("/profile", status_code=303)

@router.post("/password")
async def change_password(
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(login_required)
):
    """Смена пароля"""
    db_user = await db.get(User, user.id)
    if not db_user:
         return RedirectResponse("/profile?error=Ошибка сессии", status_code=303)

    if not verify_password(current_password, db_user.password_hash):
        return RedirectResponse("/profile?error=Неверный текущий пароль", status_code=303)
    
    if new_password != confirm_password:
        return RedirectResponse("/profile?error=Пароли не совпадают", status_code=303)
        
    db_user.password_hash = get_password_hash(new_password)
    await db.commit()
    
    return RedirectResponse("/profile?success=Пароль успешно изменен", status_code=303)