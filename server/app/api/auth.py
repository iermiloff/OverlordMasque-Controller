from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_session
from ..deps import LoginGuard, client_ip, rate_limit
from ..models import Device, RefreshToken, User
from ..security import (
    dummy_verify,
    gen_refresh_token,
    hash_token,
    issue_access_token,
    verify_password,
)

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginIn(BaseModel):
    login: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=4, max_length=128)
    device_id: str = Field(min_length=4, max_length=128)
    device_name: str = Field(default="PC", max_length=128)
    platform: Literal["windows", "android", "web"] = "windows"


class RefreshIn(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=256)
    device_id: str = Field(min_length=4, max_length=128)


class LogoutIn(BaseModel):
    refresh_token: str = Field(min_length=16, max_length=256)


async def _register_device(session: AsyncSession, user: User, body: LoginIn) -> None:
    now = datetime.now(timezone.utc)
    devices = list(
        (
            await session.scalars(
                select(Device)
                .where(Device.user_id == user.id)
                .order_by(Device.last_seen_at.asc())
            )
        ).all()
    )
    for d in devices:
        if d.device_id == body.device_id:
            d.device_name = body.device_name
            d.platform = body.platform
            d.last_seen_at = now
            return

    if len(devices) >= user.max_devices:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Достигнут лимит устройств ({user.max_devices}). Удалите старое устройство в личном кабинете.",
        )

    session.add(
        Device(
            user_id=user.id,
            device_id=body.device_id,
            device_name=body.device_name,
            platform=body.platform,
            last_seen_at=now,
        )
    )


@router.post("/login", dependencies=[rate_limit("login", 10, 60)])
async def login(body: LoginIn, request: Request, session: AsyncSession = Depends(get_session)):
    ip = client_ip(request)
    guard = LoginGuard(request.app.state.redis, ip, body.login)
    await guard.check()

    user = await session.scalar(select(User).where(User.login == body.login.strip()))
    if user is None or not verify_password(body.password, user.password_hash):
        dummy_verify(body.password)
        await guard.fail()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")

    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Аккаунт заблокирован")

    await guard.ok()
    await _register_device(session, user, body)

    raw_refresh, digest = gen_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            device_id=body.device_id,
            token_hash=digest,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.refresh_ttl_days),
        )
    )
    await session.commit()

    return {
        "access_token": issue_access_token(user.id, user.login, user.is_admin),
        "refresh_token": raw_refresh,
        "expires_in": settings.jwt_access_ttl_sec,
        "user": {
            "id": user.id,
            "login": user.login,
            "is_admin": user.is_admin,
        },
    }


@router.post("/refresh", dependencies=[rate_limit("refresh", 20, 60)])
async def refresh(body: RefreshIn, session: AsyncSession = Depends(get_session)):
    digest = hash_token(body.refresh_token)
    rt = await session.scalar(select(RefreshToken).where(RefreshToken.token_hash == digest))
    now = datetime.now(timezone.utc)

    if rt is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Недействительный refresh-токен")

    # Защита от повторного использования скомпрометированного токена (reuse detection)
    if rt.revoked or rt.expires_at <= now or rt.device_id != body.device_id:
        all_user_tokens = (
            await session.scalars(select(RefreshToken).where(RefreshToken.user_id == rt.user_id))
        ).all()
        for t in all_user_tokens:
            t.revoked = True
        await session.commit()
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессия отозвана, выполните вход заново")

    user = await session.get(User, rt.user_id)
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Аккаунт заблокирован")

    rt.revoked = True
    raw_refresh, new_digest = gen_refresh_token()
    session.add(
        RefreshToken(
            user_id=user.id,
            device_id=body.device_id,
            token_hash=new_digest,
            expires_at=now + timedelta(days=settings.refresh_ttl_days),
        )
    )

    dev = await session.scalar(
        select(Device).where(Device.user_id == user.id, Device.device_id == body.device_id)
    )
    if dev:
        dev.last_seen_at = now

    await session.commit()

    return {
        "access_token": issue_access_token(user.id, user.login, user.is_admin),
        "refresh_token": raw_refresh,
        "expires_in": settings.jwt_access_ttl_sec,
    }


@router.post("/logout")
async def logout(body: LogoutIn, session: AsyncSession = Depends(get_session)):
    rt = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(body.refresh_token))
    )
    if rt:
        rt.revoked = True
        await session.commit()
    return {"ok": True}
