"""基于 NetworkX 的记忆图存储。

增强：BFS 激活扩散检索（借鉴 NachoBot 海马体设计）。
"""
from __future__ import annotations

import json
import math
import threading
import time
from collections import deque
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
        self._lock = threading.Lock()
        self._dirty = False  # 脏标记，延迟写入
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
        with self._lock:
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
            self._dirty = True
            self._save_if_dirty()
        logger.info(f"Added relation: {subject} -[{predicate}]-> {object}")
        return edge

    def query(
        self,
        subject: str | None = None,
        predicate: str | None = None,
    ) -> list[GraphEdge]:
        """查询关系。"""
        with self._lock:
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

        with self._lock:
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

    def activated_search(
        self,
        keywords: list[str],
        top_k: int = 5,
        max_depth: int = 3,
        initial_activation: float = 1.5,
    ) -> list[tuple[str, float, list[GraphEdge]]]:
        """BFS 激活扩散检索（借鉴 NachoBot 海马体）。

        从关键词节点出发，沿边 BFS 扩散，激活值随距离衰减。
        返回 (节点名, 激活值, 相关边) 按激活值降序排列的 top_k 结果。

        算法：
        1. 对每个关键词，从图中找到匹配节点
        2. BFS 扩散：new_activation = current - (1 / edge_strength)
        3. 节点权重加成：weight_multiplier = 1.0 + min((weight - 1.0) * 0.1, 2.0)
        4. 合并所有关键词的激活映射，取 top_k
        """
        with self._lock:
            activation_map: dict[str, float] = {}
            edge_map: dict[str, list[GraphEdge]] = {}

            for keyword in keywords:
                # 找到匹配的起始节点（模糊匹配）
                start_nodes = self._find_matching_nodes(keyword)
                if not start_nodes:
                    continue

                for start_node in start_nodes:
                    # BFS 扩散
                    queue: deque[tuple[str, float, int]] = deque()
                    queue.append((start_node, initial_activation, 0))
                    visited: set[str] = set()

                    while queue:
                        node, activation, depth = queue.popleft()
                        if node in visited or depth > max_depth or activation < 0.1:
                            continue
                        visited.add(node)

                        # 更新激活映射
                        current_max = activation_map.get(node, 0.0)
                        activation_map[node] = max(current_max, activation)

                        # 收集相关边 + 扩散到邻居（合并为一次遍历）
                        if node not in edge_map:
                            edge_map[node] = []
                        for _, neighbor, data in self.graph.edges(node, data=True):
                            edge = GraphEdge(
                                subject=node,
                                predicate=data.get("predicate", ""),
                                object=neighbor,
                                confidence=data.get("confidence", 1.0),
                                created_at=data.get("created_at", time.time()),
                                source=data.get("source", ""),
                            )
                            if edge not in edge_map[node]:
                                edge_map[node].append(edge)

                            # 扩散到邻居
                            if neighbor not in visited:
                                strength = max(data.get("confidence", 0.5) * 3, 1.0)
                                new_activation = activation - (1.0 / strength)
                                node_weight = self.graph.nodes[neighbor].get("weight", 1.0)
                                weight_multiplier = 1.0 + min((node_weight - 1.0) * 0.1, 2.0)
                                new_activation *= weight_multiplier
                                if new_activation > 0.1:
                                    queue.append((neighbor, new_activation, depth + 1))

            # 按激活值排序取 top_k
            sorted_nodes = sorted(activation_map.items(), key=lambda x: x[1], reverse=True)
            results = []
            for node, activation in sorted_nodes[:top_k]:
                related_edges = edge_map.get(node, [])
                results.append((node, activation, related_edges))

            return results

    def _find_matching_nodes(self, keyword: str) -> list[str]:
        """模糊匹配图节点。"""
        keyword_lower = keyword.lower()
        matches = []
        for node in self.graph.nodes():
            node_lower = node.lower()
            # 精确匹配或包含匹配
            if keyword_lower == node_lower or keyword_lower in node_lower or node_lower in keyword_lower:
                matches.append(node)
        return matches

    def increment_node_weight(self, node: str, amount: float = 1.0) -> None:
        """增加节点权重（记忆整合时调用）。"""
        with self._lock:
            if node in self.graph:
                current = self.graph.nodes[node].get("weight", 1.0)
                self.graph.nodes[node]["weight"] = current + amount
                self._dirty = True
                self._save_if_dirty()

    def get_node_weight(self, node: str) -> float:
        """获取节点权重。"""
        with self._lock:
            if node in self.graph:
                return self.graph.nodes[node].get("weight", 1.0)
            return 1.0

    def remove_relation(
        self,
        subject: str,
        predicate: str,
        object: str,
    ) -> bool:
        """删除关系。"""
        with self._lock:
            if self.graph.has_edge(subject, object):
                edge_data = self.graph[subject][object]
                if edge_data.get("predicate") == predicate:
                    self.graph.remove_edge(subject, object)
                    self._dirty = True
                    self._save_if_dirty()
                    logger.info(f"Removed relation: {subject} -[{predicate}]-> {object}")
                    return True
            return False

    def get_all_relations(self) -> list[GraphEdge]:
        """获取所有关系。"""
        return self.query()

    def clear(self) -> None:
        """清空图。"""
        with self._lock:
            self.graph.clear()
            self._save()
            logger.info("Graph cleared")

    def _save(self) -> None:
        """持久化到 JSON。"""
        try:
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
            self._dirty = False
        except Exception as e:
            logger.error(f"[MemoryGraphStore] 保存失败: {e}")

    def _save_if_dirty(self) -> None:
        """仅在有脏数据时保存。"""
        if self._dirty:
            self._save()

    def flush(self) -> None:
        """强制保存（调用方在适当时机调用）。"""
        with self._lock:
            self._save_if_dirty()

    def _load(self) -> None:
        """从 JSON 加载。"""
        import networkx as nx

        if not self.persist_path.exists():
            return

        try:
            data = json.loads(self.persist_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, FileNotFoundError, ValueError):
            logger.warning(f"Memory graph file is invalid JSON: {self.persist_path}")
            return

        if not isinstance(data, dict):
            logger.warning(f"Memory graph file has unexpected structure (not a dict): {self.persist_path}")
            return

        self.graph = nx.DiGraph()

        # 添加节点
        for node_data in data.get("nodes", []):
            try:
                node_id = node_data.pop("id")
                self.graph.add_node(node_id, **node_data)
            except (TypeError, KeyError) as e:
                logger.warning(f"Skipping malformed graph node: {e}")

        # 添加边
        for edge_data in data.get("edges", []):
            try:
                s = edge_data.pop("subject")
                o = edge_data.pop("object")
                self.graph.add_edge(s, o, **edge_data)
            except (TypeError, KeyError) as e:
                logger.warning(f"Skipping malformed graph edge: {e}")
