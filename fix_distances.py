import asyncio
import os
import logging
import sys
from sqlalchemy import select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from dotenv import load_dotenv

# Добавляем корневую директорию в путь, чтобы можно было импортировать модули
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# Импорты твоих модулей
from models import Tracking
from services.tariff_service import get_tariff_distance
from services.railway_graph import railway_graph

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("DistanceFixer")

load_dotenv()
DB_URL = os.getenv("DATABASE_URL") # URL основной базы (где лежат грузы)

if not DB_URL:
    logger.critical("Переменная окружения DATABASE_URL не установлена! Пожалуйста, создайте .env файл или установите ее.")
    exit(1)


async def fix_all_distances():
    logger.info("🚀 Запуск массового пересчета расстояний...")
    
    # 1. Инициализируем граф (чтобы считало быстро и через координаты)
    await railway_graph.build_graph()
    
    engine = create_async_engine(DB_URL)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    async with Session() as session:
        # Берем только активные грузы (где дата прибытия пустая или статус "в пути")
        # Подправь фильтр под свою логику статусов
        stmt = select(Tracking).where(Tracking.km_left > 0) 
        result = await session.execute(stmt)
        trackings = result.scalars().all()
        
        logger.info(f"Найдено {len(trackings)} записей для проверки.")
        
        count_updated = 0
        count_errors = 0
        
        for track in trackings:
            if not track.current_station or not track.to_station:
                continue

            # Считаем
            try:
                res = await get_tariff_distance(track.current_station, track.to_station)
                
                if res and res.get('distance') is not None:
                    new_dist = res['distance']
                    
                    # Если разница большая (> 5 км), обновляем
                    old_dist = track.km_left or 0
                    if abs(old_dist - new_dist) > 5:
                        logger.info(f"♻️ ID {track.id}: {track.current_station}->{track.to_station}. Было {old_dist}, Стало {new_dist}")
                        track.km_left = new_dist
                        count_updated += 1
                else:
                    logger.warning(f"⚠️ Не удалось рассчитать: {track.current_station} -> {track.to_station}")
                    count_errors += 1
                    
            except Exception as e:
                logger.error(f"Ошибка на ID {track.id}: {e}")

        if count_updated > 0:
            logger.info(f"💾 Сохранение {count_updated} изменений в БД...")
            await session.commit()
            
    logger.info(f"✅ Готово! Обновлено: {count_updated}, Ошибок: {count_errors}")
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(fix_all_distances())
