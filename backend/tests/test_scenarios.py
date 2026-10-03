"""Independent acceptance expectations for the companion scenario matrix."""
import unittest
from travel_agent.core import Claim, PolicyEvaluator, fingerprint
from travel_agent.demo_data import DEMO_CLAIMS


EXPECTED = [
    ('APPROVE',180,0), ('APPROVE',465,0), ('APPROVE',720,0),
    ('PARTIAL_APPROVE',150,60), ('PARTIAL_APPROVE',400,160), ('PARTIAL_APPROVE',100,80),
    ('REJECT',0,65), ('REJECT',0,135),
    ('MANUAL_REVIEW',0,0), ('MANUAL_REVIEW',0,0), ('MANUAL_REVIEW',0,0), ('MANUAL_REVIEW',0,0),
    ('MANUAL_REVIEW',0,0), ('MANUAL_REVIEW',0,0), ('APPROVE',125,0), ('APPROVE',25,0),
    ('MANUAL_REVIEW',0,0), ('MANUAL_REVIEW',0,0), ('MANUAL_REVIEW',0,0), ('MANUAL_REVIEW',0,0),
    ('MANUAL_REVIEW',0,0), ('MANUAL_REVIEW',0,0), ('APPROVE',500,0), ('APPROVE',500.01,0),
    ('APPROVE',2000,0), ('MANUAL_REVIEW',0,0), ('PARTIAL_APPROVE',120,40), ('PARTIAL_APPROVE',75,20),
]


class ScenarioTests(unittest.TestCase):
    def test_all_28_independent_expectations_and_reconciliation(self):
        self.assertEqual(len(DEMO_CLAIMS), len(EXPECTED))
        before = fingerprint(DEMO_CLAIMS)
        for raw, expected in zip(DEMO_CLAIMS, EXPECTED):
            with self.subTest(claim=raw['claim_id']):
                evaluation = PolicyEvaluator().evaluate(Claim.model_validate(raw))
                result = evaluation['result']
                self.assertEqual((result.decision.value, float(result.approved_amount), float(result.deducted_amount)), expected)
                pending = evaluation['pending_amount']
                self.assertAlmostEqual(float(result.approved_amount + result.deducted_amount) + pending, float(raw['total_claimed']))
        self.assertEqual(fingerprint(DEMO_CLAIMS), before)

