#!/usr/bin/env python3
"""MFP Guard — READ-ONLY live risk monitor for MyFundedPerps traders.

It never places orders. It reads an account (REST snapshot, or a
polling watch loop) and reports DLL room, drawdown room, exposure and
margin in one screen, with alert levels.

Modes:
  --demo            simulated sandbox-style account, no key needed.
                    Output is always labelled DEMO — it is not real data.
  --snapshot        one REST read of a sandbox account (needs
                    MFP_SANDBOX_KEY, fp_test_ prefix only).
  --watch           repeat the snapshot every --interval seconds.

Only sandbox keys are accepted. A key is never printed or logged.
Standard library only — no third-party dependencies.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request

VERSION = "0.1.0"
DEFAULT_API_BASE = "https://developers.myfundedperpetuals.com/v1"
DEFAULT_STREAM_URL = "wss://account-stream.myfundedperpetuals.com/v1/stream"

# Alert thresholds on daily-loss-limit used (%).
WARN_AT = 50.0
DANGER_AT = 75.0
CRITICAL_AT = 90.0
CRITICAL_ROOM_USD = 25.0


# ---------------------------------------------------------------- helpers
def _f(value, default=0.0):
    """Coerce to float, tolerating None / strings / missing keys."""
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def validate_sandbox_key(key):
    """Accept only sandbox keys. Returns the key, or raises ValueError.

    The key itself is never printed, logged, or included in any output.
    """
    if not key:
        raise ValueError(
            "MFP_SANDBOX_KEY is not set. Set it to a sandbox key "
            "(fp_test_...) or run with --demo (no key needed)."
        )
    if not key.startswith("fp_test_"):
        raise ValueError(
            "Only sandbox keys (fp_test_...) are accepted. "
            "Live/production keys are refused by design."
        )
    return key


def demo_account():
    """Simulated sandbox-style account. Clearly fake, clearly labelled.

    Scenario: $10,000 account, down $155 on the day against a $300
    daily loss limit (51.7% DLL used -> WARN), two small positions open.
    """
    return {
        "account_id": "demo-sandbox-10000",
        "balance": 10000.00,
        "equity": 9845.00,
        "starting_balance": 10000.00,
        "daily_loss_limit": 300.00,
        "max_drawdown": 500.00,
        "day_pnl": -155.00,
        "positions": [
            {
                "symbol": "BTCUSDT",
                "side": "long",
                "size": 0.05,
                "entry_price": 68742.10,
                "mark_price": 68410.00,
                "notional": 3420.50,
                "margin_used": 342.05,
                "unrealized_pnl": -16.60,
            },
            {
                "symbol": "ETHUSDT",
                "side": "long",
                "size": 0.40,
                "entry_price": 1740.00,
                "mark_price": 1705.00,
                "notional": 682.00,
                "margin_used": 68.20,
                "unrealized_pnl": -14.00,
            },
        ],
    }


# ---------------------------------------------------------------- core logic
def compute_risk(account):
    """Compute risk figures from a normalised account dict.

    Accepted fields: balance, equity, starting_balance,
    daily_loss_limit, max_drawdown (dollars) and/or max_drawdown_pct,
    day_pnl (or daily_pnl; defaults to equity - balance),
    positions: [{notional | size*mark_price, margin_used, ...}].

    Returns a dict with dollar rooms, percentages, exposure, margin
    and an alert level: OK / WARN / DANGER / CRITICAL.
    """
    balance = _f(account.get("balance"))
    equity = _f(account.get("equity"), balance)
    starting = _f(account.get("starting_balance"), balance)

    daily_loss_limit = _f(account.get("daily_loss_limit"))
    if "day_pnl" in account:
        day_pnl = _f(account.get("day_pnl"))
    elif "daily_pnl" in account:
        day_pnl = _f(account.get("daily_pnl"))
    else:
        day_pnl = equity - balance

    daily_loss_used = max(0.0, -day_pnl)
    dll_room = daily_loss_limit - daily_loss_used
    dll_used_pct = (
        (daily_loss_used / daily_loss_limit * 100.0)
        if daily_loss_limit > 0
        else None
    )

    if account.get("max_drawdown") is not None:
        floor = starting - _f(account.get("max_drawdown"))
    elif account.get("max_drawdown_pct") is not None:
        floor = starting * (1.0 - _f(account.get("max_drawdown_pct")) / 100.0)
    else:
        floor = None
    drawdown_room = (equity - floor) if floor is not None else None

    positions = account.get("positions") or []
    gross_exposure = 0.0
    margin_used = 0.0
    for p in positions:
        notional = p.get("notional")
        if notional is None:
            notional = _f(p.get("size")) * _f(p.get("mark_price"))
        gross_exposure += abs(_f(notional))
        margin_used += _f(p.get("margin_used"))

    exposure_multiple = (gross_exposure / equity) if equity > 0 else 0.0
    margin_pct = (margin_used / equity * 100.0) if equity > 0 else 0.0
    floating_pnl = equity - balance

    # --- alert level ---
    reasons = []
    if dll_used_pct is None:
        if daily_loss_used > 0:
            level = "CRITICAL"
            reasons.append("daily loss with no daily loss limit configured")
        else:
            level = "OK"
            reasons.append("no daily loss limit configured (DLL = 0)")
    elif dll_used_pct > CRITICAL_AT:
        level = "CRITICAL"
        reasons.append(f"DLL used {dll_used_pct:.1f}% (> {CRITICAL_AT:.0f}%)")
    elif dll_used_pct >= DANGER_AT:
        level = "DANGER"
        reasons.append(f"DLL used {dll_used_pct:.1f}% (>= {DANGER_AT:.0f}%)")
    elif dll_used_pct >= WARN_AT:
        level = "WARN"
        reasons.append(f"DLL used {dll_used_pct:.1f}% (>= {WARN_AT:.0f}%)")
    else:
        level = "OK"

    if daily_loss_limit > 0 and dll_room < CRITICAL_ROOM_USD:
        level = "CRITICAL"
        reasons.append(f"DLL room ${dll_room:,.2f} (< ${CRITICAL_ROOM_USD:,.0f})")
    if drawdown_room is not None and drawdown_room <= 0:
        level = "CRITICAL"
        reasons.append("equity at or below max-drawdown floor")

    return {
        "account_id": account.get("account_id"),
        "balance": balance,
        "equity": equity,
        "starting_balance": starting,
        "floating_pnl": floating_pnl,
        "day_pnl": day_pnl,
        "daily_loss_limit": daily_loss_limit,
        "daily_loss_used": daily_loss_used,
        "dll_used_pct": dll_used_pct,
        "dll_room": dll_room,
        "drawdown_floor": floor,
        "drawdown_room": drawdown_room,
        "gross_exposure": gross_exposure,
        "exposure_multiple": exposure_multiple,
        "margin_used": margin_used,
        "margin_pct": margin_pct,
        "position_count": len(positions),
        "level": level,
        "reasons": reasons,
    }


def format_status(risk, source_label):
    """One-screen human-readable status. `source_label` says DEMO or SANDBOX."""
    pct = (
        f"{risk['dll_used_pct']:5.1f}%"
        if risk["dll_used_pct"] is not None
        else "  n/a "
    )
    floor = (
        f"${risk['drawdown_floor']:>10,.2f}"
        if risk["drawdown_floor"] is not None
        else "        n/a"
    )
    dd_room = (
        f"${risk['drawdown_room']:>10,.2f}"
        if risk["drawdown_room"] is not None
        else "        n/a"
    )
    banner = {
        "OK": "OK       — within limits",
        "WARN": "WARN     — DLL over half used",
        "DANGER": "DANGER   — DLL nearly exhausted",
        "CRITICAL": "CRITICAL — stop and check now",
    }[risk["level"]]
    lines = [
        f"MFP Guard v{VERSION}  [{source_label}]  account: {risk['account_id']}",
        "=" * 64,
        f"  Alert:    {banner}",
        f"  Equity:   ${risk['equity']:>10,.2f}   Balance: ${risk['balance']:>10,.2f}"
        f"   Floating PnL: ${risk['floating_pnl']:>+10,.2f}",
        f"  Day PnL:  ${risk['day_pnl']:>+10,.2f}",
        f"  DLL used: ${risk['daily_loss_used']:>10,.2f} / ${risk['daily_loss_limit']:>10,.2f}"
        f"  ({pct})   DLL room: ${risk['dll_room']:>10,.2f}",
        f"  DD floor: {floor}   Drawdown room: {dd_room}",
        f"  Exposure: ${risk['gross_exposure']:>10,.2f}  ({risk['exposure_multiple']:.2f}x equity)"
        f"   Margin used: ${risk['margin_used']:>10,.2f} ({risk['margin_pct']:.1f}%)",
        f"  Positions open: {risk['position_count']}",
    ]
    if risk["reasons"]:
        lines.append("  Why: " + "; ".join(risk["reasons"]))
    if source_label.startswith("DEMO"):
        lines.append("  DEMO DATA — simulated, not a real account.")
    return "\n".join(lines)


def risk_to_json(risk, source_label):
    payload = {"source": source_label, "tool": f"mfp-guard/{VERSION}", **risk}
    return json.dumps(payload, indent=2, sort_keys=True)


# ---------------------------------------------------------------- REST read
def fetch_snapshot(account_id, api_base, api_key):
    """One read-only REST snapshot. Raises on HTTP / parse failure.

    Tries GET {base}/accounts/{id}; if the response carries positions
    under a `positions` key they are used, otherwise positions are [].
    No order is ever placed here.
    """
    url = f"{api_base.rstrip('/')}/accounts/{account_id}"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + api_key,
            "Accept": "application/json",
            "User-Agent": f"MFP-Guard/{VERSION}",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"API request failed: HTTP {e.code} for {url}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"API request failed: {e.reason}") from e

    if isinstance(data, dict) and isinstance(data.get("account"), dict):
        data = data["account"]
    if not isinstance(data, dict):
        raise RuntimeError("API returned an unexpected (non-object) response")
    data.setdefault("account_id", account_id)
    data.setdefault("positions", [])
    return data


# ---------------------------------------------------------------- CLI
def build_parser():
    p = argparse.ArgumentParser(
        prog="guard.py",
        description="MFP Guard — read-only MyFundedPerps risk monitor. "
        "Never places orders.",
    )
    p.add_argument("--demo", action="store_true",
                   help="run with simulated sandbox-style data (no key)")
    p.add_argument("--account-id", default=None,
                   help="sandbox account id for --snapshot / --watch")
    p.add_argument("--snapshot", action="store_true",
                   help="one REST read of the sandbox account")
    p.add_argument("--watch", action="store_true",
                   help="repeat the snapshot every --interval seconds")
    p.add_argument("--interval", type=float, default=5.0,
                   help="seconds between watch ticks (default 5)")
    p.add_argument("--count", type=int, default=0,
                   help="watch ticks then exit (0 = run until Ctrl-C)")
    p.add_argument("--json", action="store_true",
                   help="print machine-readable JSON instead of the screen")
    return p


def _emit(account, source_label, as_json):
    risk = compute_risk(account)
    if as_json:
        print(risk_to_json(risk, source_label))
    else:
        print(format_status(risk, source_label))
    return risk


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.demo:
        source = "DEMO — simulated sandbox-style data, not real"
        account = demo_account()
        if args.watch:
            count = 0
            while True:
                _emit(account, source, args.json)
                count += 1
                if args.count and count >= args.count:
                    break
                if not args.json:
                    print(f"--- next tick in {args.interval:g}s (Ctrl-C to stop) ---")
                time.sleep(args.interval)
            return 0
        _emit(account, source, args.json)
        return 0

    if not (args.snapshot or args.watch):
        print("Choose a mode: --demo, --snapshot, or --watch "
              "(see --help).", file=sys.stderr)
        return 2
    if not args.account_id:
        print("--account-id is required for --snapshot / --watch.",
              file=sys.stderr)
        return 2
    try:
        api_key = validate_sandbox_key(os.environ.get("MFP_SANDBOX_KEY"))
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 2

    api_base = os.environ.get("MFP_API_BASE", DEFAULT_API_BASE)
    source = "SANDBOX — live sandbox read (no orders placed)"

    if args.snapshot:
        try:
            account = fetch_snapshot(args.account_id, api_base, api_key)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 2
        _emit(account, source, args.json)
        return 0

    # --watch: polling loop (the optional WebSocket stream lives in
    # ws_client.py; polling is the stdlib fallback when `websockets`
    # is not installed).
    count = 0
    while True:
        try:
            account = fetch_snapshot(args.account_id, api_base, api_key)
            _emit(account, source, args.json)
        except RuntimeError as e:
            print(f"Error: {e}", file=sys.stderr)
        count += 1
        if args.count and count >= args.count:
            break
        time.sleep(args.interval)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
