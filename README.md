# Telegram Bot Container Tracker

Этот проект — Telegram-бот для отслеживания контейнеров с поддержкой автоматического пополнения базы данных, работы с почтой, планировщика задач и интеграции с PostgreSQL.

## Возможности

- Отслеживание контейнеров через Telegram-бота
- Ежедневное автоматическое пополнение базы контейнеров
- Импорт данных из почты (IMAP)
- Экспорт и обработка данных в Excel (openpyxl, pandas)
- Асинхронная работа с базой данных (SQLAlchemy, asyncpg)
- Планирование задач (APScheduler)
- Логирование событий

## Стек технологий

- Python 3.9+
- [python-telegram-bot](https://python-telegram-bot.org/) (webhooks)
- SQLAlchemy (async)
- Alembic (миграции)
- APScheduler
- imap-tools
- pandas, openpyxl
- requests
- python-dotenv
- asyncpg, psycopg2-binary

## Быстрый старт

1. **Клонируйте репозиторий:**
   ```
   git clone https://github.com/yourusername/telegram-bot-container-tracker-2.git
   cd telegram-bot-container-tracker-2
   ```

2. **Создайте и активируйте виртуальное окружение:**
   ```
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Установите зависимости:**
   ```
   pip install -r requirements.txt
   ```

4. **Создайте файл `.env` и заполните переменные:**
   ```
   DATABASE_URL=postgresql+asyncpg://user:password@host:port/dbname
   TELEGRAM_TOKEN=ваш_токен_бота
   ADMIN_CHAT_ID=ваш_telegram_id
   RENDER_EXTERNAL_HOSTNAME=...
   PORT=10000
   ```

5. **Примените миграции базы данных:**
   ```
   alembic upgrade head
   ```

6. **Запустите бота:**
   ```
   python bot.py
   ```

## Структура проекта

- `bot.py` — основной файл запуска Telegram-бота
- `db.py` — подключение и работа с базой данных
- `config.py` — конфигурация и переменные окружения
- `handlers/` — обработчики команд и сообщений
- `services/` — бизнес-логика и сервисные функции
- `alembic/` — миграции базы данных

## Автоматическое пополнение базы

Для ежедневного пополнения базы используется APScheduler. Логика пополнения реализована в сервисах и запускается автоматически.

## Лицензия

MIT

---

**Контакты:**  
Для связи и вопросов — [@ivan_kuzy].