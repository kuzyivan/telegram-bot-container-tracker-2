import os
import hashlib
import hmac
import time
from datetime import datetime, timedelta
from typing import Optional
import logging

from jose import JWTError, jwt
from passlib.context import CryptContext
from fastapi import Request, HTTPException, status, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
# ✅ Импортируем selectinload для "жадной" загрузки связей
from sqlalchemy.orm import selectinload 

from db import SessionLocal
from models import User, UserRole
from config import TOKEN as BOT_TOKEN 

# Настраиваем логгер для auth
logger = logging.getLogger("auth")
logger.setLevel(logging.INFO)
handler = logging.StreamHandler()
handler.setFormatter(logging.Formatter('%(asctime)s - [AUTH] - %(message)s'))
logger.addHandler(handler)

# --- 1. Настройки безопасности ---
SECRET_KEY = os.getenv("SECRET_KEY", "my_super_static_secret_key_12345") 
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", 120))
COOKIE_NAME = "logistrail_session"

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- 2. Работа с паролями ---

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

# --- 3. Работа с JWT Токенами ---

def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

# --- 4. Проверка Telegram Login Widget ---

def check_telegram_authorization(auth_data: dict) -> bool:
    check_hash = auth_data.get('hash')
    if not check_hash:
        return False
    data_check_arr = []
    for key, value in sorted(auth_data.items()):
        if key != 'hash':
            data_check_arr.append(f'{key}={value}')
    data_check_string = '\n'.join(data_check_arr)
    secret_key = hashlib.sha256(BOT_TOKEN.encode()).digest()
    hash_calc = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
    if hash_calc != check_hash:
        return False
    auth_date = int(auth_data.get('auth_date', 0))
    if (time.time() - auth_date) > 86400:
        return False
    return True

# --- 5. Зависимости (Dependencies) ---

async def get_current_user(request: Request) -> Optional[User]:
    """
    Извлекает пользователя из Cookies.
    Подгружает company через selectinload, чтобы избежать DetachedInstanceError.
    """
    token = request.cookies.get(COOKIE_NAME)

    if not token:
        return None

    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id_str: str = payload.get("sub")
        if user_id_str is None:
            logger.warning("Token decode success but no 'sub' field")
            return None
        user_id = int(user_id_str)
    except JWTError as e:
        logger.warning(f"JWT Error: {e}")
        return None

    async with SessionLocal() as session:
        # ✅ ИСПРАВЛЕНИЕ: Добавлен options(selectinload(User.company))
        result = await session.execute(
            select(User)
            .where(User.id == user_id)
            .options(selectinload(User.company))
        )
        user = result.scalar_one_or_none()
        
        if not user:
            logger.warning(f"User ID {user_id} from token not found in DB")
            
        return user

# Защита: Только для авторизованных
async def login_required(user: Optional[User] = Depends(get_current_user)):
    if not user:
        raise HTTPException(
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"Location": "/login"} 
        )
    return user

# Защита: Только Админ (Строгая)
async def admin_required(user: User = Depends(login_required)):
    if user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Требуются права администратора"
        )
    return user

# 🔥 ИСПРАВЛЕНИЕ: Добавлена проверка ID компании
async def manager_required(user: User = Depends(login_required)):
    """
    Разрешает доступ только:
    1. Администраторам (Role: ADMIN)
    2. Менеджерам/Владельцам, привязанным к компании ООО "Терминал" (ID 3)
    """
    
    # ID компании "ООО Терминал"
    TERMINAL_COMPANY_ID = 3
    
    # 1. Если это глобальный администратор — пускаем всегда
    if user.role == UserRole.ADMIN:
        return user

    # 2. Проверяем роли сотрудников (Менеджер или Владелец)
    allowed_roles = [UserRole.MANAGER, UserRole.OWNER]
    if user.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Недостаточно прав. Требуется роль Менеджера."
        )

    # 3. ⛔️ ЖЕСТКАЯ ПРОВЕРКА КОМПАНИИ
    # Если пользователь не привязан к компании #3, доступ запрещен
    # Это предотвращает доступ менеджеров других клиентов к админ-панели
    if user.company_id != TERMINAL_COMPANY_ID:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Доступ к финансовой информации разрешен только сотрудникам ООО 'Терминал'."
        )
    
    return user