"""巷道维修操作日志：所有越权尝试与状态流转都落一份，便于事后追查。

日志只追加、不在业务流程里改写；越权拒绝同样记录，避免“查不到记录”。
"""
from __future__ import annotations

import threading
from datetime import datetime
from typing import Any

from app.auth import Operator
from app.store import store

MODULE_LOG = "audit_logs"
_lock = threading.Lock()


def record(
    *,
    operator: Operator | None,
    action: str,
    entry_id: int | None = None,
    result: str,
    reason: str | None = None,
    missing: list[str] | None = None,
) -> dict[str, Any]:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with _lock:
        rows = store.rows(MODULE_LOG)
        log = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "time": now,
            "module": "roadway",
            "operator_id": operator.id if operator else None,
            "operator_name": operator.name if operator else "未识别操作者",
            "role": operator.role if operator else None,
            "team": operator.team if operator else None,
            "action": action,
            "entry_id": entry_id,
            "result": result,
            "missing": missing or [],
            "reason": reason,
        }
        rows.append(log)
        return log


def list_logs(*, denied_only: bool = False, limit: int = 200) -> list[dict[str, Any]]:
    rows = list(store.rows(MODULE_LOG))
    if denied_only:
        rows = [row for row in rows if row.get("result") == "越权拒绝"]
    # 最新的在最前面
    rows.sort(key=lambda row: int(row.get("id", 0)), reverse=True)
    return rows[: max(limit, 1)]
