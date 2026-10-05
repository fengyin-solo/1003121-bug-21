"""人员身份与队伍归属。

没有接真实的登录体系之前，用工花名册 + 请求头 X-Operator-Id 表示当前操作人。
角色：
- 验收员：可以在「待验收」步骤填验收结论；
- 施工员/班组长：负责派发、开工等本队施工动作。
关键约束是「人属于且只属于一个施工队伍」，跨队任务对任何人都只读。
"""
from __future__ import annotations

from dataclasses import dataclass
from fastapi import Header

# 参与巷道维修的两支施工队伍
TEAMS = ["掘进一队", "掘进二队"]

ROLE_ACCEPTOR = "验收员"
ROLE_CONSTRUCTION = "施工员"
ROLE_FOREMAN = "班组长"

# 工花名册：工号 -> 姓名、归属队伍、角色
STAFF_DIRECTORY: dict[str, dict[str, object]] = {
    "U1001": {"name": "张建国", "team": "掘进一队", "roles": [ROLE_FOREMAN, ROLE_CONSTRUCTION]},
    "U1002": {"name": "李掘进", "team": "掘进一队", "roles": [ROLE_CONSTRUCTION]},
    "U1003": {"name": "王验收", "team": "掘进一队", "roles": [ROLE_ACCEPTOR]},
    "U1004": {"name": "赵验收", "team": "掘进一队", "roles": [ROLE_ACCEPTOR]},
    "U2001": {"name": "刘开山", "team": "掘进二队", "roles": [ROLE_FOREMAN, ROLE_CONSTRUCTION]},
    "U2002": {"name": "陈支护", "team": "掘进二队", "roles": [ROLE_CONSTRUCTION]},
    "U2003": {"name": "孙复核", "team": "掘进二队", "roles": [ROLE_ACCEPTOR]},
    "U2004": {"name": "周质检", "team": "掘进二队", "roles": [ROLE_ACCEPTOR]},
    # 其它科室人员：有账号但不属于任何施工队伍，用来验证跨队只读
    "U9001": {"name": "科室安全员", "team": None, "roles": []},
}


@dataclass(frozen=True)
class Operator:
    """当前操作人。查无此人时 known=False，按匿名处理，任何写操作都拒绝并留痕。"""

    staff_id: str | None
    name: str
    team: str | None
    roles: tuple[str, ...]
    known: bool = True

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def belongs_to(self, team: str | None) -> bool:
        return bool(self.team) and bool(team) and self.team == team


def _unknown_operator(staff_id: str | None, name: str = "") -> Operator:
    return Operator(staff_id=staff_id, name=name or "未知身份", team=None, roles=(), known=False)


def load_operator(
    x_operator_id: str | None = Header(default=None, alias="X-Operator-Id"),
    x_operator_name: str | None = Header(default=None, alias="X-Operator-Name"),
) -> Operator:
    """从请求头解析当前操作人；头缺失或工号不存在都不抛错，交给业务层拒绝并记日志。"""
    staff_id = (x_operator_id or "").strip() or None
    if staff_id is None:
        return _unknown_operator(None)
    record = STAFF_DIRECTORY.get(staff_id)
    if record is None:
        return _unknown_operator(staff_id, (x_operator_name or "").strip())
    return Operator(
        staff_id=staff_id,
        name=str(record["name"]),
        team=record["team"] if isinstance(record["team"], str) else None,
        roles=tuple(record["roles"]),  # type: ignore[arg-type]
        known=True,
    )
