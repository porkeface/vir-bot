"""记忆系统调试工具。"""

import time
from typing import Optional


class MemoryDebugTools:
    """调试工具：时间线回放、版本链查看、手动干预。"""

    def __init__(self, memory_manager):
        self.memory_manager = memory_manager

    def replay_timeline(
        self,
        user_id: str,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
    ) -> list[dict]:
        """
        按时间线回放记忆变迁。

        返回时间线事件列表，每个事件包含：
        - timestamp: 时间戳
        - action: 操作类型
        - memory_type: 记忆类型
        - content: 内容摘要
        """
        events = []

        # 查询语义记忆
        semantic_records = self.memory_manager.semantic_store.list_by_user(
            user_id
        )
        for record in semantic_records:
            if start_time and record.created_at < start_time:
                continue
            if end_time and record.created_at > end_time:
                continue
            events.append(
                {
                    "timestamp": record.created_at,
                    "action": "semantic_add",
                    "memory_id": record.memory_id,
                    "memory_type": "semantic",
                    "namespace": record.namespace,
                    "predicate": record.predicate,
                    "object": record.object,
                }
            )

        # 查询事件记忆
        episodic_records = self.memory_manager.episodic_store.list_by_user(
            user_id
        )
        for record in episodic_records:
            if start_time and record.start_at < start_time:
                continue
            if end_time and record.start_at > end_time:
                continue
            events.append(
                {
                    "timestamp": record.start_at,
                    "action": "episodic_add",
                    "memory_id": record.episode_id,
                    "memory_type": "episodic",
                    "summary": record.summary,
                }
            )

        # 按时间排序
        events.sort(key=lambda x: x["timestamp"])

        return events

    def get_version_chain(self, memory_id: str) -> list[dict]:
        """
        查看记忆版本链。

        返回版本链列表，从最新到最旧，每个元素包含：
        - memory_id: 记忆ID
        - version_number: 版本号
        - object: 对象值
        - confidence: 置信度
        - valid_from: 有效开始时间
        - valid_to: 有效结束时间
        """
        return self.memory_manager.semantic_store.get_version_chain(memory_id)

    def manual_intervention(
        self,
        memory_id: str,
        action: str,
        **kwargs,
    ) -> bool:
        """
        手动干预记忆状态。

        Actions:
        - "deactivate": 停用记忆
        - "update": 更新记忆内容
        - "delete": 删除记忆
        """
        if action == "deactivate":
            record = self.memory_manager.semantic_store.get_record_by_id(memory_id)
            if record:
                record.is_active = False
                record.updated_at = time.time()
                self.memory_manager.semantic_store.save()
                return True

        elif action == "update":
            record = self.memory_manager.semantic_store.get_record_by_id(memory_id)
            if record:
                for key, value in kwargs.items():
                    if hasattr(record, key):
                        setattr(record, key, value)
                record.updated_at = time.time()
                self.memory_manager.semantic_store.save()
                return True

        elif action == "delete":
            if self.memory_manager.semantic_store.delete_record(memory_id):
                return True

        return False

    def export_user_memory(self, user_id: str, output_path: str) -> None:
        """导出用户所有记忆到文件。"""
        import json

        data = {
            "user_id": user_id,
            "export_time": time.time(),
            "semantic": [
                {
                    "memory_id": r.memory_id,
                    "namespace": r.namespace,
                    "predicate": r.predicate,
                    "object": r.object,
                    "confidence": r.confidence,
                    "created_at": r.created_at,
                    "is_active": r.is_active,
                }
                for r in self.memory_manager.semantic_store.list_by_user(
                    user_id
                )
            ],
            "episodic": [
                {
                    "episode_id": r.episode_id,
                    "summary": r.summary,
                    "start_at": r.start_at,
                    "importance": r.importance,
                    "episode_type": r.episode_type,
                }
                for r in self.memory_manager.episodic_store.list_by_user(
                    user_id
                )
            ],
        }

        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
