import asyncio
import os

from celery import Celery
from celery.signals import setup_logging as celery_setup_logging

from app.config import settings


def run_async(coro):
    """Run an async coroutine from a Celery task.

    Handles the case where an event loop is already running
    (e.g. gevent/eventlet pool or nested calls) by running
    the coroutine in a separate thread.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        # No running loop — safe to use asyncio.run()
        return asyncio.run(coro)
    else:
        # Already in an event loop — run in a new thread
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(1) as pool:
            return pool.submit(asyncio.run, coro).result()


@celery_setup_logging.connect
def configure_celery_logging(**kwargs):
    from app.logging import setup_logging

    setup_logging(log_format=os.environ.get("LOG_FORMAT", "console"))


celery = Celery("beepub")

celery.conf.update(
    broker_url=settings.redis_url,
    result_backend=settings.redis_url,
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
    task_default_queue="default",
    imports=[
        "app.tasks.metadata",
        "app.tasks.wordcount",
        "app.tasks.illustration",
        "app.tasks.auto_tag",
        "app.tasks.text_extract",
        "app.tasks.summarize",
        "app.tasks.embed",
        "app.tasks.bulk_jobs",
    ],
    beat_schedule={
        "metadata-refresh-check": {
            "task": "app.tasks.metadata.check_and_schedule_refresh",
            "schedule": 3600.0,  # every hour
        },
    },
)
