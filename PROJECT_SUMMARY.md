# 🤖 Анализ кодовой базы AtermTrackBot

Проект AtermTrackBot представляет собой многофункциональный асинхронный Telegram-бот для логистического мониторинга, объединяющий отслеживание дислокации контейнеров, статусы терминалов и расчет Ж/Д расстояний.

---

## 🚀 1. Основная логика и Точка входа

| Файл | Описание | Основные операции |
| :--- | :--- | :--- |
| `bot.py` | **Точка входа** в приложение. Инициализирует `Application`, устанавливает логирование, регистрирует все диалоги (`ConversationHandler`), команды и колбэки. Выполняет критическую инициализацию БД (`init_db`) и запускает планировщик (`start_scheduler`) в `post_init`. | `main()`: Сборка и запуск бота. `post_init()`: Инициализация БД, установка команд, запуск планировщика. `set_bot_commands()`: Установка команд для пользователей и администратора. |
| `config.py` | Содержит все **настройки** и переменные окружения (токены, URL БД, ID админа, настройки отправки, константы отчетов). | `DATABASE_URL`, `TOKEN`, `ADMIN_CHAT_ID`, `TRACKING_REPORT_COLUMNS`, `RAILWAY_WINDING_FACTOR`. |
| `scheduler.py` | Управляет **фоновыми задачами** бота через `AsyncIOScheduler` (часовой пояс Владивостока). | `start_scheduler()`: Регистрирует задачи (рассылка, проверка почты, импорт терминала). `job_send_notifications()`: Запускает рассылку отчетов по подпискам в Telegram и Email. `job_periodic_dislocation_check()`: Периодическая проверка почты на файлы дислокации (каждые 20 минут). |

---

## 💾 2. База данных и ORM

| Файл | Описание | Основные ORM-модели |
| :--- | :--- | :--- |
| `db.py` | Настраивает **асинхронный движок SQLAlchemy** (`asyncpg`) и фабрику сессий (`async_sessionmaker`). | `init_db()`: Создает все таблицы, определенные через `Base`. |
| `db_base.py` | Предоставляет базовый класс `Base` для всех ORM-моделей SQLAlchemy. | `class Base(DeclarativeBase):`. |
| `models.py` | Определяет основные **ORM-модели** для таблиц пользователей, подписок и слежения. | `User`, `UserEmail`, `Subscription`, `Tracking`, `StationsCache`, `TrainEventLog`, `VerificationCode`. |
| `model/terminal_container.py` | Определяет ORM-модель `TerminalContainer` для хранения данных о контейнерах на терминале (клиент, поезд, статус, дата приема). | `class TerminalContainer(Base)`: Используется импортерами и запросами по поездам. |

---

## 💌 3. Обработчики (Handlers)

| Файл | Описание | Основные функции и взаимодействие |
| :--- | :--- | :--- |
| `handlers/dislocation_handlers.py` | Обрабатывает текстовые сообщения с **номерами контейнеров/вагонов**. | `handle_message()`: Извлекает номера, логирует запрос, ищет дислокацию (включая поиск по вагонам), рассчитывает расстояние. Формирует подробный отчет (1 контейнер) или Excel (много). `handle_single_container_excel_callback()`: Генерирует и отправляет Excel-отчет по нажатию кнопки. |
| `handlers/tracking_handlers.py` | Управляет **диалогом создания подписки**. | `add_subscription_start`: Начало диалога. `ask_emails`: Запрашивает выбор Email-адресов из списка пользователя. `save_subscription`: Сохраняет `Subscription` и связывает его с выбранными `UserEmail` через `SubscriptionEmail`. |
| `handlers/subscription_management_handler.py` | Управляет **просмотром и удалением** существующих подписок (`/my_subscriptions`). | `my_subscriptions_command()`: Выводит список подписок с кнопками управления. `delete_subscription_callback()`: Удаляет подписку. |
| `handlers/email_management_handler.py` | Управляет **Email-адресами** пользователя (`/my_emails`) и их **подтверждением по коду**. | `add_email_receive`: Получает адрес, отправляет код подтверждения по почте. `receive_verification_code`: Проверяет код и активирует Email в БД. |
| `handlers/train.py` | Управляет **отчетами по поездам** (только для админа). | `train_cmd`: Точка входа. Показывает список поездов (Inline-кнопки) или сразу отчет. `_respond_train_report`: Формирует отчет с клиентами (`TerminalContainer`) и последней дислокацией (`Tracking`). |
| `handlers/distance_handlers.py` | Управляет **диалогом расчета тарифного расстояния** (`/distance`). | `process_to_station()`: Получает станции и вызывает `services.tariff_service.get_tariff_distance`. |

---

## ⚙️ 4. Сервисы (Services) и Ядро Тарифа

| Файл | Описание | Основные функции и взаимодействие |
| :--- | :--- | :--- |
| `services/dislocation_importer.py` | Отвечает за **импорт данных дислокации** из Excel-файлов, полученных по почте. | `check_and_process_dislocation()`: Скачивает файл по IMAP. `process_dislocation_file()`: Читает Excel и выполняет **UPDATE/INSERT** в `Tracking`, запускает логику событий поезда. |
| `services/terminal_importer.py` | Отвечает за **импорт данных о статусах терминала** (A-Terminal) и файлов поезда. | `process_terminal_report_file()`: Обрабатывает отчет A-Terminal (статус, дата приема) и обновляет `TerminalContainer`. `import_train_from_excel()`: Проставляет номер поезда и клиента в `TerminalContainer`. |
| `services/notification_service.py` | Основной сервис для **рассылки уведомлений**. | `send_scheduled_notifications()`: Находит подписки, собирает дислокацию, отправляет сообщение в Telegram, генерирует Excel (`utils/send_tracking`) и отправляет Email (`utils/email_sender`). |
| `services/imap_service.py` | Синхронный сервис для **подключения к IMAP** и скачивания вложений (используется через `asyncio.to_thread`). | `download_latest_attachment()`: Поиск, скачивание и пометка письма как прочитанного по заданным критериям (отправитель, тема, имя файла). |
| `services/tariff_service.py` | **Асинхронный адаптер** для вызова ядра расчета Ж/Д расстояний. | `get_tariff_distance()`: Вызывает синхронный `zdtarif_bot.rail_calculator.get_distance_sync` в отдельном потоке. |
| `zdtarif_bot/rail_calculator.py` | **Синхронное ядро** расчета тарифного расстояния. Загружает справочники (`2-РП.csv`, `3-1 Рос.csv`, `3-2 Рос.csv`) при старте. | `get_distance_sync()`: Синхронно выполняет расчет. |

---

## 🛠️ 5. Утилиты (Utils)

| Файл | Описание | Основные функции |
| :--- | :--- | :--- |
| `utils/send_tracking.py` | Генерация **Excel-файлов**. | `create_excel_file()`: Создает Excel-файл из списка строк с форматированием (используя Pandas/OpenPyXL). `get_vladivostok_filename()`: Генерирует имя файла с датой и временем по Владивостоку. |
| `utils/email_sender.py` | Синхронная отправка Email через SMTP. | `send_email()`: Подключается к SMTP и отправляет письмо с вложениями (используется через `asyncio.to_thread`). `generate_verification_email()`: Формирует письмо с кодом подтверждения. |
| `utils/railway_utils.py` | Работа с **железнодорожными кодами и названиями дорог**. | `get_railway_abbreviation()`: Извлекает код дороги из строки и возвращает её общепринятое сокращение (например, `С-КАВ` из `СЕВЕРО-КАВКАЗСКАЯ (51)`). |