from datetime import datetime

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, BigInteger, Text
)
from sqlalchemy.orm import relationship

from .database import Base


class Panel(Base):
    """Одна 3x-ui панель. Хранит токен и настройки MASQUE-инбаунда."""
    __tablename__ = "panels"

    id = Column(Integer, primary_key=True)
    name = Column(String(64), unique=True, nullable=False)  # "eu1"
    url = Column(String(255), nullable=False)               # "https://panel-eu1:2053"
    api_token_encrypted = Column(Text, nullable=False)
    inbound_id = Column(Integer, nullable=False)            # id MASQUE-инбаунда
    domain = Column(String(255), nullable=False)            # что показать клиенту
    port = Column(Integer, nullable=False, default=443)
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    routes = relationship("UserRoute", back_populates="panel", cascade="all, delete-orphan")


class User(Base):
    """Пользователь OverlordMasque Online."""
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_encrypted = Column(Text, nullable=False)       # Fernet
    panel_user = Column(String(64), unique=True, nullable=False)  # "om_<id>"
    is_admin = Column(Boolean, default=False)

    subscription_status = Column(String(16), default="active")  # active/expired/suspended
    subscription_expires_at = Column(DateTime, nullable=True)
    traffic_used_bytes = Column(BigInteger, default=0)
    traffic_limit_bytes = Column(BigInteger, default=0)

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    routes = relationship("UserRoute", back_populates="user", cascade="all, delete-orphan")


class UserRoute(Base):
    """Привязка пользователя к панели. Пока просто есть/нет."""
    __tablename__ = "user_routes"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    panel_id = Column(Integer, ForeignKey("panels.id"), nullable=False)
    enabled = Column(Boolean, default=True)
    sync_error = Column(Text, nullable=True)  # последняя ошибка синка, если была
    last_synced_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="routes")
    panel = relationship("Panel", back_populates="routes")
