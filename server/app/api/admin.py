from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_session
from ..deps import current_admin
from ..models import Node, Plan, User, UserNode
from ..provisioning import attach_user_to_node, load_links, sync_user
from ..security import decrypt, encrypt, hash_password
from ..xui import XuiClient

router = APIRouter(prefix="/api/v1/admin", tags=["admin"], dependencies=[Depends(current_admin)])


class NodeIn(BaseModel):
    name: str = Field(min_length=2, max_length=64)
    panel_url: str = Field(min_length=8, max_length=255)
    api_token: str = Field(min_length=4, max_length=512)
    verify_tls: bool = True
    inbound_id: int = Field(ge=1)
    protocol: Literal["masque", "vless", "trojan"] = "masque"
    public_domain: str = Field(min_length=3, max_length=255)
    public_port: int = Field(default=443, ge=1, le=65535)
    priority: int = Field(default=100)
    is_backup: bool = False
    enabled: bool = True


class UserCreateIn(BaseModel):
    login: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=128)
    days: int = Field(default=30, ge=0)
    traffic_gb: int = Field(default=0, ge=0)
    max_devices: int = Field(default=3, ge=1, le=50)
    is_admin: bool = False
    node_ids: list[int] = Field(default_factory=list)


class UserPatchIn(BaseModel):
    is_active: bool | None = None
    add_days: int | None = None
    traffic_gb: int | None = None
    max_devices: int | None = None


class PlanIn(BaseModel):
    title: str = Field(min_length=2, max_length=64)
    days: int = Field(ge=1)
    traffic_gb: int = Field(default=0, ge=0)
    price: float = Field(gt=0)
    active: bool = True


@router.get("/nodes")
async def list_nodes(session: AsyncSession = Depends(get_session)):
    nodes = (await session.scalars(select(Node).order_by(Node.priority, Node.id))).all()
    return [
        {
            "id": n.id,
            "name": n.name,
            "panel_url": n.panel_url,
            "inbound_id": n.inbound_id,
            "protocol": n.protocol,
            "public_domain": n.public_domain,
            "public_port": n.public_port,
            "priority": n.priority,
            "is_backup": n.is_backup,
            "enabled": n.enabled,
        }
        for n in nodes
    ]


@router.post("/nodes")
async def create_node(body: NodeIn, session: AsyncSession = Depends(get_session)):
    exists = await session.scalar(select(Node).where(Node.name == body.name))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Нода с таким именем уже существует")

    node = Node(
        name=body.name.strip(),
        panel_url=body.panel_url.strip().rstrip("/"),
        api_token_enc=encrypt(body.api_token.strip()),
        verify_tls=body.verify_tls,
        inbound_id=body.inbound_id,
        protocol=body.protocol,
        public_domain=body.public_domain.strip(),
        public_port=body.public_port,
        priority=body.priority,
        is_backup=body.is_backup,
        enabled=body.enabled,
    )
    session.add(node)
    await session.commit()
    return {"id": node.id}


@router.post("/nodes/{node_id}/test")
async def test_node(node_id: int, session: AsyncSession = Depends(get_session)):
    node = await session.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нода не найдена")
    async with XuiClient(node.panel_url, decrypt(node.api_token_enc), node.verify_tls) as x:
        inbounds = await x.list_inbound_options()
    return {
        "ok": True,
        "inbounds": [
            {
                "id": i.get("id"),
                "remark": i.get("remark"),
                "protocol": i.get("protocol"),
                "port": i.get("port"),
            }
            for i in inbounds
        ],
    }


@router.delete("/nodes/{node_id}")
async def delete_node(node_id: int, session: AsyncSession = Depends(get_session)):
    node = await session.get(Node, node_id)
    if node is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Нода не найдена")
    await session.delete(node)
    await session.commit()
    return {"ok": True}


@router.get("/users")
async def list_users(session: AsyncSession = Depends(get_session)):
    users = (await session.scalars(select(User).order_by(User.id.desc()))).all()
    out = []
    for u in users:
        links = await load_links(session, u.id)
        out.append(
            {
                "id": u.id,
                "login": u.login,
                "is_admin": u.is_admin,
                "is_active": u.is_active,
                "expires_at": u.expires_at.isoformat() if u.expires_at else None,
                "traffic_used": sum(l.up + l.down for l in links),
                "traffic_limit": u.traffic_limit_bytes,
                "max_devices": u.max_devices,
                "nodes": [
                    {
                        "node_id": l.node_id,
                        "name": l.node.name,
                        "synced": l.synced,
                        "error": l.last_error,
                    }
                    for l in links
                ],
            }
        )
    return out


@router.post("/users")
async def create_user(body: UserCreateIn, session: AsyncSession = Depends(get_session)):
    exists = await session.scalar(select(User).where(User.login == body.login.strip()))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Пользователь с таким логином уже существует")

    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=body.days) if body.days > 0 else None
    )
    user = User(
        login=body.login.strip(),
        password_hash=hash_password(body.password),
        is_admin=body.is_admin,
        is_active=True,
        expires_at=expires_at,
        traffic_limit_bytes=body.traffic_gb * (1024**3),
        max_devices=body.max_devices,
    )
    session.add(user)
    await session.flush()

    if body.node_ids:
        nodes = (await session.scalars(select(Node).where(Node.id.in_(body.node_ids)))).all()
    else:
        nodes = (await session.scalars(select(Node).where(Node.enabled.is_(True)))).all()

    for n in nodes:
        await attach_user_to_node(session, user, n)

    await session.commit()
    errors = await sync_user(session, user)
    return {"id": user.id, "sync_errors": errors}


@router.patch("/users/{user_id}")
async def patch_user(user_id: int, body: UserPatchIn, session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

    if body.is_active is not None:
        user.is_active = body.is_active
    if body.add_days is not None:
        now = datetime.now(timezone.utc)
        base = user.expires_at if user.expires_at and user.expires_at > now else now
        user.expires_at = base + timedelta(days=body.add_days)
    if body.traffic_gb is not None:
        user.traffic_limit_bytes = body.traffic_gb * (1024**3)
    if body.max_devices is not None:
        user.max_devices = body.max_devices

    user.routes_revision += 1
    await session.commit()
    return {"sync_errors": await sync_user(session, user)}


@router.post("/users/{user_id}/sync")
async def force_sync_user(user_id: int, session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    return {"sync_errors": await sync_user(session, user)}


@router.delete("/users/{user_id}")
async def delete_user(user_id: int, session: AsyncSession = Depends(get_session)):
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")

    links = await load_links(session, user.id)
    for l in links:
        if l.synced:
            try:
                async with XuiClient(l.node.panel_url, decrypt(l.node.api_token_enc), l.node.verify_tls) as x:
                    await x.delete_client(l.xui_email)
            except Exception:
                pass

    await session.delete(user)
    await session.commit()
    return {"ok": True}


@router.get("/plans")
async def admin_list_plans(session: AsyncSession = Depends(get_session)):
    plans = (await session.scalars(select(Plan).order_by(Plan.id.asc()))).all()
    return [
        {
            "id": p.id,
            "title": p.title,
            "days": p.days,
            "traffic_gb": p.traffic_gb,
            "price": float(p.price),
            "active": p.active,
        }
        for p in plans
    ]


@router.post("/plans")
async def create_plan(body: PlanIn, session: AsyncSession = Depends(get_session)):
    plan = Plan(**body.model_dump())
    session.add(plan)
    await session.commit()
    return {"id": plan.id}


@router.delete("/plans/{plan_id}")
async def delete_plan(plan_id: int, session: AsyncSession = Depends(get_session)):
    plan = await session.get(Plan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тариф не найден")
    await session.delete(plan)
    await session.commit()
    return {"ok": True}
