# Telegram Bot Container Tracker
# Telegram Bot Container Tracker

Telegram-бот для отслеживания контейнеров с интеграцией почты, базы данных и планировщика задач.


## Возможности

- 📦 Отслеживание контейнеров через Telegram-бота
- 📨 Импорт данных из почты (IMAP, imap-tools)
- 📊 Экспорт и обработка данных в Excel (openpyxl, pandas)
- 🗄️ Асинхронная работа с базой данных (SQLAlchemy, asyncpg)
- 🔄 Ежедневное автоматическое пополнение базы контейнеров (APScheduler)
- 🛠️ Миграции базы данных через Alembic
- ⏰ Планирование задач (APScheduler)
- 📝 Логирование событий
- 🛡️ Админ-панель для управления отслеживанием

## Стек технологий

- Python 3.9+
- [python-telegram-bot](https://python-telegram-bot.org/) (polling, без webhooks)
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
   ```sh
   git clone https://github.com/yourusername/telegram-bot-container-tracker-2.git
   cd telegram-bot-container-tracker-2
   ```

2. **Создайте и активируйте виртуальное окружение:**
   ```sh
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Установите зависимости:**
   ```sh
   pip install -r requirements.txt
   ```

4. **Создайте файл `.env` и заполните переменные:**
   ```env
   DATABASE_URL=postgresql+asyncpg://user:password@host:port/dbname
   TELEGRAM_TOKEN=ваш_токен_бота
   ADMIN_CHAT_ID=ваш_telegram_id
   RENDER_EXTERNAL_HOSTNAME=...
   PORT=10000
   ```

5. **Примените миграции базы данных:**
   ```sh
   alembic upgrade head
   ```

6. **Запустите бота:**
   ```sh
   python bot.py
   ```

## Установка и запуск через systemd

Пример юнит-файла для запуска бота как сервиса:

```ini
[Unit]
Description=Telegram Container Tracker Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/path/to/telegram-bot-container-tracker
Environment="PYTHONUNBUFFERED=1"
ExecStart=/path/to/venv/bin/python bot.py
Restart=on-failure

[Install]
WantedBy=multi-user.target
```

1. Скопируйте юнит-файл, подставьте свои пути.
2. Поместите его в `/etc/systemd/system/container-tracker-bot.service`.
3. Выполните:
   ```sh
   sudo systemctl daemon-reload
   sudo systemctl enable container-tracker-bot
   sudo systemctl start container-tracker-bot
   ```

## Автоматическое пополнение базы

В проекте реализовано два автоматических сценария пополнения базы:

- **Проверка новых писем:**  
  Каждые 20 минут бот проверяет почтовый ящик (через IMAP) и импортирует новые данные о контейнерах.
- **Обновление базы терминала:**  
  Один раз в сутки, в 08:30 утра, происходит обновление базы контейнеров из данных терминала.

Оба сценария реализованы через APScheduler и запускаются автоматически при старте бота.

## Структура проекта

- `bot.py` — основной файл запуска Telegram-бота и инициализации всех компонентов.
- `config.py` — загрузка и валидация переменных окружения, настройка параметров.
- `db.py` — подключение к базе данных, определение моделей и вспомогательные функции работы с БД.
- `handlers/` — обработчики команд и сообщений Telegram, логика взаимодействия с пользователями.
- `services/` — бизнес-логика, сервисы для работы с контейнерами, почтой, Excel и др.
- `alembic/` — каталог миграций базы данных (скрипты Alembic).
- `mail_reader.py` — получение и обработка писем, парсинг вложений, интеграция с БД.
- `scheduler.py` — настройка и запуск планировщика задач (APScheduler), определение периодических заданий.
- `logs/` — директория для лог-файлов (создается автоматически).
- `requirements.txt` — список зависимостей проекта.

## Логирование

В проекте используется стандартный модуль `logging` для отслеживания событий, ошибок и успешных операций.

## Лицензия

MIT
