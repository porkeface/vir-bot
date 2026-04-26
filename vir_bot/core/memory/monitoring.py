"""记忆系统线上监控模块。"""

import time
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class RetrievalRecord:
    """检索记录。"""

    query: str
    user_id: str
    result_count: int
    latency_ms: float
    timestamp: float = field(default_factory=time.time)


@dataclass
class ConflictRecord:
    """冲突记录。"""

    predicate: str
    conflicting_count: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class CorrectionRecord:
    """用户纠正记录。"""

    user_id: str
    predicate: str
    timestamp: float = field(default_factory=time.time)


class MemoryMonitor:
    """记忆系统线上监控，采集检索命中率、冲突率、修正率。"""

    def __init__(self, max_records: int = 1000):
        self.max_records = max_records

        self._retrieval_records: list[RetrievalRecord] = []
        self._conflict_records: list[ConflictRecord] = []
        self._correction_records: list[CorrectionRecord] = []

        # 聚合统计
        self._retrieval_count = 0
        self._total_latency_ms = 0.0
        self._conflict_count = 0
        self._correction_count = 0

    def record_retrieval(
        self,
        query: str,
        result_count: int,
        latency_ms: float,
        user_id: str = "",
    ) -> None:
        """记录检索事件。"""
        record = RetrievalRecord(
            query=query[:100],
            user_id=user_id,
            result_count=result_count,
            latency_ms=latency_ms,
        )
        self._retrieval_records.append(record)
        self._retrieval_count += 1
        self._total_latency_ms += latency_ms

        if len(self._retrieval_records) > self.max_records:
            self._retrieval_records.pop(0)

    def record_conflict(self, predicate: str, conflicting_count: int) -> None:
        """记录冲突事件。"""
        record = ConflictRecord(
            predicate=predicate,
            conflicting_count=conflicting_count,
        )
        self._conflict_records.append(record)
        self._conflict_count += 1

        if len(self._conflict_records) > self.max_records:
            self._conflict_records.pop(0)

    def record_correction(self, user_id: str, predicate: str) -> None:
        """记录用户纠正事件。"""
        record = CorrectionRecord(
            user_id=user_id,
            predicate=predicate,
        )
        self._correction_records.append(record)
        self._correction_count += 1

        if len(self._correction_records) > self.max_records:
            self._correction_records.pop(0)

    def get_summary(self) -> dict:
        """返回汇总指标。"""
        avg_latency = (
            self._total_latency_ms / self._retrieval_count
            if self._retrieval_count > 0
            else 0.0
        )

        # 计算检索命中率
        hit_count = sum(
            1 for r in self._retrieval_records if r.result_count > 0
        )
        hit_rate = (
            hit_count / len(self._retrieval_records)
            if self._retrieval_records
            else 0.0
        )

        return {
            "retrieval": {
                "total_count": self._retrieval_count,
                "avg_latency_ms": round(avg_latency, 2),
                "hit_rate": round(hit_rate, 4),
                "recent_count": len(self._retrieval_records),
            },
            "conflict": {
                "total_count": self._conflict_count,
                "recent_count": len(self._conflict_records),
            },
            "correction": {
                "total_count": self._correction_count,
                "recent_count": len(self._correction_records),
            },
        }

    def export_prometheus(self) -> str:
        """导出为 Prometheus 格式。"""
        summary = self.get_summary()

        lines = [
            "# HELP memory_retrieval_total Total retrieval operations",
            "# TYPE memory_retrieval_total counter",
            f"memory_retrieval_total {summary['retrieval']['total_count']}",
            "",
            "# HELP memory_retrieval_latency_ms Average retrieval latency",
            "# TYPE memory_retrieval_latency_ms gauge",
            f"memory_retrieval_latency_ms {summary['retrieval']['avg_latency_ms']}",
            "",
            "# HELP memory_retrieval_hit_rate Retrieval hit rate",
            "# TYPE memory_retrieval_hit_rate gauge",
            f"memory_retrieval_hit_rate {summary['retrieval']['hit_rate']}",
            "",
            "# HELP memory_conflict_total Total conflict operations",
            "# TYPE memory_conflict_total counter",
            f"memory_conflict_total {summary['conflict']['total_count']}",
            "",
            "# HELP memory_correction_total Total correction operations",
            "# TYPE memory_correction_total counter",
            f"memory_correction_total {summary['correction']['total_count']}",
        ]

        return "\n".join(lines)

    def clear(self) -> None:
        """清空所有记录。"""
        self._retrieval_records.clear()
        self._conflict_records.clear()
        self._correction_records.clear()
        self._retrieval_count = 0
        self._total_latency_ms = 0.0
        self._conflict_count = 0
        self._correction_count = 0
