# MFP Guard — read-only risk monitor for MyFundedPerps

**Status:** working prototype, v0.1.0. Built for the MyFundedPerps
Builders Program (Starter tier: working prototype + write-up).
**Not submitted anywhere.** No application has been filed from this repo.

## The real trader problem

MyFundedPerps traders blow accounts the same quiet way: they don't
watch their daily loss limit (DLL) room, max-drawdown room, exposure
and margin in real time. The numbers exist in the terminal and the
API, but nobody stares at them while a position runs. By the time a
trader checks, the DLL is gone and the account is failed — a $36–$49
evaluation lost to inattention, not to a bad idea.

MFP Guard is one screen that answers, at a glance: *how much room do
I have left, and how bad is it?*

## What it is

A small Python CLI (standard library only, no dependencies) that reads
a MyFundedPerps account — read-only — and prints:

- Equity / balance / floating PnL / day PnL
- DLL used ($) and (%), DLL room ($)
- Max-drawdown floor and drawdown room ($)
- Gross exposure ($ and x equity), margin used ($ and %)
- Open position count
- One alert level: **OK / WARN / DANGER / CRITICAL**

Alert rules:

| Level | Rule |
|---|---|
| OK | DLL used < 50% |
| WARN | DLL used 50–75% |
| DANGER | DLL used 75–90% |
| CRITICAL | DLL used > 90%, **or** DLL room under $25, **or** equity at/below the drawdown floor |

## What it does NOT do

- **No trading.** It never places, cancels, or modifies an order.
  There is no order code in this repo at all.
- **No live credentials.** Only sandbox keys (`fp_test_...`) are
  accepted, from the environment only. A non-sandbox key is refused
  outright, and a key is never printed, logged, or included in output.
- **No profit promises.** It is a risk display, not a strategy.
- **No fake live data.** `--demo` output is simulated data and is
  labelled `DEMO` on every screen and in every JSON payload.

## How to run

No install step. Python 3.10+ is enough.

```bash
# Demo — simulated sandbox-style account, no key needed
python3 guard.py --demo

# Same, as machine-readable JSON
python3 guard.py --demo --json

# Demo watch loop (2 ticks, for a quick look)
python3 guard.py --demo --watch --count 2 --interval 5
```

### With a real sandbox key

```bash
export MFP_SANDBOX_KEY='fp_test_...'   # sandbox only — never a live key
# Optional overrides (defaults shown):
# export MFP_API_BASE='https://developers.myfundedperpetuals.com/v1'

# One read-only snapshot
python3 guard.py --snapshot --account-id <sandbox-account-id>

# Keep watching (polls the REST snapshot every 5s; Ctrl-C to stop)
python3 guard.py --watch --account-id <sandbox-account-id> --interval 5

# JSON output works with --snapshot / --watch too
python3 guard.py --snapshot --account-id <sandbox-account-id> --json
```

The optional WebSocket account stream lives in `ws_client.py`
(`wss://account-stream.myfundedperpetuals.com/v1/stream`). It needs
the third-party `websockets` package, which is **not** installed here,
so it degrades cleanly: `stream_available()` returns `False` and
`--watch` falls back to REST polling. Nothing invents stream data.

## Tests

```bash
python3 -m unittest test_guard -v
```

21 tests, all passing. They cover the alert bands (including the
exact 50% boundary), the under-$25 DLL-room rule, zero DLL, a flat
account, negative floating PnL, drawdown breach, exposure/margin
maths (including short positions counting toward exposure), the demo
scenario, JSON validity, and sandbox-key validation (live keys
refused, missing keys refused).

## Files

| File | What it is |
|---|---|
| `guard.py` | The CLI: demo data, risk maths, REST snapshot, watch loop |
| `ws_client.py` | Optional WebSocket stream client (degrades cleanly without `websockets`) |
| `test_guard.py` | 21 unit tests |
| `DEMO.md` | Captured real output from `--demo`, `--demo --json`, and the test run |
| `demo-output.txt` | The same captured output, plain text |

## Builders Program fit

- **Category:** tool on the MFP API (REST) + account stream
  (WebSocket module), sandbox-first.
- **Tier aimed at:** Starter — a working prototype plus this write-up.
- **Why it fits:** it uses only the published developer surface
  (REST accounts read + account stream), runs against the free
  sandbox, and solves a failure mode every prop trader recognises.
- **Next steps if accepted:** live-stream mode once `websockets` is
  available, per-symbol exposure breakdown, a `--quiet` mode that
  only prints on level changes, and a small web dashboard reusing the
  same `compute_risk()` core.
