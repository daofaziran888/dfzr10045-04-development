"""测试共享固件：每个测试用例前把 store 重置回干净的种子数据。

这里不重建 Store 实例，而是原地清空并重填表数据——领域服务在导入时
就持有了 `store` 对象的引用，重建实例会让它们继续读写上一份数据，
原地重置才能保证用例之间真正隔离。
"""
from __future__ import annotations

import importlib

import pytest

import app.seed as _seed


@pytest.fixture(autouse=True)
def clean_store():
    """每个测试用例使用干净的种子数据，防止跨测试数据污染。"""
    importlib.reload(_seed)
    from app.store import store

    store._tables.clear()
    store._tables.update({
        name: [dict(row) for row in rows] for name, rows in _seed.SEED_ROWS.items()
    })
    yield store
