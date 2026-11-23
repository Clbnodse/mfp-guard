"""Optional WebSocket account-stream client for MFP Guard.

Read-only: it subscribes to the account stream and yields account
updates. It never places orders.

Requires the third-party `websockets` package. If that package is not
installed, every entry point here raises a clear RuntimeError and the
caller (guard.py --watch) falls back to REST polling — nothing fails
silently and no fake stream data is ever invented.

Default stream (from MyFundedPerps docs):
    wss://account-stream.myfundedperpetuals.com/v1/stream
"""
from __future__ import annotations

import os

DEFAULT_STREAM_URL = "wss://account-stream.myfundedperpetuals.com/v1/stream"


def stream_available() -> bool:
    """True only if the `websockets` package can be imported."""
    try:
        import websockets  # noqa: F401
    except ImportError:
        return False
    return True


def require_websockets():
    if not stream_available():
        raise RuntimeError(
            "WebSocket streaming needs the `websockets` package, which is "
            "not installed. Falling back to REST polling "
            "(guard.py --watch). Install it with "
            "`pip install websockets` to enable the live stream."
        )


async def stream_account(account_id: str, api_key: str,
                         stream_url: str | None = None):
    """Async generator yielding parsed account-update dicts.

    Callers must hold a sandbox key (fp_test_...). The key is sent as
    the stream auth token and is never printed or logged here.
    """
    require_websockets()
    import websockets  # noqa: F401  (checked above)

    url = stream_url or os.environ.get(
        "MFP_ACCOUNT_STREAM", DEFAULT_STREAM_URL)
    # NOTE: exact subscribe message shape follows the published
    # account-stream docs; this module is intentionally not run in
    # --demo mode and is only exercised against the sandbox.
    async with websockets.connect(
        url, extra_headers={"Authorization": f"Bearer {api_key}"}
    ) as ws:
        await ws.send(
            '{"type": "subscribe", "account_id": "%s"}' % account_id
        )
        async for message in ws:
            import json
            yield json.loads(message)
