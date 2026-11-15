from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")

    app_name: str = "OverlordMasque Controller"
    database_url: str = "sqlite:///./controller.db"

    fernet_key: str
    jwt_secret: str
    jwt_expire_days: int = 7

    admin_username: str = "admin"
    admin_password: str = "change_me_now"

    log_level: str = "INFO"


settings = Settings()
