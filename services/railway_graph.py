# services/railway_graph.py
import networkx as nx
import logging
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from services.tariff_service import RailwaySection
from db import TariffSessionLocal

logger = logging.getLogger(__name__)

class RailwayGraph:
    _instance = None
    graph = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(RailwayGraph, cls).__new__(cls)
            cls.graph = nx.Graph()
        return cls._instance

    async def build_graph(self):
        """Загружает все участки из БД и строит граф."""
        logger.info("🚂 Построение графа железных дорог...")
        
        if not TariffSessionLocal:
            logger.error("Нет подключения к БД тарифов")
            return

        async with TariffSessionLocal() as session:
            # Загружаем все сохраненные цепочки станций
            stmt = select(RailwaySection.stations_list)
            result = await session.execute(stmt)
            all_sections = result.scalars().all()

        count_edges = 0
        for section in all_sections:
            # section - это список словарей [{'c': 'code', 'n': 'name'}, ...]
            if not section or len(section) < 2:
                continue

            # Проходим по цепочке и соединяем соседей
            for i in range(len(section) - 1):
                node_a = section[i]
                node_b = section[i+1]
                
                # Добавляем ребро (связь) между станциями
                # Вес (weight) = 1, можно улучшить, если знать км, но пока ищем просто путь
                self.graph.add_edge(
                    node_a['c'], node_b['c'], 
                    weight=1,
                    name_a=node_a['n'],
                    name_b=node_b['n']
                )
                
                # Сохраняем имена узлов, чтобы потом вернуть их пользователю
                self.graph.nodes[node_a['c']]['name'] = node_a['n']
                self.graph.nodes[node_b['c']]['name'] = node_b['n']
                
                count_edges += 1

        logger.info(f"✅ Граф построен! Узлов: {self.graph.number_of_nodes()}, Связей: {self.graph.number_of_edges()}")

    def get_shortest_path(self, code_start: str, code_end: str) -> list[str]:
        """Ищет путь между двумя кодами станций."""
        if not self.graph:
            return []

        # Попытка найти путь (с учетом 6-значных и 5-значных кодов)
        start_variants = [code_start, code_start[:-1]] if len(code_start) == 6 else [code_start]
        end_variants = [code_end, code_end[:-1]] if len(code_end) == 6 else [code_end]

        best_path = []

        for u in start_variants:
            for v in end_variants:
                if self.graph.has_node(u) and self.graph.has_node(v):
                    try:
                        # Алгоритм кратчайшего пути
                        path_codes = nx.shortest_path(self.graph, source=u, target=v)
                        
                        # Превращаем коды обратно в имена
                        path_names = []
                        for code in path_codes:
                            name = self.graph.nodes[code].get('name', code)
                            path_names.append(name)
                        
                        return path_names
                    except nx.NetworkXNoPath:
                        continue
        
        return []

# Глобальный экземпляр
railway_graph = RailwayGraph()
