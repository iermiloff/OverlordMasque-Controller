import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..db import get_session
from ..deps import client_ip, current_user, rate_limit
from ..models import Node, Payment, Plan, User
from ..provisioning import attach_user_to_node, load_links, sync_user

log = logging.getLogger("payments")
router = APIRouter(prefix="/api/v1/payments", tags=["payments"])


class PaymentIn(BaseModel):
    plan_id: int


async def _apply_paid_order(session: AsyncSession, payment: Payment) -> None:
    if payment.status == "PAID":
        return

    plan = await session.get(Plan, payment.plan_id)
    user = await session.get(User, payment.user_id)
    if plan is None or user is None:
        return

    now = datetime.now(timezone.utc)
    base = user.expires_at if user.expires_at and user.expires_at > now else now
    user.expires_at = base + timedelta(days=plan.days)
    user.is_active = True

    if plan.traffic_gb > 0:
        user.traffic_limit_bytes += plan.traffic_gb * (1024**3)
    else:
        user.traffic_limit_bytes = 0

    # Если у пользователя ещё нет ни одной ноды — автоматически привязываем ко всем включённым
    existing_links = await load_links(session, user.id)
    if not existing_links:
        enabled_nodes = (await session.scalars(select(Node).where(Node.enabled.is_(True)))).all()
        for n in enabled_nodes:
            await attach_user_to_node(session, user, n)

    user.routes_revision += 1
    payment.status = "PAID"
    payment.paid_at = now
    await session.commit()
    await sync_user(session, user)


@router.post("", dependencies=[rate_limit("pay_create", 6, 60)])
async def create_payment(
    body: PaymentIn,
    request: Request,
    user: User = Depends(current_user),
    session: AsyncSession = Depends(get_session),
):
    plan = await session.get(Plan, body.plan_id)
    if plan is None or not plan.active:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Тариф не найден")

    payment = Payment(user_id=user.id, plan_id=plan.id, amount=plan.price)
    session.add(payment)
    await session.flush()

    tx_id, redirect_url = await request.app.state.platega.create_payment(
        order_id=payment.id,
        user_id=user.id,
        user_login=user.login,
        amount=float(plan.price),
        description=f"Подписка OverlordMasque: {plan.title}",
        client_ip=client_ip(request),
    )
    payment.provider_tx_id = tx_id
    await session.commit()
    return {"payment_id": payment.id, "redirect_url": redirect_url}


@router.post("/webhook")
async def platega_webhook(request: Request, session: AsyncSession = Depends(get_session)):
    payload = await request.json()
    tx_id = str(payload.get("id") or payload.get("transactionId") or "").strip()
    if not tx_id:
        return {"ok": True}

    payment = await session.scalar(select(Payment).where(Payment.provider_tx_id == tx_id))
    if payment is None or payment.status == "PAID":
        return {"ok": True}

    # Обязательно перепроверяем статус напрямую через API Platega, не доверяя слепо входящему POST
    try:
        tx_info = await request.app.state.platega.get_transaction(tx_id)
    except Exception as e:
        log.warning("Не удалось проверить транзакцию %s в Platega: %s", tx_id, e)
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Ошибка проверки платежа")

    remote_status = str(tx_info.get("status", "")).upper()
    if remote_status in {s.upper() for s in settings.platega_success_statuses}:
        await _apply_paid_order(session, payment)
    elif remote_status in {"CANCELED", "CANCELLED", "EXPIRED", "FAILED"}:
        payment.status = "FAILED"
        await session.commit()

    return {"ok": True}
