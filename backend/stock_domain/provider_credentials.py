"""行情 Provider 凭证解析：设置页 provider_credentials > 环境变量。"""
from __future__ import annotations

import os
from typing import Callable

_credential_resolver: Callable[[str, str], str | None] | None = None

ENV_FIELD_MAP: dict[tuple[str, str], str] = {
    ("tushare", "token"): "TUSHARE_TOKEN",
    ("tickflow", "api_key"): "TICKFLOW_API_KEY",
    ("longbridge", "app_key"): "LONGBRIDGE_APP_KEY",
    ("longbridge", "app_secret"): "LONGBRIDGE_APP_SECRET",
}


def set_credential_resolver(fn: Callable[[str, str], str | None] | None) -> None:
    global _credential_resolver
    _credential_resolver = fn


def resolve(provider_id: str, field: str) -> str | None:
    if _credential_resolver is not None:
        value = _credential_resolver(provider_id, field)
        if value:
            return value
    env_key = ENV_FIELD_MAP.get((provider_id, field))
    if env_key:
        return os.getenv(env_key) or None
    return None
