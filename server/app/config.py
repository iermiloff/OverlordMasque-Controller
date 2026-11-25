from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_prefix="OMC_", extra="ignore")

    public_url: str = "https://example.com"
    database_url: str = "postgresql+asyncpg://omc:omc@db:5432/omc"
    redis_url: str = "redis://redis:6379/0"

    jwt_secret: str
    jwt_access_ttl_sec: int = 900
    refresh_ttl_days: int = 30
    fernet_key: str

    trusted_proxy_cidrs: list[str] = ["127.0.0.1/32", "172.16.0.0/12", "10.0.0.0/8"]
    default_max_devices: int = 3
    stats_interval_sec: int = 300

    platega_base_url: str = "https://platega.io"
    platega_merchant_id: str = ""
    platega_secret: str = ""
    platega_success_statuses: list[str] = ["CONFIRMED"]


settings = Settings()
