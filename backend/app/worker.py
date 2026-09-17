"""@input MySQL leases, invocation principals and completed memory calls. @output Shared dispatch and principal-isolated asynchronous governance.
@position Background worker. @doc-sync Update header and INDEX.md on changes.
"""

import asyncio
import logging
from sqlalchemy import select
from .config import settings
from .db import DB, Run, Schedule, Deployment, ToolCall, now, uid
from .runtime import run_loop, create_run, event
from .scheduling import next_time
from .deployments import start, reconcile
from .governance import extract
from .invocation import acting_as

log = logging.getLogger(__name__)


async def execute_run(id, owner):
    await run_loop(id, owner)
    async with DB() as db:
        run = await db.get(Run, id)
        if (
            run
            and run.status == "SUCCEEDED"
            and run.snapshot["definition"].get("memory_enabled")
        ):
            explicit_call = await db.scalar(
                select(ToolCall).where(
                    ToolCall.run_id == id,
                    ToolCall.capability_id == "builtin.harness.memory.manage",
                    ToolCall.status == "SUCCEEDED",
                )
            )
            if explicit_call:
                return
            try:
                with acting_as((run.snapshot.get("publication") or {}).get("end_user_id"), run.snapshot.get("memory_policy")):
                    await extract(run.user_id, run.agent_id, run.task, run.result)
            except Exception:
                log.exception("Memory extraction failed for %s", id)


async def serve():
    owner = uid()
    running = set()
    deployments = set()
    try:
        while True:
            try:
                await reconcile(deployments)
                async with DB.begin() as db:
                    expired = list(
                        (
                            await db.scalars(
                                select(Run)
                                .where(
                                    Run.status.in_(
                                        [
                                            "RUNNING",
                                            "PAUSE_REQUESTED",
                                            "CANCEL_REQUESTED",
                                        ]
                                    ),
                                    Run.lease_until < now(),
                                )
                                .with_for_update(skip_locked=True)
                            )
                        ).all()
                    )
                    for run in expired:
                        calls = list(
                            (
                                await db.scalars(
                                    select(ToolCall).where(
                                        ToolCall.run_id == run.id,
                                        ToolCall.status == "RUNNING",
                                    )
                                )
                            ).all()
                        )
                        for call in calls:
                            call.status = "UNKNOWN"
                        run.status = "NEEDS_REVIEW" if calls else "PAUSED"
                        run.lease_owner = None
                        await event(db, run, "RUN_RECOVERED", {"status": run.status})
                    slots = max(0, settings.workers - len(running))
                    rows = (
                        list(
                            (
                                await db.scalars(
                                    select(Run)
                                    .where(Run.status == "QUEUED")
                                    .order_by(Run.created)
                                    .limit(slots)
                                    .with_for_update(skip_locked=True)
                                )
                            ).all()
                        )
                        if slots
                        else []
                    )
                    for run in rows:
                        run.status = "RUNNING"
                        run.lease_owner = owner
                        run.lease_until = now() + 15000
                        await event(db, run, "RUN_STARTED")
                    ids = [r.id for r in rows]
                    schedules = list(
                        (
                            await db.scalars(
                                select(Schedule)
                                .where(
                                    Schedule.enabled == True,
                                    Schedule.next_at > 0,
                                    Schedule.next_at <= now(),
                                )
                                .with_for_update(skip_locked=True)
                            )
                        ).all()
                    )
                    for schedule in schedules:
                        previous = (
                            await db.get(Run, schedule.last_run)
                            if schedule.last_run
                            else None
                        )
                        if now() - schedule.next_at < 60000 and (
                            not previous
                            or previous.status in {"SUCCEEDED", "FAILED", "CANCELLED"}
                        ):
                            try:
                                run = await create_run(
                                    db,
                                    schedule.user_id,
                                    schedule.agent_id,
                                    schedule.task,
                                    trigger="SCHEDULED",
                                    schedule_id=schedule.id,
                                )
                                schedule.last_run = run.id
                            except ValueError:
                                log.exception("Schedule target unavailable")
                        schedule.next_at = next_time(schedule.config, now())
                        if not schedule.next_at:
                            schedule.enabled = False
                for id in ids:
                    task = asyncio.create_task(execute_run(id, owner))
                    running.add(task)
                    task.add_done_callback(running.discard)
                async with DB() as db:
                    ids = list(
                        (
                            await db.scalars(
                                select(Deployment.id).where(
                                    Deployment.status == "QUEUED"
                                )
                            )
                        ).all()
                    )
                for id in ids:
                    if id not in deployments:
                        deployments.add(id)

                        async def deploy(id=id):
                            try:
                                await start(id)
                            except Exception as exc:
                                async with DB.begin() as db:
                                    row = await db.get(Deployment, id)
                                    row.status = "FAILED"
                                    row.error = str(exc)
                            finally:
                                deployments.discard(id)

                        asyncio.create_task(deploy())
            except Exception:
                log.exception("Worker tick failed")
            await asyncio.sleep(1)
    finally:
        for task in running:
            task.cancel()
        await asyncio.gather(*running, return_exceptions=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(serve())
