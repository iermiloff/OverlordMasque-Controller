import logging
import uuid
import httpx
from .config import settings

log = logging.getLogger("platega")


class PlategaError(Exception):
    def __init__(self, status: int, payload: dict):
        super().__init__(f"Platega {status}: {payload.get('code')} {payload.get('message')}")
        self.status = status
        self.trace_id = payload.get("traceId")


class PlategaClient:
    def __init__(self):
        self._http = httpx.AsyncClient(
            base_url=settings.platega_base_url.rstrip("/"),
            headers={
                "X-MerchantId": settings.platega_merchant_id,
                "X-Secret": settings.platega_secret,
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=httpx.Timeout(15.0, connect=5.0),
        )

    async def close(self):
        await self._http.aclose()

    async def _check(self, r: httpx.Response) -> dict:
        try:
            payload = r.json()
        except ValueError:
            payload = {}
        if r.status_code >= 400:
            err = PlategaError(r.status_code, payload)
            log.error("Platega error, traceId=%s: %s", err.trace_id, err)
            raise err
        return payload

    async def get_transaction(self, tx_id: str) -> dict:
        uuid.UUID(tx_id)
        return await self._check(await self._http.get(f"/transaction/{tx_id}"))

    async def create_payment(
        self,
        order_id: str,
        user_id: int,
        user_login: str,
        amount: float,
        description: str,
        client_ip: str = "",
    ) -> tuple[str, str]:
        """Создаёт платёж через /v2/transaction/process (выбор способа оплаты на форме Platega)."""
        synthetic_email = user_login if "@" in user_login else f"omc{user_id}@mail.ru"
        meta = {
            "user_email": synthetic_email,
            "userId": str(user_id),
            "userName": user_login,
        }
        if client_ip:
            meta["clientIp"] = client_ip

        body = {
            "paymentDetails": {
                "amount": round(float(amount), 2),
                "currency": "RUB",
            },
            "description": description[:255],
            "return": f"{settings.public_url.rstrip('/')}/cabinet?pay=success",
            "failedUrl": f"{settings.public_url.rstrip('/')}/cabinet?pay=fail",
            "orderId": order_id,
            "payload": order_id,
            "metadata": meta,
        }

        data = await self._check(await self._http.post("/v2/transaction/process", json=body))
        tx_id = data.get("transactionId")
        pay_url = data.get("url") or data.get("redirect")
        if not tx_id or not pay_url:
            raise PlategaError(502, {"code": "BAD_RESPONSE", "message": "Нет transactionId или url"})
        return str(tx_id), str(pay_url)
