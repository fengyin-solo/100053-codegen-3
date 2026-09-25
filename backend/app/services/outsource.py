"""委外合同业务规则：合同登记、暂停恢复，以及结算汇总、上限拦截与核定的口径都收在这里。

结算链路：天窗（已销记，按申请单位归属）与处置单（已验收，按处置人员归属）的已完成工作量，
乘上合同登记的结算单价得到汇总金额，再按合同扣款比例扣款得到应结金额；
应结金额超出合同月度上限、扣款比例缺失、申报金额与合同条款对不上，一律不允许保存。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "outsource"
SETTLE_MODULE = "outsource_settle"
WINDOW_MODULE = "window"
DISPOSE_MODULE = "dispose"

CONTRACT_REQUIRED = ["委外单位", "服务范围", "天窗单价", "处置单价", "扣款比例", "月度上限"]
CONTRACT_ACTIONS = {"暂停合作": "已暂停", "恢复合作": "合作中"}
SETTLE_ACTIONS = ["核定", "作废"]
MONEY_TOLERANCE = 0.005


def _to_money(value: Any) -> float | None:
    """把输入解析成金额（保留两位小数）；空值或非法数字返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return round(float(text), 2)
    except ValueError:
        return None


def _to_ratio(value: Any) -> float | None:
    """把输入解析成扣款比例；支持 0.05 与 5% 两种写法，空值或非法数字返回 None。"""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("%"):
            return round(float(text[:-1]) / 100, 4)
        return round(float(text), 4)
    except ValueError:
        return None


def _month_of(value: Any) -> str:
    """从日期文本里取结算月份（2026-09-05 -> 2026-09）。"""
    return str(value or "")[:7]


def _valid_month(month: str) -> bool:
    if len(month) != 7 or month[4] != "-":
        return False
    year, _, mon = month.partition("-")
    return year.isdigit() and mon.isdigit() and 1 <= int(mon) <= 12


def _fmt(value: float | None) -> str:
    return f"{value:.2f}" if value is not None else "—"


class OutsourceService:
    # ---------- 合同登记与流转 ----------

    def list_contracts(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("合同编号", "")) or keyword in str(row.get("委外单位", ""))
            ]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_contract(self, entry_id: int) -> dict[str, Any] | None:
        return store.find(MODULE, entry_id)

    def find_contract_by_code(self, code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("合同编号", "")) == code:
                return row
        return None

    def create_contract(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        missing = [field for field in CONTRACT_REQUIRED if not str(values.get(field) or "").strip()]
        if missing:
            return None, [f"缺少必填字段：{'、'.join(missing)}"]
        window_price = _to_money(values.get("天窗单价"))
        dispose_price = _to_money(values.get("处置单价"))
        month_cap = _to_money(values.get("月度上限"))
        ratio = _to_ratio(values.get("扣款比例"))
        problems: list[str] = []
        if window_price is None or window_price < 0:
            problems.append("天窗单价不是有效金额")
        if dispose_price is None or dispose_price < 0:
            problems.append("处置单价不是有效金额")
        if month_cap is None or month_cap <= 0:
            problems.append("月度上限不是有效金额")
        if ratio is None:
            problems.append("扣款比例缺失，请按合同条款登记")
        elif not 0 <= ratio < 1:
            problems.append("扣款比例应在 0~1 之间（如 0.05 或 5%）")
        if problems:
            return None, problems
        vendor = str(values.get("委外单位")).strip()
        for row in store.rows(MODULE):
            if row.get("委外单位") == vendor and row.get("status") == "合作中":
                return None, [f"委外单位「{vendor}」已有合作中的合同 {row.get('合同编号')}，请勿重复登记"]
        rows = store.rows(MODULE)
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        entry: dict[str, Any] = {
            "id": next_id,
            "合同编号": f"OUTS-{next_id:04d}",
            "委外单位": vendor,
            "服务范围": str(values.get("服务范围")).strip(),
            "天窗单价": window_price,
            "处置单价": dispose_price,
            "扣款比例": ratio,
            "月度上限": month_cap,
            "签订日期": str(values.get("签订日期") or date.today().isoformat()),
            "到期日期": str(values.get("到期日期") or ""),
            "联系人": str(values.get("联系人") or ""),
            "status": "合作中",
            "pending": True,
            "abnormal": False,
        }
        rows.append(entry)
        return entry, []

    def run_contract_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"委外合同 {entry_id} 不存在或已归档"
        if action not in CONTRACT_ACTIONS:
            return None, f"动作「{action}」不属于委外合同可执行范围"
        target = CONTRACT_ACTIONS[action]
        if entry.get("status") == target:
            return None, f"合同 {entry.get('合同编号')} 已经处于「{target}」状态"
        entry["status"] = target
        entry["pending"] = target == "合作中"
        entry["abnormal"] = target != "合作中"
        # 暂停合作时，未结算的单据（待核定结算单）挂起保留；恢复合作时原样放回，不丢数据。
        cascaded = 0
        for row in store.rows(SETTLE_MODULE):
            if row.get("合同编号") != entry.get("合同编号"):
                continue
            if target == "已暂停" and row.get("status") == "待核定":
                row["status"] = "已挂起"
                row["abnormal"] = True
                cascaded += 1
            elif target == "合作中" and row.get("status") == "已挂起":
                row["status"] = "待核定"
                row["abnormal"] = False
                cascaded += 1
        if target == "已暂停":
            held = len(self.collect_workload(entry, ""))
            return entry, f"合同已暂停合作，{cascaded} 张待核定结算单已挂起，{held} 笔未结算工作量保留待恢复后结算"
        return entry, f"合同已恢复合作，{cascaded} 张结算单回到待核定"

    # ---------- 工作量汇总 ----------

    def _settled_refs(self) -> set[tuple[str, int]]:
        """已核定结算单占用过的单据，不再进入后续汇总，避免重复结算。"""
        refs: set[tuple[str, int]] = set()
        for row in store.rows(SETTLE_MODULE):
            if row.get("status") != "已核定":
                continue
            for item in row.get("工作量明细") or []:
                refs.add((str(item.get("来源")), int(item.get("单据id", 0))))
        return refs

    def collect_workload(self, contract: dict[str, Any], month: str) -> list[dict[str, Any]]:
        """汇总该合同在指定月份已完成、未结算的天窗与处置单；month 为空串时不过滤月份。"""
        vendor = str(contract.get("委外单位") or "")
        refs = self._settled_refs()
        window_price = _to_money(contract.get("天窗单价")) or 0.0
        dispose_price = _to_money(contract.get("处置单价")) or 0.0
        items: list[dict[str, Any]] = []
        for row in store.rows(WINDOW_MODULE):
            if row.get("status") != "已销记":
                continue
            if str(row.get("申请单位") or "") != vendor:
                continue
            if month and _month_of(row.get("实际时段") or row.get("计划时段")) != month:
                continue
            if ("天窗", int(row.get("id", 0))) in refs:
                continue
            items.append({
                "来源": "天窗",
                "单据id": int(row.get("id", 0)),
                "单号": row.get("天窗编号"),
                "工作量": 1,
                "单价": window_price,
                "金额": round(window_price, 2),
            })
        for row in store.rows(DISPOSE_MODULE):
            if row.get("status") != "已验收":
                continue
            if str(row.get("处置人员") or "") != vendor:
                continue
            if month and _month_of(row.get("完成时间")) != month:
                continue
            if ("处置单", int(row.get("id", 0))) in refs:
                continue
            items.append({
                "来源": "处置单",
                "单据id": int(row.get("id", 0)),
                "单号": row.get("处置单号"),
                "工作量": 1,
                "单价": dispose_price,
                "金额": round(dispose_price, 2),
            })
        return items

    def _build_amounts(
        self, contract: dict[str, Any], items: list[dict[str, Any]]
    ) -> tuple[float, float | None, float | None, float | None, float | None]:
        gross = round(sum(float(item.get("金额", 0)) for item in items), 2)
        ratio = _to_ratio(contract.get("扣款比例"))
        deduction = round(gross * ratio, 2) if ratio is not None else None
        net = round(gross - deduction, 2) if deduction is not None else None
        cap = _to_money(contract.get("月度上限"))
        return gross, ratio, deduction, net, cap

    def _term_problems(
        self, contract: dict[str, Any], net: float | None, cap: float | None
    ) -> list[str]:
        """按合同条款判定：扣款比例缺失、应结金额超月度上限，都给出拦截原因。"""
        problems: list[str] = []
        if _to_ratio(contract.get("扣款比例")) is None:
            problems.append(f"合同 {contract.get('合同编号')} 的扣款比例缺失，无法按合同条款计算扣款金额")
        if cap is None:
            problems.append(f"合同 {contract.get('合同编号')} 缺少月度上限条款")
        elif net is not None and net > cap:
            problems.append(
                f"应结金额 {_fmt(net)} 元超出合同月度上限 {_fmt(cap)} 元，"
                f"超出 {_fmt(round(net - cap, 2))} 元，不允许保存"
            )
        return problems

    def aggregate(self, entry_id: int, month: str) -> tuple[dict[str, Any] | None, str]:
        """汇总预览：只算不存，给双方对数用；被拦截时把原因一并带回。"""
        contract = store.find(MODULE, entry_id)
        if contract is None:
            return None, f"委外合同 {entry_id} 不存在或已归档"
        if not _valid_month(month):
            return None, f"结算月份「{month}」格式应为 2026-09 这样的年月"
        items = self.collect_workload(contract, month)
        suspended = contract.get("status") == "已暂停"
        for item in items:
            item["结算状态"] = "已挂起" if suspended else "待结算"
        gross, ratio, deduction, net, cap = self._build_amounts(contract, items)
        problems = self._term_problems(contract, net, cap)
        if suspended:
            problems.append(f"合同已暂停合作，{len(items)} 笔未结算工作量已挂起保留，恢复合作后再结算")
        if not items:
            problems.append(f"{month} 没有已完成且未结算的天窗或处置单")
        return {
            "合同编号": contract.get("合同编号"),
            "委外单位": contract.get("委外单位"),
            "合同状态": contract.get("status"),
            "结算月份": month,
            "明细": items,
            "天窗工作量": sum(1 for item in items if item["来源"] == "天窗"),
            "处置工作量": sum(1 for item in items if item["来源"] == "处置单"),
            "汇总金额": gross,
            "扣款比例": ratio,
            "扣款金额": deduction,
            "应结金额": net,
            "月度上限": cap,
            "可否保存": not problems,
            "拦截原因": problems,
        }, "汇总完成"

    # ---------- 结算单保存与核定 ----------

    def list_settlements(
        self,
        *,
        keyword: str | None = None,
        month: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        rows = store.rows(SETTLE_MODULE)
        if keyword:
            rows = [
                row for row in rows
                if keyword in str(row.get("结算单号", ""))
                or keyword in str(row.get("委外单位", ""))
                or keyword in str(row.get("合同编号", ""))
            ]
        if month:
            rows = [row for row in rows if row.get("结算月份") == month]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return rows[start:start + size], total

    def get_settlement(self, settle_id: int) -> dict[str, Any] | None:
        return store.find(SETTLE_MODULE, settle_id)

    def create_settlement(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        code = str(values.get("合同编号") or "").strip()
        month = str(values.get("结算月份") or "").strip()
        missing = []
        if not code:
            missing.append("合同编号")
        if not month:
            missing.append("结算月份")
        if missing:
            return None, [f"缺少必填字段：{'、'.join(missing)}"]
        if not _valid_month(month):
            return None, [f"结算月份「{month}」格式应为 2026-09 这样的年月"]
        contract = self.find_contract_by_code(code)
        if contract is None:
            return None, [f"合同 {code} 不存在，请先登记委外合同"]
        items = self.collect_workload(contract, month)
        if contract.get("status") == "已暂停":
            return None, [
                f"合同 {code} 已暂停合作，{len(items)} 笔未结算工作量已挂起保留，恢复合作后再结算"
            ]
        for row in store.rows(SETTLE_MODULE):
            if (
                row.get("合同编号") == code
                and row.get("结算月份") == month
                and row.get("status") != "已作废"
            ):
                return None, [f"合同 {code} 在 {month} 已有结算单 {row.get('结算单号')}（{row.get('status')}），请勿重复汇总"]
        if not items:
            return None, [f"合同 {code} 在 {month} 没有已完成且未结算的天窗或处置单"]
        gross, ratio, deduction, net, cap = self._build_amounts(contract, items)
        problems = self._term_problems(contract, net, cap)
        if problems:
            return None, problems
        declared_raw = values.get("申报金额")
        declared = _to_money(declared_raw)
        if declared_raw is not None and str(declared_raw).strip():
            if declared is None:
                return None, ["申报金额不是有效数字，请按群里对数的金额填写"]
            if net is not None and abs(declared - net) > MONEY_TOLERANCE:
                return None, [
                    f"申报金额 {_fmt(declared)} 元与按合同条款汇总的应结金额 {_fmt(net)} 元对不上，"
                    f"差额 {_fmt(round(declared - net, 2))} 元，请核对工作量与扣款比例后再保存"
                ]
        rows = store.rows(SETTLE_MODULE)
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        entry: dict[str, Any] = {
            "id": next_id,
            "结算单号": f"SETL-{month}-{next_id:04d}",
            "合同编号": code,
            "委外单位": contract.get("委外单位"),
            "结算月份": month,
            "天窗工作量": sum(1 for item in items if item["来源"] == "天窗"),
            "处置工作量": sum(1 for item in items if item["来源"] == "处置单"),
            "工作量明细": items,
            "汇总金额": gross,
            "扣款比例": ratio,
            "扣款金额": deduction,
            "应结金额": net,
            "月度上限": cap,
            "申报金额": declared,
            "status": "待核定",
            "pending": True,
            "abnormal": False,
            "核定时间": None,
            "备注": str(values.get("备注") or ""),
        }
        rows.append(entry)
        return entry, []

    def run_settle_action(self, settle_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(SETTLE_MODULE, settle_id)
        if entry is None:
            return None, f"结算单 {settle_id} 不存在或已归档"
        if action not in SETTLE_ACTIONS:
            return None, f"动作「{action}」不属于委外结算可执行范围"
        status = str(entry.get("status") or "")
        if status == "已核定":
            return None, f"结算单 {entry.get('结算单号')} 已核定，核定结果已固化，刷新与重复操作都不会改变"
        if status == "已作废":
            return None, f"结算单 {entry.get('结算单号')} 已作废，不能再执行{action}"
        if action == "作废":
            entry["status"] = "已作废"
            entry["pending"] = False
            entry["abnormal"] = False
            return entry, f"结算单 {entry.get('结算单号')} 已作废，工作量可重新汇总"
        # 以下为核定：先把挂起与合同状态拦住，再按合同条款复核金额。
        if status == "已挂起":
            return None, f"合同暂停合作中，结算单 {entry.get('结算单号')} 已挂起，恢复合作后再核定"
        contract = self.find_contract_by_code(str(entry.get("合同编号") or ""))
        if contract is None:
            return None, f"结算单关联的合同 {entry.get('合同编号')} 不存在，不能核定"
        if contract.get("status") == "已暂停":
            return None, "合同已暂停合作，结算单已挂起，恢复合作后再核定"
        problems = self._recheck_settlement(entry, contract)
        if problems:
            return None, "核定前复核发现金额与合同条款对不上：" + "；".join(problems) + "，请作废后重新汇总"
        entry["status"] = "已核定"
        entry["pending"] = False
        entry["abnormal"] = False
        entry["核定时间"] = date.today().isoformat()
        return entry, f"结算单 {entry.get('结算单号')} 已核定，应结金额 {_fmt(entry.get('应结金额'))} 元，结果已固化"

    def _recheck_settlement(self, entry: dict[str, Any], contract: dict[str, Any]) -> list[str]:
        """核定前复核：单据还在、状态没变、单价与扣款比例算出来的金额和结算单一致、没超上限。"""
        problems: list[str] = []
        items = entry.get("工作量明细") or []
        refs = self._settled_refs()
        prices = {"天窗": _to_money(contract.get("天窗单价")), "处置单": _to_money(contract.get("处置单价"))}
        done_status = {"天窗": "已销记", "处置单": "已验收"}
        modules = {"天窗": WINDOW_MODULE, "处置单": DISPOSE_MODULE}
        gross = 0.0
        for item in items:
            source = str(item.get("来源"))
            doc_no = item.get("单号")
            row = store.find(modules.get(source, ""), int(item.get("单据id", 0)))
            if row is None:
                problems.append(f"单据 {doc_no} 已不存在")
                continue
            if row.get("status") != done_status.get(source):
                problems.append(f"单据 {doc_no} 状态已变为「{row.get('status')}」，不再是已完成")
            if (source, int(item.get("单据id", 0))) in refs:
                problems.append(f"单据 {doc_no} 已在其他结算单中核定，不能重复结算")
            price = prices.get(source)
            if price is None:
                problems.append(f"合同缺少{source}结算单价")
                continue
            expect = round(float(item.get("工作量", 1)) * price, 2)
            if abs(expect - float(item.get("金额", 0))) > MONEY_TOLERANCE:
                problems.append(f"单据 {doc_no} 按合同单价应为 {_fmt(expect)} 元，结算单上是 {_fmt(_to_money(item.get('金额')))} 元")
            gross = round(gross + expect, 2)
        ratio = _to_ratio(contract.get("扣款比例"))
        if ratio is None:
            problems.append("合同扣款比例缺失，无法复核扣款金额")
            return problems
        deduction = round(gross * ratio, 2)
        net = round(gross - deduction, 2)
        if abs(gross - float(entry.get("汇总金额", 0))) > MONEY_TOLERANCE:
            problems.append(f"汇总金额重算为 {_fmt(gross)} 元，与结算单 {_fmt(_to_money(entry.get('汇总金额')))} 元不一致")
        if abs(net - float(entry.get("应结金额", 0))) > MONEY_TOLERANCE:
            problems.append(f"应结金额重算为 {_fmt(net)} 元，与结算单 {_fmt(_to_money(entry.get('应结金额')))} 元不一致")
        cap = _to_money(contract.get("月度上限"))
        if cap is None:
            problems.append("合同缺少月度上限条款")
        elif net > cap:
            problems.append(f"应结金额 {_fmt(net)} 元超出合同月度上限 {_fmt(cap)} 元")
        return problems
