from celery import Celery

from app.config import settings

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
    ],
    beat_schedule={
        "metadata-refresh-check": {
            "task": "app.tasks.metadata.check_and_schedule_refresh",
            "schedule": 3600.0,  # every hour
        },
    },
)
