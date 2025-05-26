import os
import subprocess
import shutil
import time
from apscheduler.schedulers.background import BackgroundScheduler

# Переменные окружения
GITHUB_REPO = os.getenv("GITHUB_BACKUP_REPO")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
PG_DUMP_PATH = os.getenv("PG_DUMP_PATH", "pg_dump")  # путь к pg_dump если не в PATH

# Название файла дампа и временная папка
BACKUP_FILENAME = "backup.dump"
CLONE_FOLDER = "backup_repo_clone"

def backup_database():
    if not GITHUB_REPO or not GITHUB_TOKEN:
        print("❌ Нет GITHUB_BACKUP_REPO или GITHUB_TOKEN.")
        return

    try:
        if os.path.exists(CLONE_FOLDER):
            shutil.rmtree(CLONE_FOLDER)

        clone_url = GITHUB_REPO.replace("https://", f"https://{GITHUB_TOKEN}@")
        subprocess.run(["git", "clone", clone_url, CLONE_FOLDER], check=True)

        backup_file_path = os.path.join(CLONE_FOLDER, BACKUP_FILENAME)

        pg_env = {
            "PGHOST": os.getenv("POSTGRES_HOST"),
            "PGPORT": os.getenv("POSTGRES_PORT", "5432"),
            "PGUSER": os.getenv("POSTGRES_USER"),
            "PGPASSWORD": os.getenv("POSTGRES_PASSWORD"),
        }
        db_name = os.getenv("POSTGRES_DB")

        dump_cmd = [
            PG_DUMP_PATH,
            "-Fc",  # custom формат
            "-f", backup_file_path,
            db_name
        ]
        subprocess.run(dump_cmd, check=True, env={**os.environ, **pg_env})

        os.chdir(CLONE_FOLDER)
        subprocess.run(["git", "add", BACKUP_FILENAME], check=True)
        subprocess.run(["git", "commit", "-m", f"Backup {time.strftime('%Y-%m-%d %H:%M:%S')}"], check=True)
        subprocess.run(["git", "push"], check=True)
        os.chdir("..")
        shutil.rmtree(CLONE_FOLDER)

        print("✅ Бэкап PostgreSQL базы успешно отправлен в GitHub.")
    except Exception as e:
        print(f"❗ Ошибка при бэкапе: {e}")

def start_backup_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(backup_database, "interval", hours=24)
    scheduler.start()
    print("🔄 Планировщик бэкапа запущен.")
