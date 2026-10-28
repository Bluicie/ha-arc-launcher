"""Client for the local control API of Arc Launcher."""

from __future__ import annotations

from http import HTTPStatus
import json
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import API_PREFIX, DEFAULT_PORT, LONG_REQUEST_TIMEOUT, REQUEST_TIMEOUT


class ArcLauncherError(Exception):
    """The TV refused the request or could not be reached."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


class ArcLauncherConnectionError(ArcLauncherError):
    """The TV did not answer (off, asleep, or Arc Launcher is not the home app)."""


class ArcLauncherAuthError(ArcLauncherError):
    """Not paired (401) or control from other apps is turned off (403)."""


class ArcLauncherApi:
    """Talks to one TV. The API refuses browser Origins and Hosts that are not an IP or .local name."""

    def __init__(
        self, session: ClientSession, host: str, port: int = DEFAULT_PORT, token: str | None = None
    ) -> None:
        self._session = session
        self.host = host
        self.port = port
        self.token = token

    @property
    def base_url(self) -> str:
        host = f"[{self.host}]" if ":" in self.host else self.host
        return f"http://{host}:{self.port}{API_PREFIX}"

    @property
    def backup_url(self) -> str:
        """Where other TVs fetch this TV's layout while it shares it."""
        return f"{self.base_url}/backup"

    async def info(self) -> dict[str, Any]:
        return await self._request("GET", "info", auth=False)

    async def status(self) -> dict[str, Any]:
        return await self._request("GET", "status")

    async def pair(self, client: str) -> dict[str, Any]:
        """Show a 6-digit code on the TV."""
        return await self._request("POST", "pair", {"client": client}, auth=False)

    async def confirm_pair(self, code: str) -> dict[str, Any]:
        """Exchange the code for a token ({token, id, name})."""
        return await self._request("POST", "pair/confirm", {"code": code}, auth=False)

    async def sync(self, force: bool = True) -> dict[str, Any]:
        return await self._request("POST", "sync", {"force": force}, timeout=LONG_REQUEST_TIMEOUT)

    async def backup(self) -> dict[str, Any]:
        """Write a timestamped backup file on the TV."""
        return await self._request("POST", "backup")

    async def get_backup(self) -> dict[str, Any]:
        return await self._request("GET", "backup", timeout=LONG_REQUEST_TIMEOUT)

    async def restore(self, backup: dict[str, Any]) -> dict[str, Any]:
        return await self._request("POST", "restore", backup, timeout=LONG_REQUEST_TIMEOUT)

    async def set_quick_actions(self, actions: list[dict[str, Any]]) -> dict[str, Any]:
        """Replace the buttons on the TV's status bar; an empty list removes them."""
        return await self._request("PUT", "quick-actions", {"actions": actions})

    async def update_settings(self, **settings: Any) -> dict[str, Any]:
        """PUT share/autoSync/autoBackup/follow; returns the new status."""
        return await self._request("PUT", "settings", settings)

    async def _request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None = None,
        *,
        auth: bool = True,
        timeout: int = REQUEST_TIMEOUT,
    ) -> Any:
        headers = {"Authorization": f"Bearer {self.token}"} if auth and self.token else {}
        try:
            async with self._session.request(
                method,
                f"{self.base_url}/{path}",
                json=body,
                headers=headers,
                timeout=ClientTimeout(total=timeout),
            ) as response:
                status = response.status
                text = await response.text()
        except (ClientError, TimeoutError) as err:
            raise ArcLauncherConnectionError(f"Cannot reach {self.host}: {err}") from err
        try:
            data = json.loads(text) if text else None
        except ValueError as err:
            raise ArcLauncherError(f"Unexpected answer from {self.host}", status) from err
        if status >= 400:
            message = data.get("error") if isinstance(data, dict) else None
            message = message or f"HTTP {status}"
            if status in (HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN):
                raise ArcLauncherAuthError(message, status)
            raise ArcLauncherError(message, status)
        return data
