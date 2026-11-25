"""来源批领域服务：维护契约版本对应的原始数据批次与业务行数据集。

来源批是同一批源数据，可以被多个订阅领取；批次本身不裁剪列，
按订阅投影发生在取数链路上，批次只保证列集合、水位与可用状态。
"""
from __future__ import annotations

from typing import Any

from app.services.base import BaseModuleService
from app.store import store

_ROW_META_KEYS = {"id", "批次编号", "行序", "status", "pending", "abnormal"}


class SourceBatchService(BaseModuleService):
    MODULE = "source_batch"
    ENTITY = "来源批次"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["批次编号", "契约编号", "绑定版本", "来源标识", "数据行数", "列集合", "数据水位", "入库时间"]
    REQUIRED_FIELDS = ["批次编号", "契约编号", "绑定版本"]
    STATUS_ORDER = ["待入库", "可读", "已撤回", "已失效"]
    ACTION_RULES = {"确认可读": "可读", "撤回批次": "已撤回", "标记失效": "已失效"}
    NEGATIVE_ACTIONS = ["撤回批次", "标记失效"]

    def get_batch_for_version(self, contract_id: str, version_no: str) -> dict[str, Any] | None:
        """按契约版本找到当前可读的来源批，多个批次取最后入库的一个。"""
        batches = [
            row for row in store.rows(self.MODULE)
            if row.get("契约编号") == contract_id
            and row.get("绑定版本") == version_no
            and row.get("status") == "可读"
        ]
        if not batches:
            return None
        return max(batches, key=lambda row: int(row.get("id", 0)))

    def read_batch_rows(self, batch_id: str) -> list[dict[str, Any]]:
        """读取批次业务行，剔除元数据并按行序稳定排序。"""
        raw = [
            row for row in store.rows("_source_batch_row")
            if str(row.get("批次编号", "")) == str(batch_id)
        ]
        raw.sort(key=lambda row: int(row.get("行序", 0) or 0))
        return [
            {k: v for k, v in row.items() if k not in _ROW_META_KEYS}
            for row in raw
        ]

    def declare_columns(self, batch_id: str) -> list[str]:
        """返回批次声明的列集合；声明缺失时从实际行推断。"""
        for row in store.rows(self.MODULE):
            if str(row.get("批次编号", "")) == str(batch_id):
                declared = [c.strip() for c in str(row.get("列集合", "")).split(",") if c.strip()]
                if declared:
                    return declared
                break
        columns: list[str] = []
        for row in self.read_batch_rows(batch_id):
            for key in row:
                if key not in columns:
                    columns.append(key)
        return columns

    def verify_batch(self, batch_id: str) -> dict[str, Any]:
        """核验批次：声明列集合与业务行实际列必须一致。"""
        batch = next(
            (row for row in store.rows(self.MODULE)
             if str(row.get("批次编号", "")) == str(batch_id)),
            None,
        )
        if batch is None:
            return {"ok": False, "reason": f"来源批 {batch_id} 不存在"}
        actual: list[str] = []
        for row in self.read_batch_rows(batch_id):
            for key in row:
                if key not in actual:
                    actual.append(key)
        declared = [c.strip() for c in str(batch.get("列集合", "")).split(",") if c.strip()]
        missing = [c for c in declared if c not in actual]
        extra = [c for c in actual if declared and c not in declared]
        return {
            "ok": not missing and not extra,
            "batch_id": batch_id,
            "declared_columns": declared,
            "actual_columns": actual,
            "missing_columns": missing,
            "undeclared_columns": extra,
            "row_count": len(self.read_batch_rows(batch_id)),
        }

    def list_batches_for_version(self, contract_id: str, version_no: str) -> list[dict[str, Any]]:
        """查询契约版本名下的全部批次数据集。"""
        return [
            row for row in store.rows(self.MODULE)
            if row.get("契约编号") == contract_id and row.get("绑定版本") == version_no
        ]


def read_source_batch(batch_id: str) -> dict:
    """模块级入口：核验来源批并返回批次与其业务行数据集。"""
    service = SourceBatchService()
    verification = service.verify_batch(batch_id)
    return {
        "batch_id": batch_id,
        "columns": service.declare_columns(batch_id),
        "rows": service.read_batch_rows(batch_id),
        "verification": verification,
    }
