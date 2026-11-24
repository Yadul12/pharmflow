from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import IS_VERCEL
from app.database import close_pool, init_pool
from app.routers.api import router as api_router


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not IS_VERCEL:
        init_pool()
    yield
    if not IS_VERCEL:
        close_pool()


app = FastAPI(
    title="PharmFlow Analytics API",
    description="Healthcare E-commerce Customer, Order Funnel & Retention Analytics Engine",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)
