"""委外合同接口：登记委外单位与合同条款，把天窗与处置单的工作量汇总成结算单并核定。

结算单相关的具体路径声明在 /{entry_id} 之前，避免被编号路由截胡。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.outsource import OutsourceService

router = APIRouter(prefix="/api/outsource", tags=["委外合同"])

service = OutsourceService()

CONTRACT_LIST_FIELDS = ["合同编号", "委外单位", "服务范围", "天窗单价", "处置单价", "扣款比例", "月度上限", "合同状态"]
SETTLE_LIST_FIELDS = ["结算单号", "合同编号", "委外单位", "结算月份", "汇总金额", "扣款金额", "应结金额", "结算状态"]
CONTRACT_STATUSES = ["合作中", "已暂停"]
SETTLE_STATUSES = ["待核定", "已核定", "已挂起", "已作废"]


@router.get("/settlements", response_model=PageResult[dict])
def list_settlements(
    keyword: str | None = Query(default=None, description="按结算单号、合同编号或委外单位检索"),
    month: str | None = Query(default=None, description="结算月份，如 2026-09"),
    status: str | None = Query(default=None, description="待核定、已核定、已挂起、已作废"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按条件翻页查看结算单；已核定的结算单返回的是固化快照，刷新不会变。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_settlements(keyword=keyword, month=month, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("/settlements", response_model=ActionResult)
def create_settlement(payload: EntryPayload) -> ActionResult:
    """把某合同某月的工作量汇总保存成结算单；超上限、缺条款、对不上账都会被拦下并说明原因。"""
    entry, problems = service.create_settlement(payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message=f"结算单 {entry.get('结算单号')} 已保存，待核定", entry=entry)


@router.get("/settlements/export")
def export_settlements() -> dict[str, Any]:
    """导出结算单清单：返回当前全量结算数据。"""
    items, total = service.list_settlements(page=1, size=10000)
    return {"module": "outsource_settle", "total": total, "items": items}


@router.get("/settlements/{settle_id}", response_model=dict)
def get_settlement(settle_id: int) -> dict:
    """读取单张结算单明细；不存在时给出可读的错误说明。"""
    entry = service.get_settlement(settle_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"结算单 {settle_id} 不存在或已归档")
    return entry


@router.post("/settlements/{settle_id}/actions", response_model=ActionResult)
def run_settle_action(settle_id: int, payload: EntryPayload) -> ActionResult:
    """对结算单执行核定、作废；核定前会按合同条款复核金额，对不上就拦下。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_settle_action(settle_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("", response_model=PageResult[dict])
def list_contracts(
    keyword: str | None = Query(default=None, description="按合同编号或委外单位检索"),
    status: str | None = Query(default=None, description="合作中、已暂停"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按委外单位与状态过滤合同列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_contracts(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.post("", response_model=ActionResult)
def create_contract(payload: EntryPayload) -> ActionResult:
    """登记委外合同：单位、服务范围、结算单价、扣款比例与月度上限缺一不可。"""
    entry, problems = service.create_contract(payload.values)
    if problems:
        return ActionResult(ok=False, message="；".join(problems))
    return ActionResult(ok=True, message=f"委外合同 {entry.get('合同编号')} 已登记", entry=entry)


@router.get("/export")
def export_contracts() -> dict[str, Any]:
    """导出委外合同清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_contracts(page=1, size=10000)
    return {"module": "outsource", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_contract(entry_id: int) -> dict:
    """读取单条委外合同明细；不存在时给出可读的错误说明。"""
    entry = service.get_contract(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"委外合同 {entry_id} 不存在或已归档")
    return entry


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_contract_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对合同执行暂停合作、恢复合作；暂停时未结算工作量挂起保留而不是丢掉。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_contract_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.get("/{entry_id}/aggregate")
def aggregate_workload(
    entry_id: int,
    month: str = Query(description="结算月份，如 2026-09"),
) -> dict[str, Any]:
    """汇总预览：把该合同当月已完成的天窗与处置单按合同条款算成应结金额，只算不存。"""
    result, message = service.aggregate(entry_id, month)
    if result is None:
        raise HTTPException(status_code=404, detail=message)
    return result
