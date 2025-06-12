from db import SessionLocal
from models import Tracking

def main():
    session = SessionLocal()
    try:
        new_entry = Tracking(container_number="TEST1234567")
        session.add(new_entry)
        session.commit()
        print("✅ Контейнер добавлен:", new_entry.container_number)
    except Exception as e:
        print("❌ Ошибка:", e)
    finally:
        session.close()

if __name__ == "__main__":
    main()


