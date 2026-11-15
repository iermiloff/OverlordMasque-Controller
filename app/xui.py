import logging
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class XuiError(Exception):
    pass


class XuiClient:
    """
    Минимальный HTTP-клиент к 3x-ui. Все методы бросают XuiError при неудаче.
    """

    def __init__(self, base_url: str, api_token: str, timeout: float = 10.0):
        self.base_url = base_url.rstrip("/")
        self.api_token = api_token
        self.timeout = timeout

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Accept": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> Any:
        url = f"{self.base_url}{path}"
        try:
            with httpx.Client(timeout=self.timeout, verify=True) as client:
                resp = client.request(method, url, headers=self._headers(), **kwargs)
        except httpx.RequestError as e:
            raise XuiError(f"Сетевая ошибка при запросе к {url}: {e}") from e

        if resp.status_code != 200:
            raise XuiError(f"HTTP {resp.status_code} от {url}: {resp.text[:200]}")

        try:
            data = resp.json()
        except Exception as e:
            raise XuiError(f"Ответ не JSON от {url}: {resp.text[:200]}") from e

        if not data.get("success", False):
            msg = data.get("msg", "unknown")
            raise XuiError(f"3x-ui вернул success=false: {msg}")

        return data.get("obj")

    # --- Inbounds ---

    def list_inbounds(self) -> list[dict]:
        return self._request("GET", "/panel/api/inbounds/list") or []

    def get_inbound(self, inbound_id: int) -> dict | None:
        try:
            return self._request("GET", f"/panel/api/inbounds/get/{inbound_id}")
        except XuiError:
            return None


    def add_client(self, inbound_id: int, email: str, password: str,
                   enable: bool = True, total_gb: int = 0, expiry_time: int = 0) -> Any:
        payload = {
            "client": {
                "email": email,
                "password": password,
                "enable": enable,
                "totalGB": total_gb,
                "expiryTime": expiry_time,
            },
            "inboundIds": [inbound_id],
        }
        return self._request("POST", "/panel/api/clients/add", json=payload)

    def update_client(self, email: str, inbound_id: int, password: str | None = None,
                      enable: bool | None = None) -> Any:
        patch: dict = {"email": email}
        if password is not None:
            patch["password"] = password
        if enable is not None:
            patch["enable"] = enable
        payload = {"client": patch, "inboundIds": [inbound_id]}
        return self._request("POST", f"/panel/api/clients/update/{email}", json=payload)

    def delete_client(self, email: str) -> Any:
        return self._request("POST", f"/panel/api/clients/del/{email}")

    def get_client(self, email: str) -> dict | None:
        try:
            return self._request("GET", f"/panel/api/clients/get/{email}")
        except XuiError:
            return None
