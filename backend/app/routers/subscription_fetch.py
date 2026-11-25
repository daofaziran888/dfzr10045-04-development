"""订阅取数接口：按订阅列投影取源批、续取分段、复取快照与列承诺版本切换。

这些是带领域语义的动作接口，不适用通用资源路由的增删改语义，
所以在动态 `/{module}` 路由之前单独注册。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from app.integration.subscription_fetch_chain import (
    continue_fetch_segment,
    fetch_subscription_batch,
    inspect_receipt,
    refetch_snapshot_segment,
    switch_column_promise_version,
)

router = APIRouter(prefix="/api/fetch", tags=["订阅取数"])


class FetchPayload(BaseModel):
    subscription_id: str
    endpoint_id: str
    page_size: int = 20
    today: str | None = None


class ContinuePayload(BaseModel):
    receipt_id: str
    page: int | None = None
    page_size: int | None = None
    today: str | None = None


class RefetchPayload(BaseModel):
    receipt_id: str
    page: int = 1
    today: str | None = None


class SwitchVersionPayload(BaseModel):
    contract_id: str
    new_version: str
    change_summary: str = "适用列承诺版本切换"
    compatibility: str = "向后兼容"
    retire_previous: bool = True


@router.post("/subscribe")
def subscribe_fetch(payload: FetchPayload) -> dict[str, Any]:
    """订阅取数：按列权限与契约版本投影源批，签发回执并交付首段。"""
    return fetch_subscription_batch(
        payload.subscription_id, payload.endpoint_id,
        page_size=payload.page_size, today=payload.today,
    )


@router.post("/continue")
def continue_segment(payload: ContinuePayload) -> dict[str, Any]:
    """持回执续取下一段，必须沿用回执钉住的同一份仍有效列承诺。"""
    return continue_fetch_segment(
        payload.receipt_id, page=payload.page, page_size=payload.page_size, today=payload.today,
    )


@router.post("/refetch")
def refetch_segment(payload: RefetchPayload) -> dict[str, Any]:
    """持回执复取快照分段，只读取该回执归属内的授权列。"""
    return refetch_snapshot_segment(payload.receipt_id, page=payload.page, today=payload.today)


@router.get("/inspect/{receipt_id}")
def inspect(receipt_id: str, today: str | None = Query(default=None)) -> dict[str, Any]:
    """复核回执逐段实际列与后续领取资格。"""
    return inspect_receipt(receipt_id, today=today)


@router.post("/switch-version")
def switch_version(payload: SwitchVersionPayload) -> dict[str, Any]:
    """切换契约适用的列承诺版本，并按需废止旧版本。"""
    return switch_column_promise_version(
        payload.contract_id, payload.new_version,
        change_summary=payload.change_summary,
        compatibility=payload.compatibility,
        retire_previous=payload.retire_previous,
    )
