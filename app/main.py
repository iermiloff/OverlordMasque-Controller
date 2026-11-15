import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI, Depends, HTTPException, Header
from sqlalchemy.orm import Session

from .config import settings
from .database import Base, engine, get_db
from .models import Panel, User, UserRoute
from .schemas import (
    LoginRequest, LoginResponse, AccountInfo, SubscriptionInfo, RouteItem,
    PanelCreate, UserCreateRequest, UserConfigResponse,
)
from .security import (
    encrypt, decrypt, hash_password, verify_password, create_jwt, decode_jwt,
)
from .xui import XuiClient, XuiError

logging.basicConfig(level=settings.log_level)
logger = logging.getLogger(__name__)


# --- Инициализация ---

def _ensure_admin(db: Session):
    admin = db.query(User).filter(User.username == settings.admin_username).first()
    if admin:
        return
    admin = User(
        username=settings.admin_username,
        password_hash=hash_password(settings.admin_password),
        password_encrypted=encrypt(settings.admin_password),
        panel_user="om_admin",
        is_admin=True,
        subscription_status="active",
    )
    db.add(admin)
    db.commit()
    logger.info(f"Создан админ '{settings.admin_username}'")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    from .database import SessionLocal
    db = SessionLocal()
    try:
        _ensure_admin(db)
    finally:
        db.close()
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)


# --- Зависимости ---

def get_current_user(authorization: str = Header(...), db: Session = Depends(get_db)) -> User:
    if not authorization.startswith("Bearer "):
        raise HTTPException(401, "Missing Bearer token")
    token = authorization[7:]
    try:
        payload = decode_jwt(token)
    except Exception as e:
        raise HTTPException(401, f"Invalid token: {e}")
    username = payload.get("sub")
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(401, "User not found")
    return user


def get_admin_user(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(403, "Admin access required")
    return user


# --- Вспомогательное: собрать маршруты пользователя ---

def _build_routes_for_user(user: User, db: Session) -> tuple[list[RouteItem], list[dict]]:
    """
    Читает UserRoute для пользователя, для каждой панели проверяет
    наличие клиента и собирает маршруты.
    Возвращает (routes, sync_report).
    """
    routes: list[RouteItem] = []
    sync_report: list[dict] = []

    for ur in db.query(UserRoute).filter(UserRoute.user_id == user.id).all():
        panel = ur.panel
        if not panel or not panel.enabled:
            sync_report.append({
                "panel": panel.name if panel else "?",
                "status": "skipped",
                "error": "panel disabled or missing",
            })
            continue

        token = decrypt(panel.api_token_encrypted)
        client = XuiClient(panel.url, token)

        try:
            inbound = client.get_inbound(panel.inbound_id)
        except XuiError as e:
            sync_report.append({"panel": panel.name, "status": "unreachable", "error": str(e)})
            ur.sync_error = str(e)[:500]
            continue

        if not inbound:
            sync_report.append({"panel": panel.name, "status": "inbound_not_found"})
            continue

        # Проверяем, есть ли наш клиент в инбаунде
        settings_dict = inbound.get("settings") or {}
        if isinstance(settings_dict, str):
            import json
            try:
                settings_dict = json.loads(settings_dict)
            except Exception:
                settings_dict = {}

        clients = settings_dict.get("clients", [])
        found = next((c for c in clients if c.get("email") == user.panel_user), None)

        if not found:
            sync_report.append({"panel": panel.name, "status": "client_missing"})
            ur.sync_error = "client not found in inbound"
            continue

        # Собираем данные инбаунда для маршрута
        stream = inbound.get("streamSettings") or {}
        if isinstance(stream, str):
            import json
            try:
                stream = json.loads(stream)
            except Exception:
                stream = {}

        masque_settings = stream.get("masqueSettings") or {}
        path = masque_settings.get("path")
        tls_settings = stream.get("tlsSettings") or {}
        alpn = tls_settings.get("alpn") or ["h3", "h2"]
        utls = tls_settings.get("fingerprint")

        routes.append(RouteItem(
            id=f"rt_{panel.name}_{user.id}",
            name=panel.name,
            domain=panel.domain,
            port=panel.port,
            path=path,
            alpn=alpn,
            utls=utls,
            mtu=None,  # берётся из настроек клиента, если понадобится
        ))
        sync_report.append({"panel": panel.name, "status": "ok"})
        ur.sync_error = None
        ur.last_synced_at = datetime.utcnow()

    db.commit()
    return routes, sync_report


# --- Auth ---

@app.post("/api/v1/auth/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == payload.username).first()
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "Неверный логин или пароль")

    if user.subscription_status != "active":
        raise HTTPException(403, f"Подписка {user.subscription_status}")

    routes, _ = _build_routes_for_user(user, db)
    panel_pass = decrypt(user.password_encrypted)
    token = create_jwt(user.username, is_admin=user.is_admin)

    from datetime import timedelta
    expires = datetime.utcnow() + timedelta(days=settings.jwt_expire_days)

    return LoginResponse(
        token=token,
        expires_at=expires,
        account=AccountInfo(
            username=user.username,
            panel_user=user.panel_user,
            panel_pass=panel_pass,
            subscription=SubscriptionInfo(
                status=user.subscription_status,
                expires_at=user.subscription_expires_at,
                traffic_used_bytes=user.traffic_used_bytes,
                traffic_limit_bytes=user.traffic_limit_bytes,
            ),
        ),
        routes=routes,
    )


# --- Routes (приложение запрашивает повторно) ---

@app.get("/api/v1/routes")
def get_routes(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    routes, sync_report = _build_routes_for_user(user, db)
    panel_pass = decrypt(user.password_encrypted)
    return {
        "account": AccountInfo(
            username=user.username,
            panel_user=user.panel_user,
            panel_pass=panel_pass,
            subscription=SubscriptionInfo(
                status=user.subscription_status,
                expires_at=user.subscription_expires_at,
                traffic_used_bytes=user.traffic_used_bytes,
                traffic_limit_bytes=user.traffic_limit_bytes,
            ),
        ),
        "routes": routes,
        "sync": sync_report,
    }


# --- Admin: управление панелями ---

@app.post("/api/v1/admin/panels")
def add_panel(payload: PanelCreate, _: User = Depends(get_admin_user),
              db: Session = Depends(get_db)):
    if db.query(Panel).filter(Panel.name == payload.name).first():
        raise HTTPException(409, f"Panel '{payload.name}' already exists")

    # Проверяем, что панель доступна и инбаунд существует
    client = XuiClient(payload.url, payload.api_token)
    try:
        inbound = client.get_inbound(payload.inbound_id)
    except XuiError as e:
        raise HTTPException(400, f"Панель недоступна: {e}")

    if not inbound:
        raise HTTPException(400, f"Инбаунд {payload.inbound_id} не найден")

    if inbound.get("protocol") != "masque":
        raise HTTPException(400,
            f"Инбаунд {payload.inbound_id} имеет протокол "
            f"'{inbound.get('protocol')}', а не 'masque'")

    panel = Panel(
        name=payload.name,
        url=payload.url,
        api_token_encrypted=encrypt(payload.api_token),
        inbound_id=payload.inbound_id,
        domain=payload.domain,
        port=payload.port,
    )
    db.add(panel)
    db.commit()
    return {"id": panel.id, "name": panel.name}


@app.get("/api/v1/admin/panels")
def list_panels(_: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    return [
        {
            "id": p.id, "name": p.name, "url": p.url,
            "inbound_id": p.inbound_id, "domain": p.domain,
            "port": p.port, "enabled": p.enabled,
        }
        for p in db.query(Panel).all()
    ]


# --- Admin: создание пользователей ---

@app.post("/api/v1/admin/users")
def create_user(payload: UserCreateRequest, _: User = Depends(get_admin_user),
                db: Session = Depends(get_db)):
    if db.query(User).filter(User.username == payload.username).first():
        raise HTTPException(409, f"User '{payload.username}' already exists")

    panels = db.query(Panel).filter(Panel.enabled == True).all()
    if not panels:
        raise HTTPException(400, "Нет доступных панелей")

    # Создаём пользователя
    user = User(
        username=payload.username,
        password_hash=hash_password(payload.password),
        password_encrypted=encrypt(payload.password),
        panel_user="",  # заполним после flush
        subscription_status="active",
        subscription_expires_at=datetime.utcnow() + __import__("datetime").timedelta(days=payload.subscription_days),
        traffic_used_bytes=0,
        traffic_limit_bytes=payload.traffic_limit_gb * 1024**3,
    )
    db.add(user)
    db.flush()  # получаем id
    user.panel_user = f"om_{user.id}"
    db.commit()

    # Создаём клиента на всех панелях
    sync_report = []
    for panel in panels:
        token = decrypt(panel.api_token_encrypted)
        client = XuiClient(panel.url, token)

        try:
            # Пытаемся update — если клиент уже есть, обновим
            try:
                client.update_client(
                    email=user.panel_user,
                    inbound_id=panel.inbound_id,
                    password=payload.password,
                    enable=True,
                )
                status = "updated"
            except XuiError:
                # Если не вышло — добавляем
                client.add_client(
                    inbound_id=panel.inbound_id,
                    email=user.panel_user,
                    password=payload.password,
                    enable=True,
                )
                status = "created"

            db.add(UserRoute(
                user_id=user.id,
                panel_id=panel.id,
                enabled=True,
                last_synced_at=datetime.utcnow(),
            ))
            sync_report.append({"panel": panel.name, "status": status})
        except XuiError as e:
            logger.error(f"Не удалось синхронизировать {user.panel_user} на {panel.name}: {e}")
            sync_report.append({"panel": panel.name, "status": "failed", "error": str(e)[:300]})
            db.add(UserRoute(
                user_id=user.id,
                panel_id=panel.id,
                enabled=False,
                sync_error=str(e)[:500],
            ))

    db.commit()
    return {
        "id": user.id,
        "username": user.username,
        "panel_user": user.panel_user,
        "panel_pass": payload.password,
        "sync": sync_report,
    }


# --- Admin: показать конфиг пользователя ---

@app.get("/api/v1/admin/users/{username}/config", response_model=UserConfigResponse)
def user_config(username: str, _: User = Depends(get_admin_user),
                db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(404, f"User '{username}' not found")

    routes, sync_report = _build_routes_for_user(user, db)

    return UserConfigResponse(
        username=user.username,
        panel_user=user.panel_user,
        panel_pass=decrypt(user.password_encrypted),
        subscription=SubscriptionInfo(
            status=user.subscription_status,
            expires_at=user.subscription_expires_at,
            traffic_used_bytes=user.traffic_used_bytes,
            traffic_limit_bytes=user.traffic_limit_bytes,
        ),
        routes=routes,
        panel_sync=sync_report,
    )


@app.get("/")
def root():
    return {"app": settings.app_name, "status": "running"}

import os
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# --- CORS (для удобства разработки и открытия /admin) ---

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # в продакшене ограничить
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Раздача статики и /admin ---

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(_STATIC_DIR, exist_ok=True)

if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


@app.get("/admin", include_in_schema=False)
def admin_panel():
    """Отдаёт одностраничную админ-панель."""
    path = os.path.join(_STATIC_DIR, "admin.html")
    if not os.path.exists(path):
        raise HTTPException(500, "admin.html не найден в app/static/")
    return FileResponse(path, media_type="text/html")


# --- Admin: список пользователей ---

@app.get("/api/v1/admin/users")
def list_users(_: User = Depends(get_admin_user), db: Session = Depends(get_db)):
    users = db.query(User).filter(User.is_admin == False).all()
    return [
        {
            "id": u.id,
            "username": u.username,
            "panel_user": u.panel_user,
            "subscription_status": u.subscription_status,
            "subscription_expires_at": u.subscription_expires_at,
            "traffic_used_bytes": u.traffic_used_bytes,
            "traffic_limit_bytes": u.traffic_limit_bytes,
            "created_at": u.created_at,
            "routes_count": len(u.routes),
        }
        for u in users
    ]


# --- Admin: удаление пользователя ---

@app.delete("/api/v1/admin/users/{username}")
def delete_user(username: str, _: User = Depends(get_admin_user),
                db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == username).first()
    if not user:
        raise HTTPException(404, f"User '{username}' not found")
    if user.is_admin:
        raise HTTPException(400, "Нельзя удалить админа")

    # Удаляем клиентов на всех панелях (не блокируем удаление при ошибке)
    cleanup_report = []
    for ur in user.routes:
        panel = ur.panel
        if not panel:
            continue
        try:
            token = decrypt(panel.api_token_encrypted)
            client = XuiClient(panel.url, token)
            client.delete_client(user.panel_user)
            cleanup_report.append({"panel": panel.name, "status": "deleted"})
        except XuiError as e:
            logger.warning(
                f"Не удалось удалить клиента {user.panel_user} "
                f"с панели {panel.name}: {e}")
            cleanup_report.append(
                {"panel": panel.name, "status": "failed", "error": str(e)[:300]})

    db.delete(user)
    db.commit()
    return {"username": username, "cleanup": cleanup_report}


# --- Admin: удаление панели ---

@app.delete("/api/v1/admin/panels/{panel_id}")
def delete_panel(panel_id: int, _: User = Depends(get_admin_user),
                 db: Session = Depends(get_db)):
    panel = db.query(Panel).filter(Panel.id == panel_id).first()
    if not panel:
        raise HTTPException(404, f"Panel {panel_id} not found")

    # Клиентов в 3x-ui не трогаем — админ почистит вручную,
    # если посчитает нужным. UserRoute удалятся каскадом.
    name = panel.name
    db.delete(panel)
    db.commit()
    return {"id": panel_id, "name": name, "status": "deleted"}
