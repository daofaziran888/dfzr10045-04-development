"""交付分段领域服务：记录取数回执下每一次分段交付的列与行区间。

分段只登记已发生的交付事实：归属回执、页码、承诺版本、可读列和行区间，
事后复核据此比对每一段实际交付列是否越出回执归属。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store


class DeliverySegmentService(BaseModuleService):
    MODULE = "delivery_segment"
    ENTITY = "交付分段"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["分段编号", "所属回执", "快照编号", "页码", "承诺版本", "可读列", "起始行", "结束行"]
    REQUIRED_FIELDS = ["分段编号", "所属回执", "快照编号"]
    STATUS_ORDER = ["待交付", "已交付", "已作废"]
    ACTION_RULES = {"确认交付": "已交付", "作废分段": "已作废"}
    NEGATIVE_ACTIONS = ["作废分段"]

    def get_segments_for_receipt(self, receipt_id: str) -> list[dict[str, Any]]:
        """读取回执名下的全部交付分段，按页码排序。"""
        segments = [
            row for row in store.rows(self.MODULE)
            if str(row.get("所属回执", "")) == str(receipt_id)
        ]
        segments.sort(key=lambda row: int(row.get("页码", 0) or 0))
        return segments

    def read_segment_rows(self, segment_id: str) -> list[dict[str, Any]]:
        """读取分段实际交付行，按行序稳定排序。"""
        raw = [
            row for row in store.rows("_delivery_row")
            if str(row.get("分段编号", "")) == str(segment_id)
        ]
        raw.sort(key=lambda row: int(row.get("行序", 0) or 0))
        return [
            {k: v for k, v in row.items() if k not in {"分段编号", "行序"}}
            for row in raw
        ]

    def actual_columns(self, segment_id: str) -> list[str]:
        """汇总分段实际交付行里出现的列。"""
        columns: list[str] = []
        for row in self.read_segment_rows(segment_id):
            for key in row:
                if key not in columns:
                    columns.append(key)
        return columns

    def verify_segment_scope(self, segment_id: str) -> dict[str, Any]:
        """核验分段交付列未越出所属回执的可读列范围。"""
        segment = next(
            (row for row in store.rows(self.MODULE)
             if str(row.get("分段编号", "")) == str(segment_id)),
            None,
        )
        if segment is None:
            return {"ok": False, "reason": f"分段 {segment_id} 不存在"}
        expected = [c.strip() for c in str(segment.get("可读列", "")).split(",") if c.strip()]
        actual = self.actual_columns(segment_id)
        outside = [c for c in actual if c not in expected]
        missing = [c for c in expected if c not in actual]
        return {
            "ok": not outside,
            "segment_id": segment_id,
            "expected_columns": expected,
            "actual_columns": actual,
            "outside_columns": outside,
            "missing_columns": missing,
            "row_count": len(self.read_segment_rows(segment_id)),
        }
