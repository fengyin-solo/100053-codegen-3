"""委外合同管理接口：合同登记、工作量归集、月度结算核定三套资源。

金额类写操作全部走服务端按合同条款重算：扣款比例缺失、金额与条款对不上、
超过月度上限都会被拦下并把原因带回到前端；核定通过后结果固化。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.outsource import OutsourceService

router = APIRouter(prefix="/api/outsource", tags=["委外合同管理"])

service = OutsourceService()


# ---------------------------------------------------------------------- 合同
@router.get("/contracts", response_model=PageResult[dict])
def list_contracts(
    keyword: str | None = Query(default=None, description="按合同编号或单位名称检索"),
    status: str | None = Query(default=None, description="合作中、暂停合作"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按编号、单位与合作状态过滤委外合同；多家单位的合同各自独立。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_contracts(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/contracts/{entry_id}", response_model=dict)
def get_contract(entry_id: int) -> dict:
    """读取单份委外合同（含结算单价明细、扣款比例与月度上限）。"""
    entry = service.get_contract(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"委外合同 {entry_id} 不存在或已归档")
    return entry


@router.post("/contracts", response_model=ActionResult)
def create_contract(payload: EntryPayload) -> ActionResult:
    """登记委外单位与合同条款；扣款比例/月度上限/单价缺失都会被拦下并说明原因。"""
    entry, message = service.create_contract(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message or "合同登记失败")
    return ActionResult(ok=True, message=f"委外合同 {entry['合同编号']} 已登记", entry=entry)


@router.post("/contracts/{entry_id}/actions", response_model=ActionResult)
def run_contract_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """暂停合作会把未结算单据挂起留存，恢复合作时原样释放，已核定结果不动。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_contract_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message or "合同动作未生效")
    return ActionResult(ok=True, message=message or "合同状态已更新", entry=entry)


# -------------------------------------------------------------------- 工作量
@router.get("/workloads", response_model=PageResult[dict])
def list_workloads(
    keyword: str | None = Query(default=None, description="按工作量编号或来源单号检索"),
    status: str | None = Query(default=None, description="待结算、已挂起、已计入、已结算"),
    contract_id: int | None = Query(default=None, description="按合同过滤"),
    month: str | None = Query(default=None, description="按作业月份 YYYY-MM 过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """工作量台账：按合同、月份、状态过滤，方便对数时追溯到天窗/处置单。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_workloads(
        keyword=keyword, status=status, contract_id=contract_id, month=month, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/sources")
def list_sources(source_type: str | None = Query(default=None, description="天窗、处置")) -> dict[str, Any]:
    """可作结算依据的已完成单据：已销记天窗、已验收处置单（只读，不改既有流程）。"""
    items = service.list_sources(source_type)
    return {"total": len(items), "items": items}


@router.post("/workloads", response_model=ActionResult)
def create_workload(payload: EntryPayload) -> ActionResult:
    """把天窗/处置单的完成量登记成工作量，单价取合同条款，重复登记会被拦下。"""
    entry, message = service.create_workload(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message or "工作量登记失败")
    return ActionResult(ok=True, message=f"工作量 {entry['工作量编号']} 已登记，金额 {entry['金额']:.2f} 元", entry=entry)


# ---------------------------------------------------------------------- 结算
@router.get("/settlements", response_model=PageResult[dict])
def list_settlements(
    keyword: str | None = Query(default=None, description="按结算编号或单位名称检索"),
    status: str | None = Query(default=None, description="待核定、已挂起、已核定、已作废"),
    contract_id: int | None = Query(default=None, description="按合同过滤"),
    month: str | None = Query(default=None, description="按结算月份 YYYY-MM 过滤"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """月度结算台账：同一家单位同一月按合同各自计算，互不串账。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_settlements(
        keyword=keyword, status=status, contract_id=contract_id, month=month, page=page, size=size
    )
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/settlements/{entry_id}", response_model=dict)
def get_settlement(entry_id: int) -> dict:
    """读取单份结算单明细（含工作量清单与核定时的条款快照）。"""
    entry = service.get_settlement(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"结算单 {entry_id} 不存在或已归档")
    return entry


@router.post("/settlements/preview", response_model=ActionResult)
def preview_settlement(payload: EntryPayload) -> ActionResult:
    """测算不落库：先按合同条款汇总金额并提示是否超月度上限，确认后再保存。"""
    calc, message = service.preview_settlement(payload.values)
    if calc is None:
        return ActionResult(ok=False, message=message or "结算测算失败")
    calc.pop("__contract", None)
    return ActionResult(ok=True, message="结算测算完成，确认无误后可保存", entry=calc)


@router.post("/settlements", response_model=ActionResult)
def create_settlement(payload: EntryPayload) -> ActionResult:
    """保存月度结算：超额、条款对不上、单位已暂停都会被拦下，保存的是条款快照。"""
    entry, message = service.create_settlement(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message or "结算单保存失败")
    return ActionResult(
        ok=True,
        message=f"结算单 {entry['结算编号']} 已保存待核定，应结金额 {entry['应结金额']:.2f} 元",
        entry=entry,
    )


@router.post("/settlements/{entry_id}/actions", response_model=ActionResult)
def run_settlement_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """提交核定（结果固化）、重新测算（复核条款）、作废（释放工作量，单据保留）。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_settlement_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message or "结算动作未生效")
    return ActionResult(ok=True, message=message or "结算状态已更新", entry=entry)
