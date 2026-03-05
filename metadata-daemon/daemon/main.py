import asyncio
import logging

from daemon.queue import run_worker
from daemon.scheduler import create_scheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger(__name__)


async def main():
    scheduler = create_scheduler()
    scheduler.start()
    logger.info("APScheduler started")

    try:
        await run_worker()
    finally:
        scheduler.shutdown()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Metadata daemon interrupted; shutting down")
