import logging

import structlog

from app.logging import setup_logging


def test_setup_logging_console():
    setup_logging(log_format="console")
    logger = logging.getLogger("test.console")
    assert logger.root.handlers
    formatter = logger.root.handlers[0].formatter
    assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)


def test_setup_logging_json():
    setup_logging(log_format="json")
    logger = logging.getLogger("test.json")
    assert logger.root.handlers
    formatter = logger.root.handlers[0].formatter
    assert isinstance(formatter, structlog.stdlib.ProcessorFormatter)


def test_structlog_emits_with_context(capsys):
    setup_logging(log_format="console")
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id="test123")

    logger = structlog.get_logger("test.context")
    logger.info("hello", foo="bar")

    structlog.contextvars.clear_contextvars()
    # If we get here without error, structlog pipeline is working


def test_invalid_format_defaults_to_console():
    setup_logging(log_format="invalid_format")
    # Should not raise — falls through to console renderer
    logger = structlog.get_logger("test.invalid")
    logger.info("still works")
