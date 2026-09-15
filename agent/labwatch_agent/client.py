from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from labwatch_agent.config import AgentConfig

logger = logging.getLogger("labwatch.agent")


class AgentAuthError(Exception):
    """Agent credentials were rejected; the service should re-register."""


class AgentClient:
    def __init__(self, cfg: AgentConfig, agent_id: str = "", secret: str = ""):
        self.cfg = cfg
        self.agent_id = agent_id
        self.secret = secret
        verify: bool | str = cfg.tls_verify
        if cfg.tls_ca_file:
            verify = cfg.tls_ca_file
        self._client = httpx.Client(
            base_url=cfg.server_url.rstrip("/"),
            timeout=20.0,
            verify=verify,
            trust_env=False,
        )
        self._backoff = 1.0

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> dict[str, str]:
        if self.agent_id and self.secret:
            return {"Authorization": f"Bearer {self.agent_id}:{self.secret}"}
        return {}

    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = kwargs.pop("headers", {})
        headers.update(self._headers())
        try:
            response = self._client.request(method, path, headers=headers, **kwargs)
            if response.status_code < 500:
                self._backoff = 1.0
            if response.status_code == 401:
                raise AgentAuthError(f"{method} {path} -> 401 {response.text[:400]}")
            if response.status_code >= 400:
                logger.warning(
                    "Server %s %s -> %s %s",
                    method,
                    path,
                    response.status_code,
                    (response.text or "")[:500],
                )
            return response
        except httpx.HTTPError as exc:
            logger.warning("Server request failed: %s", exc)
            raise

    def register(self, registration_token: str, identity: dict[str, Any], agent_uuid: str, version: str, inventory_id: str = "") -> dict[str, Any]:
        payload = {
            "registration_token": registration_token,
            "identity": identity,
            "agent_uuid": agent_uuid,
            "agent_version": version,
        }
        if inventory_id:
            payload["inventory_id"] = inventory_id
        r = self._request("POST", "/api/agents/register", json=payload)
        r.raise_for_status()
        data = r.json()
        self.agent_id = data["agent_id"]
        self.secret = data["agent_secret"]
        return data

    def heartbeat(self, payload: dict[str, Any]) -> dict[str, Any]:
        r = self._request("POST", "/api/agents/heartbeat", json=payload)
        r.raise_for_status()
        return r.json()

    def inventory(self, payload: dict[str, Any]) -> dict[str, Any]:
        r = self._request("POST", "/api/agents/inventory", json=payload)
        r.raise_for_status()
        return r.json()

    def metrics(self, payload: dict[str, Any]) -> dict[str, Any]:
        r = self._request("POST", "/api/agents/metrics", json=payload)
        r.raise_for_status()
        return r.json()

    def events(self, items: list[dict[str, Any]]) -> None:
        r = self._request("POST", "/api/agents/events", json=items)
        r.raise_for_status()

    def logs(self, items: list[dict[str, Any]]) -> None:
        r = self._request("POST", "/api/agents/logs", json=items)
        r.raise_for_status()

    def sleep_backoff(self) -> None:
        time.sleep(min(self._backoff, 60))
        self._backoff = min(self._backoff * 2, 60)
