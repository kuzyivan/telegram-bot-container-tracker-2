# web/main.py
import sys
import os
import uvicorn
from fastapi import FastAPI, Depends # Добавили Depends
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse

sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from web.routers import public, admin, auth # <-- Добавили auth
from web.auth import login_required # <-- Импортируем функцию защиты
from web.routers import public, admin, auth, client # <--- Добавили client

app = FastAPI(title="Logistrail Tracker")

app.mount("/static", StaticFiles(directory="web/static"), name="static")

# 1. Публичные роуты (Логин, Главная - если она публичная)
app.include_router(auth.router)
app.include_router(public.router)

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