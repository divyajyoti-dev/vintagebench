"""Check API keys are set and each service answers one free request.

Never prints key values. Prints OK/FAIL per check; exits non-zero on any FAIL.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable

KEYS = ("FRED_API_KEY", "OPENAI_API_KEY", "TOGETHER_API_KEY")
TOGETHER_BASE_URL = "https://api.together.xyz/v1"


def check_fred() -> str:
    from fredapi import Fred

    info = Fred(api_key=os.environ["FRED_API_KEY"]).get_series_info("PAYEMS")
    return f"PAYEMS: {info['title']}"


def _list_models(base_url: str | None, key_var: str) -> str:
    from openai import OpenAI

    client = OpenAI(api_key=os.environ[key_var], base_url=base_url, max_retries=0, timeout=20)
    return f"{len(list(client.models.list()))} models"


def check_openai() -> str:
    return _list_models(None, "OPENAI_API_KEY")


def check_together() -> str:
    return _list_models(TOGETHER_BASE_URL, "TOGETHER_API_KEY")


def _error(exc: Exception) -> str:
    """Describe an exception with any key values redacted."""
    msg = str(exc).splitlines()[0][:200] if str(exc) else ""
    for key in KEYS:
        if value := os.environ.get(key):
            msg = msg.replace(value, "***")
    return f"{type(exc).__name__}: {msg}"


def main() -> int:
    ok = True
    for key in KEYS:
        present = bool(os.environ.get(key))
        ok &= present
        print(f"{'OK  ' if present else 'FAIL'} env {key} {'set' if present else 'missing'}")

    checks: dict[str, tuple[str, Callable[[], str]]] = {
        "FRED series info": ("FRED_API_KEY", check_fred),
        "OpenAI list models": ("OPENAI_API_KEY", check_openai),
        "Together list models": ("TOGETHER_API_KEY", check_together),
    }
    for name, (key, fn) in checks.items():
        if not os.environ.get(key):
            print(f"FAIL {name}: skipped, {key} missing")
            ok = False
            continue
        try:
            print(f"OK   {name}: {fn()}")
        except Exception as exc:  # noqa: BLE001
            print(f"FAIL {name}: {_error(exc)}")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
