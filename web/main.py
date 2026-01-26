# web/main.py
import sys
import os
import uvicorn
import asyncio 
from fastapi import FastAPI, Depends 
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from contextlib import asynccontextmanager
try:
    from fastapi_cache import FastAPICache
    from fastapi_cache.backends.inmemory import InMemoryBackend
    HAS_CACHE = True
except ImportError:
    HAS_CACHE = False

from services.railway_graph import railway_graph
import config

from web.routers import public, admin, auth, client, profile
from db import init_db
from web.auth import login_required
from web.constants import DEFAULT_VAT_RATE # Импорт для логирования при старте

@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- ЗАПУСК ---
    try:
        print(f"🚀 Запуск системы. Базовая ставка НДС: {DEFAULT_VAT_RATE}%")
        await init_db()
        
        # Инициализация кэша
        if HAS_CACHE:
            if config.REDIS_URL:
                try:
                    from redis import asyncio as aioredis
                    from fastapi_cache.backends.redis import RedisBackend
                    redis = aioredis.from_url(config.REDIS_URL, encoding="utf8", decode_responses=True)
                    FastAPICache.init(RedisBackend(redis), prefix="fastapi-cache")
                    print("🚀 Кэш инициализирован (Redis)")
                except Exception as e:
                    print(f"⚠️ Ошибка инициализации Redis кэша: {e}. Используем In-Memory.")
                    FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")
            else:
                FastAPICache.init(InMemoryBackend(), prefix="fastapi-cache")
                print("🚀 Кэш инициализирован (In-Memory)")
        else:
            print("⚠️ Кэширование отключено: библиотека fastapi-cache2 не установлена")

        # 🔥 Строим граф дорог
        try:
            await railway_graph.build_graph()
        except asyncio.CancelledError:
            print("⚠️ Построение графа прервано (сервер перезагружается)...")
            raise 
        except Exception as e:
            print(f"❌ Ошибка построения графа: {e}")
            
        yield
    except asyncio.CancelledError:
        pass 
    # --- ЗАВЕРШЕНИЕ ---

app = FastAPI(title="Logistrail Tracker", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="web/static"), name="static")

# 1. Публичные роуты (Логин, Главная)
app.include_router(auth.router)
app.include_router(public.router)

# Роутер профиля пользователя
app.include_router(
    profile.router,
    dependencies=[Depends(login_required)]
)

# 2. Админские роуты (ЗАЩИЩЕНЫ)
app.include_router(
    admin.router, 
    dependencies=[Depends(login_required)] 
)

app.include_router(
    client.router, 
    dependencies=[Depends(login_required)]
)

# Редирект с корня на логин или дашборд
@app.get("/")
async def root_redirect():
    return RedirectResponse("/login")

if __name__ == "__main__":
    uvicorn.run(
        "web.main:app", 
        host="0.0.0.0", 
        port=8002, 
        reload=True,
        reload_excludes=[
            ".venv", 
            ".venv/*",
            "*/.venv/*",
            "venv", 
            "venv/*",
            ".git", 
            "__pycache__", 
            "logs", 
            "downloads",
            "download_container",
            "download_train",
            "*.log",
            "*.xml",
            "*.pyc",
            "*.pyo"
        ]
    )