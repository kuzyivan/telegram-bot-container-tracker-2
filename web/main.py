import sys
import os
import uvicorn
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# --- Хак для импорта из родительской папки ---
# Это нужно, чтобы Python видел папку 'web' и корень проекта как модули
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

# Импортируем наши роутеры
from web.routers import public

app = FastAPI(title="Logistrail Tracker")

# 1. Подключаем статические файлы (CSS, картинки, JS)
# Они будут доступны по адресу /static/filename
# Убедись, что папка web/static существует!
app.mount("/static", StaticFiles(directory="web/static"), name="static")

# 2. Подключаем роутеры (разделы сайта)
app.include_router(public.router)

# Запуск сервера
if __name__ == "__main__":
    # reload=True позволяет менять код без перезагрузки сервера
    # ИСПРАВЛЕНО: Порт 8002, чтобы не конфликтовать с ботом на 8000
    uvicorn.run("web.main:app", host="0.0.0.0", port=8002, reload=True)