import ipaddress
import time
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWTError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import settings
from .db import get_session
from .models import User
from .security import decode_access_token

_bearer = HTTPBearer(auto_error=False)
_TRUSTED_NETS = [ipaddress.ip_network(c) for c in settings.trusted_proxy_cidrs]


def client_ip(request: Request) -> str:
    remote = request.client.host if request.client else "0.0.0.0"
    try:
        addr = ipaddress.ip_address(remote)
        if any(addr in net for net in _TRUSTED_NETS):
            xff = request.headers.get("x-forwarded-for", "")
            if xff:
                first = xff.split(",")[0].strip()
                ipaddress.ip_address(first)
                return first
    except ValueError:
        pass
    return remote


def rate_limit(scope: str, limit: int, window_sec: int):
    async def _dep(request: Request):
        redis = request.app.state.redis
        ip = client_ip(request)
        bucket = int(time.time()) // window_sec
        key = f"rl:{scope}:{ip}:{bucket}"
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window_sec + 2)
        if count > limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Слишком много запросов, повторите позже",
                headers={"Retry-After": str(window_sec)},
            )

    return Depends(_dep)


class LoginGuard:
    """Защита от перебора паролей до вызова ресурсоёмкого Argon2."""

    def __init__(self, redis, ip: str, login: str):
        self.redis = redis
        self.ip_key = f"bf:ip:{ip}"
        self.acc_key = f"bf:acc:{login.lower()}"

    async def check(self) -> None:
        ip_fails = int(await self.redis.get(self.ip_key) or 0)
        acc_fails = int(await self.redis.get(self.acc_key) or 0)
        if ip_fails >= 15 or acc_fails >= 8:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Временная блокировка из-за неудачных попыток входа (15 мин)",
            )

    async def fail(self) -> None:
        for k in (self.ip_key, self.acc_key):
            val = await self.redis.incr(k)
            if val == 1:
                await self.redis.expire(k, 900)

    async def ok(self) -> None:
        await self.redis.delete(self.ip_key, self.acc_key)


async def current_user(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
    session: AsyncSession = Depends(get_session),
) -> User:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация")
    try:
        payload = decode_access_token(creds.credentials)
        user_id = int(payload["sub"])
    except (PyJWTError, KeyError, ValueError):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный или истёкший токен")

    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Аккаунт заблокирован или удалён")
    return user


async def current_admin(user: User = Depends(current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Требуются права администратора")
    return user
