from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.routers import auth, health
from db.session import engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(title="WikingerBot API", lifespan=lifespan)

app.include_router(health.router)
app.include_router(auth.router)
