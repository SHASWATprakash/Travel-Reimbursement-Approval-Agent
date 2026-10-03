from __future__ import annotations

import asyncio
import copy
import hashlib
import html
import json
import os
import re
import time
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import Enum
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

POLICIES = {
    "POL-CAT-01": "Eligible categories — Reimbursable when incurred for a documented business purpose: Airfare (economy class only — see POL-AIR-01); Lodging (hotel room charges); Meals (subject to per-diem limits — see POL-PD-01); Ground transport (taxi, rideshare, train, rental car, parking); Conference / registration fees.",
    "POL-CAT-02": "Ineligible items — Never reimbursable; rejected (deducted in full): Alcohol and minibar charges; Spa, gym, and personal entertainment; In-room movies, personal shopping, gifts; Traffic fines, penalties, and late fees; Any personal (non-business) expense.",
    "POL-PD-01": "Meals — Maximum $75 per day. Amounts above the daily cap are deducted; the rest is reimbursed.",
    "POL-PD-02": "Lodging — Maximum $200 per night. Amounts above the nightly cap are deducted; the rest is reimbursed.",
    "POL-PD-03": "Ground transport — Maximum $50 per day. Amounts above the cap are deducted.",
    "POL-AIR-01": "Airfare class — Only economy class airfare is reimbursable. Business/first-class fares are a policy exception and must be routed to Manual Review (not auto-deducted, because a pre-approval may exist).",
    "POL-RCT-01": "Receipt required above $25 — Any single line item greater than $25 requires an attached, itemized receipt. Airfare and lodging always require a receipt regardless of amount.",
    "POL-RCT-02": "Missing receipt handling — If a receipt is missing for an item that requires one, the item is not silently rejected — the claim is routed to Manual Review so the reviewer can request the receipt.",
    "POL-APR-01": "Auto-approve tier — Total ≤ $500: may be auto-approved by the agent if fully compliant.",
    "POL-APR-02": "Manager tier — Total > $500 and ≤ $2,000: eligible for approval, treated as approvable when fully compliant.",
    "POL-APR-03": "Director / Manual-Review tier — Total > $2,000: exceeds the agent's auto-approval authority and must be routed to Manual Review (director approval required), even if otherwise compliant.",
    "POL-TIME-01": "Submission window — Claims must be submitted within 30 days of the expense date. Late claims are routed to Manual Review.",
}
DECISION_GUIDANCE = "Approve: every item eligible, all receipts present, all within per-diem, total within an approvable tier. Partially Approve: claim valid but some amounts exceed caps; reimburse up to the cap. Reject: items ineligible with nothing reimbursable. Manual Review: any ambiguity, policy exception, high value, missing required receipt, or conflicting information. Prefer Manual Review over forcing a decision. Approval thresholds use reimbursable amounts after deductions."
LIMIT_TABLE = {"meals": {"amount": "75.00", "unit": "day", "ref": "POL-PD-01"}, "lodging": {"amount": "200.00", "unit": "night", "ref": "POL-PD-02"}, "ground_transport": {"amount": "50.00", "unit": "day", "ref": "POL-PD-03"}}
SAMPLE_CLAIMS = [
    {"claim_id": "CLM-001", "employee": "A. Rivera", "purpose": "Attend 2-day industry conference (business)", "business_documented": True, "trip_start": "2026-06-10", "trip_end": "2026-06-12", "submitted": "2026-06-20", "total_claimed": "1110.00", "currency": "USD", "items": [
        {"item_id": "I1", "category": "airfare", "description": "Round-trip economy airfare", "amount": "420.00", "receipt_attached": True, "airfare_class": "economy"},
        {"item_id": "I2", "category": "lodging", "description": "Hotel, 2 nights @ $180", "amount": "360.00", "receipt_attached": True, "units": 2},
        {"item_id": "I3", "category": "meals", "description": "Meals, 3 days @ ~$60/day", "amount": "180.00", "receipt_attached": True, "units": 3},
        {"item_id": "I4", "category": "conference_fees", "description": "Conference registration", "amount": "150.00", "receipt_attached": True}]},
    {"claim_id": "CLM-002", "employee": "B. Osei", "purpose": "Weekend hotel stay", "business_documented": False, "trip_start": "2026-06-14", "trip_end": "2026-06-15", "submitted": "2026-06-25", "total_claimed": "380.00", "currency": "USD", "items": [
        {"item_id": "I1", "category": "spa", "description": "Hotel spa package", "amount": "300.00", "receipt_attached": True},
        {"item_id": "I2", "category": "minibar", "description": "In-room minibar", "amount": "80.00", "receipt_attached": True}]},
    {"claim_id": "CLM-003", "employee": "C. Nakamura", "purpose": "Client site visit (business)", "business_documented": True, "trip_start": "2026-06-08", "trip_end": "2026-06-10", "submitted": "2026-06-22", "total_claimed": "940.00", "currency": "USD", "items": [
        {"item_id": "I1", "category": "airfare", "description": "Round-trip economy airfare", "amount": "300.00", "receipt_attached": True, "airfare_class": "economy"},
        {"item_id": "I2", "category": "lodging", "description": "Hotel, 2 nights @ $250", "amount": "500.00", "receipt_attached": True, "units": 2},
        {"item_id": "I3", "category": "meals", "description": "Meals, 2 days @ $70/day", "amount": "140.00", "receipt_attached": True, "units": 2}]},
    {"claim_id": "CLM-004", "employee": "D. Fischer", "purpose": "International vendor negotiation (business)", "business_documented": True, "trip_start": "2026-06-16", "trip_end": "2026-06-18", "submitted": "2026-06-28", "total_claimed": "3000.00", "currency": "USD", "items": [
        {"item_id": "I1", "category": "airfare", "description": "Business-class international airfare", "amount": "2400.00", "receipt_attached": True, "airfare_class": "business"},
        {"item_id": "I2", "category": "lodging", "description": "Hotel, 3 nights", "amount": "600.00", "receipt_attached": False, "units": 3}]},
    {"claim_id": "CLM-005", "employee": "E. Haddad", "purpose": "Client dinner / business development", "business_documented": True, "trip_start": "2026-06-11", "trip_end": "2026-06-11", "submitted": "2026-06-24", "total_claimed": "220.00", "currency": "USD", "items": [
        {"item_id": "I1", "category": "meals", "description": "Client dinner for 4 (business development)", "amount": "220.00", "receipt_attached": False, "units": 1}]},
]

CENT = Decimal("0.01")


def money(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("Boolean is not a monetary amount")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("Invalid monetary amount") from None
    if not result.is_finite() or result < 0 or result > 10000000:
        raise ValueError("USD amount must be finite, non-negative and have at most two decimal places")
    try:
        rounded = result.quantize(CENT)
    except InvalidOperation:
        raise ValueError("Invalid monetary precision") from None
    if result != rounded:
        raise ValueError("USD amount must have at most two decimal places")
    return rounded


def jsonable(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return jsonable(value.model_dump())
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    return value


def fingerprint(value: Any) -> str:
    return hashlib.sha256(json.dumps(jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Expense(StrictModel):
    item_id: str = Field(min_length=1, max_length=40)
    category: str = Field(min_length=1, max_length=60)
    description: str = Field(min_length=1, max_length=1000)
    amount: Decimal = Field(gt=0)
    receipt_attached: bool = Field(strict=True)
    receipt_itemized: bool = Field(default=True, strict=True)  # Appendix B's Yes is assumed itemized, not OCR-verified.
    units: int | None = Field(default=None, ge=1, le=366, strict=True)
    expense_date: date | None = None
    airfare_class: Literal["economy", "business", "first"] | None = None
    _amount = field_validator("amount", mode="before")(money)


class Claim(StrictModel):
    claim_id: str = Field(min_length=1, max_length=60, pattern=r"^[A-Za-z0-9_-]+$")
    employee: str = Field(min_length=1, max_length=100)
    purpose: str = Field(min_length=1, max_length=2000)
    business_documented: bool = Field(strict=True)
    trip_start: date
    trip_end: date
    submitted: date
    currency: Literal["USD"] = "USD"
    total_claimed: Decimal = Field(gt=0)
    items: list[Expense] = Field(min_length=1, max_length=50)
    _total = field_validator("total_claimed", mode="before")(money)

    @model_validator(mode="after")
    def unique_items(self):
        if len({x.item_id for x in self.items}) != len(self.items):
            raise ValueError("Each item_id must be unique within its claim")
        return self


class Decision(str, Enum):
    APPROVE = "APPROVE"
    PARTIAL_APPROVE = "PARTIAL_APPROVE"
    REJECT = "REJECT"
    MANUAL_REVIEW = "MANUAL_REVIEW"


REASON_CODES = frozenset({
    "POLICY_COMPLIANT", "LIMIT_EXCEEDED", "INELIGIBLE_EXPENSE",
    "RECEIPT_MISSING", "AIRFARE_CLASS_EXCEPTION", "DIRECTOR_APPROVAL_REQUIRED",
    "LATE_SUBMISSION", "CONFLICTING_INFORMATION", "POLICY_AMBIGUITY",
    "MODEL_UNAVAILABLE", "OUTPUT_VALIDATION_FAILED",
})


class ClaimResult(StrictModel):
    claim_id: str
    decision: Decision
    approved_amount: Decimal
    deducted_amount: Decimal
    missing_docs: list[str]
    policy_refs: list[str]
    confidence: float = Field(ge=0, le=1)
    explanation: str = Field(min_length=1, max_length=12000)
    tools_used: list[str]
    _amounts = field_validator("approved_amount", "deducted_amount", mode="before")(money)


class Finding(StrictModel):
    code: str
    message: str
    policy_refs: list[str]
    item_ids: list[str] = Field(default_factory=list)
    review: bool = False


def finding(code: str, message: str, refs: list[str], items: list[str] | None = None, review: bool = False) -> dict:
    if code not in REASON_CODES or not set(refs).issubset(POLICIES):
        raise ValueError("Unknown reason code or policy citation")
    return Finding(code=code, message=message, policy_refs=refs, item_ids=items or [], review=review).model_dump()


class PolicyRepository:
    """Explicit lookup is sufficient for twelve fixed rules; no vector database."""
    def __init__(self):
        self.rules = dict(POLICIES)
        self.version = fingerprint({"rules": self.rules, "limits": LIMIT_TABLE, "guidance": DECISION_GUIDANCE})

    def lookup(self, refs: list[str] | None = None) -> dict:
        refs = list(self.rules) if refs is None else refs
        if any(ref not in self.rules for ref in refs):
            raise ValueError("Unknown policy reference")
        return {"policy_version": self.version, "rules": {ref: self.rules[ref] for ref in refs}, "decision_guidance": DECISION_GUIDANCE}

class PolicyEvaluator:
    ELIGIBLE = {"airfare", "lodging", "meals", "ground_transport", "conference_fees"}
    INELIGIBLE = {"alcohol", "minibar", "spa", "gym", "personal_entertainment", "in_room_movies", "personal_shopping", "gifts", "traffic_fines", "penalties", "late_fees", "personal"}

    def __init__(self, repository: PolicyRepository | None = None):
        self.repository = repository or PolicyRepository()

    def check_eligibility(self, claim: Claim) -> dict:
        findings = []
        for item in claim.items:
            if item.category in self.INELIGIBLE:
                findings.append(finding("INELIGIBLE_EXPENSE", f"{item.item_id}: {item.category} is deducted in full (${item.amount:.2f}).", ["POL-CAT-02"], [item.item_id]))
            elif item.category not in self.ELIGIBLE:
                findings.append(finding("POLICY_AMBIGUITY", f"{item.item_id}: category '{item.category}' is not resolved by the policy.", ["POL-CAT-01", "POL-CAT-02"], [item.item_id], True))
            else:
                if not claim.business_documented:
                    findings.append(finding("POLICY_AMBIGUITY", f"{item.item_id}: documented business purpose is missing.", ["POL-CAT-01"], [item.item_id], True))
                if item.category == "airfare":
                    if item.airfare_class in {"business", "first"}:
                        findings.append(finding("AIRFARE_CLASS_EXCEPTION", f"{item.item_id}: {item.airfare_class}-class airfare requires checking pre-approval; do not automatically deduct it.", ["POL-AIR-01"], [item.item_id], True))
                    elif item.airfare_class is None:
                        findings.append(finding("POLICY_AMBIGUITY", f"{item.item_id}: airfare class is unspecified.", ["POL-AIR-01"], [item.item_id], True))
                    elif re.search(r"\b(business.class|first.class)\b", item.description, re.I):
                        findings.append(finding("CONFLICTING_INFORMATION", f"{item.item_id}: description conflicts with economy-class metadata.", ["POL-AIR-01"], [item.item_id], True))
        refs = []
        if any(i.category in self.ELIGIBLE or i.category not in self.INELIGIBLE for i in claim.items):
            refs.append("POL-CAT-01")
        if any(i.category not in self.ELIGIBLE for i in claim.items):
            refs.append("POL-CAT-02")
        if any(i.category == "airfare" for i in claim.items):
            refs.append("POL-AIR-01")
        return {"findings": findings, "policy_refs": refs}

    def check_receipts(self, claim: Claim) -> dict:
        findings, missing = [], []
        for item in claim.items:
            if item.amount > 25 or item.category in {"airfare", "lodging"}:
                if not item.receipt_attached or not item.receipt_itemized:
                    doc = f"{item.item_id}: itemized {item.category} receipt"
                    missing.append(doc)
                    findings.append(finding("RECEIPT_MISSING", f"{doc} is required and {'missing' if not item.receipt_attached else 'not itemized'}; request it before deciding.", ["POL-RCT-01", "POL-RCT-02"], [item.item_id], True))
        return {"missing_docs": missing, "findings": findings, "policy_refs": ["POL-RCT-01"] + (["POL-RCT-02"] if missing else [])}

    def calculate_limits(self, claim: Claim) -> dict:
        findings, lines, groups = [], [], defaultdict(list)
        trip_days = (claim.trip_end - claim.trip_start).days + 1
        for item in claim.items:
            eligible = item.category in self.ELIGIBLE
            limit = LIMIT_TABLE.get(item.category)
            permitted = item.amount if eligible or item.category not in self.INELIGIBLE else Decimal(0)
            line = {"item_id": item.item_id, "category": item.category, "claimed": item.amount, "provisional_allowed": permitted, "provisional_deducted": item.amount - permitted, "policy_refs": ["POL-CAT-02"] if item.category in self.INELIGIBLE else []}
            lines.append(line)
            if limit:
                units = item.units or (1 if item.expense_date else None)
                if units is None:
                    findings.append(finding("POLICY_AMBIGUITY", f"{item.item_id}: number of {limit['unit']}s is missing; no cap is invented.", [limit["ref"]], [item.item_id], True))
                    continue
                maximum_units = max(0, trip_days - 1) if item.category == "lodging" else trip_days
                if units > maximum_units:
                    findings.append(finding("CONFLICTING_INFORMATION", f"{item.item_id}: stated {units} {limit['unit']}(s) exceed the trip's {maximum_units}; retain the supplied count and verify dates.", [limit["ref"]], [item.item_id], True))
                if item.expense_date and units > 1:
                    findings.append(finding("POLICY_AMBIGUITY", f"{item.item_id}: a multi-day amount needs a dated breakdown.", [limit["ref"]], [item.item_id], True))
                groups[(item.category, item.expense_date)].append((item, line, units))
        for (category, expense_date), grouped in groups.items():
            limit = LIMIT_TABLE[category]
            # Separate undated aggregate rows may overlap. Do not multiply caps per row.
            if expense_date is None and len(grouped) > 1:
                findings.append(finding("POLICY_AMBIGUITY", f"Multiple undated {category} rows may overlap; request daily/nightly allocation.", [limit["ref"]], [x[0].item_id for x in grouped], True))
                continue
            units = grouped[0][2] if expense_date is None else 1
            remaining = Decimal(limit["amount"]) * units
            for item, line, _ in grouped:
                allowed = min(item.amount, max(Decimal(0), remaining))
                remaining -= allowed
                excess = item.amount - allowed
                line.update(provisional_allowed=allowed, provisional_deducted=excess, policy_refs=[limit["ref"]])
                if excess:
                    findings.append(finding("LIMIT_EXCEEDED", f"{item.item_id}: ${item.amount:.2f} claimed; ${allowed:.2f} allowed after the ${limit['amount']} per-{limit['unit']} cap; ${excess:.2f} excess.", [limit["ref"]], [item.item_id]))
        for category in LIMIT_TABLE:
            category_items = [i for i in claim.items if i.category == category]
            if any(i.expense_date is None for i in category_items) and any(i.expense_date is not None for i in category_items):
                findings.append(finding("POLICY_AMBIGUITY", f"Dated and undated {category} rows may overlap; obtain a daily/nightly breakdown before applying caps.", [LIMIT_TABLE[category]["ref"]], [i.item_id for i in category_items], True))
        return jsonable({"lines": lines, "provisional_allowed": sum(x["provisional_allowed"] for x in lines), "provisional_deducted": sum(x["provisional_deducted"] for x in lines), "findings": findings, "policy_refs": sorted({r for x in lines for r in x["policy_refs"]})})

    def check_timeliness(self, claim: Claim) -> dict:
        findings = []
        if claim.trip_end < claim.trip_start:
            findings.append(finding("CONFLICTING_INFORMATION", "Trip end precedes trip start.", ["POL-TIME-01"], review=True))
        if sum(x.amount for x in claim.items) != claim.total_claimed:
            findings.append(finding("CONFLICTING_INFORMATION", "Declared total does not equal the sum of line items; reconcile the claim.", [], review=True))
        for item in claim.items:
            start = item.expense_date or claim.trip_start
            end = item.expense_date or claim.trip_end
            if claim.submitted < end:
                findings.append(finding("CONFLICTING_INFORMATION", f"{item.item_id}: submission predates the stated expense interval.", ["POL-TIME-01"], [item.item_id], True))
            elif (claim.submitted - end).days > 30:
                findings.append(finding("LATE_SUBMISSION", f"{item.item_id}: even the latest possible expense date is more than 30 days before submission.", ["POL-TIME-01"], [item.item_id], True))
            elif (claim.submitted - start).days > 30:
                findings.append(finding("POLICY_AMBIGUITY", f"{item.item_id}: trip interval crosses the 30-day deadline; obtain exact expense date.", ["POL-TIME-01"], [item.item_id], True))
        return {"findings": findings, "policy_refs": ["POL-TIME-01"]}

    def check_approval_threshold(self, claim: Claim) -> dict:
        limits = self.calculate_limits(claim)
        eligibility = self.check_eligibility(claim)
        unresolved = any(f["review"] for f in eligibility["findings"] + limits["findings"])
        amount = money(limits["provisional_allowed"])
        if unresolved:
            return {"tier": "UNRESOLVED", "candidate_amount": float(amount), "findings": [], "policy_refs": [], "note": "Provisional amount depends on unresolved eligibility or limits; do not infer director authority from gross claim amount."}
        ref = "POL-APR-01" if amount <= 500 else "POL-APR-02" if amount <= 2000 else "POL-APR-03"
        findings = [finding("DIRECTOR_APPROVAL_REQUIRED", f"Reimbursable amount ${amount:.2f} exceeds $2,000; director approval required.", [ref], review=True)] if amount > 2000 else []
        return {"tier": {"POL-APR-01": "AUTO", "POL-APR-02": "MANAGER", "POL-APR-03": "DIRECTOR"}[ref], "candidate_amount": float(amount), "findings": findings, "policy_refs": [ref]}

    def evaluate(self, claim: Claim) -> dict:
        policy_context = self.repository.lookup()
        evidence = {name: getattr(self, name)(claim) for name in CHECK_NAMES}
        findings = [f for block in evidence.values() for f in block["findings"]]
        refs = sorted({r for block in evidence.values() for r in block["policy_refs"]} | {r for f in findings for r in f["policy_refs"]})
        limits = evidence["calculate_limits"]
        review = any(f["review"] for f in findings)
        allowed, deducted = money(limits["provisional_allowed"]), money(limits["provisional_deducted"])
        decision = Decision.MANUAL_REVIEW if review else Decision.REJECT if allowed == 0 else Decision.PARTIAL_APPROVE if deducted else Decision.APPROVE
        if decision == Decision.APPROVE:
            findings.append(finding("POLICY_COMPLIANT", f"All items are eligible, documented, timely and within limits; ${allowed:.2f} is approvable in the {evidence['check_approval_threshold']['tier'].lower()} tier.", refs))
        sentences = [f"{f['code']}: {f['message']}" + (f" ({', '.join(f['policy_refs'])})" if f["policy_refs"] else "") for f in findings]
        if review:
            sentences.append(f"The full ${claim.total_claimed:.2f} remains pending; approved and deducted amounts are both zero until review. Calculated allowances are provisional.")
        elif decision != Decision.APPROVE:
            sentences.append(f"Final recommendation: {decision.value}; ${allowed:.2f} approved and ${deducted:.2f} deducted. Supporting checks: {', '.join(refs)}.")
        ambiguous = any(f["code"] in {"POLICY_AMBIGUITY", "CONFLICTING_INFORMATION"} for f in findings)
        result = ClaimResult(claim_id=claim.claim_id, decision=decision, approved_amount=0 if review else allowed, deducted_amount=0 if review else deducted, missing_docs=evidence["check_receipts"]["missing_docs"], policy_refs=refs, confidence=0.70 if ambiguous else 0.95, explanation=" ".join(sentences), tools_used=list(TOOL_NAMES))
        return {"result": result, "policy_context": policy_context, "findings": findings, "checks": evidence, "lines": limits["lines"], "pending_amount": float(claim.total_claimed) if review else 0, "reason_codes": sorted({f["code"] for f in findings})}


CHECK_NAMES = ("check_eligibility", "check_receipts", "calculate_limits", "check_approval_threshold", "check_timeliness")
TOOL_NAMES = ("lookup_policy",) + CHECK_NAMES
