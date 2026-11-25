import asyncio
import getpass
import sys

from sqlalchemy import select

from app.db import Base, SessionLocal, engine
from app.models import User
from app.security import hash_password


async def main() -> None:
    if len(sys.argv) < 2:
        print("Использование: python create_admin.py <login>")
        sys.exit(1)

    login = sys.argv[1].strip()
    password = getpass.getpass("Введите пароль администратора (мин. 10 символов): ")
    if len(password) < 10:
        print("Ошибка: пароль должен быть не короче 10 символов.")
        sys.exit(1)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with SessionLocal() as session:
        existing = await session.scalar(select(User).where(User.login == login))
        if existing:
            existing.password_hash = hash_password(password)
            existing.is_admin = True
            existing.is_active = True
            await session.commit()
            print(f"Пользователь '{login}' обновлён и назначен администратором.")
        else:
            user = User(
                login=login,
                password_hash=hash_password(password),
                is_admin=True,
                is_active=True,
                max_devices=10,
            )
            session.add(user)
            await session.commit()
            print(f"Администратор '{login}' успешно создан.")


if __name__ == "__main__":
    asyncio.run(main())
