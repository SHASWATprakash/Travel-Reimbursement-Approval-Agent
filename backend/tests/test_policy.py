from travel_agent.core import *

import io
import unittest


class PolicyTests(unittest.TestCase):
    """Controlled variants test rules; SAMPLE_CLAIMS remains the only demo dataset."""
    def setUp(self):
        self.evaluator = PolicyEvaluator()

    def single(self, category="conference_fees", amount="75.00", receipt=True, **item_fields):
        raw = copy.deepcopy(SAMPLE_CLAIMS[0])
        item = {"item_id": "I1", "category": category, "description": "Boundary variation of the supplied claim", "amount": amount, "receipt_attached": receipt}
        item.update(item_fields)
        raw.update(items=[item], total_claimed=amount)
        return raw

    def evaluate(self, raw):
        return self.evaluator.evaluate(Claim.model_validate(raw))

    def assert_outcome(self, raw, decision, approved, deducted):
        evidence = self.evaluate(raw)
        result = evidence["result"]
        self.assertEqual(result.decision.value, decision)
        self.assertEqual(result.approved_amount, Decimal(str(approved)))
        self.assertEqual(result.deducted_amount, Decimal(str(deducted)))
        self.assertTrue(set(result.policy_refs).issubset(POLICIES))
        self.assertTrue(set(evidence["reason_codes"]).issubset(REASON_CODES))
        for code in evidence["reason_codes"]:
            self.assertIn(code + ":", result.explanation)
        for f in evidence["findings"]:
            for ref in f["policy_refs"]:
                self.assertIn(ref, result.policy_refs)
                self.assertIn(ref, result.explanation)
        self.assertEqual(result.tools_used, list(TOOL_NAMES))
        self.assertEqual(result.approved_amount + result.deducted_amount + money(evidence["pending_amount"]), money(raw["total_claimed"]))
        return evidence

    def test_all_five_supplied_results_and_exact_schema(self):
        expected = [("APPROVE", "1110", "0"), ("REJECT", "0", "380"), ("PARTIAL_APPROVE", "840", "100"), ("MANUAL_REVIEW", "0", "0"), ("MANUAL_REVIEW", "0", "0")]
        required = {"claim_id", "decision", "approved_amount", "deducted_amount", "missing_docs", "policy_refs", "confidence", "explanation", "tools_used"}
        for raw, outcome in zip(SAMPLE_CLAIMS, expected):
            with self.subTest(claim=raw["claim_id"]):
                evidence = self.assert_outcome(raw, *outcome)
                self.assertEqual(set(jsonable(evidence["result"])), required)
                self.assertEqual(jsonable(evidence["result"])["claim_id"], raw["claim_id"])

    def test_sample_monetary_reconciliation(self):
        evaluations = [self.evaluate(c) for c in SAMPLE_CLAIMS]
        self.assertEqual(sum(e["result"].approved_amount for e in evaluations), Decimal("1950.00"))
        self.assertEqual(sum(e["result"].deducted_amount for e in evaluations), Decimal("480.00"))
        self.assertEqual(sum(money(e["pending_amount"]) for e in evaluations), Decimal("3220.00"))

    def test_missing_receipt_names_and_manual_review_precedence(self):
        four, five = [self.evaluate(SAMPLE_CLAIMS[i]) for i in (3, 4)]
        self.assertEqual(four["result"].missing_docs, ["I2: itemized lodging receipt"])
        self.assertEqual(five["result"].missing_docs, ["I1: itemized meals receipt"])
        self.assertEqual(money(five["lines"][0]["provisional_deducted"]), Decimal("145"))
        self.assertEqual(five["result"].deducted_amount, 0)
        self.assertNotIn("POL-APR-03", four["result"].policy_refs)
        self.assertEqual(four["checks"]["check_approval_threshold"]["tier"], "UNRESOLVED")

    def test_receipt_threshold_is_strictly_above_25(self):
        self.assert_outcome(self.single(amount="25.00", receipt=False), "APPROVE", "25", "0")
        e = self.assert_outcome(self.single(amount="25.01", receipt=False), "MANUAL_REVIEW", "0", "0")
        self.assertIn("RECEIPT_MISSING", e["reason_codes"])

    def test_airfare_and_lodging_always_require_receipts(self):
        for category, fields in [("airfare", {"airfare_class": "economy"}), ("lodging", {"units": 1})]:
            with self.subTest(category=category):
                self.assert_outcome(self.single(category, "20", False, **fields), "MANUAL_REVIEW", "0", "0")

    def test_attached_non_itemized_receipt_requires_review(self):
        e = self.assert_outcome(self.single(receipt_itemized=False), "MANUAL_REVIEW", "0", "0")
        self.assertIn("not itemized", e["result"].explanation)

    def test_approval_boundaries(self):
        cases = [("500", "APPROVE", "AUTO"), ("500.01", "APPROVE", "MANAGER"), ("2000", "APPROVE", "MANAGER"), ("2000.01", "MANUAL_REVIEW", "DIRECTOR")]
        for amount, decision, tier in cases:
            with self.subTest(amount=amount):
                e = self.assert_outcome(self.single(amount=amount), decision, amount if decision == "APPROVE" else "0", "0")
                self.assertEqual(e["checks"]["check_approval_threshold"]["tier"], tier)

    def test_approval_threshold_uses_post_cap_amount(self):
        e = self.assert_outcome(self.single("lodging", "2500", units=2), "PARTIAL_APPROVE", "400", "2100")
        self.assertEqual(e["checks"]["check_approval_threshold"]["tier"], "AUTO")
        self.assertNotIn("DIRECTOR_APPROVAL_REQUIRED", e["reason_codes"])

    def test_category_caps_and_cent_boundaries(self):
        for category, cap in [("meals", Decimal("75")), ("lodging", Decimal("200")), ("ground_transport", Decimal("50"))]:
            for excess in (Decimal("0"), Decimal("0.01")):
                with self.subTest(category=category, excess=excess):
                    raw = self.single(category, str(cap + excess), units=1)
                    self.assert_outcome(raw, "APPROVE" if not excess else "PARTIAL_APPROVE", cap, excess)

    def test_category_specific_counts(self):
        e = self.evaluate(SAMPLE_CLAIMS[2])
        self.assertEqual([money(x["provisional_allowed"]) for x in e["lines"]], [Decimal("300"), Decimal("400"), Decimal("140")])

    def test_all_ineligible_categories_are_deducted(self):
        for category in PolicyEvaluator.INELIGIBLE:
            with self.subTest(category=category):
                self.assert_outcome(self.single(category, "10", False), "REJECT", "0", "10")

    def test_mixed_eligible_and_ineligible_items(self):
        raw = self.single(amount="100")
        raw["items"].append({"item_id": "I2", "category": "alcohol", "description": "Boundary variation", "amount": "10", "receipt_attached": False})
        raw["total_claimed"] = "110"
        self.assert_outcome(raw, "PARTIAL_APPROVE", "100", "10")

    def test_unknown_category_requires_review(self):
        e = self.assert_outcome(self.single("unrecognized_category"), "MANUAL_REVIEW", "0", "0")
        self.assertIn("POLICY_AMBIGUITY", e["reason_codes"])

    def test_missing_business_purpose_requires_review(self):
        raw = self.single()
        raw["business_documented"] = False
        self.assert_outcome(raw, "MANUAL_REVIEW", "0", "0")

    def test_airfare_classes_and_conflicting_description(self):
        for airfare_class in ("business", "first", None):
            with self.subTest(airfare_class=airfare_class):
                self.assert_outcome(self.single("airfare", "300", airfare_class=airfare_class), "MANUAL_REVIEW", "0", "0")
        raw = self.single("airfare", "300", airfare_class="economy", description="Business-class international airfare")
        e = self.assert_outcome(raw, "MANUAL_REVIEW", "0", "0")
        self.assertIn("CONFLICTING_INFORMATION", e["reason_codes"])

    def test_timeliness_30_and_31_days(self):
        for elapsed, decision in [(30, "APPROVE"), (31, "MANUAL_REVIEW")]:
            with self.subTest(elapsed=elapsed):
                raw = self.single(expense_date="2026-06-10")
                raw["submitted"] = "2026-07-10" if elapsed == 30 else "2026-07-11"
                self.assert_outcome(raw, decision, "75" if elapsed == 30 else "0", "0")

    def test_trip_interval_crossing_timeliness_boundary(self):
        raw = self.single()
        raw["submitted"] = "2026-07-11"
        e = self.assert_outcome(raw, "MANUAL_REVIEW", "0", "0")
        self.assertIn("POLICY_AMBIGUITY", e["reason_codes"])

    def test_all_possible_dates_late(self):
        raw = self.single()
        raw["submitted"] = "2026-07-13"
        e = self.assert_outcome(raw, "MANUAL_REVIEW", "0", "0")
        self.assertIn("LATE_SUBMISSION", e["reason_codes"])

    def test_submission_before_expense_and_reversed_trip(self):
        for changes in [{"submitted": "2026-06-09"}, {"trip_end": "2026-06-09"}]:
            with self.subTest(changes=changes):
                raw = self.single()
                raw.update(changes)
                e = self.assert_outcome(raw, "MANUAL_REVIEW", "0", "0")
                self.assertIn("CONFLICTING_INFORMATION", e["reason_codes"])

    def test_total_mismatch_requires_review(self):
        raw = self.single()
        raw["total_claimed"] = "76"
        e = self.assert_outcome(raw, "MANUAL_REVIEW", "0", "0")
        self.assertIn("CONFLICTING_INFORMATION", e["reason_codes"])

    def test_missing_or_conflicting_quantity(self):
        for fields in [{}, {"units": 4}, {"units": 2, "expense_date": "2026-06-10"}]:
            with self.subTest(fields=fields):
                self.assert_outcome(self.single("meals", "140", **fields), "MANUAL_REVIEW", "0", "0")

    def test_multiple_same_day_items_share_one_cap(self):
        raw = self.single("meals", "40", expense_date="2026-06-10")
        raw["items"].append({"item_id": "I2", "category": "meals", "description": "Boundary variation", "amount": "50", "receipt_attached": True, "expense_date": "2026-06-10"})
        raw["total_claimed"] = "90"
        self.assert_outcome(raw, "PARTIAL_APPROVE", "75", "15")

    def test_distinct_dated_days_receive_distinct_caps(self):
        raw = self.single("meals", "70", expense_date="2026-06-10")
        raw["items"].append({"item_id": "I2", "category": "meals", "description": "Boundary variation", "amount": "70", "receipt_attached": True, "expense_date": "2026-06-11"})
        raw["total_claimed"] = "140"
        self.assert_outcome(raw, "APPROVE", "140", "0")

    def test_overlapping_undated_rows_require_review(self):
        for dated_second in (False, True):
            with self.subTest(dated_second=dated_second):
                raw = self.single("meals", "70", units=1)
                item = {"item_id": "I2", "category": "meals", "description": "Boundary variation", "amount": "70", "receipt_attached": True, "units": 1}
                if dated_second:
                    item["expense_date"] = "2026-06-10"
                raw["items"].append(item)
                raw["total_claimed"] = "140"
                self.assert_outcome(raw, "MANUAL_REVIEW", "0", "0")

    def test_invalid_money_is_rejected(self):
        values = [True, None, "NaN", "Infinity", "-1", "0.001", "1e1000", "not-money", [], {}]
        for value in values:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    money(value)
        self.assertEqual(money("0.10") + money("0.20"), Decimal("0.30"))

    def test_zero_amount_and_non_boolean_flags_rejected(self):
        for raw in [self.single(amount="0"), self.single(receipt="yes"), self.single(units=True)]:
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    Claim.model_validate(raw)
        raw = self.single()
        raw["business_documented"] = "true"
        with self.assertRaises(ValueError):
            Claim.model_validate(raw)

    def test_extra_fields_currency_and_duplicate_items_rejected(self):
        for changes in [{"currency": "INR"}, {"unexpected_field": True}]:
            raw = self.single()
            raw.update(changes)
            with self.assertRaises(ValueError):
                Claim.model_validate(raw)
        raw = self.single()
        raw["items"].append(copy.deepcopy(raw["items"][0]))
        with self.assertRaises(ValueError):
            Claim.model_validate(raw)

    def test_unknown_citations_and_reason_codes_rejected(self):
        with self.assertRaises(ValueError):
            PolicyRepository().lookup(["POL-FAKE-01"])
        with self.assertRaises(ValueError):
            finding("FAKE_REASON", "bad", [])
        with self.assertRaises(ValueError):
            finding("POLICY_AMBIGUITY", "bad", ["POL-FAKE-01"])
        self.assertEqual(PolicyRepository().lookup([])["rules"], {})

    def test_confidence_is_evidence_strength_not_approval_probability(self):
        clear_review = self.evaluate(SAMPLE_CLAIMS[4])["result"]
        ambiguous_review = self.evaluate(SAMPLE_CLAIMS[3])["result"]
        self.assertEqual(clear_review.confidence, 0.95)
        self.assertEqual(ambiguous_review.confidence, 0.70)
        self.assertEqual(clear_review.decision, Decision.MANUAL_REVIEW)

    def test_input_and_policy_are_not_modified(self):
        before_claims, before_rules = fingerprint(SAMPLE_CLAIMS), fingerprint(POLICIES)
        for raw in SAMPLE_CLAIMS:
            self.evaluate(raw)
        self.assertEqual(fingerprint(SAMPLE_CLAIMS), before_claims)
        self.assertEqual(fingerprint(POLICIES), before_rules)
        self.assertEqual(PolicyRepository().version, PolicyRepository().version)

    def test_json_serialization_and_schema_validation(self):
        result = self.evaluate(SAMPLE_CLAIMS[2])["result"]
        exported = jsonable(result)
        self.assertEqual(ClaimResult.model_validate(exported), result)
        self.assertEqual(json.loads(json.dumps(exported))["approved_amount"], 840.0)
        self.assertEqual(jsonable((date(2026, 6, 10), Decision.APPROVE)), ["2026-06-10", "APPROVE"])


def run_policy_tests() -> dict:
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PolicyTests)
    report = unittest.TextTestRunner(stream=stream, verbosity=1).run(suite)
    print(stream.getvalue().strip())
    if not report.wasSuccessful():
        raise AssertionError("Policy acceptance checks failed")
    return {"test_methods": report.testsRun, "failures": len(report.failures), "errors": len(report.errors), "status": "PASS"}
