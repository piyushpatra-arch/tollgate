"""Stage 1: identify the calling app (and therefore its team and risk tier)."""

from __future__ import annotations

import hmac

from gateway.config import AppConfig, AppsFile
from gateway.errors import GatewayError


class IdentityResolver:
    def __init__(self, apps: AppsFile) -> None:
        self._apps = apps.apps

    def resolve(self, api_key: str | None) -> AppConfig:
        if api_key:
            for app in self._apps:
                if hmac.compare_digest(app.api_key, api_key):
                    return app
        raise GatewayError(401, "unauthenticated", "missing or unknown X-Tollgate-Key")
