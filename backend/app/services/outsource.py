"""委外合同管理业务规则：合同条款、工作量归集、月度结算与挂起都收在这里。

设计口径：
- 合同条款（单价明细、扣款比例、月度上限）是结算唯一依据，金额一律由服务端按条款重算，
  前端传入的金额只用于核对，对不上就拦下。
- 同一家委外单位同一份合同、同一个月各自计算；已核定结算计入该合同当月累计，
  累计（含本次）超过月度上限的不允许保存。
- 单位暂停合作时，未结算的工作量与待核定结算单只是「挂起」，恢复合作后原样释放，
  已核定的结果不受影响，核定后金额即固化，刷新也不会变。
- 天窗、处置单的既有流程不动，这里只读取「已销记天窗 / 已验收处置单」作为工作量来源。
"""
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from app.store import store

CONTRACT_MODULE = "outsource_contract"
WORKLOAD_MODULE = "outsource_workload"
SETTLEMENT_MODULE = "outsource_settlement"

# 天窗与处置是既有模块，这里只读引用，不改它们的流程。
SOURCE_MODULES = {"天窗": ("window", "已销记", "实际时段"), "处置": ("dispose", "已验收", "完成时间")}

CONTRACT_REQUIRED = ["合同编号", "单位名称", "服务范围"]
CONTRACT_STATUSES = ["合作中", "暂停合作"]
WORKLOAD_STATUSES = ["待结算", "已挂起", "已计入", "已结算"]
SETTLEMENT_STATUSES = ["待核定", "已挂起", "已核定", "已作废"]

MONEY_TOLERANCE = 0.01
MONTH_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")
DATE_MONTH_PATTERN = re.compile(r"(\d{4})-(\d{2})")


def _to_number(value: Any) -> float | None:
    """把登记口径里的数字收窄成 float；空串、非数字都算无效。"""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _money(value: float) -> float:
    """金额统一保留两位小数，避免 0.1+0.2 这类尾数干扰对账。"""
    return round(value + 0.0, 2)


def _next_id(rows: list[dict[str, Any]]) -> int:
    return max((int(row.get("id", 0)) for row in rows), default=0) + 1


class OutsourceService:
    # ------------------------------------------------------------------ 合同
    def list_contracts(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(CONTRACT_MODULE)
        if keyword:
            rows = [
                row
                for row in rows
                if keyword in str(row.get("合同编号", "")) or keyword in str(row.get("单位名称", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_contract(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(CONTRACT_MODULE, entry_id)

    def create_contract(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        """登记委外合同：单位、服务范围、单价明细、扣款比例、月度上限缺一不可。"""
        missing = [field for field in CONTRACT_REQUIRED if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"

        rate = _to_number(values.get("扣款比例"))
        if rate is None:
            return None, "扣款比例缺失：请按合同条款填写扣款比例（百分数，如 10 表示 10%），没有扣款依据不能登记合同"
        if rate < 0 or rate > 100:
            return None, "扣款比例超出合理范围：应为 0~100 之间的百分数"

        cap = _to_number(values.get("月度上限"))
        if cap is None:
            return None, "月度上限缺失：请按合同条款填写月度应结金额上限，没有上限无法判定超额扣款"
        if cap < 0:
            return None, "月度上限不能为负数"

        price_items, message = self._parse_price_items(values.get("单价明细"))
        if message:
            return None, message

        rows = store.rows(CONTRACT_MODULE)
        code = str(values["合同编号"]).strip()
        if any(str(row.get("合同编号")) == code for row in rows):
            return None, f"合同编号 {code} 已存在，请核对后重新登记"

        entry = {
            "id": _next_id(rows),
            "合同编号": code,
            "单位名称": str(values["单位名称"]).strip(),
            "服务范围": str(values["服务范围"]).strip(),
            "单价明细": price_items,
            "扣款比例": rate,
            "月度上限": _money(cap),
            "status": CONTRACT_STATUSES[0],
            "pending": True,
            "abnormal": False,
        }
        rows.append(entry)
        return entry, None

    def run_contract_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str | None]:
        contract = store.find(CONTRACT_MODULE, entry_id)
        if contract is None:
            return None, f"委外合同 {entry_id} 不存在或已归档"
        if action == "暂停合作":
            if contract["status"] != "合作中":
                return None, "只有合作中的合同可以暂停合作"
            contract["status"] = "暂停合作"
            contract["abnormal"] = True
            held_workloads, held_settlements = self._apply_hold(contract, hold=True)
            return contract, (
                f"已暂停与{contract['单位名称']}的合作：{held_workloads} 条未结算工作量、"
                f"{held_settlements} 份待核定结算单已挂起留存，恢复合作后可继续结算"
            )
        if action == "恢复合作":
            if contract["status"] != "暂停合作":
                return None, "只有暂停合作的合同可以恢复合作"
            contract["status"] = "合作中"
            contract["abnormal"] = False
            released = self._apply_hold(contract, hold=False)
            return contract, f"已恢复与{contract['单位名称']}的合作，{released} 条挂起单据已释放回原状态"
        return None, f"动作「{action}」不属于委外合同可执行范围"

    def _parse_price_items(self, raw: Any) -> tuple[list[dict[str, Any]], str | None]:
        """收窄结算单价表：至少一个服务项，项目名不重复，单价为非负数字。"""
        if not isinstance(raw, list) or not raw:
            return [], "结算单价缺失：请至少登记一个服务项目的结算单价，否则工作量无法计价"
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for raw_item in raw:
            if not isinstance(raw_item, dict):
                return [], "单价明细格式不正确：每行需包含作业项目与单价"
            name = str(raw_item.get("作业项目") or "").strip()
            price = _to_number(raw_item.get("单价"))
            if not name:
                return [], "单价明细里存在空的作业项目名称，请补全后再保存"
            if price is None:
                return [], f"服务项目「{name}」的结算单价缺失或不是数字，没有计价依据不能登记"
            if price < 0:
                return [], f"服务项目「{name}」的结算单价不能为负数"
            if name in seen:
                return [], f"服务项目「{name}」在单价明细里重复，请合并成一行"
            seen.add(name)
            items.append({"作业项目": name, "单价": _money(price)})
        return items, None

    def _price_of(self, contract: dict[str, Any], item_name: str) -> float | None:
        for item in contract["单价明细"]:
            if item["作业项目"] == item_name:
                return float(item["单价"])
        return None

    # ------------------------------------------------------------------ 挂起
    def _apply_hold(self, contract: dict[str, Any], *, hold: bool) -> tuple[int, int] | int:
        """暂停合作：在途工作量/结算单挂起；恢复合作：按挂起前状态原样释放。

        挂起是可逆动作：挂起前是什么状态，恢复后还是什么状态——已计入结算单的工作量
        恢复后仍是「已计入」（继续留在挂起结算单里，不能放回待结算否则会被重复汇总）；
        尚未被结算单收走的工作量恢复后仍可参与下一次汇总。
        """
        held_workloads = 0
        for workload in store.rows(WORKLOAD_MODULE):
            if workload.get("合同id") != contract["id"]:
                continue
            if hold:
                if workload["status"] in ("待结算", "已计入"):
                    workload["挂起前状态"] = workload["status"]
                    workload["status"] = "已挂起"
                    workload["abnormal"] = True
                    held_workloads += 1
            elif workload["status"] == "已挂起" and "挂起前状态" in workload:
                workload["status"] = workload.pop("挂起前状态")
                workload["abnormal"] = False
                held_workloads += 1

        held_settlements = 0
        for settlement in store.rows(SETTLEMENT_MODULE):
            if settlement.get("合同id") != contract["id"]:
                continue
            if hold:
                if settlement["status"] == "待核定":
                    settlement["挂起前状态"] = settlement["status"]
                    settlement["status"] = "已挂起"
                    settlement["abnormal"] = True
                    held_settlements += 1
            elif settlement["status"] == "已挂起" and "挂起前状态" in settlement:
                settlement["status"] = settlement.pop("挂起前状态")
                settlement["abnormal"] = False
                held_settlements += 1

        return (held_workloads, held_settlements) if hold else held_workloads + held_settlements

    # ------------------------------------------------------------------ 工作量
    def list_workloads(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        contract_id: int | None = None,
        month: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(WORKLOAD_MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("工作量编号", "")) or keyword in str(row.get("来源单号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if contract_id is not None:
            rows = [row for row in rows if row.get("合同id") == contract_id]
        if month:
            rows = [row for row in rows if row.get("作业月份") == month]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def list_sources(self, source_type: str | None = None) -> list[dict[str, Any]]:
        """可登记工作量的来源单据：已销记天窗、已验收处置单，给登记下拉做依据。"""
        types = [source_type] if source_type in SOURCE_MODULES else list(SOURCE_MODULES)
        result: list[dict[str, Any]] = []
        for kind in types:
            module, done_status, date_field = SOURCE_MODULES[kind]
            for row in store.rows(module):
                if row.get("status") != done_status:
                    continue
                result.append({
                    "来源类型": kind,
                    "来源单号": row.get("天窗编号") if kind == "天窗" else row.get("处置单号"),
                    "作业项目口径": row.get("作业类型") if kind == "天窗" else row.get("处置措施"),
                    "作业区段": row.get("作业区段", ""),
                    "委外单位": row.get("申请单位", "") if kind == "天窗" else "",
                    "完成时间": row.get(date_field, ""),
                    "作业月份": self._month_of(row.get(date_field)),
                })
        return result

    def create_workload(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        contract_id = _to_number(values.get("合同id"))
        contract = store.find(CONTRACT_MODULE, int(contract_id)) if contract_id is not None else None
        if contract is None:
            return None, "请选择有效的委外合同，工作量必须挂到具体合同上计价"
        if contract["status"] == "暂停合作":
            return None, f"{contract['单位名称']}已暂停合作，不能新增工作量；此前未结算的单据已挂起留存"

        source_type = str(values.get("来源类型") or "").strip()
        if source_type not in SOURCE_MODULES:
            return None, "来源类型只能是「天窗」或「处置」，工作量必须来自已完成的天窗或处置单"
        source_code = str(values.get("来源单号") or "").strip()
        if not source_code:
            return None, "缺少必填字段：来源单号，干了多少活必须有天窗或处置单作依据"

        item_name = str(values.get("作业项目") or "").strip()
        if not item_name:
            return None, "缺少必填字段：作业项目"
        unit_price = self._price_of(contract, item_name)
        if unit_price is None:
            return None, (
                f"作业项目「{item_name}」不在合同 {contract['合同编号']} 的结算单价范围内，"
                "合同外工作量不能计价，请先核对服务范围或补充合同条款"
            )

        quantity = _to_number(values.get("数量"))
        if quantity is None or quantity <= 0:
            return None, "工作量数量必须是大于 0 的数字，请按天窗/处置单实际完成量填写"

        source = self._find_source(source_type, source_code)
        if source is None:
            return None, f"{source_type}单据 {source_code} 不存在，工作量没有原始单据依据，不能登记"
        if "__invalid__" in source:
            return None, str(source["__invalid__"])
        month = self._month_of(source.get(SOURCE_MODULES[source_type][2]))
        if not month:
            return None, f"{source_type}单据 {source_code} 缺少完成时间，无法判定归属结算月份"

        workloads = store.rows(WORKLOAD_MODULE)
        duplicate = next(
            (
                row
                for row in workloads
                if row.get("来源类型") == source_type
                and row.get("来源单号") == source_code
                and row.get("作业项目") == item_name
            ),
            None,
        )
        if duplicate is not None:
            return None, f"{source_type}单据 {source_code} 的「{item_name}」已登记过工作量（{duplicate['工作量编号']}），不能重复结算"

        amount = _money(quantity * unit_price)
        new_id = _next_id(workloads)
        entry = {
            "id": new_id,
            "工作量编号": f"GZL-{month.replace('-', '')}-{new_id:03d}",
            "合同id": contract["id"],
            "合同编号": contract["合同编号"],
            "委外单位": contract["单位名称"],
            "来源类型": source_type,
            "来源单号": source_code,
            "作业项目": item_name,
            "结算单价": unit_price,
            "数量": quantity,
            "金额": amount,
            "作业月份": month,
            "status": "待结算",
            "pending": True,
            "abnormal": False,
        }
        workloads.append(entry)
        return entry, None

    def _find_source(self, source_type: str, source_code: str) -> dict[str, Any] | None:
        module, done_status, _ = SOURCE_MODULES[source_type]
        code_field = "天窗编号" if source_type == "天窗" else "处置单号"
        for row in store.rows(module):
            if str(row.get(code_field)) == source_code:
                if row.get("status") != done_status:
                    kind = "销记" if source_type == "天窗" else "验收"
                    return {"__invalid__": f"{source_type}单据 {source_code} 尚未{kind}，作业未完成不能计入结算"}
                return row
        return None

    def _month_of(self, value: Any) -> str | None:
        match = DATE_MONTH_PATTERN.search(str(value or ""))
        return f"{match.group(1)}-{match.group(2)}" if match else None

    # ------------------------------------------------------------------ 结算
    def list_settlements(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        contract_id: int | None = None,
        month: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(SETTLEMENT_MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("结算编号", "")) or keyword in str(row.get("委外单位", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        if contract_id is not None:
            rows = [row for row in rows if row.get("合同id") == contract_id]
        if month:
            rows = [row for row in rows if row.get("结算月份") == month]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_settlement(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(SETTLEMENT_MODULE, entry_id)

    def preview_settlement(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        """测算不落库：把某月待结算工作量按合同条款汇总，并给出超额判定。"""
        calc, _, message = self._build_calculation(values)
        if message:
            return None, message
        return calc, None

    def create_settlement(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
        contract_id = _to_number(values.get("合同id"))
        contract = store.find(CONTRACT_MODULE, int(contract_id)) if contract_id is not None else None
        if contract is None:
            return None, "请选择有效的委外合同，结算必须按具体合同条款计算"
        month = str(values.get("结算月份") or "").strip()
        if not MONTH_PATTERN.match(month):
            return None, "结算月份格式不正确，应为 YYYY-MM（如 2026-09）"

        # 同一份合同同一个月只允许一份在途结算（待核定或已挂起），避免重复汇总串账。
        active = next(
            (
                row
                for row in store.rows(SETTLEMENT_MODULE)
                if row.get("合同id") == contract["id"]
                and row.get("结算月份") == month
                and row["status"] in ("待核定", "已挂起")
            ),
            None,
        )
        if active is not None:
            held = "（已随暂停合作挂起，恢复合作后继续处理）" if active["status"] == "已挂起" else ""
            return None, f"{contract['单位名称']} {month} 已有一份{active['status']}结算（{active['结算编号']}）{held}，请先核定或作废后再重新汇总"

        calc, picked, message = self._build_calculation(values)
        if message:
            return None, message
        contract = calc["__contract"]

        settlements = store.rows(SETTLEMENT_MODULE)
        seq = sum(1 for row in settlements if row.get("合同id") == contract["id"] and row.get("结算月份") == month) + 1
        entry = {
            "id": _next_id(settlements),
            "结算编号": f"JS-{month.replace('-', '')}-{contract['id']:02d}-{seq:02d}",
            "合同id": contract["id"],
            "合同编号": contract["合同编号"],
            "委外单位": contract["单位名称"],
            "结算月份": month,
            "扣款比例": calc["扣款比例"],
            "月度上限": calc["月度上限"],
            "工作量金额": calc["工作量金额"],
            "扣款金额": calc["扣款金额"],
            "应结金额": calc["应结金额"],
            "已核定金额": calc["已核定金额"],
            "累计应结": calc["累计应结"],
            "工作量清单": deepcopy(calc["明细"]),
            "条款快照": {"单价明细": deepcopy(contract["单价明细"]), "扣款比例": contract["扣款比例"], "月度上限": contract["月度上限"]},
            "status": "待核定",
            "pending": True,
            "abnormal": calc["超上限"],
        }
        settlements.append(entry)
        for workload in picked:
            workload["status"] = "已计入"
        return entry, None

    def _build_calculation(
        self, values: dict[str, Any]
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], str | None]:
        contract_id = _to_number(values.get("合同id"))
        contract = store.find(CONTRACT_MODULE, int(contract_id)) if contract_id is not None else None
        if contract is None:
            return None, [], "请选择有效的委外合同，结算必须按具体合同条款计算"
        month = str(values.get("结算月份") or "").strip()
        if not MONTH_PATTERN.match(month):
            return None, [], "结算月份格式不正确，应为 YYYY-MM（如 2026-09）"
        if contract["status"] == "暂停合作":
            return None, [], f"{contract['单位名称']}已暂停合作，未结算单据已挂起，恢复合作后才能汇总结算"

        picked = [
            row
            for row in store.rows(WORKLOAD_MODULE)
            if row.get("合同id") == contract["id"]
            and row.get("作业月份") == month
            and row.get("status") == "待结算"
        ]
        if not picked:
            return None, [], f"{contract['单位名称']} {month} 没有待结算的工作量，不能生成空结算单"

        rate = contract.get("扣款比例")
        if rate is None:
            return None, [], "合同扣款比例缺失，按条款无法判定扣款，请先补齐合同条款"
        cap = contract.get("月度上限")
        if cap is None:
            return None, [], "合同月度上限缺失，按条款无法判定超额，请先补齐合同条款"

        details: list[dict[str, Any]] = []
        gross = 0.0
        for workload in sorted(picked, key=lambda row: (row["来源类型"], row["来源单号"], row["id"])):
            unit_price = self._price_of(contract, workload["作业项目"])
            if unit_price is None:
                return None, [], (
                    f"工作量 {workload['工作量编号']} 的作业项目「{workload['作业项目']}」"
                    "已不在合同单价范围内，金额与合同条款对不上，不能结算"
                )
            line_amount = _money(float(workload["数量"]) * unit_price)
            if abs(line_amount - float(workload["金额"])) > MONEY_TOLERANCE:
                return None, [], (
                    f"工作量 {workload['工作量编号']} 登记金额 {workload['金额']} "
                    f"与合同单价重算金额 {line_amount} 对不上，请按合同条款核对后再结算"
                )
            gross += line_amount
            details.append({
                "工作量编号": workload["工作量编号"],
                "来源类型": workload["来源类型"],
                "来源单号": workload["来源单号"],
                "作业项目": workload["作业项目"],
                "数量": workload["数量"],
                "结算单价": unit_price,
                "金额": line_amount,
            })

        gross = _money(gross)
        deduction = _money(gross * float(rate) / 100)
        payable = _money(gross - deduction)
        approved_total = _money(
            sum(
                float(row.get("应结金额", 0))
                for row in store.rows(SETTLEMENT_MODULE)
                if row.get("合同id") == contract["id"]
                and row.get("结算月份") == month
                and row["status"] == "已核定"
            )
        )
        cumulative = _money(approved_total + payable)
        over_limit = cumulative - float(cap) > MONEY_TOLERANCE

        calc = {
            "合同编号": contract["合同编号"],
            "委外单位": contract["单位名称"],
            "结算月份": month,
            "工作量金额": gross,
            "扣款比例": float(rate),
            "扣款金额": deduction,
            "应结金额": payable,
            "月度上限": float(cap),
            "已核定金额": approved_total,
            "累计应结": cumulative,
            "超上限": over_limit,
            "明细": details,
            "__contract": contract,
        }
        if over_limit:
            return None, [], (
                f"按合同 {contract['合同编号']} 条款，{month} 累计应结 {cumulative:.2f} 元，"
                f"超过月度上限 {float(cap):.2f} 元（已核定 {approved_total:.2f} 元，本次 {payable:.2f} 元，"
                f"超额 {_money(cumulative - float(cap)):.2f} 元），超出上限的金额不允许保存"
            )
        return calc, picked, None

    def run_settlement_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str | None]:
        settlement = store.find(SETTLEMENT_MODULE, entry_id)
        if settlement is None:
            return None, f"结算单 {entry_id} 不存在或已归档"
        contract = store.find(CONTRACT_MODULE, int(settlement["合同id"]))

        if action == "提交核定":
            if settlement["status"] == "已挂起":
                return None, "结算单已随暂停合作挂起，未结算单据保留不丢；请先恢复合作后再提交核定"
            if settlement["status"] != "待核定":
                return None, "只有待核定的结算单可以提交核定；已核定结果固化，不能重复核定"
            message = self._verify_locked_terms(settlement, contract)
            if message:
                return None, message
            settlement["status"] = "已核定"
            settlement["pending"] = False
            settlement["abnormal"] = False
            for workload in self._captured_workloads(settlement):
                workload["status"] = "已结算"
                workload["pending"] = False
            return settlement, f"结算单 {settlement['结算编号']} 已核定，应结金额 {settlement['应结金额']:.2f} 元已固化，后续刷新不再变化"

        if action == "重新测算":
            # 核定后的结果不允许再算；待核定单也只按保存时的条款快照复核，保证口径前后一致。
            if settlement["status"] == "已核定":
                return None, "结算单已核定，核定结果已固化，不能再刷新；金额一律以核定时的合同条款为准"
            if settlement["status"] == "已挂起":
                return None, "结算单已随暂停合作挂起，请先恢复合作后再测算"
            if settlement["status"] == "已作废":
                return None, "结算单已作废，不能重新测算"
            message = self._verify_locked_terms(settlement, contract)
            if message:
                return None, message
            return settlement, (
                f"已按合同条款复核：工作量金额 {settlement['工作量金额']:.2f}、扣款 "
                f"{settlement['扣款金额']:.2f}、应结 {settlement['应结金额']:.2f} 元，与保存结果一致"
            )

        if action == "作废":
            if settlement["status"] == "已核定":
                return None, "已核定的结算结果不允许作废或改动；如需调整请另行走补充协议流程"
            if settlement["status"] == "已作废":
                return None, "结算单已经是作废状态"
            settlement["status"] = "已作废"
            settlement["pending"] = False
            released = 0
            for workload in self._captured_workloads(settlement):
                workload["status"] = "待结算"
                workload["pending"] = True
                released += 1
            return settlement, f"结算单已作废，{released} 条工作量释放回待结算，可重新汇总（原单据保留不丢）"

        return None, f"动作「{action}」不属于委外结算可执行范围"

    def _captured_workloads(self, settlement: dict[str, Any]) -> list[dict[str, Any]]:
        codes = {line["工作量编号"] for line in settlement.get("工作量清单", [])}
        return [
            row
            for row in store.rows(WORKLOAD_MODULE)
            if row.get("工作量编号") in codes and row.get("status") in ("已计入", "已挂起")
        ]

    def _verify_locked_terms(
        self, settlement: dict[str, Any], contract: dict[str, Any] | None
    ) -> str | None:
        """核定/复核前的最后一道闸：单位状态、条款一致性、金额重算、月度上限全部对得上才放行。"""
        if contract is None:
            return "对应委外合同已不存在，结算单失去条款依据，不能核定"
        if contract["status"] == "暂停合作":
            return f"{contract['单位名称']}处于暂停合作状态，挂起的结算单不能核定，请先恢复合作"

        snapshot = settlement.get("条款快照", {})
        if snapshot.get("扣款比例") is None:
            return "结算单缺少扣款比例条款，扣款没有依据，不能核定"
        if snapshot.get("月度上限") is None:
            return "结算单缺少月度上限条款，无法判定超额，不能核定"

        price_book = {item["作业项目"]: float(item["单价"]) for item in snapshot.get("单价明细", [])}
        gross = 0.0
        for line in settlement.get("工作量清单", []):
            unit_price = price_book.get(line["作业项目"])
            if unit_price is None:
                return f"作业项目「{line['作业项目']}」不在合同单价范围内，金额与合同条款对不上，不能核定"
            expected = _money(float(line["数量"]) * unit_price)
            if abs(expected - float(line["金额"])) > MONEY_TOLERANCE:
                return (
                    f"明细「{line['工作量编号']}」金额 {float(line['金额']):.2f} 与合同单价重算 "
                    f"{expected:.2f} 对不上，不能核定"
                )
            gross += expected
        gross = _money(gross)

        rate = float(snapshot["扣款比例"])
        deduction = _money(gross * rate / 100)
        payable = _money(gross - deduction)
        if abs(gross - float(settlement["工作量金额"])) > MONEY_TOLERANCE:
            return f"工作量金额 {float(settlement['工作量金额']):.2f} 与条款重算 {gross:.2f} 对不上，不能核定"
        if abs(deduction - float(settlement["扣款金额"])) > MONEY_TOLERANCE:
            return f"扣款金额 {float(settlement['扣款金额']):.2f} 与条款重算 {deduction:.2f} 对不上，不能核定"
        if abs(payable - float(settlement["应结金额"])) > MONEY_TOLERANCE:
            return f"应结金额 {float(settlement['应结金额']):.2f} 与条款重算 {payable:.2f} 对不上，不能核定"

        other_approved = _money(
            sum(
                float(row.get("应结金额", 0))
                for row in store.rows(SETTLEMENT_MODULE)
                if row.get("合同id") == contract["id"]
                and row.get("结算月份") == settlement["结算月份"]
                and row["status"] == "已核定"
                and row["id"] != settlement["id"]
            )
        )
        cumulative = _money(other_approved + payable)
        if cumulative - float(snapshot["月度上限"]) > MONEY_TOLERANCE:
            return (
                f"核定后 {settlement['结算月份']} 累计应结 {cumulative:.2f} 元超过合同月度上限 "
                f"{float(snapshot['月度上限']):.2f} 元，不能核定"
            )
        return None
