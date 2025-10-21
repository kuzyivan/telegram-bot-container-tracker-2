# services/osm_service.py
import re
import httpx
import asyncio
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from db import SessionLocal
from models import StationsCache as StationCache # Импортируем StationsCache, но используем как StationCache
from logger import get_logger
from config import OVERPASS_API_URL

logger = get_logger(__name__)
logger.info("<<<<< ЗАГРУЖЕНА НОВАЯ ВЕРСИЯ OSM SERVICE v15.0 (финальная, исправленная) >>>>>")

# Структура для хранения координат
class StationCoords:
    def __init__(self, lat: float, lon: float):
        self.lat = lat
        self.lon = lon

# ❗️--- ПРОВЕРЬТЕ ТОЧНОЕ ИМЯ КЛАССА ЗДЕСЬ ---❗️
class OsmService: 
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)

    async def _query_overpass(self, query: str) -> dict | None:
        """Отправляет запрос к Overpass API и возвращает JSON."""
        try:
            response = await self.client.post(OVERPASS_API_URL, data=query)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            logger.error(f"Ошибка сети при запросе к Overpass API: {e}")
        except httpx.HTTPStatusError as e:
            logger.error(f"Ошибка статуса HTTP от Overpass API: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Неожиданная ошибка при запросе к Overpass API: {e}", exc_info=True)
        return None

    def generate_name_variations(self, station_name_with_code: str) -> list[str]:
        """Генерирует варианты названия станции для поиска в OSM."""
        
        # 1. Извлекаем чистое имя и код (если есть)
        name_part = station_name_with_code
        code_part = None
        match_code = re.search(r'\s*\((\d+)\)\s*$', name_part)
        if match_code:
            name_part = name_part[:match_code.start()].strip()
            code_part = match_code.group(1)

        # 2. Базовая очистка от скобок и лишних пробелов
        name = re.sub(r'\s*\([^)]*\)', '', name_part).strip()
        name = re.sub(r'\s+', ' ', name) # Убираем двойные пробелы

        variations = {name} # Начинаем с исходного очищенного имени

        # 3. Расширенный список суффиксов (из конфига или заданный здесь)
        # TODO: Перенести в config.py
        suffixes_to_remove = [
            "ТОВАРНЫЙ", "ПАССАЖИРСКИЙ", "СОРТИРОВОЧНЫЙ", "СЕВЕРНЫЙ", "ЮЖНЫЙ",
            "ЗАПАДНЫЙ", "ВОСТОЧНЫЙ", "ЦЕНТРАЛЬНЫЙ", "ГЛАВНЫЙ", "ЭКСПОРТ", "ПРИСТАНЬ",
            "ПАРК", "ЭКСП", "ГОРКА", "ПРИЧАЛ",
            # Добавим числовые варианты, чтобы убирать их как суффиксы
             "I", "II", "III", "IV", "V", "1", "2", "3", "4", "5"
        ]
        
        base_name = name
        for suffix in suffixes_to_remove:
            # Ищем суффикс как отдельное слово или через дефис, регистронезависимо
            # Добавлено \b чтобы не удалять часть слова (например, "ПОРТ" из "ПОРТОВАЯ")
            pattern = r'[\s-]+' + re.escape(suffix) + r'\b'
            new_base_name = re.sub(pattern, '', base_name, flags=re.IGNORECASE).strip()
            # Убираем возможные оставшиеся дефисы на конце
            new_base_name = new_base_name.rstrip('- ') 
            if new_base_name != base_name:
                variations.add(new_base_name) # Добавляем вариант без суффикса
                base_name = new_base_name # Обновляем базовое имя для следующих итераций

        # 4. Обработка числовых окончаний (после удаления суффиксов)
        # Ищет римские (I-V) или арабские (1-5) цифры в конце, отделенные пробелом или дефисом
        match_num = re.search(r'(.+?)[\s-]+([IVX1-5]+)$', base_name, flags=re.IGNORECASE)
        if match_num:
            name_without_num = match_num.group(1).strip()
            variations.add(name_without_num) # Добавляем вариант без номера

        # 5. Добавляем исходное имя (до очистки суффиксов) если оно отличается
        variations.add(name)

        # Сортируем от самого длинного к короткому для приоритетного поиска
        sorted_variations = sorted(list(filter(None, variations)), key=len, reverse=True)
        
        # logger.debug(f"Для '{station_name_with_code}' сгенерированы варианты: {sorted_variations}")
        return sorted_variations


    async def get_station_coordinates(self, station_name_with_code: str) -> StationCoords | None:
        """
        Ищет координаты станции сначала в кеше, потом в OSM по вариантам названия.
        Кеширует результат при успехе.
        """
        if not station_name_with_code:
            return None

        async with SessionLocal() as session:
            # 1. Поиск в кеше по полному имени с кодом
            result = await session.execute(
                select(StationCache).filter(StationCache.original_name == station_name_with_code)
            )
            cached = result.scalar_one_or_none()
            if cached and cached.latitude and cached.longitude:
                logger.info(f"Станция '{station_name_with_code}' найдена в кеше по полному имени.")
                return StationCoords(lat=cached.latitude, lon=cached.longitude)

            # 2. Генерируем варианты и ищем в кеше по ним
            variations = self.generate_name_variations(station_name_with_code)
            # logger.info(f"Для '{station_name_with_code}' сгенерированы варианты: {variations}") # Для отладки

            for name_variant in variations:
                 # Поиск в кеше по варианту имени
                 result_variant = await session.execute(
                     select(StationCache).filter(StationCache.found_name == name_variant)
                 )
                 cached_variant = result_variant.scalar_one_or_none()
                 if cached_variant and cached_variant.latitude and cached_variant.longitude:
                     logger.info(f"Станция '{station_name_with_code}' найдена в кеше по варианту '{name_variant}'.")
                     # Обновим кеш, связав оригинальное имя с найденными координатами
                     if not cached:
                         cached = StationCache(original_name=station_name_with_code)
                         session.add(cached)
                     cached.found_name = name_variant
                     cached.latitude = cached_variant.latitude
                     cached.longitude = cached_variant.longitude
                     await session.commit()
                     return StationCoords(lat=cached.latitude, lon=cached.longitude)

            # 3. Если в кеше нет - ищем в OSM по вариантам
            for name_variant in variations:
                logger.info(f"Станция '{station_name_with_code}' не найдена в кеше, запрашиваю OSM по варианту '{name_variant}'...")
                # Формируем более точный запрос к Overpass
                query = f"""
                [out:json][timeout:25];
                (
                  node["railway"="station"]["name"~"^{name_variant}$", i];
                  way["railway"="station"]["name"~"^{name_variant}$", i];
                  relation["railway"="station"]["name"~"^{name_variant}$", i];
                );
                out center;
                """
                data = await self._query_overpass(query)

                if data and data.get("elements"):
                    element = data["elements"][0] # Берем первый найденный элемент
                    coords = None
                    if element["type"] == "node":
                        coords = StationCoords(lat=element["lat"], lon=element["lon"])
                    elif "center" in element: # Для way/relation
                        coords = StationCoords(lat=element["center"]["lat"], lon=element["center"]["lon"])

                    if coords:
                        logger.info(f"✅ Найдено в OSM! Станция '{station_name_with_code}' сохранена в кеш как '{name_variant}'.")
                        # Сохраняем в кеш
                        if not cached:
                            cached = StationCache(original_name=station_name_with_code)
                            session.add(cached)
                        cached.found_name = name_variant
                        cached.latitude = coords.lat
                        cached.longitude = coords.lon
                        await session.commit()
                        return coords
                else:
                    logger.warning(f"По варианту '{name_variant}' ничего не найдено в OSM.")
                    await asyncio.sleep(1) # Небольшая пауза между запросами

        logger.error(f"❌ Не удалось найти координаты для станции '{station_name_with_code}' ни в кеше, ни в OSM.")
        return None