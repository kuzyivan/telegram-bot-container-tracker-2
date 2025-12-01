# create_admin.py
import asyncio
from sqlalchemy import select, update
from db import SessionLocal
from models import User, UserRole
from web.auth import get_password_hash
from config import ADMIN_CHAT_ID

async def create_web_admin():
    password = input("Введите пароль для Web-админки: ")
    hashed = get_password_hash(password)
    
    async with SessionLocal() as session:
        # Ищем твоего пользователя по Telegram ID
        result = await session.execute(select(User).where(User.telegram_id == ADMIN_CHAT_ID))
        user = result.scalar_one_or_none()
        
        if user:
            print(f"Пользователь {user.username} найден. Обновляем права...")
            user.role = UserRole.ADMIN
            user.password_hash = hashed
            # Зададим email_login, чтобы можно было войти через форму
            user.email_login = "admin" 
            
            session.add(user)
            await session.commit()
            print("✅ Успешно! Теперь вы можете войти в Web с логином 'admin' и вашим паролем.")
        else:
            print("❌ Пользователь с таким ADMIN_CHAT_ID не найден в БД. Сначала запустите бота и нажмите /start.")

if __name__ == "__main__":
    asyncio.run(create_web_admin())