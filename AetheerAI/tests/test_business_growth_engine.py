"""
Tests for core/business_growth_engine.py.

Covers:
- Lead acquisition and deduplication
- Marketing automation cadence loop
- Conversion tracking and lifecycle transitions
- Revenue optimization action generation
- Persistence round-trip
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.business_growth_engine import BusinessGrowthEngine


class TestBusinessGrowthEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Path(self.tmp.name) / "business_growth_store.json"
        self.engine = BusinessGrowthEngine(store_path=self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_lead_ingestion_deduplicates_by_email(self):
        result = self.engine.ingest_leads(
            [
                {
                    "email": "founder@example.com",
                    "name": "Founder",
                    "company": "Acme",
                    "stage": "lead",
                    "score": 5,
                },
                {
                    "email": "Founder@Example.com",
                    "name": "Founder Updated",
                    "company": "Acme",
                    "stage": "marketing_qualified",
                    "score": 12,
                    "metadata": {"utm": "search"},
                },
            ],
            source="web",
        )

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["total_leads"], 1)

        metrics = self.engine.metrics()
        self.assertEqual(metrics["total_leads"], 1)
        self.assertEqual(metrics["stage_counts"]["marketing_qualified"], 1)
        self.assertEqual(metrics["lead_sources"].get("web"), 1)

    def test_marketing_automation_respects_cadence(self):
        self.engine.ingest_leads(
            [{"email": "buyer@acme.com", "name": "Buyer", "company": "Acme"}],
            source="ads",
        )
        self.engine.register_campaign(
            name="Lead Nurture",
            channel="email",
            cta="Book demo",
            target_stage="lead",
            cadence_hours=1.0,
        )

        first = self.engine.run_marketing_automation(max_contacts=1, now_ts=1_000.0)
        second = self.engine.run_marketing_automation(max_contacts=1, now_ts=1_200.0)
        third = self.engine.run_marketing_automation(max_contacts=1, now_ts=5_000.0)

        self.assertEqual(first["contacts_sent"], 1)
        self.assertEqual(second["contacts_sent"], 0)
        self.assertEqual(third["contacts_sent"], 1)

        metrics = self.engine.metrics()
        self.assertGreaterEqual(metrics["automation_coverage"], 1.0)

    def test_conversion_tracking_updates_customer_lifecycle_and_revenue(self):
        ingest = self.engine.ingest_leads(
            [{"email": "ops@acme.com", "name": "Ops", "company": "Acme"}],
            source="referral",
        )
        lead_id = next(iter(self.engine._leads.keys()))

        self.assertEqual(ingest["created"], 1)
        self.engine.track_conversion(lead_id, "demo_booked")
        self.engine.track_conversion(lead_id, "trial_started")
        purchase = self.engine.track_conversion(lead_id, "purchase", value=120.0)
        self.engine.track_conversion(lead_id, "renewal", value=30.0)
        self.engine.track_conversion(lead_id, "churn")

        self.assertIsNotNone(purchase["customer"])
        lifecycle = self.engine.customer_lifecycle()
        self.assertEqual(len(lifecycle), 1)
        self.assertEqual(lifecycle[0]["stage"], "churned")
        self.assertAlmostEqual(lifecycle[0]["total_revenue"], 150.0, places=2)

        metrics = self.engine.metrics()
        self.assertEqual(metrics["customers_total"], 1)
        self.assertEqual(metrics["churned_total"], 1)
        self.assertAlmostEqual(metrics["revenue_total"], 150.0, places=2)

    def test_revenue_loop_generates_expected_gap_actions(self):
        out = self.engine.run_revenue_loop(min_new_leads=10)
        action_types = {a["action_type"] for a in out["actions"]}

        self.assertIn("create_campaigns", action_types)
        self.assertIn("increase_lead_acquisition", action_types)
        self.assertIn("instrument_conversion_tracking", action_types)

        out2 = self.engine.run_revenue_loop(min_new_leads=10)
        open_actions = self.engine.open_actions()
        self.assertEqual(len(open_actions), len({a["action_type"] for a in open_actions}))
        self.assertEqual(out2["status"], "attention_required")

    def test_persistence_round_trip(self):
        self.engine.ingest_leads(
            [{"email": "owner@startup.com", "name": "Owner", "company": "StartupCo"}],
            source="manual",
        )
        lead_id = next(iter(self.engine._leads.keys()))
        self.engine.register_campaign(
            name="Always On",
            channel="email",
            cta="Start trial",
            target_stage="lead",
            cadence_hours=24.0,
        )
        self.engine.track_conversion(lead_id, "purchase", value=99.0)

        self.assertTrue(self.store.exists())

        reloaded = BusinessGrowthEngine(store_path=self.store)
        metrics = reloaded.metrics()
        lifecycle = reloaded.customer_lifecycle()

        self.assertEqual(metrics["total_leads"], 1)
        self.assertEqual(metrics["campaign_count"], 1)
        self.assertAlmostEqual(metrics["revenue_total"], 99.0, places=2)
        self.assertEqual(len(lifecycle), 1)


if __name__ == "__main__":
    unittest.main()
