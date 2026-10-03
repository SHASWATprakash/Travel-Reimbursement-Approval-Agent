"""Entirely synthetic companion fixtures; independent of Appendix B."""
from copy import deepcopy
from decimal import Decimal


def expense(category="conference_fees", amount="150.00", receipt=True, **fields):
    return {"item_id": "E1", "category": category, "description": f"Synthetic {category.replace('_', ' ')} expense",
            "amount": str(amount), "receipt_attached": receipt, **fields}


SCENARIOS = [
    ("Compliant conference", [expense(amount="180.00")], {}),
    ("Economy airfare with receipt", [expense("airfare", "465.00", airfare_class="economy")], {}),
    ("Manager-tier lodging within cap", [expense("lodging", "720.00", units=4)], {}),
    ("Meal daily cap exceeded", [expense("meals", "210.00", units=2)], {}),
    ("Hotel nightly cap exceeded", [expense("lodging", "560.00", units=2)], {}),
    ("Ground transport cap exceeded", [expense("ground_transport", "180.00", units=2)], {}),
    ("Alcohol is ineligible", [expense("alcohol", "65.00")], {}),
    ("Personal shopping is ineligible", [expense("personal_shopping", "135.00")], {"business_documented": False}),
    ("Missing airfare receipt", [expense("airfare", "340.00", False, airfare_class="economy")], {}),
    ("Missing hotel receipt", [expense("lodging", "190.00", False, units=1)], {}),
    ("Business-class exception", [expense("airfare", "1450.00", airfare_class="business")], {}),
    ("First-class exception", [expense("airfare", "1725.00", airfare_class="first")], {}),
    ("Director approval threshold", [expense(amount="2450.00")], {}),
    ("Late submission", [expense(amount="125.00", expense_date="2026-07-10")], {"submitted": "2026-08-10"}),
    ("Exactly 30-day submission", [expense(amount="125.00", expense_date="2026-07-10")], {"submitted": "2026-08-09"}),
    ("Receipt boundary: exactly $25", [expense("meals", "25.00", False, units=1)], {}),
    ("Receipt boundary: $25.01", [expense("meals", "25.01", False, units=1)], {}),
    ("Missing expense allocation", [expense("meals", "140.00")], {}),
    ("Conflicting hotel duration", [expense("lodging", "900.00", units=6)], {}),
    ("Unknown category", [expense("unclassified", "90.00")], {}),
    ("Business purpose undocumented", [expense(amount="175.00")], {"business_documented": False}),
    ("Non-itemized receipt", [expense(amount="85.00", receipt_itemized=False)], {}),
    ("Auto-approval boundary: $500", [expense(amount="500.00")], {}),
    ("Manager boundary: $500.01", [expense(amount="500.01")], {}),
    ("Manager boundary: $2,000", [expense(amount="2000.00")], {}),
    ("Director boundary: $2,000.01", [expense(amount="2000.01")], {}),
    ("Mixed eligible and ineligible items", [expense(amount="120.00"), {**expense("minibar", "40.00"), "item_id": "E2"}], {}),
    ("Same-day meals share a cap", [expense("meals", "45.00", expense_date="2026-07-10"), {**expense("meals", "50.00", expense_date="2026-07-10"), "item_id": "E2"}], {}),
]

DEMO_CLAIMS = []
SCENARIO_LABELS = {}
for index, (label, items, overrides) in enumerate(SCENARIOS, 1):
    claim_id = f"DEMO-{index:03d}"
    raw = {"claim_id": claim_id, "employee": f"Synthetic Employee {index:02d}", "purpose": label,
           "business_documented": True, "trip_start": "2026-07-10", "trip_end": "2026-07-14",
           "submitted": "2026-07-20", "currency": "USD",
           "total_claimed": str(sum(Decimal(i["amount"]) for i in items)), "items": deepcopy(items), **overrides}
    DEMO_CLAIMS.append(raw)
    SCENARIO_LABELS[claim_id] = label
