"""巷道维修业务规则：队伍归属、验收授权、状态流转与台账复核同步。

口径约定（列表、详情、导出、页面读到的是同一份）：
- ``status`` 是任务状态的唯一存储口径；序列化时统一映射到「任务状态」，
  不再保留游离的自由文本状态字段；
- 验收通过后结论冻结在任务的「验收结论快照」里，验收人以快照签字人为准，
  人员目录后来改名、换人都不影响已落库的记录；
- 巷道维修台账的复核清单从验收结论快照同步，二者在同一把锁里完成，不允许半截状态。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.auth import (
    OPERATORS,
    ROLE_ACCEPTOR,
    Operator,
    find_by_name,
    missing_grants,
)
from app.audit import record as audit_record
from app.store import store

MODULE = "roadway"
MODULE_REVIEW = "roadway_review"
REQUIRED_FIELDS = ["任务编号", "维修巷道", "维修内容", "施工队伍"]
STATUS_ORDER = ["待派发", "施工中", "待验收", "已竣工"]
ACTION_RULES = {"派发任务": "施工中", "开始施工": "待验收", "验收竣工": "已竣工"}
ACCEPT_RESULTS = ["验收合格", "验收不合格"]

_accept_lock = threading.Lock()


@dataclass
class ActionOutcome:
    """动作执行的结构化结果，路由层据此决定 HTTP 状态与提示。"""

    entry: dict[str, Any] | None = None
    code: str = ""
    message: str = ""
    missing: list[str] = field(default_factory=list)
    http_status: int = 400


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _day_before(open_date: str) -> str:
    """存量任务回填派发日期：默认取开工日期前一日。"""
    try:
        base = datetime.strptime(open_date.strip(), "%Y-%m-%d")
        return (base - timedelta(days=1)).strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return open_date


def serialize(entry: dict[str, Any]) -> dict[str, Any]:
    """唯一出参口径：列表、详情、导出都走这里。"""
    snapshot = entry.get("验收结论快照") or {}
    return {
        "id": entry.get("id"),
        "任务编号": entry.get("任务编号"),
        "维修巷道": entry.get("维修巷道"),
        "维修内容": entry.get("维修内容"),
        "施工队伍": entry.get("施工队伍"),
        "派发日期": entry.get("派发日期"),
        "开工日期": entry.get("开工日期"),
        "竣工日期": entry.get("竣工日期"),
        "验收人员": snapshot.get("验收人员", entry.get("验收人员") or ""),
        "验收结论": snapshot.get("验收结论", ""),
        "验收意见": snapshot.get("验收意见", ""),
        "验收时间": snapshot.get("验收时间", ""),
        "历史签字保留": bool(snapshot.get("历史签字保留")),
        "任务状态": entry.get("status"),
        "status": entry.get("status"),
    }


class RoadwayService:
    def __init__(self) -> None:
        self._bootstrapped = False

    # ---------- 存量数据引导 ----------
    def bootstrap(self) -> None:
        """把存量任务收敛到新口径，仅在启动后执行一次。

        - 状态以旧 status 为准，删除游离的「任务状态」文本（修复列表与详情对不上）；
        - 竣工任务把当时的签字冻结成验收结论快照；签字人若不属于本队验收人员，
          保留原结论并标记为历史签字，不追溯、不改判；
        - 缺派发日期的存量任务，按派发日期早于开工日期的口径，回填为开工前一日；
        - 复核清单按已落库的验收结论同步。
        """
        if self._bootstrapped:
            return
        self._bootstrapped = True
        for entry in store.rows(MODULE):
            if entry.get("status") not in STATUS_ORDER:
                entry["status"] = STATUS_ORDER[0]
            entry.pop("任务状态", None)

            if not entry.get("派发日期"):
                open_date = str(entry.get("开工日期") or "").strip()
                if open_date:
                    entry["派发日期"] = _day_before(open_date)

            entry["pending"] = entry.get("status") != STATUS_ORDER[-1]
            entry["abnormal"] = False

            if entry.get("status") == STATUS_ORDER[-1] and not entry.get("验收结论快照"):
                signer = str(entry.get("验收人员") or "").strip()
                snapshot = {
                    "验收人员": signer,
                    "验收结论": entry.get("验收结论") or "验收合格",
                    "验收意见": entry.get("验收意见") or "存量历史记录，按当时签字保留",
                    "验收时间": str(entry.get("竣工日期") or _today()),
                }
                if signer and not _is_team_acceptor(signer, str(entry.get("施工队伍") or "")):
                    # 已竣工但验收人不是本队验收人员：按当时签字保留原结论
                    snapshot["历史签字保留"] = True
                    entry["abnormal"] = True
                entry["验收结论快照"] = snapshot

            if entry.get("验收结论快照"):
                self._sync_review(entry)

    # ---------- 读取 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        team: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if team:
            rows = [row for row in rows if row.get("施工队伍") == team]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [serialize(row) for row in rows[start:start + size]], total

    def all_entries(self) -> list[dict[str, Any]]:
        return [serialize(row) for row in store.rows(MODULE)]

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        return serialize(entry) if entry is not None else None

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS:
            entry[field] = str(values.get(field)).strip()
        entry["派发日期"] = str(values.get("派发日期") or _today()).strip() or _today()
        entry["开工日期"] = str(values.get("开工日期") or "").strip()
        entry["竣工日期"] = ""
        entry["验收人员"] = ""
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        return entry, []

    # ---------- 动作流转 ----------
    def run_action(
        self, entry_id: int, action: str, values: dict[str, Any], operator: Operator
    ) -> ActionOutcome:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return ActionOutcome(code="not_found", http_status=404,
                                 message=f"维修任务 {entry_id} 不存在或已归档")
        if action not in ACTION_RULES:
            return ActionOutcome(code="bad_action", http_status=400,
                                 message=f"动作「{action}」不属于巷道维修可执行范围")

        expected = STATUS_ORDER[STATUS_ORDER.index(ACTION_RULES[action]) - 1]
        if entry.get("status") != expected:
            if action == "验收竣工" and entry.get("status") == STATUS_ORDER[-1]:
                message = "该任务已被验收并落库，结论以第一次记录为准，不能重复验收"
            else:
                message = f"任务当前为「{entry.get('status')}」，{action}仅在「{expected}」状态可执行"
            audit_record(operator=operator, action=action, entry_id=entry_id,
                         result="拒绝", reason=message)
            return ActionOutcome(code="bad_status", http_status=409, message=message)

        team = str(entry.get("施工队伍") or "")
        grants = missing_grants(action, operator, team)
        if grants:
            message = f"越权操作已拒绝：{operator.name} 缺少 {'、'.join(grants)}，该任务仅可查看"
            audit_record(operator=operator, action=action, entry_id=entry_id,
                         result="越权拒绝", reason=message, missing=grants)
            return ActionOutcome(code="forbidden", http_status=403,
                                 message=message, missing=grants)

        if action == "派发任务":
            entry["status"] = STATUS_ORDER[1]
            entry["pending"] = True
            audit_record(operator=operator, action=action, entry_id=entry_id, result="成功")
            return ActionOutcome(entry=entry, code="ok", message="维修任务已派发")

        if action == "开始施工":
            entry["status"] = STATUS_ORDER[2]
            entry["pending"] = True
            entry["开工日期"] = entry.get("开工日期") or _today()
            audit_record(operator=operator, action=action, entry_id=entry_id, result="成功")
            return ActionOutcome(entry=entry, code="ok", message="任务已进入待验收")

        # 验收竣工：锁内重新校验状态与是否已有结论，只认第一次落库
        conclusion = str(values.get("验收结论") or "").strip()
        opinion = str(values.get("验收意见") or "").strip()
        if not conclusion:
            message = "验收结论为必填项，请填写验收合格或验收不合格后再提交"
            audit_record(operator=operator, action=action, entry_id=entry_id,
                         result="拒绝", reason=message, missing=["验收结论"])
            return ActionOutcome(code="bad_payload", http_status=400,
                                 message=message, missing=["验收结论"])
        if conclusion not in ACCEPT_RESULTS:
            message = f"验收结论仅支持：{'、'.join(ACCEPT_RESULTS)}"
            audit_record(operator=operator, action=action, entry_id=entry_id,
                         result="拒绝", reason=message)
            return ActionOutcome(code="bad_payload", http_status=400, message=message)

        with _accept_lock:
            if entry.get("status") != STATUS_ORDER[2]:
                message = "该任务已被验收并落库，结论以第一次记录为准"
                audit_record(operator=operator, action=action, entry_id=entry_id,
                             result="拒绝", reason=message)
                return ActionOutcome(code="already_accepted", http_status=409, message=message)

            now = _today()
            entry["验收结论快照"] = {
                "验收人员": operator.name,
                "验收人员编号": operator.id,
                "验收结论": conclusion,
                "验收意见": opinion,
                "验收时间": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            entry["验收人员"] = operator.name
            entry["竣工日期"] = now
            entry["status"] = STATUS_ORDER[3]
            entry["pending"] = False
            entry["abnormal"] = False
            self._sync_review(entry)

        audit_record(operator=operator, action=action, entry_id=entry_id, result="成功",
                     reason=f"验收结论：{conclusion}")
        return ActionOutcome(entry=entry, code="ok",
                             message=f"验收结论已落库：{conclusion}，并同步至维修台账复核清单")

    # ---------- 台账复核清单 ----------
    def _sync_review(self, entry: dict[str, Any]) -> None:
        """验收结论同步到巷道维修台账复核清单（同锁内调用，按任务编号幂等）。"""
        snapshot = entry["验收结论快照"]
        rows = store.rows(MODULE_REVIEW)
        for row in rows:
            if row.get("任务编号") == entry.get("任务编号"):
                row.update({
                    "复核状态": "已复核",
                    "施工队伍": entry.get("施工队伍"),
                    "复核结论": snapshot.get("验收结论"),
                    "复核意见": snapshot.get("验收意见"),
                    "复核人": snapshot.get("验收人员"),
                    "复核时间": snapshot.get("验收时间"),
                    "竣工日期": entry.get("竣工日期"),
                    "历史签字保留": bool(snapshot.get("历史签字保留")),
                })
                return
        rows.append({
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "任务编号": entry.get("任务编号"),
            "维修巷道": entry.get("维修巷道"),
            "施工队伍": entry.get("施工队伍"),
            "竣工日期": entry.get("竣工日期"),
            "复核状态": "已复核",
            "复核结论": snapshot.get("验收结论"),
            "复核意见": snapshot.get("验收意见"),
            "复核人": snapshot.get("验收人员"),
            "复核时间": snapshot.get("验收时间"),
            "历史签字保留": bool(snapshot.get("历史签字保留")),
        })

    def review_list(self) -> list[dict[str, Any]]:
        return [dict(row) for row in store.rows(MODULE_REVIEW)]


def _is_team_acceptor(person_name: str, team: str) -> bool:
    """签字人是否为该任务归属队伍的验收人员（目录口径）。"""
    person = find_by_name(person_name)
    return (
        person is not None
        and person.role == ROLE_ACCEPTOR
        and bool(team)
        and person.team == team
    )


def teams() -> list[str]:
    """目录中出现过的施工队伍。"""
    seen: list[str] = []
    for op in OPERATORS:
        if op.team and op.team not in seen:
            seen.append(op.team)
    return seen
