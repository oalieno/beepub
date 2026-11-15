"""Handing work to the background worker from a request."""

import logging

logger = logging.getLogger(__name__)


def enqueue_after_commit(task, *args, **kwargs) -> bool:
    """Queue a background task for something that is already saved.

    The request's own work is done and committed; the task only follows
    it up (extract a book's text, fetch its metadata). If the queue cannot
    be reached, that is not the request's failure: it is logged, the
    request still succeeds, and the admin's bulk jobs pick up what was
    missed. Whether it was queued is returned.

    Not for a task the user asked for by name (run a job, generate an
    illustration): there, failing to queue it is the answer.
    """
    try:
        task.delay(*args, **kwargs)
        return True
    except Exception:
        logger.exception("Could not queue %s%r", task.name, args)
        return False
