"""巷道维修接口：任务归属按施工队伍收紧，验收只认本队验收人员的第一次结论。

- 读取（列表/详情/导出/台账）任何人可查看，跨队打开为只读；
- 写动作必须携带 ``X-Operator-Id``；越权提交当场 403 并写明缺哪项授权；
- 验收结论同步到巷道维修台账复核清单；越权尝试全部进操作日志。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import PlainTextResponse

from app import audit
from app.auth import Operator, directory, find_operator
from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.roadway import RoadwayService, teams

router = APIRouter(prefix="/api/roadway", tags=["巷道维修"])

service = RoadwayService()


def require_roadway_operator(
    x_operator_id: str | None = Header(default=None, alias="X-Operator-Id"),
) -> Operator:
    """巷道写操作身份校验：匿名或目录外人员拒绝 401，并留一条操作日志。"""
    operator = find_operator(x_operator_id)
    if operator is None:
        audit.record(
            operator=None,
            action="写操作",
            result="越权拒绝",
            reason=f"未识别的操作者身份（X-Operator-Id={x_operator_id or '空'}）",
        )
        raise HTTPException(
            status_code=401,
            detail="未识别的操作者身份，请在页面顶部选择本人后再提交（缺少登录授权）",
        )
    return operator


@router.get("/operators")
def operator_directory() -> dict[str, Any]:
    """人员目录：前端身份选择与角色/队伍提示都以这里为准。"""
    return {"teams": teams(), "operators": directory()}


@router.get("/audit-logs")
def audit_logs(
    denied_only: bool = Query(default=False, description="只看越权拒绝记录"),
    limit: int = Query(default=200, le=500),
) -> dict[str, Any]:
    """巷道维修操作日志：成功流转与越权拒绝均可查。"""
    rows = audit.list_logs(denied_only=denied_only, limit=limit)
    return {"total": len(rows), "items": rows}


@router.get("/ledger")
def ledger() -> dict[str, Any]:
    """巷道维修台账：任务清单与复核清单读的是同一份验收口径。"""
    return {"tasks": service.all_entries(), "review": service.review_list()}


@router.get("/review")
def review_list() -> dict[str, Any]:
    """巷道维修台账复核清单。"""
    return {"total": len(service.review_list()), "items": service.review_list()}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按任务编号检索"),
    status: str | None = Query(default=None, description="待派发、施工中、待验收、已竣工"),
    team: str | None = Query(default=None, description="按施工队伍筛选"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按任务编号、状态、队伍过滤巷道维修列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, team=team,
                                        page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出巷道维修清单：与列表、详情同口径。"""
    items = service.all_entries()
    return {"module": "roadway", "total": len(items), "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条维修任务明细；不存在时给出可读的错误说明。跨队也只能看，不改数据。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"维修任务 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload, operator: Operator = Depends(require_roadway_operator)) -> ActionResult:
    """登记一条维修任务，缺字段时说明原因而不是静默丢弃。"""
    entry, missing = service.create_entry(payload.values)
    if missing:
        return ActionResult(ok=False, message=f"缺少必填字段：{'、'.join(missing)}")
    audit.record(operator=operator, action="登记任务", entry_id=entry.get("id") if entry else None,
                 result="成功", reason=str(entry.get("任务编号") if entry else ""))
    return ActionResult(ok=True, message="维修任务已登记", entry=service.get_entry(int(entry["id"])))


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(
    entry_id: int,
    payload: EntryPayload,
    operator: Operator = Depends(require_roadway_operator),
) -> ActionResult:
    """派发、施工、验收竣工；状态不符、越权、重复验收都会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    outcome = service.run_action(entry_id, action, payload.values, operator)
    if outcome.entry is None:
        raise HTTPException(status_code=outcome.http_status, detail=outcome.message)
    return ActionResult(ok=True, message=outcome.message, entry=service.get_entry(entry_id))


@router.get("/audit-logs/export.txt", response_class=PlainTextResponse)
def export_audit_logs() -> str:
    """导出操作日志文本，方便线下核查。"""
    rows = audit.list_logs(limit=500)
    lines = ["时间 | 操作者 | 角色/队伍 | 动作 | 任务 | 结果 | 原因"]
    for row in rows:
        lines.append(
            f"{row['time']} | {row['operator_name']} | {row.get('role') or '-'}/"
            f"{row.get('team') or '-'} | {row['action']} | "
            f"{row.get('entry_id') or '-'} | {row['result']} | {row.get('reason') or ''}"
        )
    return "\n".join(lines)
