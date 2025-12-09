# web/main.py
import sys
import os
import uvicorn
from fastapi import FastAPI, Depends # Добавили Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from contextlib import asynccontextmanager
from services.railway_graph import railway_graph # <-- Импорт

from web.routers import public, admin, auth, client # <--- Добавили client
from web.routers import public, admin, auth, client, profile # <--- Добавили profile
from db import init_db
from web.auth import login_required


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Запуск
    await init_db()
    
    # 🔥 Строим граф дорог
    try:
        await railway_graph.build_graph()
    except Exception as e:
        print(f"Ошибка построения графа: {e}")
        
    yield
    # Завершение...

app = FastAPI(title="Logistrail Tracker", lifespan=lifespan)

app.mount("/static", StaticFiles(directory="web/static"), name="static")

# 1. Публичные роуты (Логин, Главная - если она публичная)
app.include_router(auth.router)
app.include_router(public.router)

#Роутер профиля пользователя
app.include_router(
    profile.router,
    dependencies=[Depends(login_required)]
)

# 2. Админские роуты (ЗАЩИЩЕНЫ)
# Теперь к любому запросу на /admin/... будет применяться проверка токена
app.include_router(
    admin.router, 
    dependencies=[Depends(login_required)] 
)

app.include_router(
    client.router, 
    dependencies=[Depends(login_required)]
)

# Редирект с корня на логин или дашборд (по желанию)
@app.get("/")
async def root_redirect():
    return RedirectResponse("/login")

if __name__ == "__main__":
    uvicorn.run("web.main:app", host="0.0.0.0", port=8002, reload=True)