"""巷道维修业务规则：队伍归属、验收权限、状态流转、台账同步都收在这里。

权限口径（以服务端判定为准，前端按钮只是辅助）：
- 任务按「施工队伍」归属；读（列表/详情）对所有人开放，写只能本队人发起；
- 派发任务、开始施工：本队施工人员或班组长；
- 验收竣工：必须同时满足「本队 + 验收员角色 + 任务处于待验收」，施工队不能自己验收自己；
- 跨队打开只有查看权，越权提交当场 403 并写明缺哪项授权，同时写入操作日志。

并发口径：同一条任务的验收在锁内二次检查状态，只认第一次落库的验收结论，
后来的提交拿到 409，并被告知首次结论的验收人。

历史口径：启动时对存量数据做一次规整——按派发日期回填、已竣工且验收人非本队的
记录按当时签字保留原结论（标记为历史签字），并同步进巷道维修台账复核清单。
"""
from __future__ import annotations

import threading
from typing import Any

from app.audit import audit_log
from app.identity import ROLE_ACCEPTOR, ROLE_CONSTRUCTION, ROLE_FOREMAN, TEAMS, Operator
from app.store import store

MODULE = "roadway"
REVIEW_MODULE = "roadway_review"
REQUIRED_FIELDS = ["任务编号", "维修巷道", "维修内容", "施工队伍"]
STATUS_ORDER = ["待派发", "施工中", "待验收", "已竣工"]
# 待派发 ->（派发任务）-> 施工中 ->（开始施工）-> 待验收 ->（验收竣工）-> 已竣工
ACTION_RULES = {"派发任务": "施工中", "开始施工": "待验收"}
ACCEPT_ACTION = "验收竣工"
QUALIFIED = "合格"
UNQUALIFIED = "不合格，返工"
_ACCEPT_LOCK = threading.Lock()
_BOOTSTRAP_LOCK = threading.Lock()

CONSTRUCTION_ROLES = (ROLE_CONSTRUCTION, ROLE_FOREMAN)


class RoadwayService:
    def __init__(self) -> None:
        self._bootstrapped = False

    # ---------- 存量规整（只执行一次） ----------
    def bootstrap(self) -> None:
        with _BOOTSTRAP_LOCK:
            if self._bootstrapped:
                return
            for row in store.rows(MODULE):
                self._normalize_row(row)
            # 已竣工的存量任务按派发日期回填进台账复核清单
            completed = [
                row
                for row in store.rows(MODULE)
                if row.get("status") == STATUS_ORDER[-1]
            ]
            for row in sorted(completed, key=lambda r: str(r.get("派发日期") or "")):
                self._sync_review(row, source="存量回填")
            self._bootstrapped = True

    def _normalize_row(self, row: dict[str, Any]) -> None:
        """把旧样例数据规整成统一口径，列表、详情、页面读到的是同一份字段。"""
        # 状态只信一个权威字段 status；旧数据里「任务状态」可能是脏样例值，直接对齐
        status = row.get("status") if row.get("status") in STATUS_ORDER else STATUS_ORDER[0]
        row["status"] = status
        # 队伍归属兜底：不在已知队伍里的，归到第一支队伍（样例脏数据修复）
        team = str(row.get("施工队伍") or "").strip()
        if team not in TEAMS:
            team = TEAMS[0]
        row["施工队伍"] = team
        # 存量任务按派发日期回填：没有派发日期的，沿用开工日期，再退到竣工日期
        if not str(row.get("派发日期") or "").strip():
            row["派发日期"] = str(row.get("开工日期") or row.get("竣工日期") or "").strip()
        # 已竣工但验收人不是本队的记录：按当时签字保留原结论，不改人、不翻案
        if status == STATUS_ORDER[-1]:
            row.setdefault("验收结论", QUALIFIED)
            row.setdefault("验收时间", row.get("竣工日期") or "")
            row.setdefault("验收说明", "存量记录，按当时验收签字保留")
            if not self._is_team_acceptor(str(row.get("验收人员") or ""), team):
                row["历史签字"] = True
        else:
            # 未竣工任务不应残留验收人，避免「验收人显示成上一任」
            row.setdefault("验收人员", "")
            row.setdefault("验收结论", "")
        self._refresh_flags(row)

    @staticmethod
    def _is_team_acceptor(acceptor_name: str, team: str) -> bool:
        """判断验收签字人是不是该队的在册验收员（用于存量数据识别）。"""
        from app.identity import STAFF_DIRECTORY

        return any(
            record["name"] == acceptor_name
            and record["team"] == team
            and ROLE_ACCEPTOR in record["roles"]
            for record in STAFF_DIRECTORY.values()
        )

    @staticmethod
    def _refresh_flags(entry: dict[str, Any]) -> None:
        status = str(entry.get("status"))
        entry["pending"] = status != STATUS_ORDER[-1]
        # 列表/详情/页面统一读「任务状态」，与权威 status 永远一致
        entry["任务状态"] = status

    # ---------- 读取 ----------
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        team: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        self.bootstrap()
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("任务编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if team:
            rows = [row for row in rows if row.get("施工队伍") == team]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        self.bootstrap()
        return store.find(MODULE, entry_id)

    def list_reviews(self) -> list[dict[str, Any]]:
        """巷道维修台账的复核清单。"""
        self.bootstrap()
        return list(store.rows(REVIEW_MODULE))

    # ---------- 写入 ----------
    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        self.bootstrap()
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, missing
        team = str(values.get("施工队伍") or "").strip()
        if team not in TEAMS:
            return None, ["施工队伍（须为本矿在册施工队伍）"]
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        for field in REQUIRED_FIELDS:
            entry[field] = str(values.get(field) or "").strip()
        entry["派发日期"] = ""
        entry["开工日期"] = ""
        entry["竣工日期"] = ""
        entry["验收人员"] = ""
        entry["验收结论"] = ""
        entry["验收时间"] = ""
        entry["验收说明"] = ""
        entry["历史签字"] = False
        entry["status"] = STATUS_ORDER[0]
        self._refresh_flags(entry)
        rows.append(entry)
        return entry, []

    def run_action(
        self, entry_id: int, action: str, operator: Operator
    ) -> tuple[dict[str, Any] | None, str]:
        """派发任务、开始施工：本队施工/班组长可执行。"""
        self.bootstrap()
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"维修任务 {entry_id} 不存在或已归档"
        if action == ACCEPT_ACTION:
            return None, "验收结论必须通过验收接口提交"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于巷道维修可执行范围"

        denials = self._team_write_denials(entry, operator)
        if not any(operator.has_role(role) for role in CONSTRUCTION_ROLES):
            denials.append("施工人员或班组长角色")
        if denials:
            from app.audit import deny

            raise deny(
                operator,
                action=action,
                denials=denials,
                entry_id=entry_id,
                target_team=str(entry.get("施工队伍")),
            )

        target = ACTION_RULES[action]
        current = str(entry.get("status"))
        expected_prev = STATUS_ORDER[STATUS_ORDER.index(target) - 1]
        if current != expected_prev:
            return None, f"任务当前为「{current}」，不能执行「{action}」（需处于「{expected_prev}」）"
        entry["status"] = target
        if action == "派发任务":
            entry["派发日期"] = self._today()
        elif action == "开始施工":
            entry["开工日期"] = self._today()
        self._refresh_flags(entry)
        audit_log.add(
            result="成功",
            module=MODULE,
            action=action,
            operator=operator,
            entry_id=entry_id,
            detail=f"{operator.name} 对 {entry.get('任务编号')} 执行{action}，状态{current}->{target}",
            extra={"任务队伍": entry.get("施工队伍")},
        )
        return entry, f"维修任务已{action}"

    def accept(
        self,
        entry_id: int,
        values: dict[str, Any],
        operator: Operator,
    ) -> tuple[dict[str, Any] | None, str, str]:
        """验收竣工：本队验收员在待验收步骤填验收结论。返回 (任务, 消息, 结论)。"""
        self.bootstrap()
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"维修任务 {entry_id} 不存在或已归档", ""

        conclusion = str(values.get("验收结论") or "").strip()
        remark = str(values.get("验收说明") or values.get("说明") or "").strip()
        if conclusion not in (QUALIFIED, UNQUALIFIED):
            return None, "验收结论须为「合格」或「不合格，返工」", ""

        # 锁内完成「检查身份 -> 检查状态 -> 落库」，两人同时验收只认第一次
        with _ACCEPT_LOCK:
            current = str(entry.get("status"))
            # 已落库过合格结论：后来的提交一律拒绝，并交代首次结论
            if current == STATUS_ORDER[-1]:
                first = {
                    "验收人员": entry.get("验收人员"),
                    "验收结论": entry.get("验收结论"),
                    "验收时间": entry.get("验收时间"),
                }
                audit_log.add(
                    result="冲突",
                    module=MODULE,
                    action=ACCEPT_ACTION,
                    operator=operator,
                    entry_id=entry_id,
                    detail=(
                        f"{operator.name} 重复验收 {entry.get('任务编号')} 被拒；"
                        f"首次结论为 {first['验收人员']} 于 {first['验收时间']} 签字"
                    ),
                    extra={"任务队伍": entry.get("施工队伍"), "首次验收": first},
                )
                return (
                    None,
                    (
                        f"该任务已由 {first['验收人员']} 于 {first['验收时间']} 完成验收"
                        f"（结论：{first['验收结论']}），以第一次落库结论为准"
                    ),
                    "conflict",
                )

            # 权限逐项核对，缺哪项就在 403 里写哪项
            denials = self._team_write_denials(entry, operator)
            if not operator.has_role(ROLE_ACCEPTOR):
                denials.append("验收员角色")
            # 施工人员即便兼着账号，也不能给本队施工的任务当验收人（自己不验收自己）
            if any(operator.has_role(role) for role in CONSTRUCTION_ROLES) and ROLE_ACCEPTOR not in operator.roles:
                denials.append("非本任务施工人员（施工与验收须分离）")
            if current != "待验收":
                denials.append(f"任务处于待验收状态（当前为「{current}」）")
            if denials:
                from app.audit import deny

                raise deny(
                    operator,
                    action=ACCEPT_ACTION,
                    denials=denials,
                    entry_id=entry_id,
                    target_team=str(entry.get("施工队伍")),
                )

            # 首次落库：验收结论只写一次
            entry["验收人员"] = operator.name
            entry["验收人工号"] = operator.staff_id
            entry["验收结论"] = conclusion
            entry["验收时间"] = self._now()
            entry["验收说明"] = remark
            entry["历史签字"] = False
            if conclusion == QUALIFIED:
                entry["status"] = STATUS_ORDER[-1]
                entry["竣工日期"] = self._today()
            else:
                # 不合格返工：回到施工中，允许整改后再次送验；本结论仍进台账复核清单
                entry["status"] = "施工中"
            self._refresh_flags(entry)
            self._sync_review(entry, source="验收同步", operator=operator, remark=remark)
            audit_log.add(
                result="成功",
                module=MODULE,
                action=ACCEPT_ACTION,
                operator=operator,
                entry_id=entry_id,
                detail=f"{operator.name} 验收 {entry.get('任务编号')}：{conclusion}",
                extra={"任务队伍": entry.get("施工队伍"), "验收结论": conclusion},
            )
            if conclusion == QUALIFIED:
                return entry, f"验收完成，{entry.get('任务编号')} 已竣工", "qualified"
            return entry, "验收结论为不合格，已退回施工中整改", "unqualified"

    # ---------- 权限与台账 ----------
    @staticmethod
    def _team_write_denials(entry: dict[str, Any], operator: Operator) -> list[str]:
        target_team = str(entry.get("施工队伍") or "")
        if not operator.known:
            return ["有效在册身份"]
        if not operator.belongs_to(target_team):
            return [f"{target_team}归属（跨队仅可查看）"]
        return []

    def _sync_review(
        self,
        entry: dict[str, Any],
        *,
        source: str,
        operator: Operator | None = None,
        remark: str = "",
    ) -> dict[str, Any]:
        """把验收结论写进巷道维修台账复核清单；同一任务同一轮结论只保留首次落库版本。"""
        reviews = store.rows(REVIEW_MODULE)
        review_id = max((int(row.get("id", 0)) for row in reviews), default=0) + 1
        record = {
            "id": review_id,
            "任务编号": entry.get("任务编号"),
            "任务ID": entry.get("id"),
            "维修巷道": entry.get("维修巷道"),
            "施工队伍": entry.get("施工队伍"),
            "派发日期": entry.get("派发日期"),
            "竣工日期": entry.get("竣工日期"),
            "验收人员": entry.get("验收人员"),
            "验收结论": entry.get("验收结论"),
            "验收时间": entry.get("验收时间"),
            "验收说明": entry.get("验收说明") or remark,
            "复核状态": "复核通过" if entry.get("验收结论") == QUALIFIED else "退回返工",
            "任务状态": entry.get("status"),
            "历史签字": bool(entry.get("历史签字")),
            "来源": source,
        }
        reviews.append(record)
        return record

    @staticmethod
    def _today() -> str:
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def _now() -> str:
        from datetime import datetime

        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")
