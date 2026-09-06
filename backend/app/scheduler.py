"""스케줄러 (SPEC §3.6).

APScheduler 를 FastAPI 프로세스 안에서 돌린다 — 별도 인프라 없이 (§3.1).

| 시각 | 작업 |
|---|---|
| 매일 00:10 | 마감 경과 티켓 -> missed 이벤트 기록 |
| 매일 00:20 | 노드별 지연 집계 -> 임계 초과 시 review_days 생성 |
| 매일 09:00 | 알람 발송 |
| 매주 일 20:00 | 주간 완료율 집계 -> 주간 리뷰 알람 |

여기서 도는 것은 전부 SQL 이다. LLM 은 한 줄도 부르지 않는다 (R2).
"""

import logging
from datetime import date

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app import db
from app.services import alerts, detection
from app.services.node_status import sync_node_status

log = logging.getLogger(__name__)


async def job_record_missed(today: date | None = None) -> int:
    """매일 00:10 — 마감 경과 티켓에 missed 이벤트."""
    async with db.transaction() as conn:
        count = await detection.record_missed_tickets(conn, today)
    if count:
        log.info("missed 이벤트 %d건 기록", count)
    return count


async def job_review_days(today: date | None = None) -> int:
    """매일 00:20 — 노드별 지연 집계 -> 재점검일 생성 + 노드 상태 갱신."""
    created = 0
    async with db.transaction() as conn:
        for project_id in await _active_projects(conn):
            created += len(await detection.ensure_review_days(conn, project_id, today))
            await sync_node_status(conn, project_id)
    if created:
        log.info("재점검일 %d건 생성", created)
    return created


async def job_alerts(today: date | None = None) -> int:
    """매일 09:00 — 알람 생성.

    v1 의 채널은 앱 안의 알람 목록이다 (§3.5 GET /projects/{id}/alerts).
    웹푸시는 §0.3 에서 자를 수 있는 항목으로 표시돼 있다.
    """
    created = 0
    async with db.transaction() as conn:
        for project_id in await _active_projects(conn):
            created += await alerts.generate_alerts(conn, project_id, today)
    if created:
        log.info("알람 %d건 생성", created)
    return created


async def job_weekly_review(today: date | None = None) -> int:
    """매주 일 20:00 — 주간 완료율 집계."""
    created = 0
    async with db.transaction() as conn:
        for project_id in await _active_projects(conn):
            created += await alerts.generate_weekly_review(conn, project_id, today)
    return created


async def _active_projects(conn) -> list:  # noqa: ANN001
    rows = await conn.fetch("select id from projects where status = 'active'")
    return [r["id"] for r in rows]


def build_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(job_record_missed, CronTrigger(hour=0, minute=10), id="record_missed")
    scheduler.add_job(job_review_days, CronTrigger(hour=0, minute=20), id="review_days")
    scheduler.add_job(job_alerts, CronTrigger(hour=9, minute=0), id="alerts")
    scheduler.add_job(
        job_weekly_review, CronTrigger(day_of_week="sun", hour=20, minute=0), id="weekly_review"
    )
    return scheduler


async def run_all_now(today: date | None = None) -> dict[str, int]:
    """스케줄러 작업을 순서대로 한 번 돌린다. 데모·테스트·백필용."""
    return {
        "missed": await job_record_missed(today),
        "review_days": await job_review_days(today),
        "alerts": await job_alerts(today),
        "weekly_review": await job_weekly_review(today),
    }
