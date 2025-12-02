# web/routers/auth.py
import sys
import os
from datetime import timedelta
from fastapi import APIRouter, Request, Depends, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.future import select
from sqlalchemy.ext.asyncio import AsyncSession

sys.path.append(os.path.join(os.path.dirname(__file__), '..', '..'))

from db import SessionLocal
from models import User
# Импортируем COOKIE_NAME
from web.auth import verify_password, create_access_token, ACCESS_TOKEN_EXPIRE_MINUTES, COOKIE_NAME

router = APIRouter(tags=["auth"])
templates = Jinja2Templates(directory="web/templates")

async def get_db():
    async with SessionLocal() as session:
        yield session

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@router.post("/login", response_class=HTMLResponse)
async def login_handle(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    db: AsyncSession = Depends(get_db)
):
    stmt = select(User).where(User.email_login == username)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    error_msg = "Неверный логин или пароль"

    if not user or not user.password_hash:
        return templates.TemplateResponse("login.html", {"request": request, "error": error_msg}, status_code=401)
    
    if not verify_password(password, user.password_hash):
        return templates.TemplateResponse("login.html", {"request": request, "error": error_msg}, status_code=401)

    access_token_expires = timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    access_token = create_access_token(
        data={"sub": str(user.id), "role": user.role.value},
        expires_delta=access_token_expires
    )

    redirect_url = "/admin/dashboard" if user.role == "admin" else "/client/dashboard"

    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    
    # --- ВАЖНЫЕ НАСТРОЙКИ КУКИ ---
    response.set_cookie(
        key=COOKIE_NAME,        # Используем новое имя
        value=access_token,
        httponly=True,          # Защита от JS
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        expires=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        samesite="lax",         # Разрешает передачу при навигации
        secure=False,           # False для HTTP (если у тебя IP адрес без SSL)
        path="/"                # <--- САМОЕ ВАЖНОЕ: Кука действует на ВЕСЬ сайт
    )
    return response

@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(COOKIE_NAME, path="/") # Удаляем с правильным путем
    return response