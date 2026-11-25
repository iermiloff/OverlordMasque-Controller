from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_user, rate_limit
from ..models import Device, Plan, RefreshToken, User
from ..provisioning import is_entitled, load_links
from ..security import decrypt

router = APIRouter(prefix="/api/v1", tags=["user"])


@router.get("/me", dependencies=[rate_limit("me", 30, 60)])
async def get_me(user: User = Depends(current_user), session: AsyncSession = Depends(get_session)):
    links = await load_links(session, user.id)
    used = sum(l.up + l.down for l in links)
    entitled = is_entitled(user, used)
    devices = list(
        (
            await session.scalars(
                select(Device).where(Device.user_id == user.id).order_by(Device.last_seen_at.desc())
            )
        ).all()
    )

    return {
        "id": user.id,
        "login": user.login,
        "is_admin": user.is_admin,
        "active": entitled,
        "expires_at": user.expires_at.isoformat() if user.expires_at else None,
        "traffic_used": used,
        "traffic_limit": user.traffic_limit_bytes,
        "max_devices": user.max_devices,
        "routes_revision": user.routes_revision,
        "nodes": [
            {
                "node_id": l.node_id,
                "name": l.node.name,
                "protocol": l.node.protocol,
                "is_backup": l.node.is_backup,
                "up": l.up,
                "down": l.down,
            }
            for l in links
        ],
        "devices": [
            {
                "id": d.id,
                "device_id": d.device_id,
                "device_name": d.device_name,
                "platform": d.platform,
                "last_seen_at": d.last_seen_at.isoformat(),
            }
            for d in devices
        ],
    }


@router.delete("/me/devices/{device_row_id}", dependencies=[rate_limit("dev_del", 15, 60)])
async def delete_device(
    device_row_id: int,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    dev = await session.get(Device, device_row_id)
    if dev is None or dev.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Устройство не найдено")

    await session.execute(
        delete(RefreshToken).where(
            RefreshToken.user_id == user.id, RefreshToken.device_id == dev.device_id
        )
    )
    await session.delete(dev)
    await session.commit()
    return {"ok": True}


@router.get("/routes", dependencies=[rate_limit("routes", 30, 60)])
async def get_routes(
    request: Request,
    response: Response,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    links = await load_links(session, user.id)
    used = sum(l.up + l.down for l in links)
    entitled = is_entitled(user, used)

    etag = f'"u{user.id}-r{user.routes_revision}-e{int(entitled)}"'
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers={"ETag": etag})

    response.headers["ETag"] = etag

    if not entitled:
        return {
            "active": False,
            "revision": user.routes_revision,
            "expires_at": user.expires_at.isoformat() if user.expires_at else None,
            "routes": [],
        }

    active_links = [l for l in links if l.synced and l.node.enabled]
    active_links.sort(key=lambda l: (l.node.is_backup, l.node.priority, l.node.id))

    routes = [
        {
            "id": l.node.id,
            "name": l.node.name,
            "protocol": l.node.protocol,
            "is_backup": l.node.is_backup,
            "priority": l.node.priority,
            "domain": l.node.public_domain,
            "port": l.node.public_port,
            "user": l.xui_email,
            "password": decrypt(l.node_password_enc),
        }
        for l in active_links
    ]

    return {
        "active": True,
        "revision": user.routes_revision,
        "expires_at": user.expires_at.isoformat() if user.expires_at else None,
        "routes": routes,
    }


@router.get("/plans", dependencies=[rate_limit("plans", 30, 60)])
async def list_plans(session: AsyncSession = Depends(get_session)):
    plans = (await session.scalars(select(Plan).where(Plan.active.is_(True)).order_by(Plan.price.asc()))).all()
    return [
        {
            "id": p.id,
            "title": p.title,
            "days": p.days,
            "traffic_gb": p.traffic_gb,
            "price": float(p.price),
        }
        for p in plans
    ]
