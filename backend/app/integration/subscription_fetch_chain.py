"""订阅取数链路：订阅解析→列权限与列承诺投影→源批读取→快照冻结→回执签发→分段交付。

同一条来源批可以交给多个订阅，但每个订阅只能拿到「端点返回列 ∩ 授权可见列 ∩
绑定版本字段承诺 ∩ 源批实际列」这一份投影；回执把它钉死，后续分段、快照复取
都按回执归属内的列读取，不能借别的订阅的列权限取数。
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from app.services.fetch_receipt import FetchReceiptService
from app.services.query_plan import QueryPlanService
from app.services.result_set import ResultSetService
from app.services.subscription_plan import SubscriptionPlanService
from app.services.usage_meter import UsageMeterService
from app.store import store

_ENDPOINT_READABLE_STATUS = ("已发布", "灰度中")
_FORMAT = "%Y-%m-%d %H:%M:%S"


def fetch_subscription_batch(
    subscription_id: str,
    endpoint_id: str,
    page_size: int = 20,
    today: str | None = None,
) -> dict[str, Any]:
    """按订阅取数：解析列投影后读取源批，冻结快照、签发回执并交付首段。

    输入：订阅编号+端点+分段大小 → 处理：准入核验、列投影、源批读取、
    快照冻结、回执签发、首段交付 → 产物：回执+快照+首段数据。
    同一来源批交给两个订阅时，各自回执只含各自可见列。
    """
    service = FetchReceiptService()
    subscription = service.find_subscription(subscription_id)
    if subscription is None:
        return {"status": "error", "message": f"订阅 {subscription_id} 不存在"}
    if subscription.get("status") != "生效中":
        return {"status": "denied", "message": f"订阅 {subscription_id} 当前状态为{subscription.get('status')}，不能取数"}

    endpoint = service.find_endpoint(endpoint_id)
    if endpoint is None:
        return {"status": "error", "message": f"端点 {endpoint_id} 不存在"}
    if endpoint.get("status") not in _ENDPOINT_READABLE_STATUS:
        return {"status": "denied", "message": f"端点 {endpoint_id} 当前不可查询"}
    if endpoint.get("所属契约") != subscription.get("所属契约"):
        return {"status": "denied", "message": "订阅绑定的契约与端点所属契约不一致"}

    projection = service.resolve_projection(subscription, endpoint, today)
    if not projection.get("allowed"):
        return {
            "status": "denied",
            "message": f"订阅 {subscription.get('订阅编号')} 不能按当前列承诺取数：{projection.get('reason', '')}",
            "reason": projection.get("reason", ""),
            "promise_version": projection.get("promise_version", subscription.get("订阅版本", "")),
        }

    columns = projection["columns"]
    total_rows = len(projection["rows"])
    page_size, degraded = _clamp_page_size(subscription, endpoint, page_size)
    projected = service.project(projection["rows"], columns)

    # 查询计划与快照绑定，保证结果归属可追溯到一次具体查询。
    plan_service = QueryPlanService()
    plan = plan_service.build_plan(
        endpoint_id,
        {"订阅编号": str(subscription.get("订阅编号", ""))},
        1,
        page_size,
        estimated_rows=page_size,
        degraded=degraded,
    )
    plan_service.complete_plan(int(plan["id"]), total_rows, 10 + total_rows * 0.5)

    snapshot = _freeze_projected_snapshot(
        service, plan_id=int(plan["id"]), subscription=subscription,
        endpoint=endpoint, projection=projection, columns=columns, rows=projected,
    )
    receipt = service.issue_receipt(
        subscription, endpoint, projection, columns, snapshot,
        page_size=page_size, total_rows=total_rows,
    )
    segment = _deliver_segment(service, receipt, snapshot, page=1, page_size=page_size)
    # 一次取数只记一条计量读数，返回行数取整次投影行数，与查询计划实际行数一致；
    # 后续分段是同一份快照的复读，不重复计量行数。
    UsageMeterService().record_usage(
        str(subscription.get("消费方应用", "")), endpoint_id, 1, total_rows,
        plan_id=int(plan["id"]),
    )
    SubscriptionPlanService().record_fetch(int(subscription["id"]), total_rows)

    return {
        "status": "ok",
        "degraded": degraded,
        "receipt": receipt,
        "snapshot": _public_snapshot(snapshot),
        "plan": plan,
        "promise_version": projection["promise_version"],
        "promise_version_id": projection["promise_version_id"],
        "promise_digest": projection["promise_digest"],
        "columns": columns,
        "rows": segment["rows"],
        "page": 1,
        "page_size": page_size,
        "total_rows": total_rows,
        "total_pages": int(receipt["总页数"]),
        "segment": segment["segment"],
    }


def continue_fetch_segment(
    receipt_id: str,
    page: int | None = None,
    page_size: int | None = None,
    today: str | None = None,
) -> dict[str, Any]:
    """持回执续取下一段：必须沿用回执钉住的同一份仍有效列承诺。

    列承诺版本已失效、承诺内容变更、授权收窄或快照不可读时拒绝续取，
    并把回执与快照整体失效，避免继续用旧承诺取数。
    """
    service = FetchReceiptService()
    receipt = service.find_receipt(receipt_id)
    if receipt is None:
        return {"status": "error", "message": f"回执 {receipt_id} 不存在"}
    if receipt.get("status") == "已完成":
        return {"status": "conflict", "message": "回执对应批次已全部交付，可持回执复取快照", "receipt": receipt}

    delivered = int(receipt.get("已交付页数", "0") or "0")
    target_page = page if page is not None else delivered + 1
    total_pages = int(receipt.get("总页数", "1") or "1")
    if target_page < 1 or target_page > total_pages:
        return {"status": "error", "message": f"页号 {target_page} 超出回执范围 1..{total_pages}", "receipt": receipt}
    if target_page <= delivered:
        return {
            "status": "conflict",
            "message": f"第 {target_page} 段已经交付，可持回执复取快照",
            "receipt": receipt,
        }

    claim = service.validate_pinned_claim(receipt, today)
    if not claim.get("valid"):
        service.invalidate_receipt(receipt, str(claim.get("reason", "")))
        return {
            "status": "denied",
            "message": f"不能续取第 {target_page} 段：{claim.get('reason', '')}",
            "reason": claim.get("reason", ""),
            "receipt": receipt,
            "page": target_page,
            "eligible_for_continue": False,
            "inspection": inspect_receipt(receipt_id, today=today),
        }

    snapshot = claim["snapshot"]
    pinned_size = int(receipt.get("page_size", "20") or "20")
    segment_size = page_size or pinned_size
    if segment_size != pinned_size:
        return {
            "status": "denied",
            "message": "分批取数期间分段大小必须与回执签发时一致，否则行区间会错位",
            "receipt": receipt,
        }

    result = _deliver_segment(
        service, receipt, snapshot, page=target_page, page_size=segment_size,
    )
    return {
        "status": "ok",
        "receipt": receipt,
        "snapshot": _public_snapshot(snapshot),
        "promise_version": str(receipt.get("承诺版本", "")),
        "columns": service.receipt_columns(receipt),
        "rows": result["rows"],
        "page": target_page,
        "page_size": segment_size,
        "total_rows": int(receipt.get("总行数", "0") or "0"),
        "total_pages": int(receipt.get("总页数", "1") or "1"),
        "segment": result["segment"],
    }


def refetch_snapshot_segment(
    receipt_id: str,
    page: int = 1,
    today: str | None = None,
) -> dict[str, Any]:
    """持回执复取快照分段：只能读到该回执归属内的授权列。

    复取读的是回执绑定的同一份快照，不重新回源；即使快照里残留了
    别的订阅列，也按回执自己的可读列再投影一次。
    """
    service = FetchReceiptService()
    receipt = service.find_receipt(receipt_id)
    if receipt is None:
        return {"status": "error", "message": f"回执 {receipt_id} 不存在"}

    total_pages = int(receipt.get("总页数", "1") or "1")
    if page < 1 or page > total_pages:
        return {"status": "error", "message": f"页号 {page} 超出回执范围 1..{total_pages}", "receipt": receipt}
    delivered = int(receipt.get("已交付页数", "0") or "0")
    if page > delivered:
        return {"status": "conflict", "message": f"第 {page} 段尚未交付，不能复取", "receipt": receipt}

    claim = service.validate_pinned_claim(receipt, today)
    if not claim.get("valid"):
        return {
            "status": "denied",
            "message": f"不能复取快照：{claim.get('reason', '')}",
            "reason": claim.get("reason", ""),
            "receipt": receipt,
        }

    snapshot = claim["snapshot"]
    columns = service.receipt_columns(receipt)
    rows = service.snapshot_segment(snapshot, page, int(receipt.get("page_size", "20") or "20"), columns=columns)
    leaked = sorted({
        key for row in rows for key in row
        if key not in columns
    })
    return {
        "status": "ok",
        "receipt": receipt,
        "snapshot": _public_snapshot(snapshot),
        "promise_version": str(receipt.get("承诺版本", "")),
        "columns": columns,
        "rows": rows,
        "page": page,
        "page_size": int(receipt.get("page_size", "20") or "20"),
        "total_pages": total_pages,
        "leaked_columns": leaked,
    }


def inspect_receipt(receipt_id: str, today: str | None = None) -> dict[str, Any]:
    """复核回执：逐段列出承诺版本与实际列，并给出后续领取资格。"""
    service = FetchReceiptService()
    receipt = service.find_receipt(receipt_id)
    if receipt is None:
        return {"status": "error", "message": f"回执 {receipt_id} 不存在"}

    expected_columns = service.receipt_columns(receipt)
    snapshot = service.find_snapshot(str(receipt.get("快照编号", "")))
    segments = []
    violations = []
    for segment in _segments_for_receipt(str(receipt.get("回执编号", ""))):
        actual = _segment_columns(str(segment.get("分段编号", "")))
        outside = [column for column in actual if column not in expected_columns]
        missing = [column for column in expected_columns if column not in actual]
        if outside or missing or segment.get("承诺版本") != receipt.get("承诺版本"):
            violations.append({
                "分段编号": segment.get("分段编号"),
                "越界列": outside,
                "缺失列": missing,
                "分段承诺版本": segment.get("承诺版本"),
            })
        segments.append({
            "分段编号": segment.get("分段编号"),
            "页码": int(segment.get("页码", 0) or 0),
            "承诺版本": segment.get("承诺版本"),
            "可读列": service.split_columns(segment.get("可读列", "")),
            "实际列": actual,
            "行数": int(segment.get("行数", 0) or 0),
            "交付时间": segment.get("交付时间"),
            "status": segment.get("status"),
        })
    segments.sort(key=lambda item: item["页码"])

    claim = service.validate_pinned_claim(receipt, today)
    delivered = int(receipt.get("已交付页数", "0") or "0")
    total_pages = int(receipt.get("总页数", "1") or "1")
    can_continue = bool(claim.get("valid")) and delivered < total_pages and receipt.get("status") == "生效中"
    if delivered >= total_pages:
        continue_reason = "回执对应批次已全部交付，可持回执复取快照"
    elif not claim.get("valid"):
        continue_reason = claim.get("reason", "")
    elif receipt.get("status") != "生效中":
        continue_reason = f"回执状态为{receipt.get('status')}"
    else:
        continue_reason = f"可续取第 {delivered + 1} 段"

    return {
        "status": "ok",
        "receipt": receipt,
        "订阅编号": receipt.get("订阅编号"),
        "归属标识": receipt.get("归属标识"),
        "承诺版本": receipt.get("承诺版本"),
        "承诺摘要": receipt.get("承诺摘要"),
        "可读列": expected_columns,
        "快照编号": receipt.get("快照编号"),
        "快照列": service.split_columns(snapshot.get("可读列", "")) if snapshot else [],
        "快照状态": snapshot.get("status") if snapshot else "不存在",
        "段数": len(segments),
        "segments": segments,
        "越界分段": violations,
        "已交付页数": delivered,
        "总页数": total_pages,
        "下一段": delivered + 1 if delivered < total_pages else None,
        "可继续领取": can_continue,
        "后续领取说明": continue_reason,
    }


def switch_column_promise_version(
    contract_id: str,
    new_version: str,
    change_summary: str = "适用列承诺版本切换",
    compatibility: str = "向后兼容",
    retire_previous: bool = True,
) -> dict[str, Any]:
    """把契约当前适用的列承诺切换到新版本，并按需废止旧版本。

    retire_previous=True 时旧版本立即废止，已签发回执不能再用旧承诺续取；
    False 时旧版本保留在过渡中，只有仍可读的旧承诺可以继续分页。
    """
    from app.integration.contract_lifecycle import _write_audit, evolve_contract_version
    from app.services.fetch_receipt import READABLE_VERSION_STATUS

    contract = next(
        (row for row in store.rows("data_contract") if row.get("契约编号") == contract_id),
        None,
    )
    if contract is None:
        return {"status": "error", "message": f"契约 {contract_id} 不存在"}

    version = next(
        (row for row in store.rows("contract_version")
         if row.get("所属契约") == contract_id and row.get("版本号") == new_version),
        None,
    )
    created = False
    if version is None:
        evolved = evolve_contract_version(contract_id, new_version, change_summary, compatibility, 0)
        if evolved.get("status") != "evolved":
            return evolved
        version = evolved["version"]
        created = True

    retired: list[str] = []
    for row in store.rows("contract_version"):
        if row.get("所属契约") != contract_id or row.get("版本号") == new_version:
            continue
        if row.get("status") in READABLE_VERSION_STATUS:
            if retire_previous:
                row["status"] = "已废止"
                row["pending"] = False
                row["abnormal"] = True
                retired.append(str(row.get("版本号", "")))
            else:
                row["status"] = "过渡中"
                row["pending"] = True
    if not retire_previous:
        version["status"] = "过渡中"
        version["pending"] = True
    else:
        version["status"] = "已生效"
        version["pending"] = False
        version["abnormal"] = False

    contract["当前版本"] = new_version
    _write_audit(contract_id, "版本演进", "", new_version, "system")

    affected = [
        str(receipt.get("回执编号", ""))
        for receipt in store.rows("fetch_receipt")
        if receipt.get("承诺版本") in retired and receipt.get("status") == "生效中"
    ]
    return {
        "status": "switched",
        "contract_id": contract_id,
        "new_version": new_version,
        "created": created,
        "retired_versions": retired,
        "receipts_pending": affected,
        "version": version,
    }


# ----------------------------------------------------------------------
# 内部：快照、分段、用量
# ----------------------------------------------------------------------
def _freeze_projected_snapshot(
    service: FetchReceiptService,
    plan_id: int,
    subscription: dict[str, Any],
    endpoint: dict[str, Any],
    projection: dict[str, Any],
    columns: list[str],
    rows: list[dict[str, Any]],
) -> dict[str, Any]:
    """把按订阅投影后的结果集冻结成快照，并记录投影归属。"""
    snapshot = ResultSetService().freeze_snapshot(
        plan_id=plan_id,
        bound_version=str(projection["promise_version"]),
        rows=rows,
    )
    snapshot.update({
        "可读列": ",".join(columns),
        "承诺版本": str(projection["promise_version"]),
        "承诺版本编号": str(projection["promise_version_id"]),
        "承诺摘要": str(projection["promise_digest"]),
        "来源批次": str(projection["batch"].get("批次编号", "")),
        "订阅编号": str(subscription.get("订阅编号", "")),
        "消费方应用": str(subscription.get("消费方应用", "")),
        "归属标识": f"{subscription.get('订阅编号', '')}@{endpoint.get('端点编号', '')}",
        "契约编号": str(subscription.get("所属契约", "")),
    })
    service.store_snapshot_rows(str(snapshot["快照编号"]), rows)
    return snapshot


def _deliver_segment(
    service: FetchReceiptService,
    receipt: dict[str, Any],
    snapshot: dict[str, Any],
    page: int,
    page_size: int,
) -> dict[str, Any]:
    """从快照切出一段按回执列投影的数据、登记交付分段并推进回执水位。"""
    columns = service.receipt_columns(receipt)
    rows = service.snapshot_segment(snapshot, page, page_size, columns=columns)
    start = (page - 1) * page_size
    seg_rows = store.rows("delivery_segment")
    new_id = max((int(r.get("id", 0)) for r in seg_rows), default=0) + 1
    segment = {
        "id": new_id,
        "分段编号": f"SEG-{new_id:04d}",
        "所属回执": str(receipt.get("回执编号", "")),
        "快照编号": str(snapshot.get("快照编号", "")),
        "页码": str(page),
        "承诺版本": str(receipt.get("承诺版本", "")),
        "可读列": ",".join(columns),
        "起始行": str(start),
        "结束行": str(start + len(rows)),
        "行数": str(len(rows)),
        "交付时间": datetime.now().strftime(_FORMAT),
        "status": "已交付",
        "pending": False,
        "abnormal": False,
    }
    seg_rows.append(segment)
    _store_segment_rows(str(segment["分段编号"]), rows)
    service.mark_segment_delivered(receipt, page)
    return {"segment": segment, "rows": rows}


def _store_segment_rows(segment_id: str, rows: list[dict[str, Any]]) -> None:
    """留存分段实际交付行，供事后复核实际列。"""
    table = store.rows("_delivery_row")
    for index, row in enumerate(rows):
        entry = {"分段编号": segment_id, "行序": index}
        entry.update(row)
        table.append(entry)


def _segment_columns(segment_id: str) -> list[str]:
    """汇总某分段实际交付行里出现的列。"""
    columns: list[str] = []
    for row in store.rows("_delivery_row"):
        if str(row.get("分段编号", "")) != segment_id:
            continue
        for key in row:
            if key in ("分段编号", "行序"):
                continue
            if key not in columns:
                columns.append(key)
    return columns


def _segments_for_receipt(receipt_id: str) -> list[dict[str, Any]]:
    """读取回执名下的交付分段数据集。"""
    return [
        row for row in store.rows("delivery_segment")
        if str(row.get("所属回执", "")) == receipt_id
    ]


def _clamp_page_size(
    subscription: dict[str, Any],
    endpoint: dict[str, Any],
    page_size: int,
) -> tuple[int, bool]:
    """分段大小同时受端点分页上限与订阅配额上限约束，超出即降级。"""
    requested = max(1, int(page_size or 20))
    ceiling = int(endpoint.get("分页上限", "100") or "100")
    quota = SubscriptionPlanService().check_quota_ceiling(int(subscription["id"]), requested)
    limit = min(ceiling, quota.get("ceiling", ceiling) or ceiling)
    if requested > limit:
        return max(1, limit), True
    return requested, False


def _public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """对外返回快照时去掉以 _ 开头的内部字段。"""
    return {k: v for k, v in snapshot.items() if not k.startswith("_")}
