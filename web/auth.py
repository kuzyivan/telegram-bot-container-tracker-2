# web/auth.py
import os
import hashlib
import hmac
import time
from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db import SessionLocal
from models import User, UserRole
from config import TOKEN as BOT_TOKEN # Токен бота нужен для проверки подписи Telegram

# Настройки из .env
SECRET_KEY = os.getenv("SECRET_KEY", "unsafe_secret_key")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 120))

# Контекст для хеширования паролей (bcrypt)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- 1. Работа с паролями ---

def verify_password(plain_password, hashed_password):
    """Проверяет, совпадает ли введенный пароль с хешем."""
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    """Создает хеш пароля."""
    return pwd_context.hash(password)

# --- 2. Работа с JWT Токенами ---

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """Генерирует JWT токен с данными пользователя."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# --- 3. Проверка Telegram Login Widget ---

def check_telegram_authorization(auth_data: dict) -> bool:
    """
    Проверяет валидность данных, полученных от Telegram Login Widget.
    Подтверждает, что данные пришли от Телеграм, а не подделаны.
    """
    check_hash = auth_data.get('hash')
    if not check_hash:
        return False
    
    # Сортируем данные и собираем строку для проверки
    data_check_arr = []
    for key, value in sorted(auth_data.items()):
        if key != 'hash':
            data_check_arr.append(f'{key}={value}')
    data_check_string = '\n'.join(data_check_arr)
    
    # Вычисляем HMAC-SHA256
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    hash_calc = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    
    # Сравниваем хеши
    if hash_calc != check_hash:
        return False
        
    # Проверка на устаревание (чтобы нельзя было использовать старый запрос)
    auth_date = int(auth_data.get('auth_date', 0))
    if (time.time() - auth_date) > 86400: # 24 часа
        return False
        
    return True

# --- 4. Зависимости (Dependencies) для защиты роутов ---

async def get_current_user(request: Request) -> Optional[User]:
    """
    Извлекает пользователя из Cookies.
    Используется как Dependency в FastAPI endpoint'ах.
    """
    token = request.cookies.get("access_token")
    if not token:
        return None

    try:
        # Декодируем токен
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str = payload.get("sub") # Это наше внутреннее id из БД
        if user_id_str is None:
            return None
        user_id = int(user_id_str)
    except JWTError:
        return None

    # Ищем пользователя в БД
    async with SessionLocal() as session:
        result = await session.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        return user

# Защита: Только для авторизованных
async def login_required(user: Optional[User] = Depends(get_current_user)):
    if not user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"} # Перенаправляем на логин
        )
    return user

# Защита: Только Админ
async def admin_required(user: User = Depends(login_required)):
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Нужны права администратора"
        )
    return user