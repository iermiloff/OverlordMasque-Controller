import asyncio
import logging
import secrets
from collections import defaultdict
from datetime import datetime, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .db import SessionLocal
from .models import Node, User, UserNode
from .security import decrypt, encrypt, gen_node_password
from .xui import XuiClient, XuiError

log = logging.getLogger("provisioning")


async def load_links(session: AsyncSession, user_id: int) -> list[UserNode]:
    res = await session.scalars(
        select(UserNode).where(UserNode.user_id == user_id).options(selectinload(UserNode.node))
    )
    return list(res.all())


def is_entitled(user: User, used_bytes: int) -> bool:
    if not user.is_active:
        return False
    if user.expires_at and user.expires_at <= datetime.now(timezone.utc):
        return False
    if user.traffic_limit_bytes and used_bytes >= user.traffic_limit_bytes:
        return False
    return True


async def attach_user_to_node(session: AsyncSession, user: User, node: Node) -> UserNode:
    link = UserNode(
        user_id=user.id,
        node_id=node.id,
        xui_email=f"omc{user.id}_{user.login}"[:120],
        sub_id=secrets.token_hex(8),
        node_password_enc=encrypt(gen_node_password()),
    )
    session.add(link)
    await session.flush()
    return link


async def sync_user(session: AsyncSession, user: User) -> list[str]:
    links = await load_links(session, user.id)
    used = sum(l.up + l.down for l in links)
    entitled = is_entitled(user, used)
    expiry_ms = int(user.expires_at.timestamp() * 1000) if user.expires_at else 0
    errors: list[str] = []
    changed = False

    for link in links:
        node = link.node
        client_payload = XuiClient.build_client_payload(
            email=link.xui_email,
            password=decrypt(link.node_password_enc),
            enable=entitled and node.enabled,
            expiry_ms=expiry_ms,
            total_bytes=user.traffic_limit_bytes,
            limit_ip=user.max_devices,
            sub_id=link.sub_id,
            comment=f"omc:{user.id}",
        )
        try:
            async with XuiClient(node.panel_url, decrypt(node.api_token_enc), node.verify_tls) as x:
                if link.synced:
                    await x.update_client(link.xui_email, client_payload)
                else:
                    await x.add_client(node.inbound_id, client_payload)
                    link.synced = True
                    changed = True
            link.last_error = None
        except (XuiError, httpx.HTTPError) as e:
            link.last_error = str(e)[:500]
            errors.append(f"{node.name}: {e}")

    user.panel_enabled = entitled
    if changed:
        user.routes_revision += 1
    await session.commit()
    return errors


async def collect_stats_once() -> None:
    async with SessionLocal() as s:
        links = list((await s.scalars(
            select(UserNode)
            .where(UserNode.synced.is_(True))
            .options(selectinload(UserNode.node), selectinload(UserNode.user))
        )).all())

        by_node: dict[int, list[UserNode]] = defaultdict(list)
        for l in links:
            by_node[l.node_id].append(l)

        for node_links in by_node.values():
            node = node_links.node
            try:
                async with XuiClient(node.panel_url, decrypt(node.api_token_enc), node.verify_tls) as x:
                    for l in node_links:
                        t = await x.get_traffic(l.xui_email)
                        if isinstance(t, dict):
                            l.up = int(t.get("up", 0))
                            l.down = int(t.get("down", 0))
            except (XuiError, httpx.HTTPError) as e:
                log.warning("stats from node %s failed: %s", node.name, e)
        await s.commit()

        users = {l.user_id: l.user for l in links}
        for user in users.values():
            used = sum(l.up + l.down for l in links if l.user_id == user.id)
            if is_entitled(user, used) != user.panel_enabled:
                await sync_user(s, user)


async def stats_loop(redis, interval: int) -> None:
    while True:
        try:
            if await redis.set("lock:stats", "1", nx=True, ex=max(interval - 20, 30)):
                await collect_stats_once()
        except Exception:
            log.exception("stats loop failed")
        await asyncio.sleep(interval)
