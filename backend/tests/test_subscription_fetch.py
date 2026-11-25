"""订阅取数链路测试：按订阅列投影、回执归属、分批续取与快照复取。

覆盖：
- 同一来源批交给两个订阅时，每张回执只有它对应的可见列；
- 不能借另一订阅的列权限取数；
- 一次分批取数各页必须沿用同一份仍有效的列承诺，并标出承诺版本；
- 列承诺切换后旧回执续取被拒，末页交付的回执资格与状态正确；
- 查询快照与交付分段使用相同投影，持回执复取只能读到归属内授权列。
"""
from __future__ import annotations

import pytest

from app.integration.subscription_fetch_chain import (
    continue_fetch_segment,
    fetch_subscription_batch,
    inspect_receipt,
    refetch_snapshot_segment,
    switch_column_promise_version,
)
from app.services.access_grant import AccessGrantService
from app.services.delivery_segment import DeliverySegmentService
from app.store import store

TODAY = "2026-11-21"


def _add_subscription(sub_id: str, app_id: str, version: str = "v2.1",
                      quota: str = "1000") -> dict:
    rows = store.rows("subscription_plan")
    subscription = {
        "id": max((int(r.get("id", 0)) for r in rows), default=0) + 1,
        "订阅编号": sub_id,
        "消费方应用": app_id,
        "所属契约": "CTR-001",
        "订阅版本": version,
        "取数频率": "实时",
        "配额上限": quota,
        "订阅起日": "2026-01-01",
        "最近取数": "",
        "status": "生效中",
        "pending": True,
        "abnormal": False,
    }
    rows.append(subscription)
    return subscription


def _grant(app_id: str, columns: list[str], end: str = "2027-12-31") -> None:
    AccessGrantService().authorize(
        app_id, "EP-001", columns, "1=1", "2026-01-01", end,
    )


def _batch_a_b() -> tuple[dict, dict]:
    """A 可取 x、y；B 只能取 x，两者都从同一来源批次领取。"""
    _grant("APP-A", ["user_id", "event_type"])
    _grant("APP-B", ["user_id"])
    _add_subscription("SUB-A", "APP-A")
    _add_subscription("SUB-B", "APP-B")
    a = fetch_subscription_batch("SUB-A", "EP-001", page_size=5, today=TODAY)
    b = fetch_subscription_batch("SUB-B", "EP-001", page_size=2, today=TODAY)
    return a, b


class TestProjectionPerSubscription:
    """同一来源批按订阅列权限做不同投影"""

    def test_same_batch_two_subscriptions_get_own_columns(self):
        a, b = _batch_a_b()
        assert a["status"] == "ok" and b["status"] == "ok"
        assert a["receipt"]["来源批次"] == b["receipt"]["来源批次"] == "BATCH-0001"
        assert a["columns"] == ["user_id", "event_type"]
        assert b["columns"] == ["user_id"]
        assert set(a["rows"][0]) == {"user_id", "event_type"}
        assert set(b["rows"][0]) == {"user_id"}

    def test_receipt_records_own_columns_only(self):
        _, b = _batch_a_b()
        assert b["receipt"]["可读列"] == "user_id"
        assert "event_type" not in b["receipt"]["可读列"]
        assert b["receipt"]["归属标识"] == "SUB-B@EP-001"

    def test_cannot_borrow_other_subscription_columns(self):
        """B 的授权只有 user_id，即使 A 能读 event_type 也不能带出。"""
        _, b = _batch_a_b()
        assert "event_type" not in b["columns"]
        for row in b["rows"]:
            assert set(row) == {"user_id"}
        snapshot = store.find("result_set", int(b["snapshot"]["快照编号"].split("-")[1]))
        assert snapshot["可读列"] == "user_id"

    def test_source_batch_still_holds_all_columns(self):
        """源批本身不裁剪列，只有投影剔除越界列。"""
        _grant("APP-B", ["user_id"])
        _add_subscription("SUB-B", "APP-B")
        fetch_subscription_batch("SUB-B", "EP-001", page_size=5, today=TODAY)
        batch = next(b for b in store.rows("source_batch") if b["批次编号"] == "BATCH-0001")
        assert "event_type" in batch["列集合"]
        assert "device_fp" in batch["列集合"]

    def test_no_grant_denies_fetch(self):
        _add_subscription("SUB-NOGRANT", "APP-NOGRANT")
        result = fetch_subscription_batch("SUB-NOGRANT", "EP-001", today=TODAY)
        assert result["status"] == "denied"
        assert "列权限不可用" in result["message"]

    def test_suspended_subscription_denied(self):
        subscription = _add_subscription("SUB-SUSP", "APP-A")
        subscription["status"] = "已暂停"
        _grant("APP-A", ["user_id"])
        result = fetch_subscription_batch("SUB-SUSP", "EP-001", today=TODAY)
        assert result["status"] == "denied"

    def test_projection_never_exceeds_promise_fields(self):
        """返回列必须同时落在端点列、授权列与绑定版本字段承诺里。

        批次里的 internal_notes 既不在端点返回列也不在字段承诺里，
        即使源批实际带着它也不能出现在结果中。
        """
        _grant("APP-FULL", ["user_id", "event_type", "event_time", "device_fp"])
        _add_subscription("SUB-FULL", "APP-FULL")
        result = fetch_subscription_batch("SUB-FULL", "EP-001", page_size=5, today=TODAY)
        assert result["status"] == "ok"
        assert result["columns"] == ["user_id", "event_type", "event_time", "device_fp"]
        assert "internal_notes" not in result["columns"]
        for row in result["rows"]:
            assert "internal_notes" not in row


class TestSegmentedFetch:
    """一次分批取数的各页必须使用同一份列承诺"""

    def test_segments_share_one_projection_and_version(self):
        _, b = _batch_a_b()
        receipt_id = b["receipt"]["回执编号"]
        second = continue_fetch_segment(receipt_id, today=TODAY)
        third = continue_fetch_segment(receipt_id, today=TODAY)
        assert second["status"] == "ok" and third["status"] == "ok"
        for result in (b, second, third):
            assert result["promise_version"] == "v2.1"
            assert result["columns"] == ["user_id"]
            for row in result["rows"]:
                assert set(row) == {"user_id"}
        assert second["segment"]["承诺版本"] == "v2.1"
        assert third["segment"]["承诺版本"] == "v2.1"

    def test_segments_cover_batch_without_overlap(self):
        _, b = _batch_a_b()
        receipt_id = b["receipt"]["回执编号"]
        rows = list(b["rows"])
        rows += continue_fetch_segment(receipt_id, today=TODAY)["rows"]
        rows += continue_fetch_segment(receipt_id, today=TODAY)["rows"]
        assert [r["user_id"] for r in rows] == [f"U0000000{i}" for i in range(1, 6)]

    def test_page_size_change_mid_fetch_rejected(self):
        _, b = _batch_a_b()
        result = continue_fetch_segment(b["receipt"]["回执编号"], page_size=3, today=TODAY)
        assert result["status"] == "denied"

    def test_out_of_range_page_rejected(self):
        _, b = _batch_a_b()
        result = continue_fetch_segment(b["receipt"]["回执编号"], page=9, today=TODAY)
        assert result["status"] == "error"

    def test_redelivered_page_rejected(self):
        _, b = _batch_a_b()
        result = continue_fetch_segment(b["receipt"]["回执编号"], page=1, today=TODAY)
        assert result["status"] == "conflict"

    def test_segment_size_clamped_by_endpoint_and_quota(self):
        _grant("APP-SMALL", ["user_id"])
        _add_subscription("SUB-SMALL", "APP-SMALL", quota="1")
        result = fetch_subscription_batch("SUB-SMALL", "EP-001", page_size=50, today=TODAY)
        assert result["status"] == "ok"
        assert result["degraded"] is True
        assert result["page_size"] == 1
        assert int(result["receipt"]["总页数"]) == 5


class TestPromiseVersionSwitch:
    """列承诺切换后，旧回执的续取资格与已交付分段复核"""

    def test_old_receipt_cannot_continue_after_switch(self):
        a, b = _batch_a_b()
        b_receipt = b["receipt"]["回执编号"]
        first = continue_fetch_segment(b_receipt, today=TODAY)
        assert first["status"] == "ok"

        switch = switch_column_promise_version(
            "CTR-001", "v2.2", change_summary="新增字段，废止旧承诺",
        )
        assert switch["status"] == "switched"
        assert "v2.1" in switch["retired_versions"]

        blocked = continue_fetch_segment(b_receipt, today=TODAY)
        assert blocked["status"] == "denied"
        assert "v2.1" in blocked["message"]
        receipt = next(r for r in store.rows("fetch_receipt")
                       if r["回执编号"] == b_receipt)
        assert receipt["status"] == "已失效"
        assert receipt["abnormal"] is True

    def test_delivered_segments_keep_own_columns_and_version(self):
        _, b = _batch_a_b()
        b_receipt = b["receipt"]["回执编号"]
        continue_fetch_segment(b_receipt, today=TODAY)
        switch_column_promise_version("CTR-001", "v2.2")

        report = inspect_receipt(b_receipt, today=TODAY)
        assert report["status"] == "ok"
        assert report["承诺版本"] == "v2.1"
        assert report["可读列"] == ["user_id"]
        assert [s["页码"] for s in report["segments"]] == [1, 2]
        for segment in report["segments"]:
            assert segment["承诺版本"] == "v2.1"
            assert segment["实际列"] == ["user_id"]
            assert segment["可读列"] == ["user_id"]
        assert report["越界分段"] == []
        assert report["可继续领取"] is False
        assert "v2.1" in report["后续领取说明"]

    def test_finished_receipt_not_eligible_before_switch(self):
        a, _ = _batch_a_b()
        receipt_id = a["receipt"]["回执编号"]
        assert a["receipt"]["status"] == "已完成"
        report = inspect_receipt(receipt_id, today=TODAY)
        assert report["可继续领取"] is False
        assert "全部交付" in report["后续领取说明"]

    def test_receipt_eligibility_before_switch(self):
        _, b = _batch_a_b()
        report = inspect_receipt(b["receipt"]["回执编号"], today=TODAY)
        assert report["可继续领取"] is True
        assert report["下一段"] == 2

    def test_soft_switch_keeps_old_promise_readable(self):
        """过渡切换：旧版本仍可读，未完成回执可以继续用旧承诺续取。"""
        _, b = _batch_a_b()
        switch_column_promise_version("CTR-001", "v2.2", retire_previous=False)
        result = continue_fetch_segment(b["receipt"]["回执编号"], today=TODAY)
        assert result["status"] == "ok"
        assert result["promise_version"] == "v2.1"

    def test_new_fetch_after_switch_uses_new_version(self):
        _grant("APP-A", ["user_id", "event_type"])
        _add_subscription("SUB-A", "APP-A")
        switch_column_promise_version("CTR-001", "v2.2")
        result = fetch_subscription_batch("SUB-A", "EP-001", page_size=5, today=TODAY)
        # 订阅仍绑定 v2.1，切换后 v2.1 废止，取数必须拒绝而不是偷偷用新版本。
        assert result["status"] == "denied"

    def test_promise_content_change_invalidates_pinned_claim(self):
        """版本未废止但字段承诺被改动时，旧回执不能沿用。"""
        _, b = _batch_a_b()
        promise = next(p for p in store.rows("field_promise")
                       if p["所属版本"] == "VER-CTR-001" and p["字段名称"] == "user_id")
        promise["取值域"] = "U00000001,U00000002"
        result = continue_fetch_segment(b["receipt"]["回执编号"], today=TODAY)
        assert result["status"] == "denied"
        assert "承诺内容已变更" in result["message"]


class TestSnapshotRefetch:
    """持回执复取快照只能读到回执归属内的授权列"""

    def test_refetch_reads_delivered_segment(self):
        _, b = _batch_a_b()
        result = refetch_snapshot_segment(b["receipt"]["回执编号"], page=1, today=TODAY)
        assert result["status"] == "ok"
        assert result["columns"] == ["user_id"]
        assert result["rows"] == b["rows"]
        assert result["leaked_columns"] == []

    def test_refetch_undelivered_segment_conflicts(self):
        _, b = _batch_a_b()
        result = refetch_snapshot_segment(b["receipt"]["回执编号"], page=2, today=TODAY)
        assert result["status"] == "conflict"

    def test_snapshot_and_segment_use_same_projection(self):
        a, _ = _batch_a_b()
        snapshot = store.find("result_set", int(a["snapshot"]["快照编号"].split("-")[1]))
        segments = DeliverySegmentService().get_segments_for_receipt(a["receipt"]["回执编号"])
        assert snapshot["可读列"] == a["receipt"]["可读列"]
        for segment in segments:
            assert segment["可读列"] == snapshot["可读列"]
            assert segment["承诺版本"] == snapshot["承诺版本"]

    def test_refetch_after_switch_denied(self):
        _, b = _batch_a_b()
        switch_column_promise_version("CTR-001", "v2.2")
        result = refetch_snapshot_segment(b["receipt"]["回执编号"], page=1, today=TODAY)
        assert result["status"] == "denied"
        assert "已失效" in result["message"]

    def test_refetch_after_grant_expiry_denied(self):
        _grant("APP-EXP", ["user_id"], end="2026-11-20")
        _add_subscription("SUB-EXP", "APP-EXP")
        result = fetch_subscription_batch("SUB-EXP", "EP-001", today=TODAY)
        assert result["status"] == "denied"
        assert "授权不在有效窗口内" in result["message"]

    def test_refetch_rejects_columns_outside_receipt(self):
        """快照里被塞进额外列时，复取仍按回执列再投影一次。"""
        _, b = _batch_a_b()
        snapshot_id = b["snapshot"]["快照编号"]
        store.rows("_snapshot_rows").append({
            "快照编号": snapshot_id, "行序": 0,
            "user_id": "U00000001", "event_type": "click",
        })
        result = refetch_snapshot_segment(b["receipt"]["回执编号"], page=1, today=TODAY)
        assert result["status"] == "ok"
        assert all(set(row) == {"user_id"} for row in result["rows"])


class TestSharedBatchScenario:
    """A、B 同批领取：B 首段送达后列承诺切版本，续取与复核"""

    def test_hard_switch_denies_second_segment_and_review_is_consistent(self):
        a, b = _batch_a_b()  # A: user_id+event_type; B: user_id only
        b_receipt = b["receipt"]["回执编号"]
        assert b["rows"][0] == {"user_id": "U00000001"}
        assert b["receipt"]["已交付页数"] == "1"
        assert b["receipt"]["总页数"] == "3"

        switch_column_promise_version("CTR-001", "v2.2")

        second = continue_fetch_segment(b_receipt, today=TODAY)
        assert second["status"] == "denied"
        assert second["eligible_for_continue"] is False
        assert second["inspection"]["可继续领取"] is False

        report = inspect_receipt(b_receipt, today=TODAY)
        # 只有首段有实际交付列，它仍然只含 B 的列且标着当时钉住的 v2.1。
        assert [s["页码"] for s in report["segments"]] == [1]
        assert report["segments"][0]["实际列"] == ["user_id"]
        assert report["segments"][0]["承诺版本"] == "v2.1"
        assert report["越界分段"] == []
        assert report["可继续领取"] is False
        assert "v2.1" in report["后续领取说明"]

    def test_soft_switch_delivers_second_segment_under_pinned_columns(self):
        a, b = _batch_a_b()
        b_receipt = b["receipt"]["回执编号"]
        switch_column_promise_version("CTR-001", "v2.2", retire_previous=False)

        second = continue_fetch_segment(b_receipt, today=TODAY)
        third = continue_fetch_segment(b_receipt, today=TODAY)
        assert second["status"] == "ok" and third["status"] == "ok"

        report = inspect_receipt(b_receipt, today=TODAY)
        assert [s["页码"] for s in report["segments"]] == [1, 2, 3]
        # 首段和次段列完全一致、承诺版本都写 v2.1，且都没有越界。
        assert {tuple(s["实际列"]) for s in report["segments"]} == {("user_id",)}
        assert {s["承诺版本"] for s in report["segments"]} == {"v2.1"}
        assert report["越界分段"] == []
        # A 的回执列仍比 B 多，两个订阅从未共享同一份投影。
        assert "event_type" in a["columns"]
        assert "event_type" not in report["可读列"]
        assert report["可继续领取"] is False
        assert "全部交付" in report["后续领取说明"]

    def test_receipt_metrics_track_delivered_pages(self):
        _, b = _batch_a_b()
        b_receipt = b["receipt"]["回执编号"]
        continue_fetch_segment(b_receipt, today=TODAY)
        receipt = next(r for r in store.rows("fetch_receipt") if r["回执编号"] == b_receipt)
        assert receipt["已交付页数"] == "2"
        assert receipt["status"] == "生效中"
        continue_fetch_segment(b_receipt, today=TODAY)
        assert receipt["已交付页数"] == "3"
        assert receipt["status"] == "已完成"


class TestReceiptListing:
    """回执与分段作为业务对象可被列表接口读取"""

    def test_receipt_and_segments_are_listable(self):
        _, b = _batch_a_b()
        receipts = store.rows("fetch_receipt")
        assert any(r["回执编号"] == b["receipt"]["回执编号"] for r in receipts)
        segments = DeliverySegmentService().get_segments_for_receipt(b["receipt"]["回执编号"])
        assert len(segments) == 1
        verification = DeliverySegmentService().verify_segment_scope(segments[0]["分段编号"])
        assert verification["ok"] is True
        assert verification["actual_columns"] == ["user_id"]

    def test_seed_receipt_is_consistent(self):
        receipt = next(r for r in store.rows("fetch_receipt") if r["回执编号"] == "RCPT-0001")
        assert receipt["可读列"] == "user_id,event_type"
        report = inspect_receipt("RCPT-0001", today=TODAY)
        assert report["越界分段"] == []
