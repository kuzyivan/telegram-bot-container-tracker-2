import sys
import os
from pathlib import Path
from fastapi.templating import Jinja2Templates
from db import SessionLocal

# Путь к шаблонам (поднимаемся из web/routers/admin_modules/ -> web/templates)
current_file = Path(__file__).resolve()
templates_dir = current_file.parent.parent.parent / "templates"
templates = Jinja2Templates(directory=str(templates_dir))

async def get_db():
    async with SessionLocal() as session:
        yield session