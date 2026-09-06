"""FastAPI 진입점 (SPEC §3.2)."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.api import projects, tickets
from app.config import get_settings
from app.services.planner_runs import PlanRunner

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def build_runner() -> PlanRunner:
    from app.graphs.llm import AnthropicPlanner

    return PlanRunner(AnthropicPlanner())


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_pool()
    if not hasattr(app.state, "runner"):
        app.state.runner = build_runner()
    try:
        yield
    finally:
        await db.close_pool()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Roadmap Planner",
        description="목표를 넣으면 로드맵과 아키텍처가 함께 그려지고, "
        "진행 기록에 따라 스스로 다시 그려지는 도구",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(projects.router)
    app.include_router(tickets.router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
