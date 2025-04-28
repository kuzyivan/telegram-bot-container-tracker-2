from apscheduler.schedulers.background import BackgroundScheduler

def start_mail_checking():
    init_db()
    scheduler = BackgroundScheduler()
    scheduler.add_job(check_mail, 'interval', minutes=40)
    scheduler.start()
    print('🔄 Фоновая проверка почты запущена.')
