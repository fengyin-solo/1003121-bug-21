"""巷道维修接口：任务归属按施工队伍收紧，验收结论单独走验收接口。

- 读（列表/详情/导出/台账复核清单）对所有人开放；
- 派发、开工限本队施工人员/班组长；验收竣工限本队验收员且任务处于待验收；
- 越权提交返回 403，detail 里写明缺哪项授权；重复验收返回 409，以首次落库为准；
- 全部越权尝试都已在服务层写进操作日志，另提供 /logs 供页面查阅。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from app.audit import audit_log
from app.identity import STAFF_DIRECTORY, TEAMS, Operator, load_operator
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.roadway import ACCEPT_ACTION, RoadwayService

router = APIRouter(prefix="/api/roadway", tags=["巷道维修"])

service = RoadwayService()

LIST_FIELDS = [
    "任务编号", "维修巷道", "维修内容", "施工队伍", "派发日期", "开工日期",
    "竣工日期", "验收人员", "验收结论", "验收时间", "任务状态",
]
STATUSES = ["待派发", "施工中", "待验收", "已竣工"]


@router.get("/identity")
def identity(operator: Operator = Depends(load_operator)) -> dict[str, Any]:
    """给前端返回当前操作人及其归属/角色，用于按钮置灰和提示。"""
    return {
        "staff_id": operator.staff_id,
        "name": operator.name,
        "team": operator.team,
        "roles": list(operator.roles),
        "known": operator.known,
        "teams": TEAMS,
        "directory": [
            {"staff_id": sid, "name": record["name"], "team": record["team"], "roles": record["roles"]}
            for sid, record in STAFF_DIRECTORY.items()
        ],
    }


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    status: str | None = Query(default=None, description="待派发、施工中、待验收、已竣工"),
    team: str | None = Query(default=None, description="按施工队伍筛选"),
    page: int = 1,
    size: int = 20,
    operator: Operator = Depends(load_operator),
) -> PageResult[dict]:
    """按任务编号、状态、队伍过滤巷道维修列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, team=team, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/review-ledger")
def review_ledger(operator: Operator = Depends(load_operator)) -> dict[str, Any]:
    """巷道维修台账的复核清单：验收结论实时同步、存量记录按派发日期回填。"""
    items = service.list_reviews()
    return {"module": "roadway_review", "total": len(items), "items": items}


@router.get("/logs")
def operation_logs(operator: Operator = Depends(load_operator)) -> dict[str, Any]:
    """操作日志：所有越权尝试、重复验收冲突与正常流转都可查。"""
    return {"total": len(audit_log.rows()), "items": audit_log.rows()}


@router.get("/export")
def export_entries(operator: Operator = Depends(load_operator)) -> dict[str, Any]:
    """导出巷道维修清单：返回全量数据，字段与列表/详情同源。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "roadway", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int, operator: Operator = Depends(load_operator)) -> dict[str, Any]:
    """读取单条维修任务明细；不存在时给出可读的错误说明。任何人可查看。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"维修任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload, operator: Operator = Depends(load_operator)) -> ActionResult:
    """登记一条维修任务，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    audit_log.add(
        result="成功",
        module="roadway",
        action="登记任务",
        operator=operator,
        entry_id=entry["id"],
        detail=f"{operator.name} 登记维修任务 {entry.get('任务编号')}（{entry.get('施工队伍')}）",
    )
    return ActionResult(ok=True, message="维修任务已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int, payload: EntryPayload, operator: Operator = Depends(load_operator)
) -> ActionResult:
    """派发任务、开始施工走这里；验收竣工请走 /accept。越权 403 详情写明缺失授权。"""
    action = str(payload.values.get("action") or "").strip()
    try:
        entry, message = service.run_action(entry_id, action, operator)
    except HTTPException:
        raise
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/accept", response_model=ActionResult)
def accept_entry(
    entry_id: int, payload: EntryPayload, operator: Operator = Depends(load_operator)
) -> ActionResult:
    """本队验收员在待验收步骤填验收结论；两人同时验收只认第一次落库的结论。"""
    entry, message, kind = service.accept(entry_id, payload.values, operator)
    if kind == "conflict":
        # 409 + 结构化 detail：前端原样展示首次结论归属
        raise HTTPException(status_code=409, detail={"message": message, "conflict": True})
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
