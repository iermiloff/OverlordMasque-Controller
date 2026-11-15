from datetime import datetime
from pydantic import BaseModel, Field


# --- Auth ---

class LoginRequest(BaseModel):
    username: str
    password: str


class SubscriptionInfo(BaseModel):
    status: str
    expires_at: datetime | None
    traffic_used_bytes: int
    traffic_limit_bytes: int


class RouteItem(BaseModel):
    id: str
    name: str
    domain: str
    port: int
    path: str | None = None
    alpn: list[str] = ["h3", "h2"]
    utls: str | None = None
    mtu: int | None = None


class AccountInfo(BaseModel):
    username: str
    panel_user: str
    panel_pass: str
    subscription: SubscriptionInfo


class LoginResponse(BaseModel):
    token: str
    expires_at: datetime
    account: AccountInfo
    routes: list[RouteItem]


# --- Admin ---

class PanelCreate(BaseModel):
    name: str
    url: str
    api_token: str
    inbound_id: int
    domain: str
    port: int = 443


class UserCreateRequest(BaseModel):
    username: str
    password: str = Field(min_length=8)
    subscription_days: int = Field(default=30, ge=1)
    traffic_limit_gb: int = Field(default=0, ge=0)


class UserConfigResponse(BaseModel):
    username: str
    panel_user: str
    panel_pass: str
    subscription: SubscriptionInfo
    routes: list[RouteItem]
    panel_sync: list[dict]  # статус синка на каждой панели
