"""S4T metrics SDK for Lightning-Rod plugins — write via metrics gateway."""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime
from typing import Any
from urllib import error, request

LOG = logging.getLogger(__name__)


class MetricsWriter:
    """No-op when metrics_url/token are missing (plugin works without cloud metrics)."""

    def __init__(self, url: str | None, token: str | None, stream: str | None = None):
        self.url = (url or "").strip() or None
        self.token = (token or "").strip() or None
        self.stream = (stream or "").strip() or None
        self.enabled = bool(self.url and self.token)

    @classmethod
    def from_params(cls, params: dict | None) -> "MetricsWriter":
        params = params or {}
        return cls(
            url=params.get("metrics_url"),
            token=params.get("metrics_token"),
            stream=params.get("metrics_stream"),
        )

    def write(
        self,
        fields: dict[str, Any],
        tags: dict[str, str] | None = None,
        timestamp: datetime | None = None,
    ) -> bool:
        if not self.enabled:
            return False

        payload: dict[str, Any] = {"fields": fields}
        if tags:
            payload["tags"] = tags
        if timestamp is not None:
            payload["time"] = timestamp.isoformat()

        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": "Bearer {0}".format(self.token),
        }

        for attempt in range(3):
            try:
                req = request.Request(self.url, data=body, headers=headers, method="POST")
                with request.urlopen(req, timeout=10) as resp:
                    if 200 <= resp.status < 300:
                        return True
            except error.HTTPError as exc:
                LOG.warning("metrics write HTTP %s: %s", exc.code, exc.reason)
                if exc.code < 500:
                    return False
            except Exception as exc:
                LOG.warning("metrics write failed (attempt %s): %s", attempt + 1, exc)
            time.sleep(0.5 * (attempt + 1))
        return False
