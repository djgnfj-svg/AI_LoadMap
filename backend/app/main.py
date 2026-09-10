"""FastAPI 진입점 (SPEC §3.2)."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import db
from app.api import alerts, auth, projects, reviews, tickets
from app.config import get_settings
from app.graphs.place_graph import build_place_graph
from app.graphs.replan_graph import build_replan_graph
from app.scheduler import build_scheduler
from app.services.planner_runs import PlanRunner

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def build_planner():
    """설정에 따라 실제 Claude 또는 목업을 돌려준다.

    USE_MOCK_PLANNER=true 면 API 키 없이 생성·재설계 그래프가 끝까지 돈다 (§0.3 데모용).
    """
    settings = get_settings()
    if settings.use_mock_planner or not settings.has_real_api_key:
        from app.graphs.mock_planner import MockPlanner

        log.warning("목업 Planner 로 동작한다. LLM 을 부르지 않는다.")
        return MockPlanner()

    from app.graphs.llm import AnthropicPlanner

    return AnthropicPlanner()


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    await db.init_pool()
    if not hasattr(app.state, "runner"):
        planner = build_planner()
        app.state.runner = PlanRunner(planner)
        app.state.replan_graph = build_replan_graph(planner)
        app.state.place_graph = build_place_graph(planner)
    else:
        # 테스트가 runner 만 끼워 넣는 경우가 있다. 없는 그래프만 채운다.
        planner = app.state.runner.planner
        if not hasattr(app.state, "replan_graph"):
            app.state.replan_graph = build_replan_graph(planner)
        if not hasattr(app.state, "place_graph"):
            app.state.place_graph = build_place_graph(planner)

    scheduler = None
    if settings.scheduler_enabled:
        scheduler = build_scheduler()
        scheduler.start()
        log.info("스케줄러 시작: %s", [j.id for j in scheduler.get_jobs()])
    try:
        yield
    finally:
        if scheduler is not None:
            scheduler.shutdown(wait=False)
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
    app.include_router(auth.router)
    app.include_router(projects.router)
    app.include_router(tickets.router)
    app.include_router(alerts.router)
    app.include_router(reviews.router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
