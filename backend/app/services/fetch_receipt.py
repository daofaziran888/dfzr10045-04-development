"""取数回执领域服务：按订阅的列权限与契约版本投影源批并交付。

订阅取数不是把整张源批原样返回，而是先解析订阅绑定的契约版本与
该应用在端点上的可见列范围，取两者交集对源批做列投影；每个订阅
签发的回执只持有自己那份投影，交付分段与查询快照都用同一份投影，
后续分段必须沿用回执上钉住的列承诺版本。
"""
from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any

from app.services.access_grant import AccessGrantService
from app.services.base import BaseModuleService
from app.store import store

# 源批行里不属于业务列的元数据键，投影与摘要都不应包含它们。
_ROW_META_KEYS = {"id", "批次编号", "行序", "status", "pending", "abnormal"}
# 仍可被消费方读取的契约版本状态：过渡期内新旧并存，已废止不再可读。
READABLE_VERSION_STATUS = ("已生效", "过渡中")


class FetchReceiptService(BaseModuleService):
    MODULE = "fetch_receipt"
    ENTITY = "取数回执"
    OPERATION_TERM = "查询"
    LIST_FIELDS = ["回执编号", "订阅编号", "消费方应用", "所属端点", "来源批次", "承诺版本", "可读列", "快照编号"]
    REQUIRED_FIELDS = ["回执编号", "订阅编号", "消费方应用", "所属端点"]
    STATUS_ORDER = ["生效中", "已完成", "已失效"]
    ACTION_RULES = {"完成领取": "已完成", "强制失效": "已失效"}
    NEGATIVE_ACTIONS = ["强制失效"]

    # ------------------------------------------------------------------
    # 基础查找
    # ------------------------------------------------------------------
    def find_subscription(self, subscription_id: str) -> dict[str, Any] | None:
        """按订阅编号（或数字主键）找到订阅计划数据集。"""
        key = str(subscription_id).strip()
        for row in store.rows("subscription_plan"):
            if str(row.get("订阅编号", "")) == key:
                return row
        if key.isdigit():
            return store.find("subscription_plan", int(key))
        return None

    def find_endpoint(self, endpoint_id: str) -> dict[str, Any] | None:
        """按端点编号找到查询端点数据集。"""
        for row in store.rows("service_endpoint"):
            if row.get("端点编号") == endpoint_id:
                return row
        return None

    def find_receipt(self, receipt_id: str) -> dict[str, Any] | None:
        """按回执编号（或数字主键）找到取数回执数据集。"""
        key = str(receipt_id).strip()
        for row in store.rows(self.MODULE):
            if str(row.get("回执编号", "")) == key:
                return row
        if key.isdigit():
            return store.find(self.MODULE, int(key))
        return None

    def find_snapshot(self, snapshot_ref: str) -> dict[str, Any] | None:
        """按快照编号（或数字主键）找到结果集快照数据集。"""
        key = str(snapshot_ref).strip()
        for row in store.rows("result_set"):
            if str(row.get("快照编号", "")) == key:
                return row
        if key.isdigit():
            return store.find("result_set", int(key))
        return None

    # ------------------------------------------------------------------
    # 列承诺版本与来源批
    # ------------------------------------------------------------------
    def resolve_promise_version(self, contract_id: str, version_no: str) -> dict[str, Any]:
        """解析订阅绑定的契约版本及其字段承诺，得到列承诺版本数据集。

        版本已废止时仍然返回记录，但 readable=False，供上层给出
        「列承诺版本已失效」而不是「版本不存在」的准确原因。
        """
        version = None
        for row in store.rows("contract_version"):
            if row.get("所属契约") == contract_id and row.get("版本号") == version_no:
                version = row
                break
        if version is None:
            return {"found": False, "readable": False, "reason": f"契约版本 {version_no} 不存在"}

        promise_rows = [p for p in store.rows("field_promise")
                        if p.get("所属版本") == version.get("版本编号")]
        fields = [str(p.get("字段名称", "")) for p in promise_rows if p.get("字段名称")]
        readable = version.get("status") in READABLE_VERSION_STATUS
        return {
            "found": True,
            "readable": readable,
            "reason": "" if readable
            else f"列承诺版本 {version_no} 当前状态为{version.get('status')}，已不可读",
            "version": version,
            "version_no": version_no,
            "version_id": str(version.get("版本编号", "")),
            "promise_fields": fields,
            "promise_digest": self.promise_digest(promise_rows),
        }

    def promise_digest(self, promise_rows: list[dict[str, Any]]) -> str:
        """把字段承诺集合压成摘要，用于判断钉住的列承诺是否被改动。"""
        payload = "|".join(sorted(
            f"{p.get('字段名称', '')}:{p.get('类型声明', '')}:{p.get('空值承诺', '')}:{p.get('取值域', '')}"
            for p in promise_rows
        ))
        return hashlib.md5(payload.encode("utf-8")).hexdigest()[:16]

    def resolve_source_batch(
        self,
        contract_id: str,
        version_no: str,
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
        """读取订阅绑定版本对应的来源批及其业务行数据集。

        只接受仍可读的批次；同一版本存在多个批次时取最后入库的一个，
        返回的行已剔除批次元数据，只保留真正的业务列。
        """
        batches = [
            b for b in store.rows("source_batch")
            if b.get("契约编号") == contract_id
            and b.get("绑定版本") == version_no
            and b.get("status") not in ("已撤回", "已失效")
        ]
        if not batches:
            return None, []
        batch = max(batches, key=lambda b: int(b.get("id", 0)))
        rows = self._batch_rows(str(batch.get("批次编号", "")))
        return batch, rows

    def _batch_rows(self, batch_id: str) -> list[dict[str, Any]]:
        """取批次业务行并剔除非业务元数据、按行序稳定排序。"""
        raw = [row for row in store.rows("_source_batch_row")
               if str(row.get("批次编号", "")) == batch_id]
        raw.sort(key=lambda r: int(r.get("行序", 0) or 0))
        return [
            {k: v for k, v in row.items() if k not in _ROW_META_KEYS}
            for row in raw
        ]

    def resolve_projection(
        self,
        subscription: dict[str, Any],
        endpoint: dict[str, Any],
        today: str | None = None,
    ) -> dict[str, Any]:
        """解析一次订阅取数的可读列投影。

        可读列 = 端点返回列集合 ∩ 授权可见列范围 ∩ 绑定版本的字段承诺 ∩ 源批实际列。
        任一环节不满足都拒绝取数，不允许跳过列权限直接用源批全列。
        """
        app_id = str(subscription.get("消费方应用", ""))
        contract_id = str(subscription.get("所属契约", ""))
        endpoint_id = str(endpoint.get("端点编号", ""))
        version_no = str(subscription.get("订阅版本", ""))

        access = AccessGrantService().check_access(app_id, endpoint_id, today)
        if not access.get("allowed"):
            return {"allowed": False, "reason": f"列权限不可用：{access.get('reason', '')}"}
        grant = access["grant"]
        grant_columns = self.split_columns(grant.get("可见列范围", ""))

        promise = self.resolve_promise_version(contract_id, version_no)
        if not promise.get("readable"):
            return {"allowed": False, "reason": promise.get("reason", "列承诺版本不可读"),
                    "promise": promise, "promise_version": version_no}

        endpoint_columns = self.split_columns(endpoint.get("返回列集合", ""))
        batch, rows = self.resolve_source_batch(contract_id, version_no)
        if batch is None:
            return {"allowed": False, "reason": f"契约版本 {version_no} 没有可用的来源批",
                    "promise": promise, "promise_version": version_no}
        source_columns = self._collect_columns(rows)
        promise_columns = promise["promise_fields"]
        if not promise_columns:
            return {
                "allowed": False,
                "reason": f"契约版本 {version_no} 没有登记字段承诺，无法确定列承诺范围",
                "promise": promise,
                "promise_version": version_no,
            }

        columns = [
            column for column in endpoint_columns
            if column in grant_columns
            and column in promise_columns
            and (not source_columns or column in source_columns)
        ]
        if not columns:
            return {"allowed": False, "reason": "端点返回列、授权可见列与契约版本承诺没有交集",
                    "promise": promise, "promise_version": version_no}

        return {
            "allowed": True,
            "reason": "",
            "columns": columns,
            "grant": grant,
            "grant_id": str(grant.get("授权编号", "")),
            "endpoint_columns": endpoint_columns,
            "grant_columns": grant_columns,
            "promise": promise,
            "promise_version": version_no,
            "promise_version_id": promise["version_id"],
            "promise_digest": promise["promise_digest"],
            "promise_columns": promise_columns,
            "batch": batch,
            "source_columns": source_columns,
            "rows": rows,
        }

    # ------------------------------------------------------------------
    # 投影与回执
    # ------------------------------------------------------------------
    def project(self, rows: list[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
        """按可读列投影源批行，未授权列即使源批里存在也一律剔除。"""
        return [{column: row.get(column) for column in columns} for row in rows]

    def issue_receipt(
        self,
        subscription: dict[str, Any],
        endpoint: dict[str, Any],
        projection: dict[str, Any],
        columns: list[str],
        snapshot: dict[str, Any],
        page_size: int,
        total_rows: int,
    ) -> dict[str, Any]:
        """签发取数回执：把本次投影的归属、承诺版本与快照绑定在一张回执上。"""
        rows = store.rows(self.MODULE)
        new_id = max((int(r.get("id", 0)) for r in rows), default=0) + 1
        total_pages = max(1, (total_rows + page_size - 1) // page_size)
        receipt = {
            "id": new_id,
            "回执编号": f"RCPT-{new_id:04d}",
            "订阅编号": str(subscription.get("订阅编号", "")),
            "消费方应用": str(subscription.get("消费方应用", "")),
            "所属端点": str(endpoint.get("端点编号", "")),
            "契约编号": str(subscription.get("所属契约", "")),
            "来源批次": str(projection["batch"].get("批次编号", "")),
            "承诺版本": str(projection["promise_version"]),
            "承诺版本编号": str(projection["promise_version_id"]),
            "承诺摘要": str(projection["promise_digest"]),
            "可读列": ",".join(columns),
            "授权编号": str(projection["grant_id"]),
            "快照编号": str(snapshot.get("快照编号", "")),
            "page_size": str(page_size),
            "总行数": str(total_rows),
            "总页数": str(total_pages),
            "已交付页数": "0",
            "归属标识": f"{subscription.get('订阅编号', '')}@{endpoint.get('端点编号', '')}",
            "领取时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "status": "生效中",
            "pending": True,
            "abnormal": False,
        }
        rows.append(receipt)
        snapshot["回执编号"] = receipt["回执编号"]
        return receipt

    def receipt_columns(self, receipt: dict[str, Any]) -> list[str]:
        """读取回执自身钉住的可读列，顺序即交付顺序。"""
        return self.split_columns(receipt.get("可读列", ""))

    def validate_pinned_claim(
        self,
        receipt: dict[str, Any],
        today: str | None = None,
    ) -> dict[str, Any]:
        """复核回执钉住的列承诺与授权是否仍然有效。

        一次分批取数期间必须沿用同一份仍有效的列承诺：版本仍可读、
        承诺内容未被改动、授权仍覆盖回执列、快照仍可读且未过期。
        """
        if receipt.get("status") == "已失效":
            return {"valid": False, "reason": receipt.get("失效原因", "回执已失效")}

        subscription = self.find_subscription(str(receipt.get("订阅编号", "")))
        if subscription is None or subscription.get("status") != "生效中":
            return {"valid": False, "reason": "订阅已不处于生效中，不能继续领取"}

        version_id = str(receipt.get("承诺版本编号", ""))
        version = next(
            (v for v in store.rows("contract_version")
             if str(v.get("版本编号", "")) == version_id),
            None,
        )
        if version is None:
            return {"valid": False, "reason": f"列承诺版本 {version_id} 不存在"}
        if version.get("status") not in READABLE_VERSION_STATUS:
            return {
                "valid": False,
                "reason": f"列承诺版本 {receipt.get('承诺版本', '')} 已失效，不能沿用旧承诺续取",
            }
        promise_rows = [p for p in store.rows("field_promise")
                        if p.get("所属版本") == version_id]
        if self.promise_digest(promise_rows) != str(receipt.get("承诺摘要", "")):
            return {"valid": False, "reason": "列承诺内容已变更，旧回执不能继续沿用"}

        access = AccessGrantService().check_access(
            str(receipt.get("消费方应用", "")),
            str(receipt.get("所属端点", "")),
            today,
        )
        if not access.get("allowed"):
            return {"valid": False, "reason": f"列权限不可用：{access.get('reason', '')}"}
        grant_columns = set(self.split_columns(access["grant"].get("可见列范围", "")))
        pinned_columns = self.receipt_columns(receipt)
        missing = [column for column in pinned_columns if column not in grant_columns]
        if missing:
            return {"valid": False, "reason": f"列权限已收窄，回执列 {','.join(missing)} 不再可读"}

        snapshot = self.find_snapshot(str(receipt.get("快照编号", "")))
        if snapshot is None:
            return {"valid": False, "reason": "回执绑定的快照不存在"}
        if snapshot.get("status") != "可读":
            return {"valid": False, "reason": f"快照状态为{snapshot.get('status')}，不可复取"}
        if snapshot.get("可读列") and \
                self.split_columns(snapshot.get("可读列")) != pinned_columns:
            return {"valid": False, "reason": "快照投影与回执可读列不一致"}
        if self.is_expired(snapshot):
            return {"valid": False, "reason": "回执绑定的快照已过有效期"}

        return {"valid": True, "reason": "", "subscription": subscription,
                "snapshot": snapshot, "grant": access["grant"]}

    def snapshot_segment(
        self,
        snapshot: dict[str, Any],
        page: int,
        page_size: int,
        columns: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        """从回执绑定的同一份快照里切出指定分段，保证各页投影一致。

        分段行按快照冻结时的投影落库；传入 columns 时再按回执列收窄一次，
        防止快照里存在超出该回执归属的列。
        """
        rows = self.snapshot_rows(str(snapshot.get("快照编号", "")))
        start = (page - 1) * page_size
        segment = [dict(row) for row in rows[start:start + page_size]]
        if columns is None:
            return segment
        return [{column: row.get(column) for column in columns} for row in segment]

    def snapshot_rows(self, snapshot_id: str) -> list[dict[str, Any]]:
        """读取快照冻结的全部投影行，按行序稳定排序。"""
        rows = [
            row for row in store.rows("_snapshot_rows")
            if str(row.get("快照编号", "")) == snapshot_id
        ]
        rows.sort(key=lambda r: int(r.get("行序", 0) or 0))
        return [
            {k: v for k, v in row.items() if k not in {"快照编号", "行序"}}
            for row in rows
        ]

    def store_snapshot_rows(self, snapshot_id: str, rows: list[dict[str, Any]]) -> None:
        """把快照的投影行连同行序一起落库，供后续分段与回执复取使用。"""
        table = store.rows("_snapshot_rows")
        for index, row in enumerate(rows):
            entry = {"快照编号": snapshot_id, "行序": index}
            entry.update(row)
            table.append(entry)

    def mark_segment_delivered(self, receipt: dict[str, Any], page: int) -> None:
        """推进回执已交付页数水位，末页交付后回执转为已完成。"""
        delivered = int(receipt.get("已交付页数", "0") or "0")
        receipt["已交付页数"] = str(max(delivered, page))
        total_pages = int(receipt.get("总页数", "1") or "1")
        if int(receipt["已交付页数"]) >= total_pages:
            receipt["status"] = "已完成"
            receipt["pending"] = False
        else:
            receipt["status"] = "生效中"
            receipt["pending"] = True

    def invalidate_receipt(self, receipt: dict[str, Any], reason: str) -> None:
        """列承诺失效或授权回收时把回执整体失效，并同步失效其快照。"""
        receipt["status"] = "已失效"
        receipt["pending"] = False
        receipt["abnormal"] = True
        receipt["失效原因"] = reason
        snapshot = self.find_snapshot(str(receipt.get("快照编号", "")))
        if snapshot is not None and snapshot.get("status") == "可读":
            snapshot["status"] = "已失效"
            snapshot["abnormal"] = True

    # ------------------------------------------------------------------
    # 工具
    # ------------------------------------------------------------------
    def is_expired(self, snapshot: dict[str, Any]) -> bool:
        """按有效期水位判断快照是否已过期。"""
        expiry = str(snapshot.get("有效期", ""))
        if not expiry:
            return False
        return expiry < datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    @staticmethod
    def split_columns(value: Any) -> list[str]:
        """把逗号分隔的列声明拆成有序去重的列名列表。"""
        columns: list[str] = []
        for column in str(value or "").split(","):
            name = column.strip()
            if name and name not in columns:
                columns.append(name)
        return columns

    @staticmethod
    def _collect_columns(rows: list[dict[str, Any]]) -> list[str]:
        """汇总源批行里实际出现的业务列，保持稳定顺序。"""
        columns: list[str] = []
        for row in rows:
            for key in row:
                if key not in columns:
                    columns.append(key)
        return columns
