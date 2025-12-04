# services/railway_graph.py
import networkx as nx
import logging
from sqlalchemy import select
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
            stmt = select(RailwaySection.stations_list)
            result = await session.execute(stmt)
            all_sections = result.scalars().all()

        count_edges = 0
        for section in all_sections:
            if not section or len(section) < 2:
                continue

            for i in range(len(section) - 1):
                node_a = section[i]
                node_b = section[i+1]
                
                self.graph.add_edge(
                    node_a['c'], node_b['c'], 
                    weight=1,
                    name_a=node_a['n'],
                    name_b=node_b['n']
                )
                
                self.graph.nodes[node_a['c']]['name'] = node_a['n']
                self.graph.nodes[node_b['c']]['name'] = node_b['n']
                count_edges += 1

        logger.info(f"✅ Граф построен! Узлов: {self.graph.number_of_nodes()}, Связей: {self.graph.number_of_edges()}")

    def get_shortest_path_detailed(self, code_start: str, code_end: str) -> list[dict]:
        """
        Возвращает список словарей [{'code': '...', 'name': '...'}, ...]
        """
        if not self.graph: return []

        start_variants = [code_start, code_start[:-1]] if len(code_start) == 6 else [code_start]
        end_variants = [code_end, code_end[:-1]] if len(code_end) == 6 else [code_end]

        for u in start_variants:
            for v in end_variants:
                if self.graph.has_node(u) and self.graph.has_node(v):
                    try:
                        path_codes = nx.shortest_path(self.graph, source=u, target=v)
                        
                        result = []
                        for code in path_codes:
                            name = self.graph.nodes[code].get('name', code)
                            result.append({'code': code, 'name': name})
                        
                        return result
                    except nx.NetworkXNoPath:
                        continue
        return []

railway_graph = RailwayGraph()