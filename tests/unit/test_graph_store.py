"""测试记忆图存储。"""

from __future__ import annotations

import pytest

from vir_bot.core.memory.graph_store import GraphEdge, MemoryGraphStore


@pytest.fixture
def graph_store() -> MemoryGraphStore:
    """创建一个临时图存储。"""
    store = MemoryGraphStore(persist_path="./data/memory/test_graph_temp.json")
    store.graph.clear()
    yield store
    store.graph.clear()
    store._save()


class TestMemoryGraphStore:
    """测试 MemoryGraphStore。"""

    def test_add_relation(self, graph_store):
        """测试添加关系。"""
        edge = graph_store.add_relation(
            subject="用户",
            predicate="喜欢",
            object="火锅",
            confidence=0.9,
            source="test",
        )

        assert edge.subject == "用户"
        assert edge.predicate == "喜欢"
        assert edge.object == "火锅"
        assert edge.confidence == 0.9

        # 检查图中有边
        assert graph_store.graph.has_edge("用户", "火锅")
        edge_data = graph_store.graph["用户"]["火锅"]
        assert edge_data["predicate"] == "喜欢"

    def test_query_by_subject(self, graph_store):
        """测试按主体查询。"""
        graph_store.add_relation("用户", "喜欢", "火锅")
        graph_store.add_relation("用户", "喜欢", "日料")

        results = graph_store.query(subject="用户")
        assert len(results) == 2

    def test_query_by_predicate(self, graph_store):
        """测试按谓词查询。"""
        graph_store.add_relation("用户", "喜欢", "火锅")
        graph_store.add_relation("用户", "讨厌", "茄子")

        results = graph_store.query(predicate="喜欢")
        assert len(results) == 1
        assert results[0].object == "火锅"

    def test_query_multi_hop(self, graph_store):
        """测试多跳查询。"""
        graph_store.add_relation("用户", "喜欢", "火锅")
        graph_store.add_relation("火锅", "属于", "川菜")

        paths = graph_store.query_multi_hop(start="用户", max_hops=2)
        assert len(paths) > 0
        # 应该有一条路径：用户 -> 火锅 -> 川菜
        found = False
        for path in paths:
            if len(path) >= 3 and path[0] == "用户" and path[-1] == "川菜":
                found = True
                break
        assert found

    def test_remove_relation(self, graph_store):
        """测试删除关系。"""
        graph_store.add_relation("用户", "喜欢", "火锅")

        result = graph_store.remove_relation("用户", "喜欢", "火锅")
        assert result is True
        assert not graph_store.graph.has_edge("用户", "火锅")

    def test_remove_relation_not_exist(self, graph_store):
        """测试删除不存在的关系。"""
        result = graph_store.remove_relation("用户", "喜欢", "火锅")
        assert result is False

    def test_get_all_relations(self, graph_store):
        """测试获取所有关系。"""
        graph_store.add_relation("用户", "喜欢", "火锅")
        graph_store.add_relation("用户", "讨厌", "茄子")

        results = graph_store.get_all_relations()
        assert len(results) == 2

    def test_clear(self, graph_store):
        """测试清空图。"""
        graph_store.add_relation("用户", "喜欢", "火锅")
        graph_store.clear()
        assert len(graph_store.graph.nodes()) == 0
        assert len(graph_store.graph.edges()) == 0
