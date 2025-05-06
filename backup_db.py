import os
import subprocess
import shutil
import time
from apscheduler.schedulers.background import BackgroundScheduler

# Параметры из окружения
backup_repo = os.getenv("GITHUB_BACKUP_REPO")  # ссылка на backup-репозиторий
github_token = os.getenv("GITHUB_TOKEN")       # токен GitHub
db_file = "tracking.db"                        # имя файла базы
clone_folder = "backup_repo_clone"              # временная папка для клонирования

def backup_database():
    if not backup_repo or not github_token:
        print("❌ Ошибка: Отсутствуют переменные окружения для резервного копирования.")
        return

    try:
        # Удаляем старую папку клона если она есть
        if os.path.exists(clone_folder):
            shutil.rmtree(clone_folder)

        # Клонируем репозиторий бэкапов
        clone_url = backup_repo.replace('https://', f'https://{github_token}@')
        subprocess.run(["git", "clone", clone_url, clone_folder], check=True)

        # Копируем свежую базу в папку клона
        shutil.copy(db_file, os.path.join(clone_folder, db_file))

        # Коммит и пуш изменений
        os.chdir(clone_folder)
        subprocess.run(["git", "add", db_file], check=True)
        subprocess.run(["git", "commit", "-m", f"Backup {time.strftime('%Y-%m-%d %H:%M:%S')}"], check=True)
        subprocess.run(["git", "push"], check=True)
        os.chdir("..")

        # Чистим временную папку
        shutil.rmtree(clone_folder)

        print("✅ Бэкап базы данных успешно отправлен в GitHub.")

    except Exception as e:
        print(f"❗ Ошибка при бэкапе базы данных: {e}")

from apscheduler.triggers.cron import CronTrigger

def schedule_backup(scheduler):
    scheduler.add_job(backup_database, CronTrigger(hour=1))  # каждый день в 01:00
    print("🕒 Задача резервного копирования зарегистрирована.")
