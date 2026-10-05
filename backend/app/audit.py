"""越权拒绝与操作日志。

所有权限判断收敛在这里：
- deny(...) 抛出统一的 403，message 明确写出缺哪项授权，denials 给出可机读的缺失项；
- record_denial(...) 把每一次越权尝试落进操作日志（内存实现，接口形态按可持久化设计）。
正常的状态流转同样记一笔，保证「谁在什么时候改了哪条任务」可追溯。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.identity import ROLE_ACCEPTOR, Operator


class AuditLog:
    def __init__(self) -> None:
        self._rows: list[dict[str, Any]] = []
        self._seq = 0

    def add(
        self,
        *,
        result: str,
        module: str,
        action: str,
        operator: Operator,
        entry_id: int | None = None,
        detail: str = "",
        denials: list[str] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._seq += 1
        row = {
            "id": self._seq,
            "时间": datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            "结果": result,
            "模块": module,
            "动作": action,
            "记录ID": entry_id,
            "操作人工号": operator.staff_id,
            "操作人": operator.name,
            "所属队伍": operator.team,
            "缺失授权": list(denials or []),
            "说明": detail,
        }
        if extra:
            row.update(extra)
        self._rows.append(row)
        return row

    def rows(self) -> list[dict[str, Any]]:
        """最新的排最前，方便页面直接展示。"""
        return list(reversed(self._rows))

    def record_denial(
        self,
        *,
        module: str,
        action: str,
        operator: Operator,
        denials: list[str],
        entry_id: int | None = None,
        detail: str = "",
        extra: dict[str, Any] | None = None,
    ) -> None:
        self.add(
            result="拒绝",
            module=module,
            action=action,
            operator=operator,
            entry_id=entry_id,
            detail=detail or "缺少授权：" + "、".join(denials),
            denials=denials,
            extra=extra,
        )


audit_log = AuditLog()


def deny(
    operator: Operator,
    *,
    action: str,
    denials: list[str],
    entry_id: int | None = None,
    target_team: str | None = None,
    module: str = "roadway",
) -> HTTPException:
    """构造 403 并同步写操作日志。调用方 raise 这个异常即可。"""
    readable = "、".join(denials)
    who = operator.name if operator.known else (operator.staff_id or "未登录身份")
    detail = f"{who} 无权执行「{action}」：缺少授权[{readable}]"
    if target_team and not operator.belongs_to(target_team):
        detail += f"，任务归属「{target_team}」与当前队伍不符（跨队仅可查看）"
    audit_log.record_denial(
        module=module,
        action=action,
        operator=operator,
        denials=denials,
        entry_id=entry_id,
        detail=detail,
        extra={"任务队伍": target_team},
    )
    return HTTPException(
        status_code=403,
        detail={
            "message": detail,
            "denials": denials,
            "required_role": ROLE_ACCEPTOR if action == "验收竣工" else None,
            "required_team": target_team,
        },
    )
