from urllib.parse import quote
import httpx


class XuiError(Exception):
    pass


class XuiClient:
    """Адаптер для 3x-ui API v3.x (авторизация через Bearer API Token)."""

    def __init__(self, base_url: str, token: str, verify_tls: bool = True):
        self._http = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(15.0, connect=5.0),
            verify=verify_tls,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        await self._http.aclose()

    async def _call(self, method: str, path: str, **kwargs):
        r = await self._http.request(method, path, **kwargs)
        if r.status_code in (401, 403):
            raise XuiError(f"Ошибка авторизации панели ({r.status_code})")
        r.raise_for_status()
        data = r.json()
        if isinstance(data, dict):
            if data.get("success") is False:
                raise XuiError(data.get("msg") or "Ошибка 3x-ui API")
            if "obj" in data:
                return data["obj"]
        return data

    @staticmethod
    def build_client_payload(
        email: str,
        password: str,
        enable: bool,
        expiry_ms: int,
        total_bytes: int,
        limit_ip: int,
        sub_id: str,
        comment: str,
    ) -> dict:
        return {
            "email": email,
            "password": password,
            "enable": enable,
            "expiryTime": expiry_ms,
            "totalGB": total_bytes,
            "limitIp": limit_ip,
            "limitHwid": 0,
            "subId": sub_id,
            "comment": comment,
            "tgId": 0,
            "security": "auto",
            "reset": 0,
            "resetDay": 0,
            "resetMax": 0,
            "resetWeekday": 0,
        }

    async def list_inbound_options(self) -> list[dict]:
        """Лёгкий список инбаундов для проверки связи и выбора inbound_id."""
        res = await self._call("GET", "/panel/api/inbounds/options")
        return res if isinstance(res, list) else []

    async def get_client(self, email: str) -> dict | None:
        try:
            return await self._call("GET", f"/panel/api/clients/get/{quote(email, safe='')}")
        except XuiError:
            return None

    async def add_client(self, inbound_id: int, client: dict) -> None:
        await self._call(
            "POST",
            "/panel/api/clients/add",
            json={"client": client, "inboundIds": [inbound_id]},
        )

    async def update_client(self, email: str, client: dict) -> None:
        await self._call(
            "POST",
            f"/panel/api/clients/update/{quote(email, safe='')}",
            json=client,
        )

    async def delete_client(self, email: str) -> None:
        await self._call(
            "POST",
            f"/panel/api/clients/del/{quote(email, safe='')}",
            params={"keepTraffic": 0},
        )

    async def get_traffic(self, email: str) -> dict | None:
        return await self._call("GET", f"/panel/api/clients/traffic/{quote(email, safe='')}")
