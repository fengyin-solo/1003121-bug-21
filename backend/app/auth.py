"""操作者身份与授权目录（演示版）。

真实环境应替换为统一认证下发的登录态；当前通过请求头 ``X-Operator-Id`` 识别操作者，
人员目录里写清每个人的角色与施工队伍归属，作为巷道维修任务归属与验收授权的唯一口径。
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, HTTPException

ROLE_DISPATCH = "调度"
ROLE_WORKER = "施工"
ROLE_ACCEPTOR = "验收"
ROLES = (ROLE_DISPATCH, ROLE_WORKER, ROLE_ACCEPTOR)


@dataclass(frozen=True)
class Operator:
    id: str
    name: str
    role: str
    team: str | None


# 人员目录：id 不随改名变化；队伍归属以这里为准，任务只认归属不认人。
OPERATORS: list[Operator] = [
    Operator("U1001", "张调度", ROLE_DISPATCH, None),
    Operator("U1002", "李建国", ROLE_WORKER, "掘进一队"),
    Operator("U1003", "王石头", ROLE_WORKER, "掘进一队"),
    Operator("U1004", "刘安全", ROLE_ACCEPTOR, "掘进一队"),
    Operator("U1005", "赵得严", ROLE_ACCEPTOR, "掘进二队"),
    Operator("U1006", "孙进宝", ROLE_WORKER, "掘进二队"),
    Operator("U1007", "周长安", ROLE_ACCEPTOR, "掘进二队"),
    Operator("U1008", "吴有福", ROLE_WORKER, "开拓三队"),
    Operator("U1009", "郑公明", ROLE_ACCEPTOR, "开拓三队"),
]

_OPERATOR_INDEX = {op.id: op for op in OPERATORS}
_NAME_INDEX = {op.name: op for op in OPERATORS}


def directory() -> list[dict[str, str | None]]:
    """给前端的人员选择列表。"""
    return [
        {"id": op.id, "name": op.name, "role": op.role, "team": op.team}
        for op in OPERATORS
    ]


def find_operator(operator_id: str | None) -> Operator | None:
    if not operator_id:
        return None
    return _OPERATOR_INDEX.get(operator_id.strip())


def find_by_name(name: str) -> Operator | None:
    return _NAME_INDEX.get(name.strip())


def require_operator(x_operator_id: str | None = Header(default=None, alias="X-Operator-Id")) -> Operator:
    """写操作必须携带有效操作者；匿名或目录外人员直接拒绝。"""
    operator = find_operator(x_operator_id)
    if operator is None:
        raise HTTPException(
            status_code=401,
            detail="未识别的操作者身份，请在页面顶部选择本人后再提交（缺少登录授权）",
        )
    return operator


def missing_grants(action: str, operator: Operator, entry_team: str) -> list[str]:
    """逐项列出执行动作缺少的授权，返回空列表表示授权齐备。

    - 派发任务：只认调度角色，与队伍无关；
    - 开始施工：施工角色 + 任务归属本队；
    - 验收竣工：验收角色 + 任务归属本队（施工队自己不能给自己验收）。
    """
    grants: list[str] = []
    if action == "派发任务":
        if operator.role != ROLE_DISPATCH:
            grants.append("调度员授权")
    elif action == "开始施工":
        if operator.role != ROLE_WORKER:
            grants.append("施工人员角色授权")
        if not entry_team or operator.team != entry_team:
            grants.append(f"本队（{entry_team or '未归属'}）归属授权")
    elif action == "验收竣工":
        if operator.role != ROLE_ACCEPTOR:
            grants.append("验收人员角色授权")
        if not entry_team or operator.team != entry_team:
            grants.append(f"本队（{entry_team or '未归属'}）归属授权")
    return grants
