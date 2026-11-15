from datetime import datetime, timedelta, timezone

from cryptography.fernet import Fernet
from jose import jwt
from passlib.context import CryptContext

from .config import settings

_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
_fernet = Fernet(settings.fernet_key.encode())


# --- Fernet (для шифрования паролей и токенов в БД) ---

def encrypt(plaintext: str) -> str:
    if not plaintext:
        return ""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    return _fernet.decrypt(ciphertext.encode()).decode()


# --- Пароли для проверки при логине (хранятся как bcrypt-хеш) ---

def hash_password(password: str) -> str:
    return _pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# --- JWT ---

def create_jwt(username: str, is_admin: bool = False) -> str:
    expire = datetime.now(timezone.utc) + timedelta(days=settings.jwt_expire_days)
    payload = {"sub": username, "is_admin": is_admin, "exp": expire}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_jwt(token: str) -> dict:
    return jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
