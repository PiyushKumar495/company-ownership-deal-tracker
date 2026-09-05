"""Tests for the reconciliation logic, using an isolated in-memory database
seeded with fixture data (not the sample data used by the pipeline)."""
import unittest

from src.db import get_connection, init_db, get_or_create_company, get_or_create_investor
from src.reconcile import reconcile_valuations, reconcile_ownership, _relative_diff


class TestRelativeDiff(unittest.TestCase):
    def test_identical_values(self):
        self.assertEqual(_relative_diff(100, 100), 0.0)

    def test_both_zero(self):
        self.assertEqual(_relative_diff(0, 0), 0.0)

    def test_typical_case(self):
        self.assertAlmostEqual(_relative_diff(100, 120), 0.1667, places=3)


class TestReconcileValuations(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection(":memory:")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def _add_round(self, company_id, valuation, source, trust_tier):
        self.conn.execute(
            """INSERT INTO funding_rounds (company_id, round_type, round_date, amount_usd,
               valuation_usd, source, trust_tier, raw_reference)
               VALUES (?, 'Series A', '2026-01-01', 1000000, ?, ?, ?, 'test')""",
            (company_id, valuation, source, trust_tier),
        )
        self.conn.commit()

    def test_no_conflict_when_values_close(self):
        cid = get_or_create_company(self.conn, "Acme Co")
        self._add_round(cid, 100_000_000, "company_filing", 1)
        self._add_round(cid, 103_000_000, "news_aggregator", 3)  # 3% apart, within tolerance

        n = reconcile_valuations(self.conn)
        self.assertEqual(n, 0)

    def test_conflict_flagged_when_values_diverge(self):
        cid = get_or_create_company(self.conn, "Acme Co")
        self._add_round(cid, 100_000_000, "company_filing", 1)
        self._add_round(cid, 140_000_000, "news_aggregator", 3)  # 40% apart

        n = reconcile_valuations(self.conn)
        self.assertEqual(n, 1)

        row = self.conn.execute("SELECT * FROM data_conflicts").fetchone()
        self.assertEqual(row["status"], "auto_resolved")
        self.assertEqual(float(row["resolved_value"]), 100_000_000)

    def test_needs_review_when_same_trust_tier_disagrees(self):
        cid = get_or_create_company(self.conn, "Acme Co")
        self._add_round(cid, 100_000_000, "news_aggregator", 3)
        self._add_round(cid, 150_000_000, "news_aggregator", 3)  # same tier, disagree

        reconcile_valuations(self.conn)
        row = self.conn.execute("SELECT * FROM data_conflicts").fetchone()
        self.assertEqual(row["status"], "needs_review")


class TestReconcileOwnership(unittest.TestCase):
    def setUp(self):
        self.conn = get_connection(":memory:")
        init_db(self.conn)

    def tearDown(self):
        self.conn.close()

    def _add_stake(self, company_id, investor_name, pct, source="company_filing", tier=1):
        investor_id = get_or_create_investor(self.conn, investor_name)
        self.conn.execute(
            """INSERT INTO ownership (company_id, investor_id, round_id, stake_pct, source, trust_tier)
               VALUES (?, ?, NULL, ?, ?, ?)""",
            (company_id, investor_id, pct, source, tier),
        )
        self.conn.commit()

    def test_no_conflict_under_100_percent(self):
        cid = get_or_create_company(self.conn, "Acme Co")
        self._add_stake(cid, "Investor A", 40)
        self._add_stake(cid, "Investor B", 30)

        n = reconcile_ownership(self.conn)
        self.assertEqual(n, 0)

    def test_oversubscription_flagged(self):
        cid = get_or_create_company(self.conn, "Acme Co")
        self._add_stake(cid, "Investor A", 60)
        self._add_stake(cid, "Investor B", 55)

        n = reconcile_ownership(self.conn)
        self.assertEqual(n, 1)

        row = self.conn.execute("SELECT * FROM data_conflicts").fetchone()
        self.assertEqual(row["status"], "needs_review")
        self.assertEqual(row["field"], "stake_pct_sum")


if __name__ == "__main__":
    unittest.main()
