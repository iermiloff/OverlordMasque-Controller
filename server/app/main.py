import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from redis.asyncio import Redis

from . import web
from .api import admin, auth, payments, user
from .config import settings
from .db import Base, engine
from .platega import PlategaClient
from .provisioning import stats_loop


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    platega = PlategaClient()
    app.state.redis = redis
    app.state.platega = platega

    bg_task = asyncio.create_task(stats_loop(redis, settings.stats_interval_sec))
    try:
        yield
    finally:
        bg_task.cancel()
        await platega.close()
        await redis.aclose()


app = FastAPI(
    title="OverlordMasque Controller",
    version="2.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

app.include_router(auth.router)
app.include_router(user.router)
app.include_router(payments.router)
app.include_router(admin.router)
app.include_router(web.router)


@app.get("/")
async def root():
    return RedirectResponse(url="/cabinet")


@app.get("/health")
async def health():
    return {"status": "ok"}
