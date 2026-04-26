"""基于 NetworkX 的记忆图存储。"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

from vir_bot.utils.logger import logger


@dataclass
class GraphEdge:
    """图数据库边（关系）。"""
    subject: str
    predicate: str
    object: str
    confidence: float = 1.0
    created_at: float = field(default_factory=time.time)
    source: str = ""  # 来源（哪次对话）


class MemoryGraphStore:
    """基于 NetworkX 的记忆图存储。"""

    def __init__(self, persist_path: str = "./data/memory/memory_graph.json"):
        import networkx as nx

        self.graph = nx.DiGraph()
        self.persist_path = Path(persist_path)
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        self._load()
        logger.info(f"MemoryGraphStore initialized: path={self.persist_path}")

    def add_relation(
        self,
        subject: str,
        predicate: str,
        object: str,
        confidence: float = 1.0,
        source: str = "",
    ) -> GraphEdge:
        """添加三元组关系。"""
        edge = GraphEdge(
            subject=subject,
            predicate=predicate,
            object=object,
            confidence=confidence,
            source=source,
        )
        self.graph.add_edge(
            subject,
            object,
            predicate=predicate,
            confidence=confidence,
            created_at=edge.created_at,
            source=source,
        )
        self._save()
        logger.info(f"Added relation: {subject} -[{predicate}]-> {object}")
        return edge

    def query(
        self,
        subject: str | None = None,
        predicate: str | None = None,
    ) -> list[GraphEdge]:
        """查询关系。"""
        results: list[GraphEdge] = []
        for s, o, data in self.graph.edges(data=True):
            if subject and s != subject:
                continue
            if predicate and data.get("predicate") != predicate:
                continue
            results.append(
                GraphEdge(
                    subject=s,
                    predicate=data.get("predicate", ""),
                    object=o,
                    confidence=data.get("confidence", 1.0),
                    created_at=data.get("created_at", time.time()),
                    source=data.get("source", ""),
                )
            )
        return results

    def query_multi_hop(
        self,
        start: str,
        max_hops: int = 2,
    ) -> list[list[str]]:
        """多跳查询：返回从 start 出发的所有路径。"""
        import networkx as nx

        paths: list[list[str]] = []
        for target in self.graph.nodes():
            if target == start:
                continue
            try:
                for path in nx.all_simple_paths(self.graph, start, target, cutoff=max_hops):
                    paths.append(path)
            except nx.NetworkXNoPath:
                continue
        return paths

    def remove_relation(
        self,
        subject: str,
        predicate: str,
        object: str,
    ) -> bool:
        """删除关系。"""
        if self.graph.has_edge(subject, object):
            edge_data = self.graph[subject][object]
            if edge_data.get("predicate") == predicate:
                self.graph.remove_edge(subject, object)
                self._save()
                logger.info(f"Removed relation: {subject} -[{predicate}]-> {object}")
                return True
        return False

    def get_all_relations(self) -> list[GraphEdge]:
        """获取所有关系。"""
        return self.query()

    def clear(self) -> None:
        """清空图。"""
        self.graph.clear()
        self._save()
        logger.info("Graph cleared")

    def _save(self) -> None:
        """持久化到 JSON。"""
        import networkx as nx

        data = {
            "nodes": [{"id": n, **self.graph.nodes[n]} for n in self.graph.nodes()],
            "edges": [
                {
                    "subject": s,
                    "object": o,
                    **self.graph[s][o],
                }
                for s, o in self.graph.edges()
            ],
        }
        self.persist_path.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def _load(self) -> None:
        """从 JSON 加载。"""
        import networkx as nx

        if not self.persist_path.exists():
            return

        try:
            data = json.loads(self.persist_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError):
            logger.warning(f"Memory graph file is invalid JSON: {self.persist_path}")
            return

        self.graph = nx.DiGraph()

        # 添加节点
        for node_data in data.get("nodes", []):
            node_id = node_data.pop("id")
            self.graph.add_node(node_id, **node_data)

        # 添加边
        for edge_data in data.get("edges", []):
            s = edge_data.pop("subject")
            o = edge_data.pop("object")
            self.graph.add_edge(s, o, **edge_data)
