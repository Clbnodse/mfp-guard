#!/usr/bin/env python3
"""Unit tests for guard.py — room / percentage / alert calculations.

Run:  python3 -m unittest test_guard -v
"""
import json
import unittest

from guard import (
    compute_risk,
    demo_account,
    format_status,
    risk_to_json,
    validate_sandbox_key,
)


def base_account(**overrides):
    acct = {
        "account_id": "test-10000",
        "balance": 10000.00,
        "equity": 10000.00,
        "starting_balance": 10000.00,
        "daily_loss_limit": 300.00,
        "max_drawdown": 500.00,
        "day_pnl": 0.00,
        "positions": [],
    }
    acct.update(overrides)
    return acct


class TestDllLevels(unittest.TestCase):
    def test_ok_below_50(self):
        r = compute_risk(base_account(day_pnl=-100.00))  # 33.3% used
        self.assertAlmostEqual(r["dll_used_pct"], 100 / 3, places=2)
        self.assertAlmostEqual(r["dll_room"], 200.00)
        self.assertEqual(r["level"], "OK")

    def test_warn_50_to_75(self):
        r = compute_risk(base_account(day_pnl=-155.00))  # 51.7%
        self.assertEqual(r["level"], "WARN")
        self.assertAlmostEqual(r["dll_room"], 145.00)

    def test_warn_boundary_exactly_50(self):
        r = compute_risk(base_account(day_pnl=-150.00))
        self.assertEqual(r["level"], "WARN")

    def test_danger_75_to_90(self):
        r = compute_risk(base_account(day_pnl=-240.00))  # 80%
        self.assertEqual(r["level"], "DANGER")
        self.assertAlmostEqual(r["dll_room"], 60.00)

    def test_critical_above_90(self):
        r = compute_risk(base_account(day_pnl=-285.00))  # 95%
        self.assertEqual(r["level"], "CRITICAL")

    def test_critical_room_under_25_dollars(self):
        # Only 83.3% used, but $20 room left -> CRITICAL by the room rule.
        r = compute_risk(base_account(day_pnl=-280.00))
        self.assertAlmostEqual(r["dll_room"], 20.00)
        self.assertEqual(r["level"], "CRITICAL")
        self.assertTrue(any("room" in x for x in r["reasons"]))

    def test_profit_day_is_ok_and_room_is_full(self):
        r = compute_risk(base_account(day_pnl=120.00))
        self.assertEqual(r["daily_loss_used"], 0.0)
        self.assertEqual(r["dll_used_pct"], 0.0)
        self.assertEqual(r["dll_room"], 300.00)
        self.assertEqual(r["level"], "OK")


class TestEdgeCases(unittest.TestCase):
    def test_zero_dll_flat_account(self):
        r = compute_risk(base_account(daily_loss_limit=0.0, day_pnl=0.0))
        self.assertIsNone(r["dll_used_pct"])
        self.assertEqual(r["level"], "OK")

    def test_zero_dll_with_loss_is_critical(self):
        r = compute_risk(base_account(daily_loss_limit=0.0, day_pnl=-10.00))
        self.assertIsNone(r["dll_used_pct"])
        self.assertEqual(r["level"], "CRITICAL")

    def test_flat_account_no_positions(self):
        r = compute_risk(base_account())
        self.assertEqual(r["floating_pnl"], 0.0)
        self.assertEqual(r["gross_exposure"], 0.0)
        self.assertEqual(r["exposure_multiple"], 0.0)
        self.assertEqual(r["margin_pct"], 0.0)
        self.assertEqual(r["position_count"], 0)
        self.assertEqual(r["level"], "OK")

    def test_negative_floating_pnl(self):
        r = compute_risk(base_account(equity=9750.00, day_pnl=-250.00))
        self.assertEqual(r["floating_pnl"], -250.00)
        self.assertEqual(r["level"], "DANGER")  # 250/300 = 83.3%

    def test_drawdown_room_and_floor(self):
        r = compute_risk(base_account(equity=9700.00))
        self.assertEqual(r["drawdown_floor"], 9500.00)
        self.assertEqual(r["drawdown_room"], 200.00)

    def test_drawdown_breached_is_critical(self):
        r = compute_risk(base_account(equity=9400.00, day_pnl=-100.00))
        self.assertEqual(r["drawdown_room"], -100.00)
        self.assertEqual(r["level"], "CRITICAL")

    def test_exposure_and_margin(self):
        acct = base_account(positions=[
            {"symbol": "BTCUSDT", "notional": 5000.00, "margin_used": 500.00},
            {"symbol": "ETHUSDT", "size": 2.0, "mark_price": 1700.00,
             "margin_used": 340.00},
        ])
        r = compute_risk(acct)
        self.assertEqual(r["gross_exposure"], 8400.00)
        self.assertAlmostEqual(r["exposure_multiple"], 0.84)
        self.assertAlmostEqual(r["margin_pct"], 8.4)
        self.assertEqual(r["position_count"], 2)

    def test_short_position_counts_toward_exposure(self):
        acct = base_account(positions=[
            {"symbol": "BTCUSDT", "side": "short", "notional": -3000.00,
             "margin_used": 300.00},
        ])
        r = compute_risk(acct)
        self.assertEqual(r["gross_exposure"], 3000.00)


class TestDemoAndKeys(unittest.TestCase):
    def test_demo_account_computes_and_is_warn(self):
        r = compute_risk(demo_account())
        self.assertEqual(r["level"], "WARN")
        self.assertAlmostEqual(r["dll_used_pct"], 51.67, places=1)
        self.assertEqual(r["position_count"], 2)

    def test_demo_status_is_labelled_demo(self):
        text = format_status(compute_risk(demo_account()), "DEMO — test")
        self.assertIn("DEMO", text)
        self.assertIn("WARN", text)

    def test_json_output_is_valid_and_key_free(self):
        payload = json.loads(
            risk_to_json(compute_risk(demo_account()), "DEMO"))
        self.assertEqual(payload["level"], "WARN")
        self.assertNotIn("api_key", json.dumps(payload).lower())

    def test_sandbox_key_accepted(self):
        self.assertEqual(validate_sandbox_key("fp_test_abc123"),
                         "fp_test_abc123")

    def test_live_key_refused(self):
        with self.assertRaises(ValueError):
            validate_sandbox_key("fp_live_abc123")
        with self.assertRaises(ValueError):
            validate_sandbox_key("sk-live-abc123")

    def test_missing_key_refused(self):
        with self.assertRaises(ValueError):
            validate_sandbox_key(None)
        with self.assertRaises(ValueError):
            validate_sandbox_key("")


if __name__ == "__main__":
    unittest.main()
